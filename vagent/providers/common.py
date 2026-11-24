# -*- coding: utf-8 -*-
"""B / C 两个 Agent 共用的媒体 provider 底座：HTTP 与文件落地。

只依赖标准库；密钥来自本地设置表，不写日志、不出接口。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid

from .. import config

IMAGE_MAX_BYTES = 25 * 1024 * 1024
VIDEO_MAX_BYTES = 200 * 1024 * 1024


def http_message(detail: str) -> str:
    """从服务端的错误响应里抽一句人能看懂的话。"""
    try:
        body = json.loads(detail)
    except ValueError:
        body = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
        if isinstance(err, str) and err:
            return err[:300]
        base = body.get("base_resp") or {}
        if isinstance(base, dict) and base.get("status_msg"):
            return str(base["status_msg"])[:300]
        if body.get("message"):
            return str(body["message"])[:300]
    return (detail or "").strip()[:300] or "未知错误"


def _request(url: str, api_key: str, timeout: int, data: bytes | None = None) -> bytes:
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        url, data=data, method="POST" if data is not None else "GET", headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace") if err.fp else ""
        raise ProviderHTTPError(err.code, http_message(detail)) from None
    except urllib.error.URLError as err:
        raise ProviderHTTPError(0, f"无法连接模型服务：{err.reason}") from None
    except TimeoutError:
        raise ProviderHTTPError(0, "模型服务请求超时") from None


class ProviderHTTPError(RuntimeError):
    """HTTP 层错误（0 表示网络/超时），由各 provider 翻译成业务错误码。"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def post_json(url: str, payload: dict, api_key: str, timeout: int) -> dict:
    raw = _request(url, api_key, timeout, json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise ProviderHTTPError(0, "模型服务返回了非 JSON 响应") from None


def get_json(url: str, api_key: str, timeout: int) -> dict:
    raw = _request(url, api_key, timeout)
    try:
        return json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        raise ProviderHTTPError(0, "模型服务返回了非 JSON 响应") from None


def _media_suffix(prefix: bytes, default: str) -> str:
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP":
        return ".webp"
    if prefix[4:8] == b"ftyp":
        return ".mp4"
    return default


def download_media(url: str, default_suffix: str, max_bytes: int, timeout: int = 180) -> str:
    """下载到 uploads/generated/，返回可直接访问的 /uploads/... 路径。"""
    if not url.startswith("https://"):
        raise ProviderHTTPError(0, "模型服务返回的下载地址不是 HTTPS")
    generated = config.UPLOAD_DIR / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    name = f"{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    temporary = generated / f"{name}.part"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp, temporary.open("wb") as out:
            declared = getattr(resp, "headers", {}).get("Content-Length")
            size, prefix = 0, b""
            while True:
                block = resp.read(64 * 1024)
                if not block:
                    break
                size += len(block)
                if size > max_bytes:
                    raise ProviderHTTPError(0, "模型返回的文件超过大小上限")
                if len(prefix) < 16:
                    prefix += block[: 16 - len(prefix)]
                out.write(block)
        if size < 16 or (declared is not None and size != int(declared)):
            raise ProviderHTTPError(0, "模型文件下载不完整，请重试")
        target = generated / f"{name}{_media_suffix(prefix, default_suffix)}"
        temporary.replace(target)
        return f"/uploads/generated/{target.name}"
    finally:
        temporary.unlink(missing_ok=True)
