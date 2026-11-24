# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from flask import Blueprint, request
from ..db import _LOCK, conn, x, now_text
from ..repository import current_ids, current_messages, ensure_current
from ..responses import fail, ok


bp = Blueprint("messages", __name__)


@bp.post("/api/messages")
def api_message_create():
    ensure_current()
    pid, sid = current_ids()
    body = request.get_json(silent=True) or {}
    role = body.get("role") or "user"
    text = (body.get("text") or "").strip()
    if not text:
        return fail("BAD_REQUEST", "消息内容不能为空")
    ts = now_text()
    with _LOCK, conn() as c:
        cur = c.execute(
            "INSERT INTO messages (project_id, sub_id, role, text, meta, created_at) VALUES (?,?,?,?,?,?)",
            (pid, sid, role, text, json.dumps(body.get("meta") or {}, ensure_ascii=False), ts),
        )
        mid = cur.lastrowid
    return ok({"id": mid, "messages": current_messages()})


@bp.delete("/api/messages")
def api_message_clear():
    ensure_current()
    pid, sid = current_ids()
    x("DELETE FROM messages WHERE project_id = ? AND sub_id = ?", (pid, sid))
    return ok({"messages": []})
