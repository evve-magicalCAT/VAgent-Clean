# -*- coding: utf-8 -*-
"""从视频里抽帧，给 B 的最后一道闸（抽帧校验）用。

只做三件事：探时长、按比例抽单帧、按比例抽 3 帧。

ffmpeg / ffprobe 的查找顺序：环境变量 ``VAGENT_FFMPEG``（指向目录或可执行文件）
→ ``PATH`` → 仓库外的 ``_tools/ffmpeg/bin``。三处都没有就明确报错，不猜。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

# 片头 / 中段 / 片尾。取 10% 而不是 0%，避开很多视频开头的黑场
RATIOS = (0.10, 0.50, 0.90)

# 交给视觉模型看的图不用原尺寸，720 宽足够看清长相和服装
SCALE_WIDTH = 720

_EXE = ".exe" if os.name == "nt" else ""


def _tool(name: str) -> str:
    """找到 ffmpeg 或 ffprobe 的完整路径。"""
    env = os.environ.get("VAGENT_FFMPEG", "").strip()
    if env:
        base = Path(env)
        cand = base / (name + _EXE) if base.is_dir() else base
        if cand.exists():
            return str(cand)

    found = shutil.which(name)
    if found:
        return found

    from .. import config  # 延迟导入，避免和 config 的初始化顺序打架

    local = config.BASE_DIR.parent / "_tools" / "ffmpeg" / "bin" / (name + _EXE)
    if local.exists():
        return str(local)

    raise FileNotFoundError(
        "找不到 %s：请设置环境变量 VAGENT_FFMPEG 指向 ffmpeg 所在目录，或把它放进 PATH" % name
    )


def probe_duration(video) -> float:
    """返回视频时长（秒）。读不出来就抛错，不返回 0 让调用方在 0 秒处抽帧。"""
    res = subprocess.run(
        [
            _tool("ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(video),
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        raise RuntimeError("ffprobe 读不出时长：%s" % (res.stderr or "").strip()[:300])
    try:
        return round(float(json.loads(res.stdout)["format"]["duration"]), 3)
    except (KeyError, ValueError, TypeError):
        raise RuntimeError("ffprobe 输出里没有 duration：%s" % res.stdout[:300])


def extract_frame(video, at: float, out_path) -> Path:
    """抽单帧存成 PNG。

    定位到片尾附近时 ffmpeg 会「抽不到帧 + 返回非 0」，所以按 t → t-0.2 → t-0.5
    依次退让，最后兜底从末尾 seek（``-sseof``）。这套退让顺序是照着生产代码抄的，
    比自己只试一次稳得多。
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    def grab(args) -> bool:
        res = subprocess.run(
            [_tool("ffmpeg"), "-y", *args, "-frames:v", "1", "-vf", "scale=%d:-2" % SCALE_WIDTH, str(out)],
            capture_output=True,
        )
        return res.returncode == 0 and out.exists() and out.stat().st_size > 0

    for ss in (at, max(0.0, at - 0.2), max(0.0, at - 0.5)):
        if grab(["-ss", "%.3f" % ss, "-i", str(video)]):
            return out

    if grab(["-sseof", "-0.2", "-i", str(video)]):
        return out

    raise RuntimeError("ffmpeg 在 %.3f 秒附近抽不到帧：%s" % (at, video))


def sample_frames(video, out_dir, prefix: str, ratios=RATIOS) -> list:
    """按比例抽帧，返回抽到的路径列表（顺序与 ratios 一致）。"""
    duration = probe_duration(video)
    if duration <= 0:
        raise RuntimeError("视频时长为 0，没法按比例抽帧：%s" % video)

    out_dir = Path(out_dir)
    paths = []
    for ratio in ratios:
        path = out_dir / ("%s-%02d.png" % (prefix, int(round(ratio * 100))))
        paths.append(extract_frame(video, duration * ratio, path))
    return paths
