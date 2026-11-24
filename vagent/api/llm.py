# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import re
import threading
from pathlib import Path

from flask import Blueprint, current_app, request

from .. import config, images, llm
from ..db import now_text, q, q1, x
from ..providers import image as image_provider
from ..providers import video as video_provider
from ..repository import (
    add_asset_with_views,
    add_generated_asset,
    add_generating_asset,
    add_shot,
    current_ids,
    current_messages,
    save_asset_draft,
    save_asset_reference,
    set_asset_preview,
)
from ..responses import fail, ok
from ..serializers import jloads

bp = Blueprint("llm", __name__)


def _fixed_assets_ready(pid: str) -> dict:
    """硬闸：项目里没有可用的固定资产，就不许出视频。

    「固定资产」= 角色 / 场景类资产，且已经出过设定稿（``preview`` 里有图）。
    这条规则是**代码强制**的，不靠提示词自觉：视频工具在提交任何任务之前先过这里，
    不满足就把原因回给模型，由它去要求用户先生成三视图。
    """
    rows = q(
        "SELECT name, type, preview FROM assets WHERE project_id = ? AND archived = 0"
        " AND type IN ('角色', '场景')",
        (pid,),
    )
    if not rows:
        return {"ok": False, "reason": "这个项目里还没有角色或场景资产"}

    missing = []
    for row in rows:
        has_image = any(
            isinstance(item, dict) and item.get("kind") == "img" and item.get("url")
            for item in (jloads(row["preview"], []) or [])
        )
        if not has_image:
            missing.append("%s「%s」" % (row["type"], row["name"]))
    if missing:
        return {"ok": False, "reason": "这些固定资产还没有设定图：" + "、".join(missing[:4])}
    if not any(row["type"] == "角色" for row in rows):
        return {"ok": False, "reason": "还没有角色资产的三视图"}
    return {"ok": True, "reason": ""}


def _video_tool(args: dict, ref_image_path=None) -> dict:
    """视频工具：建镜头 + 提交 MiniMax 任务。只拿任务 ID，进度由视频页轮询。"""
    pid, sid = current_ids()
    if not pid or not sid:
        return {"ok": False, "error": "没有当前项目或子项目"}
    gate = _fixed_assets_ready(pid)
    if not gate["ok"]:
        return {
            "ok": False,
            "error": "还不能生成视频——%s。先为这个项目生成角色三视图和场景设定图，"
            "用户确认后再出视频。" % gate["reason"],
        }
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "提示词为空"}
    try:
        dur = float(args.get("dur") or 4)
    except (TypeError, ValueError):
        dur = 4.0
    dur = min(15.0, max(4.0, dur))
    try:
        if ref_image_path:
            ref = _image_data_url(Path(ref_image_path))
            task_id = video_provider.submit_reference(prompt, [ref], duration=dur)
        else:
            task_id = video_provider.submit(prompt, dur)
    except video_provider.VideoError as err:
        return {"ok": False, "error": err.message}
    shot = add_shot(str(args.get("name") or "视频镜头"), prompt, dur, provider_job=task_id)
    if not shot:
        return {"ok": False, "error": "镜头创建失败"}
    return {"ok": True, "shot_id": shot["id"], "task_id": task_id, "duration": dur}


CONFIRM_WORDS = (
    "开工",
    "确认",
    "可以",
    "好的",
    "好",
    "开始",
    "继续",
    "生成吧",
    "来吧",
    "没问题",
    "行",
    "嗯",
    "ok",
    "okay",
    "yes",
)


IMAGE_STEP_WORDS = ("设定图", "三视图", "出图", "资产描述", "生成图", "正面", "侧面", "背面")
VIDEO_STEP_WORDS = ("视频", "生成视频", "去视频", "视频页", "短片")
ASSET_CONTEXT_WORDS = (
    "角色",
    "人物",
    "她",
    "他",
    "场景",
    "背景",
    "地点",
    "外观",
    "服装",
    "设定",
    "风格",
    "参考图",
    "这张图",
    "这个角色",
    "这个场景",
)


def _has_asset_context(text: str, attachment: dict) -> bool:
    """带有资产语境的视频需求先交给主 Agent 理解，再进入确认卡。"""
    if isinstance(attachment, dict) and attachment.get("kind") == "图片":
        return True
    return any(word in (text or "") for word in ASSET_CONTEXT_WORDS)


def _save_plan_asset_drafts(plan: dict) -> list:
    """把主 Agent 识别的资产设定写入资产库，图片留到确认后生成。"""
    saved = []
    for item in (plan or {}).get("assets") or []:
        if not isinstance(item, dict):
            continue
        asset_type = str(item.get("type") or "其他").strip()
        name = str(item.get("name") or "").strip()
        desc = str(item.get("desc") or "").strip()
        if not name or not desc or asset_type not in ("角色", "场景", "风格", "其他"):
            continue
        asset = save_asset_draft(name, asset_type, desc, bool(item.get("locked", True)))
        if asset:
            saved.append(asset)
    return saved


def _pending_step(history) -> dict | None:
    """短确认时，看上一轮 Agent 问的是出图还是视频，只做那一步。"""
    for item in reversed(history or []):
        if item.get("role") != "agent":
            continue
        text = str(item.get("text") or "")
        if not text:
            continue
        image = any(word in text for word in IMAGE_STEP_WORDS)
        video = any(word in text for word in VIDEO_STEP_WORDS)
        if image and not video:
            return {"image": True, "video": False}
        if video and not image:
            return {"image": False, "video": True}
        return None
    return None


def _is_short_confirm(text: str) -> bool:
    """“开工 / 确认 / 可以 / 好”这类短回复，要沿用上一轮需求。"""
    clean = re.sub(r"[\s，。！？!?、,.~～]+", "", text or "")
    if not clean or len(clean) > 8:
        return False
    low = clean.lower()
    return any(word in low for word in CONFIRM_WORDS)


def _image_data_url(path: Path) -> str:
    suffix = path.suffix.lstrip(".").lower() or "png"
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else "image/%s" % suffix
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode("ascii"))


@bp.post("/api/intent")
def api_intent():
    """判断一句话有没有生成图片/视频的需求，前端和测试都可以先问它。"""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return fail("BAD_REQUEST", "text 不能为空")
    return ok(llm.detect_generation_need(text))


@bp.post("/api/auto/video")
def api_auto_video():
    """全自动模式：文字 + 参考图直接走 H3 全能参考，不追问、不经过语言模型。"""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return fail("BAD_REQUEST", "先写一句视频描述")
    attachment = body.get("attachment") or {}
    ref = None
    if isinstance(attachment, dict) and attachment.get("kind") == "图片":
        stored = str(attachment.get("stored") or "").strip()
        candidate = config.UPLOAD_DIR / Path(stored).name if stored else None
        if candidate and candidate.is_file():
            ref = _image_data_url(candidate)
    if not ref:
        return fail("BAD_REQUEST", "全自动模式需要上传一张参考图")
    match = re.search(r"(\d+(?:\.\d+)?)\s*秒", text)
    dur = float(match.group(1)) if match else 5.0
    dur = min(15.0, max(4.0, dur))
    project_sub = current_ids()
    if not all(project_sub):
        return fail("NO_PROJECT", "没有当前项目或子项目", 400)
    if body.get("prepareAssets"):
        if not llm.is_configured():
            return fail("BAD_REQUEST", "请在 API 设置中配置支持图片输入的语言模型", 400)
        assets = _generate_assets_tool({}, candidate, text)
        if not assets.get("ok"):
            return fail("BAD_REQUEST", assets["error"], 400)
    try:
        task_id = video_provider.submit_reference(text, [ref], duration=dur)
    except video_provider.VideoError as err:
        return fail(err.code, err.message, err.status)
    review = {"mode": "auto", "state": "queued", "job": task_id, "reference": candidate.name, "target": text}
    shot = add_shot(
        text[:12] or "全自动镜头", text, dur, provider_job=task_id, review=review, project_sub=project_sub
    )
    if not shot:
        return fail("INTERNAL_ERROR", "镜头创建失败", 500)
    if not current_app.testing:
        from .shots import start_auto_review

        start_auto_review(shot["id"], task_id)
    return ok({"shot": shot, "taskId": task_id})


def _deterministic_prompt(text: str, modules: dict) -> str:
    parts = [text.strip()]
    for key, label in (("role", "角色"), ("scene", "场景"), ("style", "风格")):
        value = str((modules.get(key) or {}).get("text") or "").strip()
        if value:
            parts.append("%s：%s" % (label, value))
    return "；".join(item for item in parts if item)


def _split_prompt(prompt: str, max_shots: int = 6) -> list:
    """把最终提示词按句子/分句切成逐镜提示词，太长时合并尾部。"""
    parts = [item.strip(" ，,") for item in re.split(r"[。！？!?；;\n]+", prompt) if item.strip(" ，,")]
    if len(parts) <= 1:
        pieces = [item.strip(" ，,") for item in re.split(r"[，,]", prompt) if item.strip(" ，,")]
        chunks, buf = [], ""
        for piece in pieces:
            if buf and len(buf) + len(piece) > 60:
                chunks.append(buf)
                buf = piece
            else:
                buf = (buf + "，" + piece) if buf else piece
        if buf:
            chunks.append(buf)
        parts = chunks or [prompt]
    if len(parts) > max_shots:
        parts = parts[: max_shots - 1] + ["；".join(parts[max_shots - 1 :])]
    return parts


@bp.post("/api/video/final-prompt")
def api_video_final_prompt():
    """最终提示词：合并需求 + 三模块 + 资产，建一个待生成镜头，不提交视频任务。"""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return fail("BAD_REQUEST", "原需求不能为空")
    modules = body.get("modules") or {}
    assets = [str(item) for item in (body.get("assets") or []) if item]
    attachment = body.get("attachment") or {}
    ref_image_path = None
    if isinstance(attachment, dict) and attachment.get("kind") == "图片":
        stored = str(attachment.get("stored") or "").strip()
        candidate = config.UPLOAD_DIR / Path(stored).name if stored else None
        if candidate and candidate.is_file():
            ref_image_path = candidate

    plan = None
    cfg = llm.resolve_config()
    force_expand = bool(body.get("force_expand"))
    llm_error = None
    if cfg["api_key"]:
        for _ in range(2):
            try:
                plan = llm.compose_video_plan(text, modules, assets, ref_image_path)
                break
            except llm.LLMError as err:
                llm_error = err
    elif force_expand:
        return fail("BAD_REQUEST", "还没有配置语言模型 API Key，无法强制扩写提示词", 400)

    if force_expand and not plan:
        message = llm_error.message if llm_error else "语言模型没有返回扩写结果"
        return fail(
            llm_error.code if llm_error else "INTERNAL_ERROR",
            "提示词扩写失败：%s；请检查语言模型后重试" % message,
            llm_error.status if llm_error else 500,
        )

    match = re.search(r"(\d+(?:\.\d+)?)\s*秒", text)
    dur = float(match.group(1)) if match else 4.0
    dur = min(15.0, max(4.0, dur))
    if plan:
        prompt = plan["prompt"]
        specs = plan["shots"]
    else:
        prompt = _deterministic_prompt(text, modules)
        specs = [
            {"prompt": segment, "dur": dur, "title": llm.short_shot_title(segment, index)}
            for index, segment in enumerate(_split_prompt(prompt), 1)
        ]

    shots = []
    folder = config.UPLOAD_DIR / "gen" / "shots"
    if ref_image_path:
        folder.mkdir(parents=True, exist_ok=True)
        suffix = Path(ref_image_path).suffix.lower() or ".png"
    for index, spec in enumerate(specs, 1):
        segment = str(spec.get("prompt") or "").strip()
        if not segment:
            continue
        try:
            shot_dur = int(round(float(spec.get("dur") or dur)))
        except (TypeError, ValueError):
            shot_dur = int(round(dur))
        shot_dur = min(15, max(4, shot_dur))
        title = str(spec.get("title") or "").strip() or llm.short_shot_title(segment, index)
        shot = add_shot(title[:30], segment, shot_dur, status="pending", ai="")
        if not shot:
            continue
        if ref_image_path:
            (folder / ("%s-first%s" % (shot["id"], suffix))).write_bytes(Path(ref_image_path).read_bytes())
        shots.append(shot)
    if not shots:
        return fail("INTERNAL_ERROR", "镜头创建失败", 500)

    asset_details = []
    ref_url = ""
    if isinstance(attachment, dict) and attachment.get("kind") == "图片":
        ref_url = str(attachment.get("url") or "").strip()
    if assets:
        for row in q(
            "SELECT id, name, type, desc, preview, ref_image FROM assets"
            " WHERE project_id = ? AND name IN (%s) ORDER BY updated_at DESC" % ",".join("?" for _ in assets),
            (current_ids()[0], *assets),
        ):
            if ref_url and not row["ref_image"]:
                x(
                    "UPDATE assets SET ref_image = ?, updated_at = ? WHERE id = ?",
                    (ref_url, now_text(), row["id"]),
                )
            asset_details.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "type": row["type"],
                    "desc": row["desc"],
                    "preview": [
                        item.get("url")
                        for item in (jloads(row["preview"], []) or [])
                        if isinstance(item, dict) and item.get("url")
                    ][:3],
                    "needsReferenceViews": bool(ref_url and row["type"] == "角色"),
                }
            )
    return ok(
        {
            "shot": shots[0],
            "shots": shots,
            "prompt": prompt,
            "dur": shots[0]["dur"],
            "assets": assets,
            "assetDetails": asset_details,
        }
    )


def _generate_assets_tool(args: dict, ref_image_path=None, default_text: str = "") -> dict:
    """Agent 工具：先生成角色三视图和场景概念图，作为视频设定资产。"""
    cfg = image_provider.resolve_config()
    if not cfg["api_key"]:
        return {"ok": False, "error": "还没有配置图片模型 API Key"}
    role_desc = str(args.get("role") or "").strip() or default_text or "角色"
    scene_desc = str(args.get("scene") or "").strip() or default_text or "场景"
    role_name = str(args.get("role_name") or "").strip()[:30]
    scene_name = str(args.get("scene_name") or "").strip()[:30]
    refs = [str(ref_image_path)] if ref_image_path else []

    def draft_name(asset_type: str, fallback: str) -> str:
        pid, _sid = current_ids()
        rows = q(
            "SELECT name, preview FROM assets WHERE project_id = ? AND type = ?"
            " AND archived = 0 ORDER BY updated_at DESC LIMIT 8",
            (pid, asset_type),
        )
        for row in rows:
            preview = jloads(row["preview"], [])
            if not any(
                isinstance(item, dict) and item.get("kind") == "img" and item.get("url") for item in preview
            ):
                return row["name"]
        return fallback

    role_asset = add_generating_asset(role_name or draft_name("角色", "角色·最终设定"), "角色", role_desc)
    scene_asset = add_generating_asset(scene_name or draft_name("场景", "场景·最终设定"), "场景", scene_desc)
    if not role_asset and not scene_asset:
        return {"ok": False, "error": "资产创建失败"}
    _run_final_asset_job(
        role_asset["id"] if role_asset else "",
        scene_asset["id"] if scene_asset else "",
        role_desc,
        scene_desc,
        refs,
    )
    created = []
    for asset, label in ((role_asset, "角色"), (scene_asset, "场景")):
        if not asset:
            continue
        row = q1("SELECT * FROM assets WHERE id = ?", (asset["id"],))
        if not row:
            continue
        preview = jloads(row["preview"], [])
        if preview:
            created.append({"id": row["id"], "name": row["name"], "type": row["type"], "desc": row["desc"]})
    if not created:
        return {"ok": False, "error": "设定图生成失败，未得到可用资产"}
    return {"ok": True, "assets": created, "message": "已生成角色三视图和场景概念图"}


def _local_upload(url):
    if not url or not str(url).startswith("/uploads/"):
        return None
    path = (config.UPLOAD_DIR / str(url)[len("/uploads/") :]).resolve()
    try:
        path.relative_to(config.UPLOAD_DIR.resolve())
    except ValueError:
        return None
    return str(path) if path.is_file() else None


def _guess_asset(history, text: str, asset_refs: dict):
    """兜底：找当前要改的资产（引用名优先，其次最近更新的资产）。"""
    pid, _sid = current_ids()
    if not pid:
        return None
    for item in reversed(history or []):
        if item.get("role") != "agent":
            continue
        match = re.search(r"「([^」]+)」", str(item.get("text") or ""))
        if match:
            row = q1("SELECT * FROM assets WHERE project_id = ? AND name = ?", (pid, match.group(1)))
            if row:
                return row
        break
    for name in asset_refs or {}:
        if name and name in text:
            row = q1("SELECT * FROM assets WHERE project_id = ? AND name = ?", (pid, name))
            if row:
                return row
    return q1("SELECT * FROM assets WHERE project_id = ? ORDER BY updated_at DESC LIMIT 1", (pid,))


def _text_arg(value) -> str:
    if isinstance(value, (list, tuple)):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _classify_modification(text: str, history, asset_refs: dict) -> dict:
    """判断用户要修改的对象：asset / shot / video / none。"""
    t = str(text or "").strip()
    cancel_shot = re.search(r"(不要|别|不用)(再)?(改|动).{0,2}(镜头|分镜)", t)
    cancel_asset = re.search(r"(不要|别|不用)(再)?(改|动).{0,2}(资产|角色|设定图)", t)
    shot_change = re.search(r"(改|修改|调整|优化|重做).{0,6}(镜头|分镜)", t)
    if shot_change and not cancel_shot:
        return {"target": "shot", "reason": "用户明确要改镜头"}
    if cancel_shot:
        return {"target": "none", "reason": "用户明确不改镜头"}
    asset_change = re.search(r"(改|修改|调整|更新|优化|重做).{0,6}(资产|角色|场景|设定图|外观|形象)", t)
    if asset_change and not cancel_asset:
        return {"target": "asset", "reason": "用户明确要改资产"}
    if cancel_asset:
        return {"target": "none", "reason": "用户明确不改资产"}
    if re.search(r"(视频|整片|成片)", t) and re.search(r"(改|修改|调整|重做|生成)", t):
        return {"target": "video", "reason": "用户指向整片"}

    agent_seen = 0
    last_agent = ""
    for item in reversed(history or []):
        if item.get("role") != "agent":
            continue
        agent_seen += 1
        meta = item.get("meta") or {}
        agent_text = str(item.get("text") or "")
        if agent_seen == 1:
            last_agent = agent_text
        if meta.get("assetProposals") or meta.get("assetDraft") or meta.get("assetUpdates"):
            return {"target": "asset", "reason": "仍在资产修改会话"}
        if agent_seen >= 4:
            break
    if re.search(r"(镜头|分镜)", last_agent):
        return {"target": "shot", "reason": "上一轮在聊镜头"}
    if re.search(r"(资产|角色|设定图|外观)", last_agent):
        return {"target": "asset", "reason": "上一轮在聊资产"}
    if any(name and name in t for name in (asset_refs or {})):
        return {"target": "asset", "reason": "提到已有资产名"}
    return {"target": "none", "reason": "无法判断"}


def _judge_modify_tool(args: dict, history, asset_refs: dict) -> dict:
    text = str(args.get("text") or "").strip()
    result = _classify_modification(text, history, asset_refs)
    target = result["target"]
    asset_name = ""
    if target == "asset":
        for item in reversed(history or []):
            if item.get("role") != "agent":
                continue
            match = re.search(r"「([^」]+)」", str(item.get("text") or ""))
            if match:
                asset_name = match.group(1)
                break
        if not asset_name:
            for name in asset_refs or {}:
                if name in text:
                    asset_name = name
                    break
    shot_no = ""
    if target == "shot":
        _pid, sid = current_ids()
        if sid:
            row = q1("SELECT no FROM shots WHERE sub_id = ? ORDER BY created_at ASC LIMIT 1", (sid,))
            shot_no = row["no"] if row else ""
    return {"ok": True, **result, "assetName": asset_name, "shotNo": shot_no}


def _propose_asset_change_tool(args: dict) -> dict:
    """先返回详细变更方案，不生成图片、不覆盖资产。"""
    pid, _sid = current_ids()
    if not pid:
        return {"ok": False, "error": "没有当前项目"}
    name = _text_arg(args.get("name"))
    desc = _text_arg(args.get("desc"))
    if not name or not desc:
        return {"ok": False, "error": "需要资产名称和修改后的描述"}
    row = q1("SELECT * FROM assets WHERE project_id = ? AND name = ?", (pid, name))
    if not row:
        return {"ok": False, "error": "资产库里没有「%s」" % name}
    return {
        "ok": True,
        "proposal": {
            "assetId": row["id"],
            "assetName": row["name"],
            "type": row["type"],
            "desc": desc,
            "changes": _text_arg(args.get("changes")),
        },
    }


def _update_asset_tool(args: dict, ref_image_path=None) -> dict:
    """修改已有资产的描述并重新生成设定图（角色三视图 / 场景概念图）。"""
    pid, _sid = current_ids()
    if not pid:
        return {"ok": False, "error": "没有当前项目"}
    name = str(args.get("name") or "").strip()
    desc = str(args.get("desc") or "").strip()
    if not name or not desc:
        return {"ok": False, "error": "需要资产名称和更新后的描述"}
    row = q1("SELECT * FROM assets WHERE project_id = ? AND name = ?", (pid, name))
    if not row:
        return {"ok": False, "error": "资产库里没有「%s」" % name}
    cfg = image_provider.resolve_config()
    if not cfg["api_key"]:
        return {"ok": False, "error": "还没有配置图片模型 API Key"}
    ref = ref_image_path or _local_upload(row["ref_image"])
    if not ref:
        for item in jloads(row["preview"], []):
            if isinstance(item, dict) and item.get("kind") == "img":
                ref = _local_upload(item.get("url"))
                if ref:
                    break
    try:
        images.configure(mode="live", api_key=cfg["api_key"], image_model=cfg["model"])
        if row["type"] == "角色":
            result = images.run(
                {
                    "kind": "keyframe",
                    "payload": {
                        "task": "asset_views",
                        "asset_id": row["id"],
                        "name": name,
                        "type": "角色",
                        "desc": desc,
                        "ref_images": [str(ref)] if ref else [],
                    },
                }
            )
            urls = [item["url"] for item in (result.get("views") or []) if item.get("url")]
            if not urls:
                return {"ok": False, "error": "三视图生成失败"}
            asset = add_asset_with_views(name, row["type"], desc, urls, row["ref_image"] or "")
        else:
            result = images.run(
                {
                    "kind": "keyframe",
                    "payload": {
                        "task": "asset_image",
                        "asset_id": row["id"],
                        "name": name,
                        "type": row["type"],
                        "desc": desc,
                        "ref_images": [str(ref)] if ref else [],
                    },
                }
            )
            views = [item for item in (result.get("views") or []) if item.get("url")]
            if not views:
                return {"ok": False, "error": "概念图生成失败"}
            asset = add_generated_asset(name, row["type"], desc, views[0]["url"])
    except (RuntimeError, ValueError) as err:
        return {"ok": False, "error": str(err)[:300]}
    if not asset:
        return {"ok": False, "error": "资产更新失败"}
    previews = [item["url"] for item in (asset.get("preview") or []) if item.get("url")]
    return {
        "ok": True,
        "asset": {
            "id": asset["id"],
            "name": asset["name"],
            "type": asset["type"],
            "desc": asset.get("desc", ""),
            "updatedAt": asset.get("updatedAt", ""),
            "previews": previews,
        },
    }


def _shot_update_tool(args: dict) -> dict:
    """更新指定镜头的提示词；按编号定位。"""
    _pid, sid = current_ids()
    if not sid:
        return {"ok": False, "error": "没有当前子项目"}
    shot_no = str(args.get("shot_no") or "").strip()
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return {"ok": False, "error": "镜头提示词为空"}
    rows = q("SELECT * FROM shots WHERE sub_id = ? ORDER BY created_at ASC, id ASC", (sid,))
    target = None
    target_no = ""
    for index, row in enumerate(rows, 1):
        no = "%02d" % index
        if no.lstrip("0") == shot_no.lstrip("0") or str(row["name"]).strip() == shot_no:
            target = row
            target_no = no
            break
    if target is None:
        return {"ok": False, "error": "没有找到镜头 %s" % shot_no}
    x("UPDATE shots SET prompt = ?, updated_at = ? WHERE id = ?", (prompt, now_text(), target["id"]))
    return {"ok": True, "shot_id": target["id"], "shot_no": target_no}


def _run_final_asset_job(role_id, scene_id, role_desc, scene_desc, refs):
    """后台生成角色三视图 / 场景概念图，完成后回填预览。"""
    cfg = image_provider.resolve_config()
    if not cfg["api_key"]:
        if role_id:
            set_asset_preview(role_id, [])
        if scene_id:
            set_asset_preview(scene_id, [])
        return
    try:
        images.configure(mode="live", api_key=cfg["api_key"], image_model=cfg["model"])
    except Exception:  # noqa: BLE001
        if role_id:
            set_asset_preview(role_id, [])
        if scene_id:
            set_asset_preview(scene_id, [])
        return

    if role_id:
        try:
            result = images.run(
                {
                    "kind": "keyframe",
                    "payload": {
                        "task": "asset_views",
                        "asset_id": role_id,
                        "name": "角色·最终设定",
                        "type": "角色",
                        "desc": role_desc,
                        "ref_images": refs,
                    },
                }
            )
            urls = [item["url"] for item in (result.get("views") or []) if item.get("url")]
            labels = ["正面", "侧面", "背面"]
            preview = [
                {"kind": "img", "url": url, "label": labels[index] if index < 3 else "生成图"}
                for index, url in enumerate(urls[:3])
            ]
            set_asset_preview(role_id, preview)
        except Exception:  # noqa: BLE001
            set_asset_preview(role_id, [])

    if scene_id:
        try:
            result = images.run(
                {
                    "kind": "keyframe",
                    "payload": {
                        "task": "asset_image",
                        "asset_id": scene_id,
                        "name": "场景·最终设定",
                        "type": "场景",
                        "desc": scene_desc,
                        "ref_images": refs,
                    },
                }
            )
            views = [item for item in (result.get("views") or []) if item.get("url")]
            preview = [{"kind": "img", "url": views[0]["url"], "label": "概念图"}] if views else []
            set_asset_preview(scene_id, preview)
        except Exception:  # noqa: BLE001
            set_asset_preview(scene_id, [])


@bp.post("/api/video/final-assets")
def api_video_final_assets():
    """按最终提示词生成相关资产：角色三视图 + 场景概念图。"""
    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return fail("BAD_REQUEST", "最终提示词不能为空")
    modules = body.get("modules") or {}
    ref_url = str(body.get("ref") or "").strip()
    ref_path = None
    if ref_url.startswith("/uploads/"):
        candidate = (config.UPLOAD_DIR / ref_url[len("/uploads/") :]).resolve()
        try:
            candidate.relative_to(config.UPLOAD_DIR.resolve())
        except ValueError:
            candidate = None
        if candidate and candidate.is_file():
            ref_path = candidate

    cfg = image_provider.resolve_config()
    if not cfg["api_key"]:
        return fail("BAD_REQUEST", "还没有配置图片模型 API Key")
    refs = [str(ref_path)] if ref_path else []
    ref_url = ref_url if ref_path else ""

    role = modules.get("role") or {}
    role_desc = (role.get("text") or "").strip() or prompt
    scene = modules.get("scene") or {}
    scene_desc = (scene.get("text") or "").strip() or prompt

    role_asset = add_generating_asset("角色·最终设定", "角色", role_desc, ref_url)
    scene_asset = add_generating_asset("场景·最终设定", "场景", scene_desc, ref_url)
    created = [asset for asset in (role_asset, scene_asset) if asset]
    if not created:
        return fail("INTERNAL_ERROR", "资产创建失败", 500)

    threading.Thread(
        target=_run_final_asset_job,
        args=(
            role_asset["id"] if role_asset else "",
            scene_asset["id"] if scene_asset else "",
            role_desc,
            scene_desc,
            refs,
        ),
        daemon=True,
    ).start()
    return ok({"assets": created, "generating": True})


@bp.post("/api/llm/plan")
def api_llm_plan():
    """把一句自然语言拆成分镜，不写数据库、不创建任何对象。"""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return fail("BAD_REQUEST", "镜头描述不能为空")
    if len(text) > 2000:
        return fail("BAD_REQUEST", "描述太长了，控制在 2000 字以内")
    cfg = llm.resolve_config()
    if not cfg["api_key"]:
        return fail("BAD_REQUEST", "还没有配置语言模型 API Key")
    history = current_messages()
    if history and history[-1].get("role") == "user" and (history[-1].get("text") or "").strip() == text:
        history = history[:-1]
    pid, _sid = current_ids()
    rows = (
        q(
            "SELECT name, type, desc, locked, preview, ref_image FROM assets WHERE project_id = ?"
            " ORDER BY updated_at DESC LIMIT 12",
            (pid,),
        )
        if pid
        else []
    )

    def _asset_line(row):
        desc = (row["desc"] or "").strip()[:30]
        return f"{row['type']}「{row['name']}」{('：' + desc) if desc else ''}"

    parts = []
    locked = [row for row in rows if row["locked"]]
    if locked:
        parts.append("已锁定：" + "；".join(_asset_line(row) for row in locked))
    rest = [row for row in rows if not row["locked"]]
    if rest:
        parts.append("其他：" + "；".join(_asset_line(row) for row in rest))
    context = "\n".join(parts)

    # 确认三视图时用户通常不会再传图：回退到资产上存的参考图/第一张预览图
    def _local_upload(url):
        if not url or not str(url).startswith("/uploads/"):
            return None
        path = (config.UPLOAD_DIR / str(url)[len("/uploads/") :]).resolve()
        try:
            path.relative_to(config.UPLOAD_DIR.resolve())
        except ValueError:
            return None
        return str(path) if path.is_file() else None

    asset_refs = {}
    for row in rows:
        ref = _local_upload(row["ref_image"])
        if not ref:
            for item in jloads(row["preview"], []):
                if isinstance(item, dict) and item.get("kind") == "img":
                    ref = _local_upload(item.get("url"))
                    if ref:
                        break
        if ref:
            asset_refs[row["name"]] = ref

    attachment = body.get("attachment") or {}
    ref_image_path = None
    if isinstance(attachment, dict) and attachment.get("kind") == "图片":
        stored = str(attachment.get("stored") or "").strip()
        candidate = config.UPLOAD_DIR / Path(stored).name if stored else None
        if candidate and candidate.is_file():
            ref_image_path = candidate
    auto = bool(body.get("auto"))
    short_confirm = _is_short_confirm(text)
    confirm_kind = str(body.get("confirm_kind") or "").strip()
    confirm = ("三项已确认" in text) or ("不要再追问" in text) or short_confirm or bool(confirm_kind)
    need = llm.detect_generation_need(text)
    if confirm_kind == "asset":
        need = {"image": True, "video": False}
    elif confirm_kind == "shot":
        need = {"image": False, "video": False}
    elif confirm_kind == "video":
        need = {"image": False, "video": True}
    elif short_confirm and "三项已确认" not in text:
        pending = _pending_step(history)
        if pending:
            need = pending
    shot_edit = False
    asset_edit = False
    if not confirm_kind and not need["video"]:
        verdict = _classify_modification(text, history, asset_refs)
        if verdict["target"] == "shot":
            shot_edit = True
            need = {"image": False, "video": False}
        elif verdict["target"] == "asset":
            asset_edit = True
            need = {"image": True, "video": False}
        elif verdict["target"] == "video":
            need = {"image": False, "video": True}
    if confirm and not (need["image"] or need["video"]):
        # 确认消息本身没有“照片/视频”等词，回退到上一条用户需求判断
        for item in reversed(history):
            if item.get("role") == "user":
                prev = llm.detect_generation_need(str(item.get("text") or ""))
                if prev["image"] or prev["video"]:
                    need = prev
                    break
    if confirm and ref_image_path is None:
        # 确认轮通常不会重复传图：取最近一条带图片附件的用户消息
        for item in reversed(history):
            if item.get("role") != "user":
                continue
            attachment_meta = item.get("meta") or {}
            attachment = attachment_meta.get("attachment") or {}
            stored = str(attachment.get("stored") or "").strip()
            if attachment.get("kind") == "图片" and stored:
                candidate = config.UPLOAD_DIR / Path(stored).name
                if candidate.is_file():
                    ref_image_path = candidate
                    break
    review_video_assets = need["video"] and not auto and not confirm and _has_asset_context(text, attachment)
    if need["video"] and not auto and not confirm and not review_video_assets:
        # 普通模式：没有资产语境时保留三模块确认，避免直接提交视频任务
        questions = [
            {
                "text": "角色：上传图片 / 文字描述 / Agent 自动补全",
                "options": ["上传图片", "文字描述", "Agent 自动补全"],
            },
            {
                "text": "场景：上传图片 / 文字描述 / Agent 自动补全",
                "options": ["上传图片", "文字描述", "Agent 自动补全"],
            },
            {
                "text": "风格：上传图片 / 文字描述 / Agent 自动补全",
                "options": ["上传图片", "文字描述", "Agent 自动补全"],
            },
        ]
        plan = {
            "summary": "生成视频前，先确认角色、场景和风格。",
            "shots": [],
            "assets": [],
            "questions": questions,
            "clarify": {"needed": True, "questions": questions},
        }
        return ok(
            {
                "plan": plan,
                "images": [],
                "videos": [],
                "reply": "生成视频前，先确认角色、场景和风格，选完会自动继续。",
                "model": cfg["model"],
                "intent": need,
            }
        )
    try:
        result = llm.chat_plan(
            text,
            history=history,
            context=context,
            ref_image_path=ref_image_path,
            video_handler=None if review_video_assets else _video_tool,
            asset_refs=asset_refs,
            need=need,
            no_clarify=confirm or asset_edit,
            shot_handler=_shot_update_tool if (confirm_kind == "shot" or shot_edit) else None,
            asset_handler=(
                None if review_video_assets else lambda args, ref: _generate_assets_tool(args, ref, text)
            ),
            assets_first=bool(auto and need.get("video")),
            asset_update_handler=lambda args, ref: _update_asset_tool(args, ref),
            force_asset_update=confirm_kind == "asset",
            asset_proposal_handler=_propose_asset_change_tool,
            force_asset_proposal=asset_edit,
            force_shot_update=shot_edit,
            modify_judge_handler=lambda args: _judge_modify_tool(args, history, asset_refs),
            defer_generation=review_video_assets,
        )
    except llm.LLMError as err:
        return fail(err.code, err.message, err.status)
    if asset_edit and not result.get("asset_proposals"):
        row = _guess_asset(history, text, asset_refs)
        if row:
            fallback = _propose_asset_change_tool(
                {
                    "name": row["name"],
                    "desc": ("%s；%s" % (row["desc"] or "", text)).strip("；"),
                    "changes": text,
                }
            )
            if fallback.get("ok"):
                result["asset_proposals"] = [fallback["proposal"]]
    if review_video_assets:
        attachment_url = str(attachment.get("url") or "").strip() if isinstance(attachment, dict) else ""
        if attachment_url:
            for item in (result.get("plan") or {}).get("assets") or []:
                if item.get("type") == "角色":
                    asset = save_asset_reference(
                        str(item.get("name") or "角色·参考图"),
                        "角色",
                        str(item.get("desc") or text),
                        attachment_url,
                    )
                    if asset:
                        result.setdefault("asset_updates", []).append(asset)
                    break
        _save_plan_asset_drafts(result.get("plan") or {})
        if isinstance(result.get("plan"), dict) and not result["plan"].get("questions"):
            question = {
                "text": "请确认角色、场景和风格：可上传图片、填写描述，或交给 Agent 自动补全。",
                "options": ["上传图片", "文字描述", "Agent 自动补全"],
            }
            result["plan"]["questions"] = [question]
            result["plan"]["clarify"] = {"needed": True, "questions": [question], "missing": []}
    if confirm and isinstance(result.get("plan"), dict):
        result["plan"]["questions"] = []
    for image in result["images"]:
        asset = add_generated_asset(image["name"], image["type"], image["desc"], image["url"])
        if asset:
            image["assetId"] = asset["id"]
    for group in result.get("three_views") or []:
        asset = add_asset_with_views(
            group["name"], group["type"], group["desc"], group["urls"], group.get("ref", "")
        )
        for url in group["urls"]:
            result["images"].append(
                {
                    "name": group["name"],
                    "type": group["type"],
                    "desc": group["desc"],
                    "url": url,
                    "assetId": asset["id"] if asset else None,
                }
            )
    return ok(
        {
            "plan": result["plan"],
            "images": result["images"],
            "assetUpdates": [
                {
                    **asset,
                    "previews": asset.get("previews")
                    or [
                        item.get("url")
                        for item in (asset.get("preview") or [])
                        if isinstance(item, dict) and item.get("url")
                    ],
                }
                for asset in result.get("asset_updates", [])
            ],
            "assetProposals": result.get("asset_proposals", []),
            "videos": result["videos"],
            "reply": result["reply"],
            "contextUsage": result.get("contextUsage"),
            "model": cfg["model"],
            "intent": need,
        }
    )
