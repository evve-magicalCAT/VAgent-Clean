# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

_SKILL_ROOT = Path(__file__).resolve().parent.parent / "skills" / "rui-skills-client" / "rui-skills"


def rui_skill(reference: str = "") -> dict:
    """读取本地 Rui-Skills 工作流；可按需带出一份参考文档，不执行第三方引擎。"""
    skill_file = _SKILL_ROOT / "SKILL.md"
    if not skill_file.is_file():
        return {"ok": False, "error": "Rui-Skills 未安装"}
    text = skill_file.read_text(encoding="utf-8")
    version = ""
    version_file = _SKILL_ROOT / "VERSION"
    if version_file.is_file():
        version = version_file.read_text(encoding="utf-8").strip()
    refs = sorted(path.stem for path in (_SKILL_ROOT / "references").glob("*.md"))
    payload = {
        "ok": True,
        "name": "rui-skills",
        "version": version,
        "license": "Rui NonCommercial 1.0（商用需另行授权）",
        "skill": text[:14000],
        "references": refs,
    }
    name = (reference or "").strip()
    if name:
        path = _SKILL_ROOT / "references" / (name + ".md")
        if path.is_file():
            payload["reference"] = path.stem
            payload["reference_text"] = path.read_text(encoding="utf-8")[:10000]
        else:
            payload["reference_error"] = "没有这个参考文件：%s" % name
    return payload
