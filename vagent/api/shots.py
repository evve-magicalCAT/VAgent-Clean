# -*- coding: utf-8 -*-
from __future__ import annotations
import base64
import json
import os
import time
import threading
import uuid
from pathlib import Path
import shutil
from flask import Blueprint, request
from .. import config, images, llm
from ..images.frames import sample_frames
from ..config import FRAMES, TONES
from ..db import _LOCK, conn, q, q1, x, now_text
from ..providers import image as image_provider
from ..providers import video as video_provider
from ..repository import current_ids, current_shots, ensure_current
from ..responses import fail, ok
from ..serializers import jloads, row_to_shot


bp = Blueprint("shots", __name__)

# 首帧由 B 落在 uploads/gen/shots/<shot_id>-first.<ext>，这里按同一约定读回
_FRAME_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# 出图模型最不擅长画手：手一贴近脸就容易多指、粘连。首帧阶段先把手约束住，
# 否则坏首帧会被视频模型原样放大。只加在给模型的提示词里，不改用户存的镜头提示词。
_FRAME_HAND_RULE = "双手自然下垂或自然摆动，不要贴近、遮挡或贴住脸部；手指数量正确、结构清晰、不交叉。"


def _frame_dir() -> Path:
    return config.UPLOAD_DIR / "gen" / "shots"


def _frame_url(path) -> str:
    """换成浏览器能访问的 /uploads/... 地址；不在 uploads 下就返回空串。"""
    if not path:
        return ""
    try:
        rel = Path(path).resolve().relative_to(config.UPLOAD_DIR.resolve())
    except (ValueError, OSError):
        return ""
    return "/uploads/" + rel.as_posix()


def find_first_frame(shot_id: str):
    """按约定找这个镜头已经存好的首帧。没有就返回 None。"""
    base = _frame_dir() / ("%s-first" % shot_id)
    for ext in _FRAME_EXTS:
        path = base.with_suffix(ext)
        if path.exists():
            return path
    return None


def _frame_marker(shot_id: str) -> Path:
    """首帧确认标记；不新增数据库字段，把确认状态和首帧文件放在一起。"""
    return _frame_dir() / ("%s-first.confirmed" % shot_id)


def _clear_first_frame_confirmation(shot_id: str) -> None:
    try:
        _frame_marker(shot_id).unlink()
    except OSError:
        pass


def _mark_first_frame_confirmed(shot_id: str, path: Path) -> None:
    """记录当前首帧的 mtime/size；首帧被外部覆盖后标记自动失效。"""
    path = Path(path)
    try:
        stat = path.stat()
    except OSError as err:
        raise video_provider.VideoError("INTERNAL_ERROR", "首帧文件不存在，无法确认", 500) from err
    marker = _frame_marker(shot_id)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {"mtime_ns": stat.st_mtime_ns, "size": stat.st_size, "at": now_text()},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _is_first_frame_confirmed(shot_id: str, path: Path | None) -> bool:
    if not path:
        return False
    try:
        stat = Path(path).stat()
        meta = json.loads(_frame_marker(shot_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False
    if not isinstance(meta, dict):
        return False
    return meta.get("mtime_ns") == stat.st_mtime_ns and meta.get("size") == stat.st_size


def ensure_first_frame(row, force: bool = False) -> Path:
    """没有首帧就让图片 Agent 出一张；没配图片 key 时走 mock，保证链路不断。

    ``force`` 用于「重抽」：先删掉旧文件，再重新出一张。重抽或新出图都会
    清掉确认标记，必须重新给用户确认。
    """
    if force:
        old = find_first_frame(row["id"])
        _clear_first_frame_confirmation(row["id"])
        if old:
            try:
                Path(old).unlink()
            except OSError:
                pass
    hit = find_first_frame(row["id"])
    if hit:
        return hit
    _clear_first_frame_confirmation(row["id"])
    cfg = image_provider.resolve_config()
    if cfg.get("api_key"):
        images.configure(
            mode="live", api_key=cfg["api_key"], image_model=cfg["model"], base_url=cfg.get("base_url", "")
        )
    else:
        images.configure(mode="mock")
    text = (row["prompt"] or row["name"] or "").strip()
    prompt = (text + "。" if text else "") + _FRAME_HAND_RULE
    result = images.run({"kind": "keyframe", "payload": {"shot_id": row["id"], "prompt": prompt}})
    path = Path(result["first_frame"])
    if not path.exists():
        raise video_provider.VideoError("INTERNAL_ERROR", "首帧生成失败：没有落盘", 500)
    return path


def _data_url(path: Path) -> str:
    """MiniMax 接受 base64 data URL，本地首帧不用先传图床。"""
    suffix = path.suffix.lstrip(".").lower() or "png"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return "data:image/%s;base64,%s" % (suffix, payload)


def _asset_image_path(row):
    """资产参考图落盘路径：优先 ref_image，其次预览里的第一张真图。"""
    urls = []
    if row["ref_image"]:
        urls.append(row["ref_image"])
    for item in jloads(row["preview"], []):
        if isinstance(item, dict) and item.get("kind") == "img" and item.get("url"):
            urls.append(item["url"])
    for url in urls:
        if not str(url).startswith("/uploads/"):
            continue
        path = (config.UPLOAD_DIR / str(url)[len("/uploads/") :].split("?")[0]).resolve()
        try:
            path.relative_to(config.UPLOAD_DIR.resolve())
        except ValueError:
            continue
        if path.is_file():
            return path
    return None


def _asset_image_paths(row, limit: int = 3):
    """资产可用于比对的所有本地图片：参考图 + 三视图，最多 ``limit`` 张。

    ``_asset_image_path`` 只取第一张（选参考图够用）；抽帧校验要拿整个角色的
    正/侧/背去比，所以这里返回全部。
    """
    urls = []
    if row["ref_image"]:
        urls.append(row["ref_image"])
    for item in jloads(row["preview"], []):
        if isinstance(item, dict) and item.get("kind") == "img" and item.get("url"):
            urls.append(item["url"])
    out = []
    for url in urls:
        if not str(url).startswith("/uploads/"):
            continue
        path = (config.UPLOAD_DIR / str(url)[len("/uploads/") :].split("?")[0]).resolve()
        try:
            path.relative_to(config.UPLOAD_DIR.resolve())
        except ValueError:
            continue
        if path.is_file() and path not in out:
            out.append(path)
            if len(out) >= limit:
                break
    return out


def _select_shot_assets(project_id: str, prompt: str, limit: int = 4):
    """Agent 自动选择：优先提示词里出现的资产名，其次最新角色/场景。"""
    rows = q(
        "SELECT * FROM assets WHERE project_id = ? AND archived = 0 ORDER BY updated_at DESC",
        (project_id,),
    )
    usable = [(row, _asset_image_path(row)) for row in rows]
    usable = [(row, path) for row, path in usable if path]
    if not usable:
        return []
    named = [(row, path) for row, path in usable if row["name"] and row["name"] in prompt]
    picked = list(named[:limit])
    picked_ids = {row["id"] for row, _path in picked}
    for wanted in ("角色", "场景"):
        if len(picked) >= limit:
            break
        for row, path in usable:
            if row["id"] not in picked_ids and row["type"] == wanted:
                picked.append((row, path))
                picked_ids.add(row["id"])
                break
    for row, path in usable:
        if len(picked) >= limit:
            break
        if row["id"] not in picked_ids:
            picked.append((row, path))
            picked_ids.add(row["id"])
    return picked[:limit]


@bp.get("/api/shots")
def api_shots():
    ensure_current()
    shots = current_shots()
    return ok({"shots": shots, "total": len(shots), "totalDur": round(sum(s["dur"] for s in shots), 2)})


@bp.post("/api/shots")
def api_shot_create():
    ensure_current()
    pid, sid = current_ids()
    if not pid or not sid:
        return fail("NO_PROJECT", "请先新建项目和子项目", 400)
    body = request.get_json(silent=True) or {}
    count = q1("SELECT COUNT(*) AS n FROM shots WHERE sub_id = ?", (sid,))["n"]
    sid_new = f"{sid}-{int(time.time() * 1000) % 1000000}{uuid.uuid4().hex[:4]}"
    frame = FRAMES[count % len(FRAMES)]
    tones = TONES[count % len(TONES)]
    ts = now_text()
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO shots (id, project_id, sub_id, name, dur, status, frame, locked, prompt,"
            " tones, progress, ai, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sid_new,
                pid,
                sid,
                (body.get("name") or f"镜头 {count + 1}").strip(),
                float(body.get("dur") or 3.0),
                "pending",
                frame,
                0,
                (body.get("prompt") or "").strip(),
                json.dumps(tones),
                0,
                "",
                ts,
                ts,
            ),
        )
    shots = current_shots()
    return ok({"shot": next((s for s in shots if s["id"] == sid_new), None), "shots": shots})


@bp.patch("/api/shots/<shot_id>")
def api_shot_patch(shot_id):
    row = q1("SELECT * FROM shots WHERE id = ?", (shot_id,))
    if not row:
        return fail("SHOT_NOT_FOUND", f"镜头「{shot_id}」不存在", 404)
    body = request.get_json(silent=True) or {}
    fields, args = [], []
    if isinstance(body.get("prompt"), str):
        if not body["prompt"].strip():
            return fail("BAD_REQUEST", "prompt 不能为空")
        fields.append("prompt = ?")
        args.append(body["prompt"].strip())
    if isinstance(body.get("name"), str) and body["name"].strip():
        fields.append("name = ?")
        args.append(body["name"].strip())
    if body.get("dur") is not None:
        try:
            fields.append("dur = ?")
            args.append(round(float(body["dur"]), 2))
        except (TypeError, ValueError):
            return fail("BAD_REQUEST", "dur 必须是数字")
    if isinstance(body.get("status"), str) and body["status"].strip():
        fields.append("status = ?")
        args.append(body["status"].strip())
    if isinstance(body.get("frame"), str) and body["frame"].strip():
        fields.append("frame = ?")
        args.append(body["frame"].strip())
    if isinstance(body.get("tones"), list) and body["tones"]:
        fields.append("tones = ?")
        args.append(json.dumps(body["tones"]))
    if isinstance(body.get("locked"), bool):
        fields.append("locked = ?")
        args.append(1 if body["locked"] else 0)
    if isinstance(body.get("refMode"), bool):
        fields.append("ref_mode = ?")
        args.append(1 if body["refMode"] else 0)
    if isinstance(body.get("refAssets"), list):
        fields.append("ref_assets = ?")
        args.append(json.dumps([str(item) for item in body["refAssets"] if item]))
    if body.get("progress") is not None:
        try:
            fields.append("progress = ?")
            args.append(max(0, min(100, int(body["progress"]))))
        except (TypeError, ValueError):
            return fail("BAD_REQUEST", "progress 必须是 0-100 的整数")
    if isinstance(body.get("ai"), str):
        fields.append("ai = ?")
        args.append(body["ai"])
    if not fields:
        return fail("BAD_REQUEST", "没有可更新的字段")
    # 提示词变了，旧首帧就不再对应这镜内容；涉及资产模式切换也会让首帧失效。
    prompt_changed = isinstance(body.get("prompt"), str) and body["prompt"].strip() != (row["prompt"] or "")
    ref_mode_changed = isinstance(body.get("refMode"), bool) and bool(body["refMode"]) != bool(
        row["ref_mode"]
    )
    if prompt_changed or ref_mode_changed:
        _clear_first_frame_confirmation(shot_id)
    fields.append("updated_at = ?")
    args.append(now_text())
    args.append(shot_id)
    x(f"UPDATE shots SET {', '.join(fields)} WHERE id = ?", tuple(args))
    shots = current_shots()
    return ok({"shot": next((s for s in shots if s["id"] == shot_id), None)})


@bp.delete("/api/shots/<shot_id>")
def api_shot_delete(shot_id):
    if not q1("SELECT id FROM shots WHERE id = ?", (shot_id,)):
        return fail("SHOT_NOT_FOUND", f"镜头「{shot_id}」不存在", 404)
    x("DELETE FROM shots WHERE id = ?", (shot_id,))
    return ok({"deleted": shot_id, "shots": current_shots()})


@bp.post("/api/shots/<shot_id>/split")
def api_shot_split(shot_id):
    row = q1("SELECT * FROM shots WHERE id = ?", (shot_id,))
    if not row:
        return fail("SHOT_NOT_FOUND", f"镜头「{shot_id}」不存在", 404)
    body = request.get_json(silent=True) or {}
    dur = float(row["dur"])
    ratio = body.get("ratio")
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        ratio = 0.5
    ratio = min(0.9, max(0.1, ratio))
    head = round(dur * ratio, 2)
    tail = round(dur - head, 2)
    new_id = f"{row['sub_id']}-{int(time.time() * 1000) % 1000000}{uuid.uuid4().hex[:4]}"
    ts = now_text()
    with _LOCK, conn() as c:
        c.execute("UPDATE shots SET dur = ?, updated_at = ? WHERE id = ?", (head, ts, shot_id))
        c.execute(
            "INSERT INTO shots (id, project_id, sub_id, name, dur, status, frame, locked, prompt,"
            " tones, progress, ai, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                new_id,
                row["project_id"],
                row["sub_id"],
                f"{row['name']} · 后半",
                tail,
                "pending",
                row["frame"],
                0,
                row["prompt"],
                row["tones"],
                0,
                "",
                ts,
                ts,
            ),
        )
    return ok({"shots": current_shots(), "newId": new_id})


@bp.put("/api/shots/bulk")
def api_shots_bulk():
    """整组替换当前子项目的镜头：用于撤销、文字剪辑、排序。"""
    ensure_current()
    pid, sid = current_ids()
    if not pid or not sid:
        return fail("NO_PROJECT", "没有当前子项目", 400)
    body = request.get_json(silent=True) or {}
    shots = body.get("shots")
    if not isinstance(shots, list):
        return fail("BAD_REQUEST", "shots 必须是数组")
    ts = now_text()
    with _LOCK, conn() as c:
        c.execute("DELETE FROM shots WHERE sub_id = ?", (sid,))
        for i, s in enumerate(shots):
            new_id = s.get("id") or f"{sid}-{int(time.time() * 1000) % 1000000}{uuid.uuid4().hex[:4]}{i}"
            c.execute(
                "INSERT INTO shots (id, project_id, sub_id, name, dur, status, frame, locked, prompt,"
                " tones, progress, ai, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id,
                    pid,
                    sid,
                    s.get("name") or f"镜头 {i + 1}",
                    float(s.get("dur") or 3.0),
                    s.get("status") or "pending",
                    s.get("frame") or "street",
                    1 if s.get("locked") else 0,
                    s.get("prompt") or "",
                    json.dumps(s.get("tones") or TONES[i % len(TONES)]),
                    0,
                    s.get("ai") or "",
                    ts,
                    ts,
                ),
            )
    return ok({"shots": current_shots()})


@bp.post("/api/shots/<shot_id>/video")
def api_shot_video_submit(shot_id):
    """视频 Agent：提交一次逐镜生成。只拿任务 ID，结果由 GET 轮询。"""
    row = q1("SELECT * FROM shots WHERE id = ?", (shot_id,))
    if not row:
        return fail("SHOT_NOT_FOUND", f"镜头「{shot_id}」不存在", 404)
    if row["provider_job"] and row["status"] == "redraw":
        return ok({"shot": row_to_shot(row), "taskId": row["provider_job"], "state": "running"})
    prompt = (row["prompt"] or "").strip()
    if not prompt:
        return fail("BAD_REQUEST", "镜头还没有提示词")
    mode = "first_frame"
    first_frame_url = ""
    used_assets = []
    try:
        if row["ref_mode"]:
            selected_ids = [str(item) for item in jloads(row["ref_assets"], [])]
            picked = []
            if selected_ids:
                for asset_id in selected_ids:
                    asset = q1(
                        "SELECT * FROM assets WHERE id = ? AND project_id = ?", (asset_id, row["project_id"])
                    )
                    path = _asset_image_path(asset) if asset else None
                    if asset and path:
                        picked.append((asset, path))
            if not picked:
                picked = _select_shot_assets(row["project_id"], prompt)
            if not picked:
                return fail("BAD_REQUEST", "涉及资产模式下没有可用资产，请先生成或上传资产", 400)
            used_assets = [asset["id"] for asset, _path in picked]
            descriptions = []
            for asset, path in picked:
                descriptions.append("%s：%s" % (asset["name"], (asset["desc"] or "").strip()))
            full_prompt = prompt + "\n\n参考资产设定：\n" + "\n".join(descriptions)
            task_id = video_provider.submit_reference(
                full_prompt,
                [_data_url(path) for _asset, path in picked],
                duration=float(row["dur"]),
            )
            if not selected_ids:
                x(
                    "UPDATE shots SET ref_assets = ? WHERE id = ?",
                    (json.dumps(used_assets), shot_id),
                )
            mode = "assets"
        else:
            # 首帧模式不再自动补图：必须先由用户在视频页生成并确认首帧。
            frame = find_first_frame(shot_id)
            if not frame:
                return fail("BAD_REQUEST", "请先生成并确认首帧，再生成视频", 400)
            if not _is_first_frame_confirmed(shot_id, frame):
                return fail("BAD_REQUEST", "首帧还没有确认，请确认后再生成视频", 400)
            first_frame_url = _frame_url(frame)
            task_id = video_provider.submit(prompt, float(row["dur"]), first_frame=_data_url(frame))
    except video_provider.VideoError as err:
        return fail(err.code, err.message, err.status)
    x(
        "UPDATE shots SET provider_job = ?, status = 'redraw', progress = 0, ai = 'video',"
        " clip_path = '', updated_at = ? WHERE id = ?",
        (task_id, now_text(), shot_id),
    )
    return ok(
        {
            "shot": row_to_shot(q1("SELECT * FROM shots WHERE id = ?", (shot_id,))),
            "taskId": task_id,
            "state": "queued",
            "mode": mode,
            "firstFrame": first_frame_url,
            "assets": used_assets,
        }
    )


@bp.post("/api/shots/<shot_id>/ref-assets/auto")
def api_shot_ref_assets_auto(shot_id):
    """Agent 自动选择这个镜头涉及的资产。"""
    row = q1("SELECT * FROM shots WHERE id = ?", (shot_id,))
    if not row:
        return fail("SHOT_NOT_FOUND", f"镜头「{shot_id}」不存在", 404)
    picked = _select_shot_assets(row["project_id"], row["prompt"] or "")
    if not picked:
        return fail("BAD_REQUEST", "资产库里还没有可用图片，请先生成资产", 400)
    ids = [asset["id"] for asset, _path in picked]
    x(
        "UPDATE shots SET ref_mode = 1, ref_assets = ?, updated_at = ? WHERE id = ?",
        (json.dumps(ids), now_text(), shot_id),
    )
    return ok(
        {
            "shot": row_to_shot(q1("SELECT * FROM shots WHERE id = ?", (shot_id,))),
            "assetIds": ids,
        }
    )


@bp.get("/api/shots/<shot_id>/video")
def api_shot_video_status(shot_id):
    """查询逐镜生成进度；成功时下载并写回 clip_path。前端每隔几秒调一次。"""
    row = q1("SELECT * FROM shots WHERE id = ?", (shot_id,))
    if not row:
        return fail("SHOT_NOT_FOUND", f"镜头「{shot_id}」不存在", 404)
    review = row_to_shot(row)["review"]
    if review.get("mode") == "auto":
        if not row["clip_path"]:
            state = "failed" if row["status"] == "failed" else "running"
        else:
            state = "succeeded" if review.get("state") == "done" else "running"
        return ok(
            {
                "state": state,
                "clipUrl": row["clip_path"],
                "shot": row_to_shot(row),
                "error": review.get("summary", ""),
            }
        )
    if row["clip_path"]:
        # 已经有成片就直接返回；顺带把状态补正成已确认，避免界面永远停在「生成中」
        if row["status"] != "confirmed" or int(row["progress"] or 0) != 100:
            x(
                "UPDATE shots SET status = 'confirmed', progress = 100, updated_at = ? WHERE id = ?",
                (now_text(), shot_id),
            )
            row = q1("SELECT * FROM shots WHERE id = ?", (shot_id,))
        return ok({"state": "succeeded", "clipUrl": row["clip_path"], "shot": row_to_shot(row)})
    job = row["provider_job"]
    if not job:
        return fail("BAD_REQUEST", "这个镜头还没有提交视频任务")
    try:
        info = video_provider.query(job)
    except video_provider.VideoError as err:
        return fail(err.code, err.message, err.status)
    ts = now_text()
    if info["state"] == "succeeded":
        try:
            clip = video_provider.download(info["url"])
        except video_provider.VideoError as err:
            return fail(err.code, err.message, err.status)
        x(
            "UPDATE shots SET clip_path = ?, status = 'confirmed', progress = 100, ai = '', updated_at = ?"
            " WHERE id = ?",
            (clip, ts, shot_id),
        )
        return ok(
            {
                "state": "succeeded",
                "clipUrl": clip,
                "shot": row_to_shot(q1("SELECT * FROM shots WHERE id = ?", (shot_id,))),
            }
        )
    if info["state"] in ("failed", "cancelled"):
        x(
            "UPDATE shots SET status = 'failed', progress = 0, ai = '', updated_at = ? WHERE id = ?",
            (ts, shot_id),
        )
        return ok(
            {
                "state": info["state"],
                "error": str(info.get("error") or ""),
                "shot": row_to_shot(q1("SELECT * FROM shots WHERE id = ?", (shot_id,))),
            }
        )
    # 模型不报百分比，这里按状态给一个粗略进度，别让界面永远停在 0%
    x(
        "UPDATE shots SET progress = ?, updated_at = ? WHERE id = ?",
        (10 if info["state"] == "queued" else 50, ts, shot_id),
    )
    return ok(
        {
            "state": info["state"],
            "clipUrl": "",
            "shot": row_to_shot(q1("SELECT * FROM shots WHERE id = ?", (shot_id,))),
        }
    )


@bp.get("/api/shots/<shot_id>/keyframe")
def api_shot_keyframe_get(shot_id):
    """读这个镜头已经存好的首帧（B 出的图）。没有就 exists=false，不报错。"""
    if not q1("SELECT id FROM shots WHERE id = ?", (shot_id,)):
        return fail("SHOT_NOT_FOUND", f"镜头「{shot_id}」不存在", 404)
    path = find_first_frame(shot_id)
    return ok(
        {
            "shotId": shot_id,
            "url": _frame_url(path),
            "exists": bool(path),
            "confirmed": _is_first_frame_confirmed(shot_id, path),
        }
    )


@bp.post("/api/shots/<shot_id>/keyframe")
def api_shot_keyframe_generate(shot_id):
    """让图片 Agent 给这个镜头出一张首帧。已存在就直接返回，不重复花钱。

    ``{"force": true}`` 表示重抽：删掉旧图再出，用于手指贴脸这类瑕疵。
    ``{"confirm": true}`` 表示用户已确认这张首帧，允许后续提交视频。
    """
    row = q1("SELECT * FROM shots WHERE id = ?", (shot_id,))
    if not row:
        return fail("SHOT_NOT_FOUND", f"镜头「{shot_id}」不存在", 404)
    if not (row["prompt"] or "").strip():
        return fail("BAD_REQUEST", "镜头还没有提示词")
    body = request.get_json(silent=True) or {}
    force = bool(body.get("force"))
    confirm = bool(body.get("confirm"))
    if confirm and not force and not find_first_frame(shot_id):
        return fail("BAD_REQUEST", "请先生成首帧，确认前需要先看到画面", 400)
    try:
        path = ensure_first_frame(row, force=force)
        if confirm:
            _mark_first_frame_confirmed(shot_id, path)
    except video_provider.VideoError as err:
        return fail(err.code, err.message, err.status)
    except (RuntimeError, ValueError, OSError) as err:
        return fail("INTERNAL_ERROR", f"首帧生成失败：{str(err)[:300]}", 500)
    return ok(
        {
            "shotId": shot_id,
            "url": _frame_url(path),
            "exists": True,
            "confirmed": _is_first_frame_confirmed(shot_id, path),
        }
    )


@bp.post("/api/shots/<shot_id>/review")
def api_shot_review(shot_id):
    row = q1("SELECT * FROM shots WHERE id = ?", (shot_id,))
    if not row:
        return fail("SHOT_NOT_FOUND", f"镜头「{shot_id}」不存在", 404)
    body = request.get_json(silent=True) or {}
    mode = body.get("mode")
    if mode not in ("manual", "auto"):
        return fail("BAD_REQUEST", "请选择手动或自动确认")
    prior = row_to_shot(row)["review"]
    if prior.get("mode") == "auto" and prior.get("state") != "done":
        return ok(prior)
    if prior.get("mode") == "auto":
        mode = "auto"
    try:
        result = _review_content(row, mode, body.get("prompt", row["prompt"]))
    except llm.LLMError as err:
        return fail(err.code, err.message, err.status)
    x(
        "UPDATE shots SET review = ? WHERE id = ? AND clip_path = ? AND provider_job = ?",
        (json.dumps(result, ensure_ascii=False), shot_id, row["clip_path"], row["provider_job"]),
    )
    return ok(result)


def _review_content(row, mode, target, reference=None):
    clip = _local_media(row["clip_path"])
    if not clip or not clip.is_file() or not clip.resolve().is_relative_to(config.UPLOAD_DIR.resolve()):
        raise llm.LLMError("BAD_REQUEST", "这个镜头还没有可读取的成片", 400)
    cfg = llm.resolve_config()
    if not llm.is_configured(cfg):
        raise llm.LLMError("BAD_REQUEST", "请在 API 设置中配置支持图片输入的语言模型", 400)
    refs = config.BASE_DIR / "skills" / "minimax-h3-video-reverse-skill" / "references"
    if not isinstance(target, str):
        raise llm.LLMError("BAD_REQUEST", "镜头提示词须为文本", 400)
    try:
        guide = "\n".join(
            (refs / name).read_text(encoding="utf-8")
            for name in ("video-observation.md", "narrative-confirmation.md")
        )
        system = (
            guide + "\n当前只执行内容确认阶段。输入是按时间排序的画面抽样，未核听声音。"
            "分镜目标是对照资料，不能当作画面证据。不要补写未看见的事件或生成新提示词。"
            "只返回 JSON。summary 用中文简述实际可见的主体、动作起止、场景和运镜。"
            "另用 reason 简要说明哪些提示词要求与画面吻合、冲突或无法核实。"
            "verdict 只能是 pass（一致）、fail（有明确的关键冲突）或 uncertain（证据不足）。"
            "明确区分未在采样帧中看清和观察到矛盾；有明确冲突优先判 fail。"
        )
        temp = config.UPLOAD_DIR / "gen" / "reviews" / uuid.uuid4().hex
        temp.mkdir(parents=True)
        try:
            ratios = (0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 0.99)
            paths = sample_frames(clip, temp, "review", ratios=ratios)
            content = [{"type": "image_url", "image_url": {"url": llm._data_uri(p)}} for p in paths]
        finally:
            shutil.rmtree(temp)
        content.append({"type": "text", "text": "分镜目标：" + target})
        if reference:
            content.append({"type": "text", "text": "下面是用户最初提供的参考图，仅作目标对照。"})
            content.append({"type": "image_url", "image_url": {"url": llm._data_uri(reference)}})
        response = llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": content}],
            cfg=cfg,
            temperature=0.1,
        )
        result = llm._extract_json(response)
        summary = result.get("summary")
        verdict = result.get("verdict")
        reason = result.get("reason")
        if (
            not isinstance(summary, str)
            or not summary.strip()
            or verdict not in ("pass", "fail", "uncertain")
            or not isinstance(reason, str)
            or not reason.strip()
        ):
            raise llm.LLMError("INTERNAL_ERROR", "模型未返回完整的审核结果", 502)
    except llm.LLMError:
        raise
    except (OSError, RuntimeError, ValueError) as err:
        raise llm.LLMError("INTERNAL_ERROR", f"成片审核失败：{str(err)[:300]}", 500) from err
    return {
        "shotId": row["id"],
        "job": row["provider_job"],
        "clip": row["clip_path"],
        "mode": mode,
        "state": "done",
        "summary": summary.strip(),
        "verdict": verdict,
        "reason": reason.strip(),
        "target": target,
    }


def _auto_process(shot_id, job):
    failures = 0
    while True:
        row = q1("SELECT * FROM shots WHERE id = ? AND provider_job = ?", (shot_id, job))
        if not row:
            return
        review = jloads(row["review"], {})
        if review.get("job") != job or review.get("state") != "queued":
            return
        try:
            if row["clip_path"]:
                reference = config.UPLOAD_DIR / Path(review["reference"]).name
                result = _review_content(row, "auto", review["target"], reference)
                break
            info = video_provider.query(job)
            if info["state"] == "succeeded":
                clip = video_provider.download(info["url"])
                x(
                    "UPDATE shots SET clip_path = ?, progress = 100, status = 'confirmed', ai = '', updated_at = ? WHERE id = ? AND provider_job = ?",
                    (clip, now_text(), shot_id, job),
                )
                failures = 0
                continue
            if info["state"] in ("failed", "cancelled"):
                result = {**review, "summary": str(info.get("error") or "视频生成失败"), "verdict": "error"}
                break
            failures = 0
        except (llm.LLMError, video_provider.VideoError, OSError, ValueError) as err:
            failures += 1
            if failures >= 3 or getattr(err, "status", 500) < 500:
                result = {**review, "verdict": "error", "summary": str(err)[:400]}
                break
        time.sleep(5)
    result["state"] = "done"
    x(
        "UPDATE shots SET review = ?, status = CASE WHEN clip_path = '' THEN 'failed' ELSE status END, updated_at = ? WHERE id = ? AND provider_job = ?",
        (json.dumps(result, ensure_ascii=False), now_text(), shot_id, job),
    )


def start_auto_review(shot_id, job):
    threading.Thread(target=_auto_process, args=(shot_id, job), daemon=True).start()


def resume_auto_reviews():
    for row in q("SELECT id, provider_job, review FROM shots WHERE review != '{}'"):
        review = jloads(row["review"], {})
        if (
            review.get("mode") == "auto"
            and review.get("state") == "queued"
            and review.get("job") == row["provider_job"]
        ):
            start_auto_review(row["id"], row["provider_job"])


@bp.post("/api/shots/<shot_id>/verify")
def api_shot_verify(shot_id):
    """抽帧校验：从成片里抽 3 帧，跟资产设定图比对，判断还是不是同一个主体。

    只做判定、不改镜头状态：不通过时由用户决定重抽哪一镜。
    """
    row = q1("SELECT * FROM shots WHERE id = ?", (shot_id,))
    if not row:
        return fail("SHOT_NOT_FOUND", f"镜头「{shot_id}」不存在", 404)
    clip = _local_media(row["clip_path"])
    if not clip:
        return fail("BAD_REQUEST", "这个镜头还没有生成视频，先出片再校验")
    picked = []
    for asset_id in [str(item) for item in jloads(row["ref_assets"], [])]:
        asset = q1("SELECT * FROM assets WHERE id = ? AND project_id = ?", (asset_id, row["project_id"]))
        if asset:
            picked.append(asset)
    if not picked:
        picked = [asset for asset, _path in _select_shot_assets(row["project_id"], row["prompt"] or "")]
    refs = []
    for asset in picked:
        refs.extend(_asset_image_paths(asset))
    if not refs:
        return fail("BAD_REQUEST", "这个镜头没有可比的资产图，请先生成资产三视图")
    cfg = image_provider.resolve_config()
    key = cfg.get("api_key") or os.environ.get("ARK_API_KEY", "")
    if key:
        images.configure(mode="live", api_key=key, image_model=cfg["model"], base_url=cfg.get("base_url", ""))
    else:
        images.configure(mode="mock")
    try:
        got = images.run(
            {
                "kind": "verify",
                "payload": {
                    "task": "verify",
                    "clip": str(clip),
                    "ref_images": [str(path) for path in refs[:6]],
                    "prefix": shot_id,
                },
            }
        )
    except (RuntimeError, ValueError, OSError) as err:
        return fail("INTERNAL_ERROR", f"抽帧校验失败：{str(err)[:300]}", 500)
    return ok(
        {
            "shotId": shot_id,
            "pass": bool(got.get("pass")),
            "issues": got.get("issues") or [],
            "frames": [{"url": _frame_url(path)} for path in got.get("frames") or []],
            "refs": [{"url": _frame_url(path)} for path in got.get("refs") or []],
        }
    )


def _local_media(url: str):
    """把 /uploads/... 换成磁盘路径；不存在就返回 None。"""
    if not url or not url.startswith("/uploads/"):
        return None
    path = config.UPLOAD_DIR / url[len("/uploads/") :]
    return path if path.exists() else None


@bp.post("/api/shots/stitch")
def api_shots_stitch():
    """把当前子项目里已生成的镜头按时间轴拼成一条成片。

    模型只给 6 / 10 秒，这里按每个镜头在时间轴上的 dur 裁齐：
    ``{"mode": "trim"}`` 裁掉多余、定格补足；``{"mode": "speed"}`` 整段变速对齐。
    """
    ensure_current()
    pid, sid = current_ids()
    if not sid:
        return fail("NO_PROJECT", "没有当前子项目", 400)
    rows = q("SELECT * FROM shots WHERE sub_id = ? ORDER BY created_at ASC, id ASC", (sid,))
    if not rows:
        return fail("BAD_REQUEST", "当前子项目还没有镜头")
    body = request.get_json(silent=True) or {}
    mode = "speed" if body.get("mode") == "speed" else "trim"
    clips, durations, missing = [], [], []
    for row in rows:
        local = _local_media(row["clip_path"])
        if not local:
            missing.append(row["name"] or row["id"])
            continue
        clips.append(local)
        durations.append(float(row["dur"]))
    if missing:
        return fail("BAD_REQUEST", "这些镜头还没有生成视频：%s" % "、".join(missing[:6]), 400)
    try:
        got = video_provider.stitch(clips, durations, mode=mode)
    except video_provider.VideoError as err:
        return fail(err.code, err.message, err.status)
    return ok({"url": got["url"], "duration": got["duration"], "count": len(clips), "mode": mode})


@bp.post("/api/shots/generate")
def api_shots_generate():
    ensure_current()
    pid, sid = current_ids()
    if not sid:
        return fail("NO_PROJECT", "没有当前子项目", 400)
    shots = q("SELECT id, dur FROM shots WHERE sub_id = ?", (sid,))
    ts = now_text()
    with _LOCK, conn() as c:
        for s in shots:
            c.execute(
                "UPDATE shots SET status = 'confirmed', progress = 0, updated_at = ? WHERE id = ?",
                (ts, s["id"]),
            )
    total = sum(float(s["dur"]) for s in shots)
    return ok({"count": len(shots), "totalDur": round(total, 2), "shots": current_shots()})
