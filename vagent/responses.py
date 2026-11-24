# -*- coding: utf-8 -*-
"""统一响应与密钥掩码。"""
from __future__ import annotations
import copy
from flask import jsonify
from .db import load_settings
from .config import MASK_DOTS, MASK_KEEP_TAIL


def ok(data=None):
    return jsonify({"ok": True, "data": data})


def fail(code: str, message: str, status: int = 400):
    resp = jsonify({"ok": False, "error": {"code": code, "message": message}})
    resp.status_code = status
    return resp


def mask_key(raw: str) -> str:
    if not raw:
        return ""
    raw = str(raw)
    if len(raw) <= 8:
        return "•" * len(raw)
    prefix = raw.split("-", 1)[0] + "-" if "-" in raw[:8] else ""
    return f"{prefix}{'•' * MASK_DOTS}{raw[-MASK_KEEP_TAIL:]}"


def public_settings() -> dict:
    out = {}
    for key, cfg in load_settings().items():
        item = {k: copy.deepcopy(v) for k, v in cfg.items() if k != "api_key"}
        item["api_key"] = mask_key(cfg.get("api_key", ""))
        item["api_key_masked"] = item["api_key"]
        out[key] = item
    return out
