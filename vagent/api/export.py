# -*- coding: utf-8 -*-
"""导出：本地生成清单与字幕，不调用任何外部服务。"""
from __future__ import annotations
from flask import Blueprint, current_app, jsonify
from ..db import q, q1, now_text
from ..repository import current_ids, current_materials, current_messages, current_shots, ensure_current
from ..serializers import row_to_asset


bp = Blueprint("export", __name__)


@bp.get("/api/export/manifest")
def api_export_manifest():
    ensure_current()
    pid, _sid = current_ids()
    proj = q1("SELECT * FROM projects WHERE id = ?", (pid,)) if pid else None
    data = {
        "app": "Vagent",
        "exportedAt": now_text(),
        "project": dict(proj) if proj else None,
        "shots": current_shots(),
        "assets": (
            [row_to_asset(r) for r in q("SELECT * FROM assets WHERE project_id = ?", (pid,))] if pid else []
        ),
        "materials": current_materials(),
        "note": "本地导出清单：未做真实视频编码，可在接入视频模型后替换为实际渲染。",
    }
    resp = jsonify(data)
    resp.headers["Content-Disposition"] = 'attachment; filename="vagent-manifest.json"'
    return resp


@bp.get("/api/export/chat.md")
def api_export_chat():
    """把当前项目 / 子项目的对话导成 Markdown，方便直接改。"""
    ensure_current()
    pid, sid = current_ids()
    proj = q1("SELECT name FROM projects WHERE id = ?", (pid,)) if pid else None
    sub = q1("SELECT name FROM subs WHERE id = ?", (sid,)) if sid else None
    lines = [
        f"# {proj['name'] if proj else '未命名项目'} · {sub['name'] if sub else '未分集'} · 对话记录",
        "",
        f"- 导出时间：{now_text()}",
        f"- 消息数：{len(current_messages())}",
        "",
    ]
    for message in current_messages():
        who = "我" if message["role"] == "user" else "主 Agent"
        lines += [f"## {who} · {message['createdAt']}", "", (message["text"] or "").strip() or "（空）", ""]
        meta = message.get("meta") or {}
        for item in meta.get("questions") or []:
            text = item.get("q") or item.get("text") if isinstance(item, dict) else item
            if text:
                lines.append(f"> 追问：{text}")
        if meta.get("images"):
            lines.append(f"> 生成图片：{len(meta['images'])} 张")
        if message.get("meta"):
            lines.append("")
    body = "\n".join(lines).rstrip() + "\n"
    resp = current_app.response_class(body, content_type="text/markdown; charset=utf-8")
    resp.headers["Content-Disposition"] = 'attachment; filename="vagent-chat.md"'
    return resp


def _srt_time(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@bp.get("/api/export/subtitles.srt")
def api_export_srt():
    shots = current_shots()
    lines, t = [], 0.0
    for i, s in enumerate(shots, 1):
        text = (s.get("prompt") or s.get("name") or "").strip()
        lines += [str(i), f"{_srt_time(t)} --> {_srt_time(t + s['dur'])}", text, ""]
        t += s["dur"]
    body = "\n".join(lines) if lines else "1\n00:00:00,000 --> 00:00:02,000\n（还没有镜头）\n"
    resp = current_app.response_class(body, mimetype="application/x-subrip")
    resp.headers["Content-Disposition"] = 'attachment; filename="vagent-subtitles.srt"'
    return resp
