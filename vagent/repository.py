# -*- coding: utf-8 -*-
"""数据查询与派生结构：项目列表、当前上下文、资产范围、镜头、用量。"""
from __future__ import annotations

import json
import time
import uuid

from .db import _LOCK, conn, meta_get, meta_set, now_text, q, q1
from .serializers import jloads, row_to_asset, row_to_material, row_to_project, row_to_shot, row_to_sub


def project_list() -> list:
    projects = []
    for prow in q("SELECT * FROM projects ORDER BY archived ASC, updated_at DESC"):
        subs = []
        for srow in q("SELECT * FROM subs WHERE project_id = ? ORDER BY created_at ASC", (prow["id"],)):
            agg = q1(
                "SELECT COUNT(*) AS n, COALESCE(SUM(dur), 0) AS d FROM shots WHERE sub_id = ?",
                (srow["id"],),
            )
            ac = q1("SELECT COUNT(*) AS n FROM assets WHERE sub_id = ?", (srow["id"],))
            subs.append(row_to_sub(srow, agg["n"], agg["d"], ac["n"]))
        p = row_to_project(prow, subs)
        p["subsCount"] = len(subs)
        agg = q1("SELECT COUNT(*) AS n FROM shots WHERE project_id = ?", (prow["id"],))
        ac = q1("SELECT COUNT(*) AS n FROM assets WHERE project_id = ?", (prow["id"],))
        p["shots"] = agg["n"]
        p["assets"] = ac["n"]
        p["members"] = []
        p["edited"] = (prow["updated_at"] or "")[:16]
        projects.append(p)
    return projects


def find_project(pid: str):
    row = q1("SELECT * FROM projects WHERE id = ?", (pid,))
    return row_to_project(row) if row else None


def current_ids() -> tuple:
    return meta_get("current_project"), meta_get("current_sub")


def sub_of_project(pid: str) -> list:
    return [dict(r) for r in q("SELECT * FROM subs WHERE project_id = ? ORDER BY created_at ASC", (pid,))]


def ensure_current() -> None:
    """当前项目缺失或已删除时，自动落到第一个可用项目 / 子项目。"""
    pid, sid = current_ids()
    prows = q("SELECT * FROM projects ORDER BY archived ASC, updated_at DESC")
    if not prows:
        if pid or sid:
            meta_set("current_project", "")
            meta_set("current_sub", "")
        return
    ids = [r["id"] for r in prows]
    if pid not in ids:
        pid = ids[0]
        meta_set("current_project", pid)
        sid = ""
    subs = sub_of_project(pid)
    if not subs:
        meta_set("current_sub", "")
        return
    if sid not in [s["id"] for s in subs]:
        meta_set("current_sub", subs[0]["id"])


def current_summary() -> dict:
    ensure_current()
    pid, sid = current_ids()
    if not pid:
        return {"projectId": "", "subId": "", "name": "", "sub": "", "tag": ""}
    prow = q1("SELECT * FROM projects WHERE id = ?", (pid,))
    srow = q1("SELECT * FROM subs WHERE id = ?", (sid,)) if sid else None
    return {
        "projectId": pid,
        "subId": sid,
        "name": prow["name"] if prow else "",
        "sub": (srow["name"].split("·")[0].strip() if srow else "未分集"),
        "tag": prow["kind"] if prow else "",
    }


def scope_assets(scope: str, pid: str, sid: str) -> list:
    """
    project  = 当前子项目可见：子项目私有 + 项目级（继承）
    inherit  = 仅项目级（继承自父项目）
    all      = 全部资产（含其他项目）
    """
    if scope == "inherit":
        rows = q("SELECT * FROM assets WHERE project_id = ? AND sub_id = '' ORDER BY created_at DESC", (pid,))
    elif scope == "all":
        rows = q("SELECT * FROM assets ORDER BY created_at DESC")
    else:
        rows = q(
            "SELECT * FROM assets WHERE project_id = ? AND (sub_id = ? OR sub_id = '') ORDER BY created_at DESC",
            (pid, sid),
        )
    return [row_to_asset(r) for r in rows]


def scope_stats(assets: list) -> dict:
    return {
        "total": len(assets),
        "inherit": sum(1 for a in assets if a["source"] == "inherit"),
        "private": sum(1 for a in assets if a["source"] != "inherit"),
        "locked": sum(1 for a in assets if a["locked"]),
        "generating": sum(1 for a in assets if a["ai"] in ("generating", "running")),
    }


def current_shots() -> list:
    pid, sid = current_ids()
    if not pid or not sid:
        return []
    rows = q("SELECT * FROM shots WHERE sub_id = ? ORDER BY created_at ASC, id ASC", (sid,))
    return [row_to_shot(r, f"{i + 1:02d}") for i, r in enumerate(rows)]


def current_materials() -> list:
    pid, sid = current_ids()
    return [
        row_to_material(r)
        for r in q(
            "SELECT * FROM materials WHERE project_id = ? AND (sub_id = ? OR sub_id = '') ORDER BY created_at ASC",
            (pid, sid),
        )
    ]


def current_messages() -> list:
    pid, sid = current_ids()
    rows = q("SELECT * FROM messages WHERE project_id = ? AND sub_id = ? ORDER BY id ASC", (pid, sid))
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "text": r["text"],
            "meta": jloads(r["meta"], {}),
            "createdAt": r["created_at"],
        }
        for r in rows
    ]


def usage_payload() -> dict:
    budget = int(float(meta_get("budget", "500") or 500))
    confirmed = q1("SELECT COUNT(*) AS n FROM shots WHERE status = 'confirmed'")["n"]
    return {
        "total": 0.0,
        "monthBefore": 0.0,
        "budget": budget,
        "usedPct": 0,
        "remaining": float(budget),
        "byModel": [],
        "trend": [],
        "projectShare": [],
        "records": [],
        "generatedShots": confirmed,
        "spend": {
            "monthTotal": 0.0,
            "monthBefore": 0.0,
            "budget": budget,
            "usedPct": 0,
            "categories": [],
            "daily": [],
            "topProjects": [],
            "records": [],
        },
    }


def add_shot(
    name: str,
    prompt: str,
    dur: float,
    *,
    provider_job: str = "",
    status: str = "redraw",
    ai: str = "video",
    review=None,
    project_sub=None,
) -> dict | None:
    """供主 Agent 的视频工具调用：建一个已经带 provider 任务的镜头。"""
    pid, sid = project_sub or current_ids()
    if not pid or not sid:
        return None
    count = q1("SELECT COUNT(*) AS n FROM shots WHERE sub_id = ?", (sid,))["n"]
    shot_id = f"{sid}-{int(time.time() * 1000) % 1000000}{uuid.uuid4().hex[:4]}"
    ts = now_text()
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO shots (id, project_id, sub_id, name, dur, status, frame, locked, prompt,"
            " tones, progress, ai, provider_job, review, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                shot_id,
                pid,
                sid,
                (name or "视频镜头").strip()[:30],
                round(float(dur), 2),
                status,
                "street",
                0,
                prompt,
                "[]",
                0,
                ai,
                provider_job,
                json.dumps(review or {}, ensure_ascii=False),
                ts,
                ts,
            ),
        )
    return row_to_shot(q1("SELECT * FROM shots WHERE id = ?", (shot_id,)), f"{count + 1:02d}")


def add_asset_with_views(
    name: str, asset_type: str, desc: str, urls: list, ref_url: str = "", *, project_sub=None
) -> dict | None:
    """把三视图（正/侧/背）一次性沉淀成一项资产；同名资产直接更新。"""
    pid, sid = project_sub or current_ids()
    if not pid:
        return None
    clean = [url for url in (urls or []) if url][:3]
    if not clean:
        return None
    labels = ["正面", "侧面", "背面"]
    preview = [
        {"kind": "img", "url": url, "label": labels[i] if i < len(labels) else "生成图"}
        for i, url in enumerate(clean)
    ]
    preview_json = json.dumps(preview, ensure_ascii=False)
    name = (name or "三视图设定").strip()[:30]
    asset_type = asset_type or "角色"
    ts = now_text()
    row = q1("SELECT * FROM assets WHERE project_id = ? AND name = ?", (pid, name))
    if row:
        with _LOCK, conn() as c:
            c.execute(
                "UPDATE assets SET preview = ?, ref_image = ?, desc = ?, type = ?, ai = 'none',"
                " updated_at = ? WHERE id = ?",
                (preview_json, ref_url, desc or "", asset_type, ts, row["id"]),
            )
        return row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (row["id"],)))

    aid = next_id("assets", "a")
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO assets (id, project_id, sub_id, name, type, source, locked, desc, ai,"
            " preview, ref_image, ref_shots, archived, from_project, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,'',?,?)",
            (
                aid,
                pid,
                sid,
                name,
                asset_type,
                "private",
                0,
                desc or "",
                "none",
                preview_json,
                ref_url,
                "[]",
                ts,
                ts,
            ),
        )
    return row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (aid,)))


def add_generating_asset(name: str, asset_type: str, desc: str, ref_url: str = "") -> dict | None:
    """先落一条 ai=generating 的资产，图片在后台生成后再回填预览。"""
    pid, sid = current_ids()
    if not pid:
        return None
    name = (name or "生成中资产").strip()[:30]
    asset_type = asset_type or "其他"
    ts = now_text()
    row = q1("SELECT * FROM assets WHERE project_id = ? AND name = ?", (pid, name))
    if row:
        with _LOCK, conn() as c:
            c.execute(
                "UPDATE assets SET ai = 'generating', preview = '[]', desc = ?, type = ?,"
                " ref_image = ?, updated_at = ? WHERE id = ?",
                (desc or "", asset_type, ref_url, ts, row["id"]),
            )
        return row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (row["id"],)))

    aid = next_id("assets", "a")
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO assets (id, project_id, sub_id, name, type, source, locked, desc, ai,"
            " preview, ref_image, ref_shots, archived, from_project, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,'',?,?)",
            (
                aid,
                pid,
                sid,
                name,
                asset_type,
                "private",
                0,
                desc or "",
                "generating",
                "[]",
                ref_url,
                "[]",
                ts,
                ts,
            ),
        )
    return row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (aid,)))


def save_asset_draft(name: str, asset_type: str, desc: str, locked: bool = True) -> dict | None:
    """沉淀主 Agent 识别出的资产设定，保留占位预览等待后续出图。"""
    pid, sid = current_ids()
    if not pid:
        return None
    name = (name or "未命名设定").strip()[:30]
    asset_type = (asset_type or "其他").strip()[:10]
    desc = (desc or "").strip()[:1000]
    preview = json.dumps(
        [
            {"kind": "fig", "sym": "fig-front", "label": "正面"},
            {"kind": "fig", "sym": "fig-side", "label": "侧面"},
            {"kind": "fig", "sym": "fig-back", "label": "背面"},
        ],
        ensure_ascii=False,
    )
    ts = now_text()
    row = q1("SELECT * FROM assets WHERE project_id = ? AND name = ?", (pid, name))
    if row:
        existing = jloads(row["preview"], [])
        has_image = any(
            isinstance(item, dict) and item.get("kind") == "img" and item.get("url") for item in existing
        )
        with _LOCK, conn() as c:
            c.execute(
                "UPDATE assets SET type = ?, desc = ?, locked = ?,"
                " preview = CASE WHEN ? THEN preview ELSE ? END, updated_at = ? WHERE id = ?",
                (asset_type, desc, 1 if locked else 0, 1 if has_image else 0, preview, ts, row["id"]),
            )
        return row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (row["id"],)))

    aid = next_id("assets", "a")
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO assets (id, project_id, sub_id, name, type, source, locked, desc, ai,"
            " preview, ref_image, ref_shots, archived, from_project, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,'',?,?)",
            (
                aid,
                pid,
                sid,
                name,
                asset_type,
                "private",
                1 if locked else 0,
                desc,
                "none",
                preview,
                "",
                "[]",
                ts,
                ts,
            ),
        )
    return row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (aid,)))


def save_asset_reference(name: str, asset_type: str, desc: str, ref_url: str) -> dict | None:
    """先把用户上传图作为资产封面和参考图保存下来。"""
    asset = save_asset_draft(name, asset_type, desc, locked=True)
    if not asset or not ref_url:
        return asset
    preview = json.dumps([{"kind": "img", "url": ref_url, "label": "用户参考图"}], ensure_ascii=False)
    with _LOCK, conn() as c:
        c.execute(
            "UPDATE assets SET preview = ?, ref_image = ?, ai = 'none', updated_at = ? WHERE id = ?",
            (preview, ref_url, now_text(), asset["id"]),
        )
    return row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (asset["id"],)))


def set_asset_preview(asset_id: str, preview: list, ai: str = "none") -> None:
    with _LOCK, conn() as c:
        c.execute(
            "UPDATE assets SET preview = ?, ai = ?, updated_at = ? WHERE id = ?",
            (json.dumps(preview or [], ensure_ascii=False), ai, now_text(), asset_id),
        )


def add_generated_asset(name: str, asset_type: str, desc: str, url: str) -> dict | None:
    """语言模型通过工具出图后，把结果沉淀成资产（同名则只更新预览）。"""
    pid, sid = current_ids()
    if not pid:
        return None
    preview = json.dumps([{"kind": "img", "url": url, "label": "生成图"}], ensure_ascii=False)
    ts = now_text()
    row = q1("SELECT * FROM assets WHERE project_id = ? AND name = ?", (pid, name))
    if row:
        with _LOCK, conn() as c:
            c.execute(
                "UPDATE assets SET preview = ?,"
                " desc = CASE WHEN ? <> '' THEN ? ELSE desc END,"
                " ai = 'none', updated_at = ? WHERE id = ?",
                (preview, desc or "", desc or "", ts, row["id"]),
            )
        return row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (row["id"],)))
    aid = next_id("assets", "a")
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO assets (id, project_id, sub_id, name, type, source, locked, desc, ai,"
            " preview, ref_shots, archived, from_project, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,0,'',?,?)",
            (
                aid,
                pid,
                sid,
                name,
                asset_type or "其他",
                "private",
                0,
                desc or "",
                "none",
                preview,
                "[]",
                ts,
                ts,
            ),
        )
    return row_to_asset(q1("SELECT * FROM assets WHERE id = ?", (aid,)))


def next_id(table: str, prefix: str) -> str:
    """自增 ID：计数器放在 meta 里，避免同一事务内多次取号拿到重复值。"""
    with _LOCK:
        key = f"seq:{table}"
        n = int(meta_get(key, "0") or 0) + 1
        meta_set(key, str(n))
    return f"{prefix}{n}"
