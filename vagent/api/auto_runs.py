"""全自动制片任务，按子项目保存进度及逐镜检查点。"""

import json
import shutil
import sqlite3
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from flask import Blueprint, current_app, request

from .. import config, llm
from ..db import _LOCK, conn, now_text, q, q1, x
from ..images.frames import sample_frames
from ..images.prompts import three_view_sheet
from ..providers import image, video
from ..repository import add_asset_with_views, add_shot, current_ids, set_asset_preview
from ..responses import fail, ok
from ..skills import rui_skill
from .shots import _review_content

bp = Blueprint("auto_runs", __name__)
MAX_ATTEMPTS = 3
MAX_PARALLEL_SHOTS = 2
POLL_TIMEOUT = 15 * 60


def _json(value):
    return json.dumps(value, ensure_ascii=False)


def _media(url):
    if not str(url).startswith("/uploads/"):
        raise ValueError("素材地址无效")
    path = (config.UPLOAD_DIR / url[9:]).resolve()
    if not path.is_relative_to(config.UPLOAD_DIR.resolve()) or not path.is_file():
        raise ValueError("找不到素材文件")
    return path


def _public(row):
    if not row:
        return None
    data = json.loads(row["data"])
    return {
        "id": row["id"],
        "subId": row["sub_id"],
        "status": row["status"],
        "stage": row["stage"],
        "shots": [
            {"name": s["name"], "stage": s.get("stage", "待生成"), "attempt": s.get("attempt", 1)}
            for s in data.get("shots", [])
        ],
        "exportUrl": data.get("exportUrl", ""),
    }


@bp.get("/api/auto/runs/current")
def api_auto_run_current():
    return ok({"run": latest_run(*current_ids())})


def latest_run(pid, sid):
    return _public(
        q1("SELECT * FROM auto_runs WHERE project_id=? AND sub_id=? ORDER BY rowid DESC LIMIT 1", (pid, sid))
    )


@bp.post("/api/auto/runs")
def api_auto_run_start():
    pid, sid = current_ids()
    if not pid or not sid:
        return fail("NO_PROJECT", "请先选择项目", 400)
    body = request.get_json(silent=True) or {}
    text = str(body.get("text") or "").strip()
    item = body.get("attachment") or {}
    source = ""
    if item:
        name = str(item.get("stored") or "")
        if not name or Path(name).name != name:
            return fail("BAD_REQUEST", "附件名称无效", 400)
        try:
            path = _media("/uploads/" + name)
            if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                source = "/uploads/" + name
            elif path.suffix.lower() in (".txt", ".md") and path.stat().st_size <= 128000:
                text = (text + "\n" + path.read_text(encoding="utf-8-sig")).strip()
            else:
                raise ValueError("请上传 PNG、JPEG、WebP 或 128 KB 以内的 UTF-8 文本")
        except (ValueError, OSError) as err:
            return fail("BAD_REQUEST", str(err), 400)
    if not text and not source:
        return fail("BAD_REQUEST", "请输入想法或上传图片、文本", 400)
    run_id = uuid.uuid4().hex
    data = {"text": text, "source": source}
    try:
        with _LOCK, conn() as c:
            c.execute(
                "INSERT INTO auto_runs VALUES (?,?,?,'running',?,?)",
                (run_id, pid, sid, "正在分析素材", _json(data)),
            )
            c.execute(
                "INSERT INTO messages(project_id,sub_id,role,text,meta,created_at) VALUES(?,?,?,?,?,?)",
                (
                    pid,
                    sid,
                    "user",
                    text or "根据参考图生成视频",
                    _json({"attachment": item} if item else {}),
                    now_text(),
                ),
            )
    except sqlite3.IntegrityError:
        return fail("BAD_REQUEST", "本分集已有全自动任务正在运行", 409)
    if not current_app.testing:
        _start(run_id)
    return ok({"run": _public(q1("SELECT * FROM auto_runs WHERE id=?", (run_id,)))})


def _ask(instructions, text, paths=()):
    content = [{"type": "text", "text": text}]
    content.extend({"type": "image_url", "image_url": {"url": llm._data_uri(p)}} for p in paths)
    return llm._extract_json(
        llm.chat([{"role": "system", "content": instructions}, {"role": "user", "content": content}])
    )


def _assets(data, scope, save):
    source = data["source"]
    refs = [_media(source)] if source else []
    if "assets" not in data:
        result = _ask(
            "分析创作需求和参考图，只提取需要跨镜复用的角色、场景或道具。返回 JSON assets 数组，每项 name、type、desc、fromImage（该主体来自上传图时为 true）。没有可复用主体可返回空数组。",
            data["text"],
            refs,
        )
        assets = result["assets"]
        if not isinstance(assets, list):
            raise ValueError("资产分析结果无效")
        data["assets"] = [
            {
                "name": str(a["name"]),
                "type": str(a["type"]),
                "desc": str(a["desc"]),
                "fromImage": bool(source and a.get("fromImage") is True),
            }
            for a in assets
        ]
        save("资产分析完成")
    for a in data["assets"]:
        if a.get("url"):
            continue
        original = source if a["fromImage"] else ""
        save("制作三视图 · " + a["name"])
        if original and not a.get("id"):
            asset = add_asset_with_views(
                a["name"], a["type"], a["desc"], [original], original, project_sub=scope
            )
            a["id"] = asset["id"]
            save("原图已存入资产库 · " + a["name"])
        prompt = three_view_sheet(a["name"], a["type"], a["desc"])
        url = image.generate(prompt, ref_images=[_media(original)] if original else [])["url"]
        if not a.get("id"):
            a["id"] = add_asset_with_views(a["name"], a["type"], a["desc"], [url], project_sub=scope)["id"]
        set_asset_preview(a["id"], [{"kind": "img", "url": url, "label": "三视图"}])
        a["url"] = url
        save("三视图已存入资产库 · " + a["name"])


def _plan(data, scope, save):
    if "shots" not in data:
        save("规划分镜与镜头提示词")
        guide = rui_skill("storyboard-pacing")
        h3 = config.BASE_DIR / "skills/minimax-h3-video-reverse-skill/references/h3-adapter.md"
        result = _ask(
            guide["reference_text"]
            + "\n"
            + h3.read_text(encoding="utf-8")
            + "\n按用户想法规划完整的连续分镜，返回 JSON shots 数组。每镜 name、prompt、dur（4 到 15 秒）、assets（本镜需要的资产 ID 数组）。保持角色和场景连续。只返回 JSON。",
            _json({"idea": data["text"], "assets": data["assets"]}),
            [_media(data["source"])] if data["source"] else [],
        )
        if not isinstance(result.get("shots"), list) or not result["shots"]:
            raise ValueError("未取得有效分镜")
        shots = []
        for item in result["shots"]:
            prompt = str(item["prompt"]).strip()
            if not prompt:
                raise ValueError("分镜提示词为空")
            shots.append(
                {
                    "name": str(item["name"]),
                    "prompt": prompt,
                    "target": prompt,
                    "dur": min(15, max(4, float(item["dur"]))),
                    "assets": item.get("assets", []),
                }
            )
        data["shots"] = shots
        save("分镜规划完成")
    for shot in data["shots"]:
        if not shot.get("id"):
            shot["id"] = add_shot(
                shot["name"], shot["prompt"], shot["dur"], project_sub=scope, status="pending", ai=""
            )["id"]
            save("分镜已写入时间轴")


def _render(shot, refs, save):
    if not shot.get("job"):
        job = video.submit_reference(
            shot["prompt"], [llm._data_uri(path) for path in refs], duration=shot["dur"]
        )
        shot["job"] = job
        shot["pollDeadline"] = time.time() + POLL_TIMEOUT
        save("等待视频生成")
    elif "pollDeadline" not in shot:
        shot["pollDeadline"] = time.time() + POLL_TIMEOUT
        save("等待视频生成")

    def remaining():
        seconds = shot["pollDeadline"] - time.time()
        if seconds <= 0:
            raise ValueError("视频生成轮询超时（15 分钟）")
        return seconds

    errors = 0
    while True:
        try:
            info = video.query(shot["job"], timeout=min(video.DEFAULT_TIMEOUT, remaining() / 2))
            remaining()
            errors = 0
        except video.VideoError:
            errors += 1
            if errors >= 3:
                raise
            time.sleep(min(5, remaining()))
            continue
        if info["state"] == "succeeded":
            return video.download(info["url"])
        if info["state"] in ("failed", "cancelled"):
            raise ValueError(str(info.get("error") or "视频生成失败"))
        time.sleep(min(5, remaining()))


def _identity(clip, refs, assets):
    temp = config.UPLOAD_DIR / "gen" / "identity" / uuid.uuid4().hex
    temp.mkdir(parents=True)
    try:
        frames = sample_frames(_media(clip), temp, "character")
        result = _ask(
            "先看成片抽帧，再对照后附参考图，判断本镜角色身份、长相、服装是否一致。"
            "空镜核对是否出现意外角色。关键证据不足不能通过。返回 JSON：pass 布尔值、reason 中文依据。",
            _json({"成片帧数": len(frames), "资产": assets}),
            [*frames, *refs],
        )
    finally:
        shutil.rmtree(temp)
    return result.get("pass") is True, str(result.get("reason") or "角色一致性证据不足")


def _shot(data, shot, number, save):
    if shot.get("passed"):
        return

    def progress(stage):
        shot["stage"] = stage
        save(f"镜头 {number}/{len(data['shots'])} · {stage}")

    selected = [a for a in data["assets"] if a["id"] in shot["assets"]]
    urls = [a["url"] for a in selected]
    if data["source"]:
        urls.insert(0, data["source"])
    if not urls:
        if not shot.get("reference"):
            progress("生成全能参考图")
            shot["reference"] = image.generate(shot["target"])["url"]
            progress("参考图已就绪")
        urls.append(shot["reference"])
    refs = [_media(url) for url in urls[:9]]
    while True:
        attempt = shot.setdefault("attempt", 1)
        progress(f"全能参考生成 · 第 {attempt} 次")
        x(
            "UPDATE shots SET prompt=?, status='redraw', ref_mode=1, ref_assets=?, progress=5 WHERE id=?",
            (shot["prompt"], _json([a["id"] for a in selected]), shot["id"]),
        )
        try:
            if not shot.get("clip"):
                shot["clip"] = _render(shot, refs, progress)
            progress("角色一致性校验")
            passed, why = _identity(shot["clip"], refs, selected)
            shot["identity"] = {"pass": passed, "reason": why}
            if not passed:
                raise ValueError(why)
            progress("画面复述校验")
            row = dict(q1("SELECT * FROM shots WHERE id=?", (shot["id"],)))
            row.update(clip_path=shot["clip"], provider_job=shot["job"])
            review = _review_content(row, "auto", shot["target"], refs[0])
            if review["verdict"] != "pass":
                raise ValueError(review["reason"])
            review["identity"] = shot["identity"]
            x(
                "UPDATE shots SET provider_job=?,clip_path=?,review=?,status='confirmed',progress=100,updated_at=? WHERE id=?",
                (shot["job"], shot["clip"], _json(review), now_text(), shot["id"]),
            )
            shot["passed"] = True
            progress("两项校验通过")
            return
        except (ValueError, video.VideoError) as err:
            reason = str(err)
            if (
                attempt >= MAX_ATTEMPTS
                or getattr(err, "status", 0) in (401, 403)
                or any(
                    word in reason.lower()
                    for word in ("moderation", "content blocked", "内容审核", "敏感", "1026")
                )
            ):
                x("UPDATE shots SET status='failed',progress=0 WHERE id=?", (shot["id"],))
                raise
            progress("调整提示词 · " + reason[:160])
            revised = _ask(
                "在保持原分镜目标和资产身份的前提下，依据失败原因修正动作、机位和可见性。只返回 JSON prompt。",
                _json({"目标": shot["target"], "上次提示词": shot["prompt"], "原因": reason}),
            )
            prompt = str(revised["prompt"]).strip()
            if not prompt:
                raise ValueError("重试提示词为空")
            shot.update(prompt=prompt, attempt=attempt + 1, job="", clip="")
            progress("准备重试")


def _generate_shots(data, save):
    shots = data["shots"]
    pending = iter([i for i, shot in enumerate(shots) if not shot.get("passed")])
    lock = threading.Lock()

    def generate(index):
        shot = shots[index].copy()

        def checkpoint(stage):
            # Publish this shot and persist the ordered snapshot under the same lock.
            with lock:
                shots[index] = shot.copy()
                save(stage)

        try:
            _shot(data, shot, index + 1, checkpoint)
        except Exception as err:
            shot["stage"] = "失败 · " + str(err)[:220]
            x("UPDATE shots SET status='failed',progress=0 WHERE id=?", (shot["id"],))
            checkpoint(f"镜头 {index + 1}/{len(shots)} · {shot['stage']}")
            raise

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_SHOTS) as pool:
        active = set()
        while True:
            while len(active) < MAX_PARALLEL_SHOTS:
                index = next(pending, None)
                if index is None:
                    break
                active.add(pool.submit(generate, index))
            if not active:
                return
            finished, active = wait(active, return_when=FIRST_COMPLETED)
            for future in finished:
                future.result()


def _work(run_id):
    row = q1("SELECT * FROM auto_runs WHERE id=?", (run_id,))
    data = json.loads(row["data"])
    scope = (row["project_id"], row["sub_id"])

    def save(stage, status="running"):
        x("UPDATE auto_runs SET stage=?,status=?,data=? WHERE id=?", (stage, status, _json(data), run_id))

    try:
        _assets(data, scope, save)
        _plan(data, scope, save)
        _generate_shots(data, save)
        save("全部镜头通过，正在拼接导出")
        clips = [_media(s["clip"]) for s in data["shots"]]
        data["exportUrl"] = video.stitch(clips, [s["dur"] for s in data["shots"]])["url"]
        save("生成完成，已导出", "done")
    except Exception as err:
        save("任务失败 · " + str(err)[:300], "failed")


def _start(run_id):
    threading.Thread(target=_work, args=(run_id,), daemon=True).start()


def resume_runs():
    for row in q("SELECT id FROM auto_runs WHERE status='running'"):
        _start(row["id"])
