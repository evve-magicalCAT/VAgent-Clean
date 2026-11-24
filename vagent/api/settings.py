# -*- coding: utf-8 -*-
from __future__ import annotations
import copy
from flask import Blueprint, request
from ..config import DEFAULT_SETTINGS
from ..db import _LOCK, load_settings, meta_set, now_text, save_settings
from ..responses import fail, mask_key, ok, public_settings


bp = Blueprint("settings", __name__)


@bp.get("/api/settings/api")
def api_settings_get():
    return ok({"api": public_settings(), "maskExample": mask_key("sk-example-placeholder-not-real")})


@bp.put("/api/settings/api")
def api_settings_put():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return fail("BAD_REQUEST", "请求体必须是 JSON 对象")
    body = payload.get("api", payload)
    if not isinstance(body, dict):
        return fail("BAD_REQUEST", "api 字段必须是对象")
    settings = load_settings()
    updated = []
    with _LOCK:
        for key, incoming in body.items():
            cfg = settings.get(key)
            if cfg is None or not isinstance(incoming, dict):
                continue
            if key == "llm" and any(
                incoming.get(f) and incoming[f] != cfg.get(f) for f in ("model", "base_url", "provider")
            ):
                cfg.pop("context_limit", None)
            if key == "llm" and "context_limit" in incoming:
                value = str(incoming["context_limit"]).strip()
                if value and (
                    not value.isascii() or not value.isdecimal() or len(value) > 9 or int(value) < 1
                ):
                    return fail("BAD_REQUEST", "上下文容量须为正整数", 400)
                cfg["context_limit"] = int(value) if value else None
            for field in ("provider", "base_url", "model", "max_duration"):
                if isinstance(incoming.get(field), str) and incoming[field].strip():
                    cfg[field] = incoming[field].strip()
            if incoming.get("concurrency") is not None:
                try:
                    cfg["concurrency"] = int(incoming["concurrency"])
                except (TypeError, ValueError):
                    pass
            raw_key = incoming.get("api_key")
            if isinstance(raw_key, str) and raw_key.strip() and "•" not in raw_key:
                cfg["api_key"] = raw_key.strip()
            cfg["status"] = {"text": "已保存", "warn": not bool(cfg.get("api_key"))}
            updated.append(key)
        if updated:
            save_settings(settings)
            meta_set("saved_at", now_text())
    if not updated:
        return fail("UNKNOWN_FIELD", "没有可识别的配置分组（llm / img / video）")
    return ok({"updated": updated, "api": public_settings()})


@bp.post("/api/settings/api/reset")
def api_settings_reset():
    with _LOCK:
        save_settings(copy.deepcopy(DEFAULT_SETTINGS))
        meta_set("saved_at", now_text())
    return ok({"api": public_settings()})


@bp.post("/api/settings/api/test")
def api_settings_test():
    """本地模拟连接测试：不发任何外部请求，只按是否填了密钥给出结果。"""
    body = request.get_json(silent=True) or {}
    key = body.get("group") or "llm"
    settings = load_settings()
    cfg = settings.get(key) or {}
    ok_flag = bool(cfg.get("api_key")) and bool(cfg.get("base_url"))
    return ok(
        {
            "group": key,
            "ok": ok_flag,
            "message": "配置完整（本地校验通过，未发起真实请求）" if ok_flag else "缺少 API Key 或 Base URL",
            "status": {"text": "已连接" if ok_flag else "未配置", "warn": not ok_flag},
        }
    )
