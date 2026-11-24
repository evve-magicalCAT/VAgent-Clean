# -*- coding: utf-8 -*-
"""火山方舟（Ark）的两件事：出图、看图。

B 用到的只有这两件：``ArkImage.generate()`` 出三视图和首帧，``ArkVision.judge()``
看抽出来的帧有没有跑偏。都只用标准库 ``urllib``，不引 SDK（红线：不加依赖）。

两个实现上的取舍来自官方样例 bytedance/agentkit-samples 的 ``image_generate.py``：
返回格式用 ``b64_json`` 而不是 ``url``——TOS 的地址不一定带签名，直接下载会 403；
拿 base64 自己解码落盘最稳。url 只作为兜底。
"""
from __future__ import annotations

import base64
import http.client
import json
import mimetypes
import time
import urllib.error
import urllib.request
from pathlib import Path


# seedream 的下限，低于这个像素数会直接 400
MIN_PIXELS = 3686400

# 重试这两类：限流和服务端抽风。4xx 里的参数错误不重试，重试也不会变对
RETRY_STATUS = (429, 500, 502, 503, 504)


class ArkError(RuntimeError):
    """方舟返回了错误，或者网络一直不通。"""


def _post(
    base_url: str, path: str, payload: dict, api_key: str, timeout: int = 180, retries: int = 2
) -> dict:
    """POST 一个 JSON，失败按次数重试，最后把错误原文抛出去。"""
    if not api_key:
        raise ArkError("没有 API key：先调 images.configure(api_key=...) 或设置 ARK_API_KEY")

    if not base_url:
        raise ArkError("请在 API 设置中填写图片模型 Base URL")
    url = base_url.rstrip("/") + path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last = ""

    for attempt in range(retries + 1):
        req = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={"Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            last = "HTTP %d: %s" % (exc.code, detail[:600])
            if exc.code in RETRY_STATUS and attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise ArkError(last)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            # IncompleteRead 也走这里：b64_json 的图能有 5MB 以上，连接中途断掉很常见，
            # 它不属于 OSError，不显式接住就会直接崩。
            last = "网络错误: %s" % exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise ArkError(last)

    raise ArkError(last or "未知错误")


def parse_size(size: str) -> tuple[int, int]:
    try:
        w, h = size.lower().split("x")
        return int(w), int(h)
    except (ValueError, AttributeError):
        raise ValueError("size 要写成 1920x1920 这种格式，收到的是 %r" % (size,))


def sniff_format(raw: bytes) -> str:
    """看魔术字节判断真实格式；认不出来返回空串。

    seedream 默认吐 **JPEG**，不管你把文件叫成什么。扩展名和内容对不上，浏览器会
    拒绝显示、图生图时 mime 也会传错，所以落盘前一律按内容改名。
    """
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if len(raw) > 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return ""


_MIME = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}


def _data_uri(path) -> str:
    raw = Path(path).read_bytes()
    fmt = sniff_format(raw) or (mimetypes.guess_type(str(path))[0] or "image/png").split("/")[-1]
    mime = _MIME.get(fmt) or "image/" + fmt
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii"))


def _as_image_ref(ref) -> str:
    """参考图：http(s) 地址原样传，本地文件转 base64 data URI。"""
    text = str(ref)
    if text.startswith(("http://", "https://", "data:")):
        return text
    return _data_uri(ref)


class ArkImage:
    """文生图 / 图生图。"""

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def generate(self, prompt: str, ref_images=None, size: str = "1920x1920", seed=None) -> dict:
        """出一张图，返回 ``{"data": bytes, "usage": {...}, "model": str}``。"""
        w, h = parse_size(size)
        if w * h < MIN_PIXELS:
            raise ValueError(
                "尺寸 %s 太小：seedream 要求至少 %d 像素，建议 1920x1920 或 2560x1440" % (size, MIN_PIXELS)
            )

        payload = {
            "model": self.model,
            "prompt": prompt,
            "size": size,
            "response_format": "b64_json",
            "watermark": False,
        }
        if seed is not None:
            payload["seed"] = int(seed)

        refs = [_as_image_ref(r) for r in (ref_images or [])]
        if refs:
            payload["image"] = refs[0] if len(refs) == 1 else refs

        result = _post(self.base_url, "/images/generations", payload, self.api_key)
        items = result.get("data") or []
        if not items:
            raise ArkError("返回里没有 data：%s" % json.dumps(result, ensure_ascii=False)[:400])

        item = items[0]
        raw = None
        if item.get("b64_json"):
            raw = base64.b64decode(item["b64_json"])
        elif item.get("url"):
            with urllib.request.urlopen(item["url"], timeout=120) as resp:
                raw = resp.read()

        if not raw:
            raise ArkError("既没有 b64_json 也没有 url：%s" % json.dumps(item, ensure_ascii=False)[:400])

        return {"data": raw, "usage": result.get("usage") or {}, "model": result.get("model") or self.model}

    def save(self, prompt: str, path, ref_images=None, size: str = "1920x1920", seed=None) -> dict:
        """出图并直接落盘，返回 ``{"path", "bytes", "usage"}``。

        返回的 path 可能和你传进来的扩展名不一样：seedream 默认吐 JPEG，传 ``x.png``
        会被改写成 ``x.jpg``，否则文件内容与后缀不符。
        """
        out = Path(path)
        got = self.generate(prompt, ref_images=ref_images, size=size, seed=seed)

        fmt = sniff_format(got["data"])
        if fmt and out.suffix.lower().lstrip(".") not in (fmt, "jpeg"):
            out = out.with_suffix("." + fmt)

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(got["data"])
        return {"path": str(out), "bytes": len(got["data"]), "usage": got["usage"]}


def parse_verdict(text: str) -> dict:
    """把模型回的文本解析成 ``{"pass": bool, "issues": [...]}``。

    模型经常把 JSON 包在 ```json 里，或者前后带一句解释，所以先剥围栏再找第一个大括号。
    解析不出来就当不通过——校验这种闸门，宁可拦错也别放过。
    """
    raw = (text or "").strip()
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            piece = part.strip()
            if piece.startswith("json"):
                piece = piece[4:].strip()
            if piece.startswith("{"):
                raw = piece
                break

    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(raw[start : end + 1])
        except ValueError:
            data = None
        if isinstance(data, dict):
            issues = data.get("issues") or []
            if not isinstance(issues, list):
                issues = [str(issues)]
            return {"pass": bool(data.get("pass")), "issues": [str(i) for i in issues]}

    return {"pass": False, "issues": ["模型没有返回可解析的判定结果：" + raw[:200]]}


class ArkVision:
    """看图判断：把帧和参考图一起丢给视觉模型，让它回答「一致吗」。"""

    def __init__(self, api_key: str, model: str, base_url: str = ""):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def ask(self, image_paths, prompt: str) -> str:
        content = []
        for path in image_paths:
            content.append({"type": "image_url", "image_url": {"url": _as_image_ref(path)}})
        content.append({"type": "text", "text": prompt})

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
        }
        result = _post(self.base_url, "/chat/completions", payload, self.api_key)
        choices = result.get("choices") or []
        if not choices:
            raise ArkError("返回里没有 choices：%s" % json.dumps(result, ensure_ascii=False)[:400])

        message = choices[0].get("message") or {}
        text = message.get("content")
        if isinstance(text, list):  # 有的模型把内容拆成多个片段
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
        return text or ""

    def judge(self, image_paths, prompt: str) -> dict:
        return parse_verdict(self.ask(image_paths, prompt))
