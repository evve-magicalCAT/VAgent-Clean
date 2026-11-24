# -*- coding: utf-8 -*-
"""C · 视频 provider：MiniMax 首帧生视频（图生视频 I2V）+ 文生视频（T2V）兜底。

对外只有四个函数：

- ``submit(prompt, duration, first_frame=...)``：提交，返回 provider 任务 ID
- ``query(task_id)``：查询状态，返回 ``{state, url, error}``
- ``download(url)``：把成片落到 ``uploads/generated/``，返回 /uploads/... 路径
- ``resolve_config() / is_configured()``：读本地设置里的 key / 模型 / 域名

两条通道共用 MiniMax 同一个域名，但版本不同：

- 有首帧 → ``POST /v1/video_generation``，``first_frame_image`` + ``prompt``（Hailuo 系列）
- 没有首帧 → ``POST /v2/video_generation``，``content`` 数组 + ``ratio``（H3 系列，兜底）

查询/取片的返回结构也不同，``query()`` 会先试 v1，再退到 v2。
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import time
import urllib.parse

from .. import config
from ..db import load_settings, record_api_call
from .common import VIDEO_MAX_BYTES, ProviderHTTPError, download_media, get_json, post_json

DEFAULT_I2V_MODEL = "MiniMax-Hailuo-2.3"
DEFAULT_RESOLUTION = "768P"
DEFAULT_TIMEOUT = 60
SILENT_HINT = "\n\nNo dialogue, no voice-over, no music, no sound effects: a completely silent video."

# 只有这些模型吃 first_frame_image；设置里如果还留着 H3 这类文生视频模型，I2V 时换成默认
_I2V_MODELS = ("minimax-hailuo", "i2v-01")

# Hailuo 只接受 6 / 10 秒
_HAILUO_SECONDS = (6, 10)


class VideoError(RuntimeError):
    def __init__(self, code: str, message: str, status: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _host(base: str) -> str:
    """把 ``https://api.minimax.cn/v2`` 这类带路径的地址收敛成 ``https://api.minimax.cn``。"""
    parts = urllib.parse.urlsplit(base.strip())
    if not parts.scheme or not parts.netloc:
        raise VideoError("BAD_REQUEST", "视频模型 Base URL 不是合法地址", 400)
    return "%s://%s" % (parts.scheme, parts.netloc)


def resolve_config() -> dict:
    cfg = load_settings().get("video") or {}
    base = (cfg.get("base_url") or "").strip()
    model = (cfg.get("model") or "").strip() or DEFAULT_I2V_MODEL
    try:
        host = _host(base)
    except VideoError:
        host = ""
    return {
        "host": host,
        "base_url": base.rstrip("/"),
        "model": model,
        "api_key": (cfg.get("api_key") or "").strip(),
    }


def is_configured() -> bool:
    return bool(resolve_config()["api_key"])


def _is_i2v(model: str) -> bool:
    low = model.strip().lower()
    return any(low.startswith(prefix) for prefix in _I2V_MODELS)


def video_options(model: str) -> dict:
    """可选画质与时长，给前端和入参校验用。"""
    if _is_i2v(model):
        return {
            "resolutions": ["768P", "1080P"],
            "durations": list(_HAILUO_SECONDS),
            "duration_min": 6,
            "duration_max": 10,
        }
    if model.strip().lower() == "minimax-h3-max":
        return {"resolutions": ["480P", "768P"], "durations": [], "duration_min": 5, "duration_max": 15}
    return {"resolutions": ["768P", "2K"], "durations": [], "duration_min": 4, "duration_max": 15}


def _clamp_duration(model: str, duration) -> int:
    """Hailuo 只认 6 / 10：把镜头时长就近抬到 6 或 10。"""
    try:
        seconds = int(round(float(duration)))
    except (TypeError, ValueError):
        return 6
    if _is_i2v(model):
        return 6 if seconds <= 6 else 10
    options = video_options(model)
    return min(options["duration_max"], max(options["duration_min"], seconds))


def _clamp_resolution(model: str, resolution: str) -> str:
    options = video_options(model)
    want = (resolution or "").strip().upper()
    if want in options["resolutions"]:
        return want
    return DEFAULT_RESOLUTION if DEFAULT_RESOLUTION in options["resolutions"] else options["resolutions"][0]


def _translate(err: ProviderHTTPError) -> VideoError:
    if err.status in (401, 403):
        return VideoError("BAD_REQUEST", "视频模型鉴权失败：%s" % err.message, 400)
    if err.status == 429:
        return VideoError("INTERNAL_ERROR", "视频模型限流，请稍后再试：%s" % err.message, 500)
    return VideoError("INTERNAL_ERROR", "视频生成失败：%s" % err.message, 500)


def _raise_for_base_resp(resp: dict) -> None:
    """MiniMax 习惯用 HTTP 200 + base_resp.status_code 报错，这里统一翻成业务错误。"""
    base = resp.get("base_resp") or {}
    if not isinstance(base, dict):
        return
    code = base.get("status_code")
    if code in (None, 0):
        return
    msg = str(base.get("status_msg") or "视频模型返回错误")[:300]
    if code in (1004, 2049):
        raise VideoError("BAD_REQUEST", "视频模型鉴权失败：%s" % msg, 400)
    if code == 1008:
        raise VideoError("BAD_REQUEST", "视频模型账户余额不足", 400)
    if code in (1026, 1027):
        raise VideoError("BAD_REQUEST", "视频描述涉及敏感内容：%s" % msg, 400)
    if code == 1002:
        raise VideoError("INTERNAL_ERROR", "视频模型限流，请稍后再试：%s" % msg, 500)
    raise VideoError("INTERNAL_ERROR", "视频生成失败（%s）：%s" % (code, msg), 500)


def submit(
    prompt: str,
    duration: float,
    first_frame: str = "",
    resolution: str = "",
    ratio: str = "",
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """提交一次生成，返回 provider 任务 ID。不在这里轮询，避免占住请求线程。"""
    cfg = resolve_config()
    if not cfg["api_key"]:
        raise VideoError("BAD_REQUEST", "还没有配置视频模型 API Key", 400)
    if not cfg["host"]:
        raise VideoError("BAD_REQUEST", "请在 API 设置中填写视频模型 Base URL", 400)
    text = (prompt or "").strip()
    if not text:
        raise VideoError("BAD_REQUEST", "视频提示词不能为空", 400)

    if first_frame:
        model = cfg["model"] if _is_i2v(cfg["model"]) else DEFAULT_I2V_MODEL
        body = {
            "model": model,
            "first_frame_image": first_frame,
            "prompt": text[:2000],
            "duration": _clamp_duration(model, duration),
            "resolution": _clamp_resolution(model, resolution),
            "prompt_optimizer": False,
            "aigc_watermark": False,
        }
        url = cfg["host"] + "/v1/video_generation"
    else:
        model = cfg["model"]
        body = {
            "model": model,
            "content": [{"type": "text", "text": text[:2000] + SILENT_HINT}],
            "duration": _clamp_duration(model, duration),
            "resolution": _clamp_resolution(model, resolution),
            "ratio": ratio if ratio in ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16") else "16:9",
        }
        url = cfg["host"] + "/v2/video_generation"

    try:
        resp = post_json(url, body, cfg["api_key"], timeout)
    except ProviderHTTPError as err:
        raise _translate(err) from None
    _raise_for_base_resp(resp)
    task_id = resp.get("task_id") or (resp.get("task") or {}).get("id")
    if not task_id:
        base = resp.get("base_resp") or {}
        reason = base.get("status_msg") or "视频模型没有返回任务 ID"
        raise VideoError("INTERNAL_ERROR", str(reason)[:300], 500)
    record_api_call("video", model)
    return str(task_id)


def submit_reference(
    prompt: str,
    reference_images: list | None = None,
    duration: float = 5,
    resolution: str = "768P",
    ratio: str = "16:9",
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """H3 全能参考（reference-to-video）：文字 + reference_image 参考图，直接出片。"""
    cfg = resolve_config()
    if not cfg["api_key"]:
        raise VideoError("BAD_REQUEST", "还没有配置视频模型 API Key", 400)
    if not cfg["host"]:
        raise VideoError("BAD_REQUEST", "请在 API 设置中填写视频模型 Base URL", 400)
    text = (prompt or "").strip()
    if not text:
        raise VideoError("BAD_REQUEST", "视频提示词不能为空", 400)
    refs = [ref for ref in (reference_images or []) if ref][:9]
    if not refs:
        raise VideoError("BAD_REQUEST", "全能参考至少需要一张参考图", 400)
    model = cfg["model"] if "h3" in cfg["model"].lower() else "MiniMax-H3"
    content = [{"type": "text", "text": text[:7000]}]
    for ref in refs:
        content.append({"type": "image_url", "image_url": {"url": ref}, "role": "reference_image"})
    body = {
        "model": model,
        "content": content,
        "duration": _clamp_duration(model, duration),
        "resolution": _clamp_resolution(model, resolution),
        "ratio": ratio if ratio in ("21:9", "16:9", "4:3", "1:1", "3:4", "9:16") else "16:9",
        "prompt_optimizer": False,
        "aigc_watermark": False,
    }
    try:
        resp = post_json(cfg["host"] + "/v2/video_generation", body, cfg["api_key"], timeout)
    except ProviderHTTPError as err:
        raise _translate(err) from None
    _raise_for_base_resp(resp)
    task_id = resp.get("task_id") or (resp.get("task") or {}).get("id")
    if not task_id:
        base = resp.get("base_resp") or {}
        reason = base.get("status_msg") or "视频模型没有返回任务 ID"
        raise VideoError("INTERNAL_ERROR", str(reason)[:300], 500)
    record_api_call("video", model)
    return str(task_id)


def _retrieve_file(host: str, key: str, file_id: str, timeout: int) -> str:
    if not file_id:
        raise VideoError("INTERNAL_ERROR", "视频任务成功但没有返回文件 ID", 500)
    url = host + "/v1/files/retrieve?file_id=" + urllib.parse.quote(file_id, safe="")
    try:
        resp = get_json(url, key, timeout)
    except ProviderHTTPError as err:
        raise _translate(err) from None
    _raise_for_base_resp(resp)
    link = str((resp.get("file") or {}).get("download_url") or "")
    if not link:
        raise VideoError("INTERNAL_ERROR", "视频任务成功但没有返回下载地址", 500)
    return link


def _query_i2v(host: str, key: str, task_id: str, timeout: int):
    """v1 查询。返回 None 表示这个任务不属于 v1。"""
    url = host + "/v1/query/video_generation?task_id=" + urllib.parse.quote(str(task_id), safe="")
    try:
        resp = get_json(url, key, timeout)
    except ProviderHTTPError as err:
        raise _translate(err) from None
    _raise_for_base_resp(resp)
    raw = str(resp.get("status") or "")
    if not raw:
        return None
    state = {
        "preparing": "queued",
        "queueing": "queued",
        "processing": "running",
        "success": "succeeded",
        "fail": "failed",
    }.get(raw.strip().lower(), "")
    if not state:
        raise VideoError("INTERNAL_ERROR", "视频模型返回了未知状态：%s" % raw, 500)
    url_out = ""
    if state == "succeeded":
        url_out = _retrieve_file(host, key, str(resp.get("file_id") or ""), timeout)
    return {"state": state, "url": url_out, "error": ""}


def _query_t2v(cfg: dict, task_id: str, timeout: int) -> dict:
    """v2 查询（老通道）。"""
    url = cfg["host"] + "/v2/query/video_generation/" + urllib.parse.quote(str(task_id), safe="")
    try:
        resp = get_json(url, cfg["api_key"], timeout)
    except ProviderHTTPError as err:
        raise _translate(err) from None
    _raise_for_base_resp(resp)
    task = resp.get("task")
    if not isinstance(task, dict):
        base = resp.get("base_resp") or {}
        raise VideoError(
            "INTERNAL_ERROR", str(base.get("status_msg") or "视频模型没有返回任务状态")[:300], 500
        )
    state = str(task.get("status") or "")
    if state not in ("queued", "running", "succeeded", "failed", "cancelled"):
        raise VideoError("INTERNAL_ERROR", "视频模型返回了未知状态：%s" % (state or "空"), 500)
    url = ""
    content = task.get("content")
    if isinstance(content, dict):
        url = str(content.get("url") or "")
    return {"state": state, "url": url, "error": task.get("error") or ""}


def query(task_id: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """查询任务状态，返回 {state, url, error}。

    先按 v1（首帧生视频）查；v1 不认得这个任务（对话里用文生视频 v2 建的）就退到 v2。
    这里不能直接把 v1 的报错抛出去，否则这类镜头会永远卡在 0%。
    """
    cfg = resolve_config()
    if not cfg["api_key"]:
        raise VideoError("BAD_REQUEST", "还没有配置视频模型 API Key", 400)
    if not cfg["host"]:
        raise VideoError("BAD_REQUEST", "请在 API 设置中填写视频模型 Base URL", 400)
    try:
        got = _query_i2v(cfg["host"], cfg["api_key"], task_id, timeout)
    except VideoError:
        got = None
    if got is not None:
        return got
    return _query_t2v(cfg, task_id, timeout)


def download(url: str) -> str:
    """把生成好的视频落到 uploads/generated/，返回 /uploads/... 路径。"""
    if not url:
        raise VideoError("INTERNAL_ERROR", "视频任务成功但没有返回下载地址", 500)
    try:
        return download_media(url, ".mp4", VIDEO_MAX_BYTES)
    except ProviderHTTPError as err:
        raise VideoError("INTERNAL_ERROR", "视频下载失败：%s" % err.message, 500) from None


# ---------------------------------------------------------------- 拼接成片
# 模型只给 6 / 10 秒，而时间轴上的镜头时长是任意的。成片必须按时间轴对齐，
# 所以这里在拼接时统一「裁到目标时长」或「变速压到目标时长」，一次编码出一条片子。

STITCH_SIZE = (1920, 1080)
STITCH_FPS = 30


def _tool(name: str) -> str:
    """找 ffmpeg / ffprobe：环境变量 VAGENT_FFMPEG → PATH → 仓库外的 _tools/ffmpeg/bin。"""
    env = os.environ.get("VAGENT_FFMPEG", "").strip()
    exe = name + (".exe" if os.name == "nt" else "")
    if env:
        base = pathlib.Path(env)
        cand = base / exe if base.is_dir() else base
        if cand.exists():
            return str(cand)
    found = shutil.which(name)
    if found:
        return found
    local = config.BASE_DIR.parent / "_tools" / "ffmpeg" / "bin" / exe
    if local.exists():
        return str(local)
    raise VideoError(
        "BAD_REQUEST",
        "找不到 %s：把 ffmpeg 解压到 %s，或设置环境变量 VAGENT_FFMPEG 指向它" % (name, local.parent),
        400,
    )


def probe_duration(path) -> float:
    """读视频真实时长（秒）。读不出来就报错，不返回 0 让裁剪算错。"""
    res = subprocess.run(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise VideoError("INTERNAL_ERROR", "ffprobe 读不出时长：%s" % (res.stderr or "").strip()[:200], 500)
    try:
        return float(json.loads(res.stdout)["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        raise VideoError("INTERNAL_ERROR", "ffprobe 输出里没有 duration", 500)


def stitch_filters(
    have, durations, mode: str = "trim", width=STITCH_SIZE[0], height=STITCH_SIZE[1], fps=STITCH_FPS
):
    """生成 filter_complex。``have`` 是每段实际时长，``durations`` 是时间轴上要的时长。

    - ``trim``：多出来的裁掉，不够的定格补足（默认，动作速度不变）
    - ``speed``：整段变速到目标时长（6 秒压成 3 秒就是 2 倍速）
    """
    parts, labels, total = [], [], 0.0
    for i, (got, want) in enumerate(zip(have, durations)):
        got = float(got or 0.0)
        target = float(want) if want and float(want) > 0 else (got or 6.0)
        total += target
        if mode == "speed" and got > 0:
            chain = "setpts=PTS*%.6f," % (target / got)
        else:
            pad = max(0.0, target - got)
            chain = "tpad=stop_mode=clone:stop_duration=%.3f,trim=0:%.3f," % (pad, max(target, 0.05))
        parts.append(
            "[%d:v]%sscale=%d:%d:force_original_aspect_ratio=decrease,"
            "pad=%d:%d:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=%d[v%d]"
            % (i, chain, width, height, width, height, fps, i)
        )
        labels.append("[v%d]" % i)
    parts.append("%sconcat=n=%d:v=1:a=0[out]" % ("".join(labels), len(labels)))
    return ";".join(parts), total


def stitch(clips, durations, mode: str = "trim", width=STITCH_SIZE[0], height=STITCH_SIZE[1], fps=STITCH_FPS):
    """把逐镜成片按时间轴拼成一条，返回 {path, url, duration}。"""
    if not clips:
        raise VideoError("BAD_REQUEST", "还没有可拼接的镜头", 400)
    if len(clips) != len(durations):
        raise VideoError("BAD_REQUEST", "拼接参数不匹配", 400)
    have = [probe_duration(path) for path in clips]
    graph, total = stitch_filters(have, durations, mode, width, height, fps)

    out_dir = config.UPLOAD_DIR / "generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / ("stitch-%s.mp4" % time.strftime("%Y%m%d%H%M%S"))
    args = [_tool("ffmpeg"), "-y"]
    for path in clips:
        args += ["-i", str(path)]
    args += [
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(out),
    ]
    res = subprocess.run(args, capture_output=True, text=True)
    if res.returncode != 0 or not out.exists():
        raise VideoError("INTERNAL_ERROR", "拼接失败：%s" % (res.stderr or "").strip()[-300:], 500)
    return {"path": str(out), "url": "/uploads/generated/%s" % out.name, "duration": round(total, 2)}
