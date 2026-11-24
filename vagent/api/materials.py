# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import Blueprint, request
from ..db import _LOCK, conn, q1, x, now_text
from ..repository import current_ids, current_materials, ensure_current, next_id
from ..responses import fail, ok
from ..serializers import row_to_material


bp = Blueprint("materials", __name__)


@bp.get("/api/materials")
def api_materials():
    ensure_current()
    return ok({"materials": current_materials()})


@bp.post("/api/materials")
def api_material_create():
    ensure_current()
    pid, sid = current_ids()
    body = request.get_json(silent=True) or {}
    mid = next_id("materials", "m")
    ts = now_text()
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO materials (id, project_id, sub_id, label, kind, dur, bg, wave, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                mid,
                pid,
                sid,
                (body.get("label") or "未命名素材").strip(),
                (body.get("kind") or "视频").strip(),
                (body.get("dur") or "").strip(),
                body.get("bg") or "linear-gradient(150deg,#2E353D,#12161A)",
                body.get("wave") or "",
                ts,
            ),
        )
    return ok({"material": row_to_material(q1("SELECT * FROM materials WHERE id = ?", (mid,)))})


@bp.delete("/api/materials/<mid>")
def api_material_delete(mid):
    if not q1("SELECT id FROM materials WHERE id = ?", (mid,)):
        return fail("MATERIAL_NOT_FOUND", f"素材「{mid}」不存在", 404)
    x("DELETE FROM materials WHERE id = ?", (mid,))
    return ok({"deleted": mid})
