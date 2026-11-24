# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import re
import uuid
from pathlib import Path
from flask import Blueprint, request
from .. import config, images, llm
from ..config import DEFAULT_ASSET_SCOPE
from ..db import _LOCK, conn, q, q1, record_api_call, x, now_text
from ..providers import image as image_provider
from ..repository import current_ids, ensure_current, next_id, scope_assets, scope_stats, sub_of_project
from ..responses import fail, ok
from ..serializers import jloads, row_to_asset


bp = Blueprint("assets", __name__)


@bp.get("/api/assets")
def api_assets():
    ensure_current()
    scope = request.args.get("scope") or DEFAULT_ASSET_SCOPE
    scope = "project" if scope in ("current", "project") else scope
    pid, sid = current_ids()
    pid = request.args.get("projectId") or pid
    sid = request.args.get("subId") or sid
    assets = scope_assets(scope, pid, sid)
    return ok(
        {
            "scope": scope,
            "requested": request.args.get("scope") or DEFAULT_ASSET_SCOPE,
            "assets": assets,
            "stats": scope_stats(assets),
            "total": len(assets),
        }
    )


def _parse_preview(raw):
    return raw if isinstance(raw, list) else []


VIEW_LABELS = {
    "front": "正面",
    "side": "侧面",
    "back": "背面",
    "concept": "概念图",
    "sheet": "三视图",
}


def save_asset_views(asset_id, views, ai="none"):
    """把 ``images.run_asset_views()`` 的结果写回资产记录。

    Agent 自己不碰数据库（README 6.1），所以这一步由调用方在这里做：拿到
    ``run(job)`` 的返回值之后调它，页面刷新就能看到图。

    返回更新后的资产 dict；资产不存在抛 ``LookupError``。
    """
    aid = str(asset_id or "").strip()
    if not q1("SELECT id FROM assets WHERE id = ?", (aid,)):
        raise LookupError(f"资产「{aid}」不存在")
    preview = []
    for item in _parse_preview(views):
        if not isinstance(item, dict):
            continue
        url = item.get("url") or ""
        if not url:
            # 图不在 uploads 下面（比如测试临时目录），前端没法访问，不写进去
            continue
        view = item.get("view") or ""
        preview.append({"kind": "img", "url": url, "label": VIEW_LABELS.get(view, view)})
    x(
        "UPDATE assets SET preview = ?, ai = ?, updated_at = ? WHERE id = ?",
        (json.dumps(preview, ensure_ascii=False), ai, now_text(), aid),
    )
    return row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (aid,)))


ENRICH_SYSTEM = (
    "你是 AI 绘图提示词工程师。把用户给的资产设定扩写成一段具体的视觉描述："
    "外貌、发型、体型、服装材质与配色、神态；场景类资产写空间结构、材质、光线和关键物件。"
    "不要写视角、构图、镜头、画幅或尺寸；不要编造与原设定冲突的信息；"
    "只输出这段描述，不要解释、不要 Markdown、不超过 200 字。"
)


def _enrich_prompt(base: str) -> str:
    """先用语言模型扩写资产设定；没配置或调用失败时退回原描述，不阻断出图。"""
    if not base:
        return base
    if not llm.is_configured():
        return base
    try:
        text = llm.chat(
            [{"role": "system", "content": ENRICH_SYSTEM}, {"role": "user", "content": base}],
            temperature=0.5,
        )
    except llm.LLMError:
        return base
    text = text.strip().strip("`").strip()
    if len(text) < 8:
        return base
    return text[:1200]


def _upload_path(url: str):
    """把 /uploads/... 换成磁盘路径；不在 uploads 下或文件不存在返回 None。"""
    if not url.startswith("/uploads/"):
        return None
    try:
        path = (config.UPLOAD_DIR / url[len("/uploads/") :]).resolve()
        path.relative_to(config.UPLOAD_DIR.resolve())
    except (ValueError, OSError):
        return None
    return path if path.is_file() else None


@bp.post("/api/assets/from-image")
def api_asset_from_image():
    """把对话里已经生成的图片转存成资产：复制图片地址与描述，不调用图片模型。"""
    ensure_current()
    pid, sid = current_ids()
    if not pid:
        return fail("NO_PROJECT", "请先新建一个项目", 400)
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    if not _upload_path(url):
        return fail("BAD_REQUEST", "图片地址无效或文件不存在")
    name = (body.get("name") or "").strip()[:30] or "对话图片"
    asset_type = (body.get("type") or "其他").strip()
    if asset_type not in ("角色", "场景", "风格", "其他"):
        asset_type = "其他"
    desc = (body.get("desc") or name).strip()[:500]

    for row in q("SELECT * FROM assets WHERE project_id = ?", (pid,)):
        for item in jloads(row["preview"], []) or []:
            if isinstance(item, dict) and item.get("url") == url:
                return ok({"asset": row_to_asset(row), "created": False})

    aid = next_id("assets", "a")
    preview = json.dumps([{"kind": "img", "url": url, "label": "生成图"}], ensure_ascii=False)
    ts = now_text()
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO assets (id, project_id, sub_id, name, type, source, locked, desc, ai,"
            " preview, ref_shots, archived, from_project, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,'',?,?)",
            (aid, pid, sid, name, asset_type, "private", 0, desc, "none", preview, "[]", ts, ts),
        )
    return ok({"asset": row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (aid,))), "created": True})


@bp.post("/api/assets")
def api_asset_create():
    ensure_current()
    pid, sid = current_ids()
    if not pid:
        return fail("NO_PROJECT", "请先新建一个项目", 400)
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return fail("BAD_REQUEST", "资产名不能为空")
    aid = next_id("assets", "a")
    sub_id = body.get("subId") or sid or ""
    source = "inherit" if body.get("scopeLevel") == "inherit" else "private"
    if source == "inherit":
        sub_id = ""
    preview = body.get("preview") or [
        {"kind": "fig", "sym": "fig-front", "label": "正面"},
        {"kind": "fig", "sym": "fig-side", "label": "侧面"},
        {"kind": "fig", "sym": "fig-back", "label": "背面"},
    ]
    ts = now_text()
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO assets (id, project_id, sub_id, name, type, source, locked, desc, ai,"
            " preview, ref_shots, archived, from_project, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,'',?,?)",
            (
                aid,
                pid,
                sub_id,
                name,
                (body.get("type") or "角色").strip(),
                source,
                1 if body.get("locked") else 0,
                (body.get("desc") or "").strip(),
                "none",
                json.dumps(preview, ensure_ascii=False),
                "[]",
                ts,
                ts,
            ),
        )
    return ok({"asset": row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (aid,)))})


@bp.patch("/api/assets/<aid>")
def api_asset_patch(aid):
    row = q1("SELECT * FROM assets WHERE id = ?", (aid,))
    if not row:
        return fail("ASSET_NOT_FOUND", f"资产「{aid}」不存在", 404)
    body = request.get_json(silent=True) or {}
    fields, args = [], []
    if isinstance(body.get("prompt"), str) or isinstance(body.get("desc"), str):
        text = body.get("prompt") if isinstance(body.get("prompt"), str) else body.get("desc")
        if not text or not text.strip():
            return fail("BAD_REQUEST", "prompt 不能为空")
        fields.append("desc = ?")
        args.append(text.strip())
    if isinstance(body.get("name"), str) and body["name"].strip():
        fields.append("name = ?")
        args.append(body["name"].strip())
    if isinstance(body.get("type"), str) and body["type"].strip():
        fields.append("type = ?")
        args.append(body["type"].strip())
    if isinstance(body.get("locked"), bool):
        fields.append("locked = ?")
        args.append(1 if body["locked"] else 0)
    if isinstance(body.get("ai"), str):
        fields.append("ai = ?")
        args.append(body["ai"])
    if isinstance(body.get("refShots"), list):
        fields.append("ref_shots = ?")
        args.append(json.dumps(body["refShots"], ensure_ascii=False))
    if isinstance(body.get("tags"), list):
        fields.append("tags = ?")
        args.append(json.dumps(body["tags"], ensure_ascii=False))
    if not fields:
        return fail("BAD_REQUEST", "没有可更新的字段")
    fields.append("updated_at = ?")
    args.append(now_text())
    args.append(aid)
    x(f"UPDATE assets SET {', '.join(fields)} WHERE id = ?", tuple(args))
    return ok({"asset": row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (aid,)))})


@bp.delete("/api/assets/<aid>")
def api_asset_delete(aid):
    if not q1("SELECT id FROM assets WHERE id = ?", (aid,)):
        return fail("ASSET_NOT_FOUND", f"资产「{aid}」不存在", 404)
    x("DELETE FROM assets WHERE id = ?", (aid,))
    return ok({"deleted": aid})


ENRICH_ASSET_SYSTEM = (
    "你是 Vagent 的主 Agent，负责把资产设定写清楚。"
    "用户会给一个资产的原始描述和项目上下文。在不改变主体身份、不添加矛盾信息的前提下，"
    "把它扩写成一段可直接用于 AI 出图的中文视觉设定：主体外观、发型或材质、服装与配色、"
    "神态或动作、环境与光线、画面风格。"
    "不要写视角、构图、画幅、镜头参数；不要解释；不要 Markdown；只输出扩写后的完整描述，150 字以内。"
)


def _asset_context(asset: dict) -> str:
    """项目与近期镜头给主 Agent 当上下文，避免扩写脱离整片风格。"""
    pid, _sid = current_ids()
    parts = []
    if pid:
        proj = q1("SELECT name, kind, desc FROM projects WHERE id = ?", (pid,))
        if proj:
            line = f"项目「{proj['name']}」（{proj['kind']}）"
            if proj["desc"]:
                line += "：" + proj["desc"]
            parts.append(line)
        shots = q(
            "SELECT name, prompt FROM shots WHERE project_id = ? ORDER BY created_at DESC LIMIT 3",
            (pid,),
        )
        for shot in shots:
            text = (shot["prompt"] or "").strip()
            if text:
                parts.append(f"近期镜头「{shot['name']}」：{text[:120]}")
    tags = asset.get("tags") or []
    if tags:
        parts.append("风格标签：" + "、".join(str(tag) for tag in tags))
    return "\n".join(parts)


@bp.post("/api/assets/<aid>/enrich")
def api_asset_enrich(aid):
    """主 Agent 结合项目与镜头上下文扩写资产描述，并记录这一次的结果。"""
    row = q1("SELECT * FROM assets WHERE id = ?", (aid,))
    if not row:
        return fail("ASSET_NOT_FOUND", f"资产「{aid}」不存在", 404)
    if row["locked"]:
        return fail("BAD_REQUEST", "资产已锁定，先解锁再丰富描述")
    asset = row_to_asset(row)
    cfg = llm.resolve_config()
    if not cfg["api_key"]:
        return fail("BAD_REQUEST", "还没有配置主 Agent 的语言模型")
    base = (asset.get("desc") or "").strip() or asset["name"]
    user = f"资产名称：{asset['name']}\n资产类型：{asset['type']}\n原描述：{base}"
    context = _asset_context(asset)
    if context:
        user += f"\n\n上下文：\n{context}"
    try:
        text = llm.chat(
            [{"role": "system", "content": ENRICH_ASSET_SYSTEM}, {"role": "user", "content": user}],
            temperature=0.6,
        )
    except llm.LLMError as err:
        return fail(err.code, err.message, err.status)
    prompt = text.strip().strip("`").strip()[:1200]
    if len(prompt) < 8:
        return fail("INTERNAL_ERROR", "主 Agent 没有返回可用的描述", 500)
    x(
        "INSERT INTO asset_enrichments (asset_id, project_id, base, prompt, model, created_at)"
        " VALUES (?,?,?,?,?,?)",
        (aid, asset.get("projectId") or "", base, prompt, cfg["model"], now_text()),
    )
    return ok({"prompt": prompt, "base": base, "model": cfg["model"]})


@bp.post("/api/assets/<aid>/preview")
def api_asset_preview(aid):
    """图片 Agent：出资产三视图（正/侧/背），落到 assets/<id>/ 并写回 preview。"""
    row = q1("SELECT * FROM assets WHERE id = ?", (aid,))
    if not row:
        return fail("ASSET_NOT_FOUND", f"资产「{aid}」不存在", 404)
    body = request.get_json(silent=True) or {}
    asset = row_to_asset(row)
    cfg = image_provider.resolve_config()
    if not cfg["api_key"]:
        return fail("BAD_REQUEST", "还没有配置图片模型 API Key", 400)
    base = (body.get("prompt") or "").strip() or (asset.get("desc") or "").strip() or asset.get("name", "")
    desc = _enrich_prompt(base)
    images.configure(
        mode="live", api_key=cfg["api_key"], image_model=cfg["model"], base_url=cfg.get("base_url", "")
    )
    # 参考图：优先用资产上存的上传图；没有就用已有预览里的第一张真图
    ref_path = _upload_path((row["ref_image"] or "").strip()) if row["ref_image"] else None
    if not ref_path:
        for item in jloads(row["preview"], []):
            if isinstance(item, dict) and item.get("kind") == "img" and item.get("url"):
                ref_path = _upload_path(item["url"])
                if ref_path:
                    break

    # 场景只要一张概念图；角色才出正 / 侧 / 背三视图
    task = "asset_image" if asset["type"] == "场景" else "asset_views"
    job = {
        "kind": "keyframe",
        "payload": {
            "task": task,
            "asset_id": aid,
            "name": asset["name"],
            "type": asset["type"],
            "desc": desc,
        },
    }
    if ref_path:
        job["payload"]["ref_images"] = [ref_path]
    try:
        result = images.run(job)
    except (RuntimeError, ValueError) as err:
        message = str(err)[:300]
        code = (
            "BAD_REQUEST" if ("401" in message or "403" in message or "参数" in message) else "INTERNAL_ERROR"
        )
        return fail(code, f"图片生成失败：{message}", 400 if code == "BAD_REQUEST" else 500)
    views = result.get("views") or []
    updated = save_asset_views(aid, views)
    for _ in views:
        record_api_call("img", cfg["model"])
    first = views[0] if views else {}
    return ok(
        {
            "asset": updated,
            "views": views,
            "audit": result.get("audit") or {},
            "image": {"url": first.get("url", ""), "model": cfg["model"]},
            "prompt": desc,
            "enriched": desc != base,
        }
    )


@bp.post("/api/assets/<aid>/draft")
def api_asset_draft(aid):
    """按变更方案生成草稿图：只返回预览，不覆盖资产。"""
    row = q1("SELECT * FROM assets WHERE id = ?", (aid,))
    if not row:
        return fail("ASSET_NOT_FOUND", f"资产「{aid}」不存在", 404)
    body = request.get_json(silent=True) or {}
    desc = (body.get("desc") or "").strip() or (row["desc"] or "").strip() or row["name"]
    changes = str(body.get("changes") or "").strip()
    image_desc = desc
    if changes:
        image_desc = (
            "【本次必须明显改版，不是微调】重点改变：%s。"
            "参考图只用于保持角色身份、材质和配色，不要沿用旧轮廓、旧比例和旧结构；"
            "与上一版相比必须有肉眼可见的大幅差异。新设定：%s" % (changes, desc)
        )
    cfg = image_provider.resolve_config()
    if not cfg["api_key"]:
        return fail("BAD_REQUEST", "还没有配置图片模型 API Key", 400)
    ref_path = _upload_path((row["ref_image"] or "").strip()) if row["ref_image"] else None
    for item in jloads(row["preview"], []):
        if ref_path:
            break
        if isinstance(item, dict) and item.get("kind") == "img" and item.get("url"):
            ref_path = _upload_path(item["url"])
    major_change = bool(re.search(r"(还是|不够|进一步|更加|更|大幅|彻底|重做|完全|夸张|强烈|太)", changes))
    if major_change:
        # 明显不满意的改版不再拿旧图当参考，避免旧轮廓把改动锁死
        ref_path = None
    images.configure(
        mode="live", api_key=cfg["api_key"], image_model=cfg["model"], base_url=cfg.get("base_url", "")
    )
    task = "asset_image" if row["type"] == "场景" else "asset_views"
    draft_id = "draft-" + uuid.uuid4().hex[:8]
    job = {
        "kind": "keyframe",
        "payload": {
            "task": task,
            "asset_id": draft_id,
            "name": row["name"],
            "type": row["type"],
            "desc": image_desc,
        },
    }
    if ref_path:
        job["payload"]["ref_images"] = [ref_path]
    try:
        result = images.run(job)
    except (RuntimeError, ValueError) as err:
        return fail("INTERNAL_ERROR", "草稿生成失败：%s" % str(err)[:300], 500)
    previews = []
    for item in _parse_preview(result.get("views") or []):
        url = item.get("url") or ""
        if not url:
            continue
        previews.append({"kind": "img", "url": url, "label": VIEW_LABELS.get(item.get("view"), "生成图")})
    if not previews:
        return fail("INTERNAL_ERROR", "草稿生成失败：没有返回图片", 500)
    for _ in previews:
        record_api_call("img", cfg["model"])
    first_path = _upload_path(previews[0]["url"])
    if first_path:
        try:
            (Path(first_path).parent / "draft.json").write_text(
                json.dumps(
                    {
                        "assetId": aid,
                        "assetName": row["name"],
                        "type": row["type"],
                        "desc": desc,
                        "previews": previews,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
    return ok(
        {
            "assetId": aid,
            "assetName": row["name"],
            "type": row["type"],
            "desc": desc,
            "draftId": draft_id,
            "previews": previews,
        }
    )


@bp.post("/api/assets/<aid>/draft/save")
def api_asset_draft_save(aid):
    """把草稿图保存为资产预览（覆盖当前资产）。"""
    row = q1("SELECT * FROM assets WHERE id = ?", (aid,))
    if not row:
        return fail("ASSET_NOT_FOUND", f"资产「{aid}」不存在", 404)
    body = request.get_json(silent=True) or {}
    raw = body.get("previews") or []
    desc = (body.get("desc") or "").strip() or (row["desc"] or "")
    preview = []
    for index, item in enumerate(raw[:3]):
        url = item.get("url") if isinstance(item, dict) else str(item)
        if not url or not str(url).startswith("/uploads/"):
            continue
        label = item.get("label") if isinstance(item, dict) else ""
        preview.append(
            {
                "kind": "img",
                "url": str(url),
                "label": label or (["正面", "侧面", "背面"][index] if index < 3 else "生成图"),
            }
        )
    if not preview:
        return fail("BAD_REQUEST", "没有可保存的草稿图", 400)
    x(
        "UPDATE assets SET preview = ?, desc = ?, ai = 'none', updated_at = ? WHERE id = ?",
        (json.dumps(preview, ensure_ascii=False), desc, now_text(), aid),
    )
    return ok({"asset": row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (aid,)))})


@bp.post("/api/assets/<aid>/copy")
def api_asset_copy(aid):
    row = q1("SELECT * FROM assets WHERE id = ?", (aid,))
    if not row:
        return fail("ASSET_NOT_FOUND", f"资产「{aid}」不存在", 404)
    new_id = next_id("assets", "a")
    ts = now_text()
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO assets (id, project_id, sub_id, name, type, source, locked, desc, ai,"
            " preview, ref_shots, archived, from_project, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                new_id,
                row["project_id"],
                row["sub_id"],
                f"{row['name']} 副本",
                row["type"],
                row["source"],
                row["locked"],
                row["desc"],
                row["ai"],
                row["preview"],
                row["ref_shots"],
                0,
                row["from_project"],
                ts,
                ts,
            ),
        )
    return ok({"asset": row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (new_id,)))})


@bp.post("/api/assets/migrate")
def api_asset_migrate():
    body = request.get_json(silent=True) or {}
    ids = [str(i) for i in (body.get("ids") or [])]
    target = (body.get("targetProjectId") or "").strip()
    mode = body.get("mode") or "copy"
    conflicts = body.get("conflicts") or {}
    if not ids:
        return fail("BAD_REQUEST", "没有选择要迁移的资产")
    tproj = q1("SELECT * FROM projects WHERE id = ?", (target,))
    if not tproj:
        return fail("PROJECT_NOT_FOUND", f"目标项目「{target}」不存在", 404)
    target_sub = (body.get("targetSubId") or "").strip()
    if not target_sub:
        subs = sub_of_project(target)
        target_sub = subs[0]["id"] if subs else ""

    moved, copied, skipped = 0, 0, 0
    ts = now_text()
    with _LOCK, conn() as c:
        for aid in ids:
            row = c.execute("SELECT * FROM assets WHERE id = ?", (aid,)).fetchone()
            if not row:
                skipped += 1
                continue
            decision = conflicts.get(aid, "keep")
            if decision == "skip":
                skipped += 1
                continue
            same = c.execute(
                "SELECT id FROM assets WHERE project_id = ? AND name = ?", (target, row["name"])
            ).fetchone()
            if same and decision == "overwrite":
                c.execute("DELETE FROM assets WHERE id = ?", (same["id"],))
            locked = row["locked"]
            if isinstance(conflicts.get(f"{aid}:lock"), str):
                locked = 1 if conflicts[f"{aid}:lock"] == "lock" else 0
            if mode == "move":
                c.execute(
                    "UPDATE assets SET project_id = ?, sub_id = ?, locked = ?, updated_at = ? WHERE id = ?",
                    (target, target_sub, locked, ts, aid),
                )
                moved += 1
            else:
                new_id = next_id("assets", "a")
                c.execute(
                    "INSERT INTO assets (id, project_id, sub_id, name, type, source, locked, desc, ai,"
                    " preview, ref_shots, archived, from_project, created_at, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        target,
                        target_sub,
                        row["name"],
                        row["type"],
                        "private",
                        locked,
                        row["desc"],
                        row["ai"],
                        row["preview"],
                        "[]",
                        0,
                        (q1("SELECT name FROM projects WHERE id = ?", (row["project_id"],)) or {"name": ""})[
                            "name"
                        ],
                        ts,
                        ts,
                    ),
                )
                copied += 1
    return ok({"mode": mode, "moved": moved, "copied": copied, "skipped": skipped, "target": target})
