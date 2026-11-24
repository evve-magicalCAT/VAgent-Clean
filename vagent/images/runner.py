# -*- coding: utf-8 -*-
"""B（图片 Agent）对外的唯一入口：``run(job)``。

这里有两种**完全不同性质**的产物，不要混：

- **资产三视图**（``asset_views``）：属于「不动的资产」。同一个角色/场景在整个项目里
  只有一套，确认后长期保存，后续所有镜头都引用它。落盘在 ``<out>/assets/<asset_id>/``
  的固定位置，重跑就覆盖，不跟着某一次任务消失。
- **镜头首帧**（``keyframe``）：属于「某一镜」。每镜一张，才对应 ``contracts.KeyframeResult``
  的 ``first_frame``。``last_frame`` 我们不填。

``verify`` 不产生新图，只对已有的视频抽帧做判定。

``mode`` 默认 ``mock``：不出网、不花钱。要真出图必须先
``configure(api_key=..., mode="live")``。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .. import config
from . import frames as frames_mod
from . import mock, prompts
from .ark import ArkError, ArkImage, ArkVision, parse_verdict

MODE_MOCK = "mock"
MODE_LIVE = "live"

TASK_ASSET_VIEWS = "asset_views"
TASK_ASSET_IMAGE = "asset_image"
TASK_KEYFRAME = "keyframe"
TASK_VERIFY = "verify"

# 三个固定视角，顺序就是交付顺序
VIEWS = ("front", "side", "back")

# 同一视角可能被 mock 写成 .png、被真模型写成 .jpg，读回来时按这个顺序找
_EXTS = (".jpg", ".jpeg", ".png", ".webp")

# 尺寸贴 seedream 的下限，再小直接被拒
SIZE_ASSET_VIEW = "1920x1920"
SIZE_KEYFRAME = "2560x1440"
# 三视图是一张横向设定稿（左特写 + 正/侧/背三格），用 16:9 才放得下四格
SIZE_SHEET = "2560x1440"
SHEET_STEM = "sheet"

_STATE = {
    "mode": (os.environ.get("VAGENT_MODE") or MODE_MOCK).strip().lower(),
    "api_key": os.environ.get("ARK_API_KEY", ""),
    "base_url": os.environ.get("ARK_BASE_URL", ""),
    "out_dir": None,
    "image_model": os.environ.get("SEEDREAM_MODEL_ID") or "doubao-seedream-5-5-261028",
    "vision_model": os.environ.get("SEED_MODEL_ID") or "doubao-seed-2-1-lite-260915",
}
_CLIENTS = {"image": None, "vision": None}


def configure(**kwargs) -> None:
    """改配置。可改：mode / api_key / base_url / out_dir / image_model / vision_model。"""
    if "mode" in kwargs and kwargs["mode"]:
        mode = str(kwargs["mode"]).strip().lower()
        if mode not in (MODE_MOCK, MODE_LIVE):
            raise ValueError("mode 只能是 mock 或 live，收到 %r" % (kwargs["mode"],))
        _STATE["mode"] = mode
    for key in ("api_key", "base_url", "image_model", "vision_model"):
        if key in kwargs and kwargs[key] is not None:
            _STATE[key] = kwargs[key]
    if "out_dir" in kwargs:
        _STATE["out_dir"] = Path(kwargs["out_dir"]) if kwargs["out_dir"] else None
    _CLIENTS["image"] = None
    _CLIENTS["vision"] = None


def mode() -> str:
    return _STATE["mode"]


def _clients() -> dict:
    """惰性建客户端；没 key 时只在真正要出图的那一刻才报错。"""
    if _STATE["mode"] != MODE_LIVE:
        return {}
    if _CLIENTS["image"] is None:
        _CLIENTS["image"] = ArkImage(_STATE["api_key"], _STATE["image_model"], _STATE["base_url"])
        _CLIENTS["vision"] = ArkVision(_STATE["api_key"], _STATE["vision_model"], _STATE["base_url"])
    return _CLIENTS


def _out_dir() -> Path:
    out = Path(_STATE["out_dir"] or (config.UPLOAD_DIR / "gen"))
    out.mkdir(parents=True, exist_ok=True)
    return out


def asset_dir(asset_id) -> Path:
    """资产图的固定目录。重跑覆盖同一批文件，不会越积越多。"""
    path = _out_dir() / "assets" / str(asset_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _url(path) -> str:
    """把落盘路径换成浏览器能访问的地址；不在 uploads 下就返回空串。"""
    try:
        rel = Path(path).resolve().relative_to(config.UPLOAD_DIR.resolve())
    except (ValueError, OSError):
        return ""
    return "/uploads/" + rel.as_posix()


def _pick(job, key, default=None):
    """job 可能是 Job 数据类，也可能只是 dict。"""
    if isinstance(job, dict):
        return job.get(key, default)
    return getattr(job, key, default)


def _entry(view: str, path) -> dict:
    return {"view": view, "path": str(path), "url": _url(path), "bytes": Path(path).stat().st_size}


def _sum_usage(usages) -> dict:
    """把多张图的 usage 加起来。"""
    total = {}
    for usage in usages or []:
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                total[key] = total.get(key, 0) + value
    return total


def _drop_siblings(directory: Path, stem: str, keep: Path) -> None:
    """同一个视角只留一个文件，避免 mock 的 .png 和真模型的 .jpg 同时存在。"""
    for ext in _EXTS:
        other = directory / (stem + ext)
        if other != keep and other.exists():
            other.unlink()


def _normalize(path: Path, directory: Path, stem: str) -> Path:
    """把文件改成固定的 ``<stem><真实后缀>``，一个视角只留一份。

    真模型的返回后缀可能是 .jpg，mock 又是 .png，名字还带 asset_id 前缀；
    资产目录要能直接被 read_views 认出来，所以统一改名。
    """
    target = directory / (stem + path.suffix.lower())
    if path != target:
        if target.exists():
            target.unlink()
        path.replace(target)
    _drop_siblings(directory, stem, target)
    return target


def read_views(asset_id) -> list:
    """读回已经保存的资产三视图。没出过图就返回空列表，不报错。

    现在是「一张设定稿」，所以先找 ``sheet``；老资产（改造前落下的是 front/side/back
    三张）继续按三张读，别让已有项目读不到图。
    """
    directory = _out_dir() / "assets" / str(asset_id)
    for ext in _EXTS:
        path = directory / (SHEET_STEM + ext)
        if path.exists():
            return [_entry(SHEET_STEM, path)]
    found = []
    for view in VIEWS:
        for ext in _EXTS:
            path = directory / (view + ext)
            if path.exists():
                found.append(_entry(view, path))
                break
    return found


def _dna_for(name, kind, desc, refs) -> dict:
    """先让视觉模型读一遍参考图，产出「画风 + 每张必须一致 + 背面怎么画」的清单。

    清单只是辅助件：没图、没 key、模型答歪了都退回 ``prompts.fallback_dna``，
    绝不能让出图卡在这一步。
    """
    if refs:
        try:
            vision = _clients().get("vision")
            if vision is not None:
                dna = prompts.parse_dna(vision.ask([refs[0]], prompts.DNA_PROMPT))
                if dna:
                    return dna
        except Exception:  # noqa: BLE001 - 清单失败不该拖垮出图
            pass
    return prompts.fallback_dna(name, kind, desc)


def run(job) -> dict:
    """执行一条任务，返回结果字典。"""
    payload = _pick(job, "payload") or {}
    if not isinstance(payload, dict):
        raise ValueError("payload 必须是 dict，收到 %r" % (type(payload).__name__,))

    task = payload.get("task")
    if not task:
        task = TASK_ASSET_VIEWS if ("asset_id" in payload and "shot_id" not in payload) else TASK_KEYFRAME

    if task == TASK_ASSET_VIEWS:
        return run_asset_views(**{k: v for k, v in payload.items() if k != "task"})
    if task == TASK_ASSET_IMAGE:
        return run_asset_image(**{k: v for k, v in payload.items() if k != "task"})
    if task == TASK_KEYFRAME:
        return run_keyframe(**{k: v for k, v in payload.items() if k != "task"})
    if task == TASK_VERIFY:
        return run_verify(**{k: v for k, v in payload.items() if k != "task"})
    raise ValueError(
        "不认识的 task：%r（只支持 %s / %s / %s）" % (task, TASK_ASSET_VIEWS, TASK_KEYFRAME, TASK_VERIFY)
    )


def _save_sheet(image, name, kind, desc, dna, directory, size, refs):
    """出一张三视图设定稿。

    模型的设定清单里常出现「胸口」「裸露」这类词，会直接被内容审核拦下（实测 400
    InputTextSensitiveContentDetected）。这里只在这一种错误上换中性词重试一次，
    其它错误照常抛出去——不要把所有失败都吞成「重试」。
    """
    path = directory / (SHEET_STEM + ".png")
    try:
        return image.save(
            prompts.three_view_sheet(name, kind, desc, dna=dna), path, ref_images=refs, size=size
        )
    except ArkError as exc:
        if "SensitiveContent" not in str(exc):
            raise
        return image.save(
            prompts.three_view_sheet(name, kind, desc, dna=prompts.soften_dna(dna)),
            path,
            ref_images=refs,
            size=size,
        )


def audit_sheet(sheet_path, ref_path=None, dna=None) -> dict:
    """出图后的体检：核对设定清单里的每条附属结构有没有画对、有没有被裁、有没有对称。

    只报告，**不自动重抽**——设定稿是一整张，重抽要整张重来，交给人决定更划算。
    任何异常都退回 ``pass=None``，绝不能让体检把出图搞失败。
    """
    vision = _clients().get("vision")
    if vision is None:
        return {"pass": None, "gaps": [], "error": "没有可用的视觉模型"}
    images = [str(sheet_path)]
    if ref_path:
        images.insert(0, str(ref_path))
    prompt = prompts.AUDIT
    if dna:
        prompt += "\n\n设定清单：\n" + json.dumps(dna, ensure_ascii=False, indent=2)
    try:
        verdict = parse_verdict(vision.ask(images, prompt))
    except Exception as exc:  # noqa: BLE001 - 体检失败不该拖垮出图
        return {"pass": None, "gaps": [], "error": str(exc)}
    gaps = list(verdict.get("issues") or [])
    if gaps and gaps[0].startswith("模型没有返回可解析"):
        return {"pass": None, "gaps": [], "error": gaps[0]}
    return {"pass": bool(verdict.get("pass")), "gaps": gaps}


def run_asset_views(asset_id=None, name=None, type="角色", desc="", ref_images=None, size=None) -> dict:
    """出资产三视图并**存到资产的固定位置**（不是某个任务的临时产物）。

    产物是一张设定稿：左边头部特写，后面正面 / 侧身 / 背面三格等高全身。出图前先让
    视觉模型读一遍 ``ref_images`` 的第一张，产出一份设定清单（画风、四格必须一致的
    东西、背面怎么画），四格由模型在一张图里一次画完——这样它自己保证四格是同一个
    角色，比分开出三张再靠提示词对齐更稳。
    """
    asset_id = str(asset_id or "").strip()
    if not asset_id:
        raise ValueError("asset_views 需要 asset_id")

    name = name or asset_id
    refs = [r for r in (ref_images or []) if r]
    out = asset_dir(asset_id)
    usages = []
    views = []

    if _STATE["mode"] == MODE_MOCK:
        # mock 只吃整数；传进来的 "1920x1920" 之类是给真模型的，这里忽略
        size_px = 512 if isinstance(size, str) or size is None else int(size)
        paths = mock.render_views(asset_id, out, size=size_px)
        for view, path in zip(VIEWS, paths):
            views.append(_entry(view, _normalize(Path(path), out, view)))
        usage = {}
        audit = {"pass": None, "gaps": [], "error": "mock 模式不做体检"}
    else:
        size = size or SIZE_SHEET
        image = _clients()["image"]
        dna = _dna_for(name, type, desc, refs)
        try:
            (out / "dna.json").write_text(json.dumps(dna, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

        got = _save_sheet(image, name, type, desc, dna, out, size, refs)
        saved = _normalize(Path(got["path"]), out, SHEET_STEM)
        usages.append(got.get("usage") or {})
        views.append(_entry(SHEET_STEM, saved))

        # 体检：只报告缺口，不自动重抽。用户看报告决定要不要整张重来。
        audit = audit_sheet(saved, refs[0] if refs else None, dna)
        usage = _sum_usage(usages)

    return {
        "task": TASK_ASSET_VIEWS,
        "asset_id": asset_id,
        "views": views,
        "audit": audit,
        "saved": True,
        "cost": 0.0,
        "usage": usage,
    }


def run_asset_image(asset_id=None, name=None, type="场景", desc="", ref_images=None, size=None) -> dict:
    """场景类资产只出一张概念图，不拆正 / 侧 / 背。"""
    asset_id = str(asset_id or "").strip()
    if not asset_id:
        raise ValueError("asset_image 需要 asset_id")

    name = name or asset_id
    refs = [r for r in (ref_images or []) if r]
    out = asset_dir(asset_id)

    if _STATE["mode"] == MODE_MOCK:
        size_px = (768, 432) if isinstance(size, str) or size is None else tuple(size)
        path = mock.render_keyframe(asset_id, out, size=size_px)
        saved = _normalize(Path(path), out, "concept")
        return {
            "task": TASK_ASSET_IMAGE,
            "asset_id": asset_id,
            "views": [_entry("concept", saved)],
            "saved": True,
            "cost": 0.0,
            "usage": {},
        }

    got = _clients()["image"].save(
        prompts.concept(name, type, desc),
        out / "concept.png",
        ref_images=refs,
        size=size or SIZE_KEYFRAME,
    )
    saved = _normalize(Path(got["path"]), out, "concept")
    return {
        "task": TASK_ASSET_IMAGE,
        "asset_id": asset_id,
        "views": [_entry("concept", saved)],
        "saved": True,
        "cost": 0.0,
        "usage": got["usage"],
    }


def run_keyframe(shot_id, prompt="", name=None, assets=None, ref_images=None, size=None) -> dict:
    """出镜头首帧。返回的 ``first_frame`` 是唯一进 ``KeyframeResult`` 的字段。"""
    shot_id = str(shot_id or "").strip()
    if not shot_id:
        raise ValueError("keyframe 需要 shot_id")

    refs = [r for r in (ref_images or []) if r]
    out = _out_dir() / "shots"
    out.mkdir(parents=True, exist_ok=True)

    if _STATE["mode"] == MODE_MOCK:
        # mock 只吃 (宽, 高)；传进来的 "2560x1440" 是给真模型的，这里忽略
        size_px = (768, 432) if isinstance(size, str) or size is None else tuple(size)
        path = mock.render_keyframe(shot_id, out, size=size_px)
        return {
            "task": TASK_KEYFRAME,
            "shot_id": shot_id,
            "first_frame": str(path),
            "url": _url(path),
            "cost": 0.0,
            "usage": {},
        }

    got = _clients()["image"].save(
        prompts.keyframe(name or shot_id, prompt, prompts.assets_brief(assets)),
        out / ("%s-first.png" % shot_id),
        ref_images=refs,
        size=size or SIZE_KEYFRAME,
    )
    return {
        "task": TASK_KEYFRAME,
        "shot_id": shot_id,
        "first_frame": got["path"],
        "url": _url(got["path"]),
        "cost": 0.0,
        "usage": got["usage"],
    }


def run_verify(clip=None, frames=None, ref_images=None, prefix=None) -> dict:
    """抽帧校验：从成片里抽 3 帧，跟已确认的资产图比对。"""
    hit = [Path(p) for p in (frames or [])]
    refs = [Path(p) for p in (ref_images or []) if p]

    if not hit:
        if not clip:
            raise ValueError("verify 需要 clip（视频）或 frames（已抽好的帧）")
        prefix = prefix or Path(str(clip)).stem
        work = _out_dir() / "verify"
        work.mkdir(parents=True, exist_ok=True)
        hit = frames_mod.sample_frames(clip, work, prefix)

    if _STATE["mode"] == MODE_MOCK:
        verdict = mock.judge(hit, refs)
    else:
        verdict = _clients()["vision"].judge([*refs, *hit], prompts.VERIFY)

    return {
        "task": TASK_VERIFY,
        "pass": bool(verdict.get("pass")),
        "issues": verdict.get("issues") or [],
        "frames": [str(p) for p in hit],
        "refs": [str(p) for p in refs],
    }
