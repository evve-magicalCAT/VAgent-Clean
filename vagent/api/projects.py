# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import time
from flask import Blueprint, request
from ..config import COVER_ARTS, COVER_GRADS, COVER_INKS
from ..db import _LOCK, conn, meta_get, meta_set, q1, x, now_text
from ..repository import current_summary, ensure_current, find_project, next_id, project_list, sub_of_project
from ..responses import fail, ok


bp = Blueprint("projects", __name__)


@bp.get("/api/projects")
def api_projects():
    return ok({"projects": project_list(), "total": len(project_list())})


@bp.get("/api/projects/<pid>")
def api_project_detail(pid):
    project = find_project(pid)
    if not project:
        return fail("PROJECT_NOT_FOUND", f"项目「{pid}」不存在", 404)
    subs = project_list()
    me = next((p for p in subs if p["id"] == pid), project)
    return ok(
        {
            "project": me,
            "subprojects": me.get("subs", []),
            "isCurrent": me["id"] == meta_get("current_project"),
        }
    )


@bp.post("/api/projects")
def api_project_create():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return fail("BAD_REQUEST", "项目名不能为空")
    pid = next_id("projects", "p")
    idx = q1("SELECT COUNT(*) AS n FROM projects")["n"]
    cover = {
        "art": COVER_ARTS[idx % len(COVER_ARTS)],
        "grad": COVER_GRADS[idx % len(COVER_GRADS)],
        "ink": COVER_INKS[idx % len(COVER_INKS)],
    }
    ts = now_text()
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO projects (id, name, kind, status, desc, archived, cover, created_at, updated_at)"
            " VALUES (?,?,?,?,?,0,?,?,?)",
            (
                pid,
                name,
                (body.get("kind") or "概念片").strip(),
                "",
                (body.get("desc") or "").strip(),
                json.dumps(cover, ensure_ascii=False),
                ts,
                ts,
            ),
        )
        # 新项目自动带一个子项目，用户可以立即开始
        sid = f"{pid}-1"
        c.execute(
            "INSERT INTO subs (id, project_id, name, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (sid, pid, "第 1 集 · 未命名", "草稿", ts, ts),
        )
    meta_set("current_project", pid)
    meta_set("current_sub", f"{pid}-1")
    return ok({"project": find_project(pid), "projectId": pid, "subId": f"{pid}-1"})


@bp.patch("/api/projects/<pid>")
def api_project_patch(pid):
    row = q1("SELECT * FROM projects WHERE id = ?", (pid,))
    if not row:
        return fail("PROJECT_NOT_FOUND", f"项目「{pid}」不存在", 404)
    body = request.get_json(silent=True) or {}
    fields, args = [], []
    if isinstance(body.get("name"), str) and body["name"].strip():
        fields.append("name = ?")
        args.append(body["name"].strip())
    if isinstance(body.get("kind"), str) and body["kind"].strip():
        fields.append("kind = ?")
        args.append(body["kind"].strip())
    if isinstance(body.get("desc"), str):
        fields.append("desc = ?")
        args.append(body["desc"].strip())
    if isinstance(body.get("archived"), bool):
        fields.append("archived = ?")
        args.append(1 if body["archived"] else 0)
    if not fields:
        return fail("BAD_REQUEST", "没有可更新的字段")
    fields.append("updated_at = ?")
    args.append(now_text())
    args.append(pid)
    x(f"UPDATE projects SET {', '.join(fields)} WHERE id = ?", tuple(args))
    ensure_current()
    return ok({"project": find_project(pid)})


@bp.delete("/api/projects/<pid>")
def api_project_delete(pid):
    if not q1("SELECT id FROM projects WHERE id = ?", (pid,)):
        return fail("PROJECT_NOT_FOUND", f"项目「{pid}」不存在", 404)
    with _LOCK, conn() as c:
        c.execute("DELETE FROM shots WHERE project_id = ?", (pid,))
        c.execute("DELETE FROM assets WHERE project_id = ?", (pid,))
        c.execute("DELETE FROM materials WHERE project_id = ?", (pid,))
        c.execute("DELETE FROM messages WHERE project_id = ?", (pid,))
        c.execute("DELETE FROM subs WHERE project_id = ?", (pid,))
        c.execute("DELETE FROM projects WHERE id = ?", (pid,))
    ensure_current()
    return ok({"deleted": pid})


@bp.post("/api/projects/<pid>/subs")
def api_sub_create(pid):
    if not q1("SELECT id FROM projects WHERE id = ?", (pid,)):
        return fail("PROJECT_NOT_FOUND", f"项目「{pid}」不存在", 404)
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        n = q1("SELECT COUNT(*) AS n FROM subs WHERE project_id = ?", (pid,))["n"]
        name = f"第 {n + 1} 集 · 未命名"
    ts = now_text()
    sid = f"{pid}-{int(time.time() * 1000) % 100000}"
    with _LOCK, conn() as c:
        c.execute(
            "INSERT INTO subs (id, project_id, name, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (sid, pid, name, "草稿", ts, ts),
        )
    meta_set("current_project", pid)
    meta_set("current_sub", sid)
    return ok({"subId": sid, "sub": {"id": sid, "projectId": pid, "name": name, "status": "草稿"}})


@bp.patch("/api/subs/<sid>")
def api_sub_patch(sid):
    row = q1("SELECT * FROM subs WHERE id = ?", (sid,))
    if not row:
        return fail("SUB_NOT_FOUND", f"子项目「{sid}」不存在", 404)
    body = request.get_json(silent=True) or {}
    fields, args = [], []
    if isinstance(body.get("name"), str) and body["name"].strip():
        fields.append("name = ?")
        args.append(body["name"].strip())
    if isinstance(body.get("status"), str) and body["status"].strip():
        fields.append("status = ?")
        args.append(body["status"].strip())
    if not fields:
        return fail("BAD_REQUEST", "没有可更新的字段")
    fields.append("updated_at = ?")
    args.append(now_text())
    args.append(sid)
    x(f"UPDATE subs SET {', '.join(fields)} WHERE id = ?", tuple(args))
    return ok({"sub": dict(q1("SELECT * FROM subs WHERE id = ?", (sid,)))})


@bp.delete("/api/subs/<sid>")
def api_sub_delete(sid):
    if not q1("SELECT id FROM subs WHERE id = ?", (sid,)):
        return fail("SUB_NOT_FOUND", f"子项目「{sid}」不存在", 404)
    with _LOCK, conn() as c:
        c.execute("DELETE FROM shots WHERE sub_id = ?", (sid,))
        c.execute("DELETE FROM assets WHERE sub_id = ?", (sid,))
        c.execute("DELETE FROM messages WHERE sub_id = ?", (sid,))
        c.execute("DELETE FROM subs WHERE id = ?", (sid,))
    ensure_current()
    return ok({"deleted": sid})


@bp.post("/api/switch")
def api_switch():
    body = request.get_json(silent=True) or {}
    pid = (body.get("projectId") or "").strip()
    sid = (body.get("subId") or "").strip()
    if pid and not q1("SELECT id FROM projects WHERE id = ?", (pid,)):
        return fail("PROJECT_NOT_FOUND", f"项目「{pid}」不存在", 404)
    if not pid:
        ensure_current()
        return ok({"currentProject": current_summary()})
    meta_set("current_project", pid)
    if sid and q1("SELECT id FROM subs WHERE id = ? AND project_id = ?", (sid, pid)):
        meta_set("current_sub", sid)
    else:
        subs = sub_of_project(pid)
        meta_set("current_sub", subs[0]["id"] if subs else "")
    return ok({"currentProject": current_summary()})
