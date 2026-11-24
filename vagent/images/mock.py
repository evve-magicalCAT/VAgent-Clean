# -*- coding: utf-8 -*-
"""Mock 图片 provider：不联网、不依赖第三方库，用标准库写出真正的 PNG。

存在的理由只有一个：``VAGENT_MODE=mock``（默认）时，让「出三视图 / 出首帧」这条链路
能完整跑通，产物是合法 PNG，浏览器 ``<img>`` 可以直接显示。

不画逼真的图，只画「一眼能分清正面、侧面、背面」的示意轮廓：
同一个 asset id 每次出的图完全一致，方便测试断言和人工比对。
"""
from __future__ import annotations

import hashlib
import struct
import zlib
from pathlib import Path

# 固定顺序，调用方按这个顺序取图
VIEWS = ("front", "side", "back")

# 每个视角一套配色，靠颜色也能区分
_PALETTE = {
    "front": ((26, 28, 34), (245, 129, 60)),
    "side": ((26, 28, 34), (196, 202, 214)),
    "back": ((26, 28, 34), (138, 143, 152)),
}
_FLOOR = ((26, 28, 34), (12, 13, 16))


def write_png(path, width: int, height: int, pixels: bytes) -> Path:
    """把 RGB 像素（行优先，每像素 3 字节）写成 PNG。"""
    stride = width * 3
    if len(pixels) != stride * height:
        raise ValueError("像素数量不对：期望 %d 字节，实际 %d" % (stride * height, len(pixels)))

    raw = bytearray()
    for y in range(height):
        raw.append(0)  # 每行的 filter type，0 = None
        raw += pixels[y * stride : (y + 1) * stride]

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(bytes(raw), 9)))
        fh.write(chunk(b"IEND", b""))
    return path


def _mix(c1, c2, t: float = 0.5):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def _rect(buf: bytearray, w: int, h: int, x0: int, y0: int, x1: int, y1: int, color) -> None:
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(w, x1)
    y1 = min(h, y1)
    if x1 <= x0:
        return
    row = bytes(color) * (x1 - x0)
    for y in range(y0, y1):
        off = (y * w + x0) * 3
        buf[off : off + len(row)] = row


def _ellipse(buf: bytearray, w: int, h: int, cx: int, cy: int, rx: int, ry: int, color) -> None:
    if rx <= 0 or ry <= 0:
        return
    for y in range(cy - ry, cy + ry + 1):
        if y < 0 or y >= h:
            continue
        dy = (y - cy) / float(ry)
        span = int(rx * (1.0 - dy * dy) ** 0.5)
        if span <= 0:
            continue
        _rect(buf, w, h, cx - span, y, cx + span + 1, y + 1, color)


def _seed_of(key) -> int:
    """由业务 id 派生稳定种子；不用 hash()，那个跨进程会变。"""
    return int(hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:8], 16)


def draw_view(view: str, size: int, seed: int) -> bytearray:
    """画一个视角。返回行优先 RGB 字节。"""
    w = h = size
    bg, ink = _PALETTE[view]
    buf = bytearray(bytes(bg) * (w * h))

    floor_y = int(h * 0.82)
    _rect(buf, w, h, 0, floor_y, w, h, _mix(*_FLOOR))

    # 同一个人：躯干宽度、身高由同一个 seed 决定，三个视角一致
    scale = 0.94 + (seed % 9) * 0.015
    body_h = int(h * 0.38 * scale)
    full_w = int(w * 0.30 * scale)
    body_w = int(full_w * 0.60) if view == "side" else full_w
    cx = w // 2 + (int(w * 0.05) if view == "side" else 0)
    top = floor_y - body_h

    _rect(buf, w, h, cx - body_w // 2, top, cx + body_w // 2, floor_y, ink)

    head_r = max(6, int(full_w * 0.44))
    head_cy = max(head_r + 2, top - int(head_r * 0.9))
    _ellipse(buf, w, h, cx, head_cy, head_r, head_r, ink)

    if view == "side":
        # 侧面：加一个鼻子凸起，没有双眼
        nose = max(3, head_r // 3)
        _rect(buf, w, h, cx + head_r - 2, head_cy - nose // 2, cx + head_r + nose, head_cy + nose // 2, ink)
    elif view == "front":
        # 正面：有双眼
        eye_dx = max(3, head_r // 3)
        eye_r = max(2, head_r // 7)
        _ellipse(buf, w, h, cx - eye_dx, head_cy - eye_r, eye_r, eye_r, bg)
        _ellipse(buf, w, h, cx + eye_dx, head_cy - eye_r, eye_r, eye_r, bg)
    else:
        # 背面：多一块「后脑勺」，没有五官
        _ellipse(
            buf, w, h, cx, head_cy - head_r // 4, int(head_r * 0.8), int(head_r * 0.5), _mix(ink, bg, 0.35)
        )

    # 角标：正面 1 个点、侧面 2 个、背面 3 个
    dot_r = max(3, w // 90)
    for i in range(VIEWS.index(view) + 1):
        _ellipse(buf, w, h, w - int(w * 0.06) - i * dot_r * 3, int(h * 0.06), dot_r, dot_r, ink)
    return buf


def render_views(asset_id: str, out_dir, size: int = 512):
    """出资产的三视图，返回 [正面, 侧面, 背面] 三个路径。"""
    out_dir = Path(out_dir)
    seed = _seed_of(asset_id)
    paths = []
    for view in VIEWS:
        path = out_dir / ("%s-%s.png" % (asset_id, view))
        write_png(path, size, size, draw_view(view, size, seed))
        paths.append(path)
    return paths


def draw_keyframe(size: tuple[int, int], seed: int) -> bytearray:
    """画一张 16:9 的示意首帧：天地线 + 几个方块 + 一个人。"""
    w, h = size
    bg = (26, 28, 34)
    buf = bytearray(bytes(bg) * (w * h))
    horizon = int(h * 0.62)
    _rect(buf, w, h, 0, horizon, w, h, (16, 17, 21))

    # 远景方块，数量随 seed 变
    for i in range(3 + seed % 4):
        bw = int(w * (0.06 + ((seed >> (i * 3)) % 7) * 0.012))
        bh = int(h * (0.12 + ((seed >> (i * 2)) % 9) * 0.03))
        x = int(w * (0.08 + i * 0.12))
        if x + bw < w:
            _rect(buf, w, h, x, horizon - bh, x + bw, horizon, (34, 36, 44) if i % 2 else (44, 47, 56))

    # 人物
    cx, ground = int(w * 0.5), int(h * 0.88)
    body_w = int(w * 0.07)
    body_h = int(h * 0.22)
    ink = (245, 129, 60)
    _rect(buf, w, h, cx - body_w // 2, ground - body_h, cx + body_w // 2, ground, ink)
    head_r = max(6, int(body_w * 0.55))
    _ellipse(buf, w, h, cx, ground - body_h - head_r, head_r, head_r, ink)

    # 左上角一道琥珀色进度条，证明这是「生成的」而不是空图
    _rect(
        buf,
        w,
        h,
        int(w * 0.04),
        int(h * 0.05),
        int(w * (0.04 + 0.18 * ((seed % 20) + 1) / 20)),
        int(h * 0.065),
        ink,
    )
    return buf


def render_keyframe(shot_id: str, out_dir, size: tuple[int, int] = (768, 432)):
    """出镜头首帧，返回路径。"""
    out_dir = Path(out_dir)
    path = out_dir / ("%s-first.png" % shot_id)
    write_png(path, size[0], size[1], draw_keyframe(size, _seed_of(shot_id)))
    return path


def judge(clip_frames, ref_images):
    """mock 校验：永远通过，但把「看了哪些图」原样报回去，方便断言链路真的走到这里。"""
    return {
        "pass": True,
        "issues": [],
        "checked": {"frames": [str(p) for p in clip_frames], "refs": [str(p) for p in ref_images]},
    }
