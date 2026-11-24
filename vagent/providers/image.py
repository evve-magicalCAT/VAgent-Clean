# -*- coding: utf-8 -*-
"""B · 图片 provider：火山方舟 Seedream（images/generations）。"""
from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from ..db import load_settings, record_api_call
from .common import IMAGE_MAX_BYTES, ProviderHTTPError, download_media, post_json

DEFAULT_MODEL = "doubao-seedream-5-5-261028"
DEFAULT_SIZE = "2K"
DEFAULT_TIMEOUT = 120


class ImageError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def resolve_config() -> dict:
    cfg = load_settings().get("img") or {}
    base = (cfg.get("base_url") or "").strip()
    base = base.rstrip("/")
    if base.endswith("/images/generations"):
        base = base[: -len("/images/generations")]
    return {
        "base_url": base,
        "model": (cfg.get("model") or "").strip() or DEFAULT_MODEL,
        "api_key": (cfg.get("api_key") or "").strip(),
    }


def is_configured() -> bool:
    return bool(resolve_config()["api_key"])


def _translate(err: ProviderHTTPError) -> ImageError:
    if err.status in (401, 403):
        return ImageError(
            "BAD_REQUEST",
            "图片模型鉴权失败：当前账号没有该模型权限，请在火山方舟控制台开通，"
            "或在「API 设置」里更换图片模型。%s" % err.message,
            400,
        )
    if err.status == 404:
        return ImageError(
            "BAD_REQUEST",
            "图片模型不存在或未开通：请在火山方舟控制台开通，或在「API 设置」里更换图片模型。%s"
            % err.message,
            400,
        )
    if err.status == 429:
        return ImageError("INTERNAL_ERROR", f"图片模型限流，请稍后再试：{err.message}", 500)
    return ImageError("INTERNAL_ERROR", f"图片生成失败：{err.message}", 500)


def _as_ref(ref) -> str:
    """参考图：http(s)/data URI 原样传，本地文件转 base64 data URI。"""
    text = str(ref)
    if text.startswith(("http://", "https://", "data:")):
        return text
    raw = Path(ref).read_bytes()
    mime = mimetypes.guess_type(str(ref))[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def generate(prompt: str, size: str = DEFAULT_SIZE, timeout: int = DEFAULT_TIMEOUT, ref_images=None) -> dict:
    """按提示词生成一张图（可带参考图做图生图），下载到本地，返回 {url, model}。"""
    cfg = resolve_config()
    if not cfg["api_key"]:
        raise ImageError("BAD_REQUEST", "还没有配置图片模型 API Key", 400)
    if not cfg["base_url"]:
        raise ImageError("BAD_REQUEST", "请在 API 设置中填写图片模型 Base URL", 400)
    text = (prompt or "").strip()
    if not text:
        raise ImageError("BAD_REQUEST", "图片提示词不能为空", 400)
    body = {
        "model": cfg["model"],
        "prompt": text[:2000],
        "size": size,
        "response_format": "url",
        "stream": False,
        "watermark": False,
    }
    refs = [_as_ref(ref) for ref in (ref_images or []) if ref]
    if refs:
        body["image"] = refs[0] if len(refs) == 1 else refs
    try:
        resp = post_json(cfg["base_url"] + "/images/generations", body, cfg["api_key"], timeout)
    except ProviderHTTPError as err:
        raise _translate(err) from None
    items = resp.get("data")
    if not isinstance(items, list) or not items or not items[0].get("url"):
        raise ImageError("INTERNAL_ERROR", "图片模型没有返回图片地址", 500)
    try:
        url = download_media(items[0]["url"], ".png", IMAGE_MAX_BYTES, timeout=timeout)
    except ProviderHTTPError as err:
        raise ImageError("INTERNAL_ERROR", f"图片下载失败：{err.message}", 500) from None
    record_api_call("img", cfg["model"])
    return {"url": url, "model": cfg["model"]}
