# -*- coding: utf-8 -*-
"""数据库行 → 前端 JSON 结构。"""
from __future__ import annotations
import json
from .config import COVER_GRADS, COVER_INKS, TONES
from . import config
from .db import q


def jloads(raw, default):
    try:
        return json.loads(raw) if raw else default
    except Exception:
        return default


_FRAME_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _has_first_frame(shot_id: str) -> bool:
    base = config.UPLOAD_DIR / "gen" / "shots" / (str(shot_id) + "-first")
    return any(base.with_suffix(ext).is_file() for ext in _FRAME_EXTS)


def _project_cover_asset(project_id: str) -> tuple:
    """取项目（含子项目）资产库里最新的一张真图，作为项目封面。"""
    rows = q(
        "SELECT preview, desc, updated_at FROM assets WHERE project_id = ? ORDER BY updated_at DESC LIMIT 30",
        (project_id,),
    )
    for row in rows:
        for item in jloads(row["preview"], []):
            if isinstance(item, dict) and item.get("kind") == "img" and item.get("url"):
                stamp = "".join(ch for ch in (row["updated_at"] or "") if ch.isdigit())
                url = item["url"] + (("&" if "?" in item["url"] else "?") + "v=" + stamp if stamp else "")
                return url, row["desc"] or ""
    return "", ""


def row_to_project(row, subs: list | None = None) -> dict:
    cover = jloads(row["cover"], {}) or {}
    cover_image, asset_desc = _project_cover_asset(row["id"])
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "status": row["status"],
        "desc": row["desc"],
        "archived": bool(row["archived"]),
        "cover": {
            "art": cover.get("art", "city"),
            "grad": cover.get("grad", COVER_GRADS[0]),
            "ink": cover.get("ink", COVER_INKS[0]),
            "image": cover_image,
            "summary": (row["desc"] or asset_desc or "").strip(),
        },
        "subs": subs if subs is not None else [],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def row_to_sub(row, shots_count: int = 0, dur: float = 0.0, assets_count: int = 0) -> dict:
    return {
        "id": row["id"],
        "projectId": row["project_id"],
        "name": row["name"],
        "status": row["status"],
        "shots": shots_count,
        "assets": assets_count,
        "dur": f"{dur:.1f}s" if dur else "",
        "inherit": f"资产继承自父项目 · {assets_count} 项",
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def row_to_asset(row) -> dict:
    return {
        "id": row["id"],
        "projectId": row["project_id"],
        "subId": row["sub_id"],
        "name": row["name"],
        "type": row["type"],
        "source": row["source"],
        "locked": bool(row["locked"]),
        "desc": row["desc"],
        "ai": row["ai"],
        "preview": jloads(row["preview"], []),
        "refImage": row["ref_image"],
        "refShots": jloads(row["ref_shots"], []),
        "tags": jloads(row["tags"], []),
        "archived": bool(row["archived"]),
        "from": row["from_project"],
        "uses": 0,
        "updatedAt": row["updated_at"],
    }


def row_to_shot(row, no: str = "") -> dict:
    review = jloads(row["review"], {})
    if review.get("job") != row["provider_job"] or review.get("clip", row["clip_path"]) != row["clip_path"]:
        review = {}
    return {
        "id": row["id"],
        "no": no,
        "projectId": row["project_id"],
        "subId": row["sub_id"],
        "name": row["name"],
        "dur": float(row["dur"]),
        "status": row["status"],
        "frame": row["frame"],
        "locked": bool(row["locked"]),
        "prompt": row["prompt"],
        "tones": jloads(row["tones"], TONES[0]),
        "progress": int(row["progress"]),
        "hasFirstFrame": _has_first_frame(row["id"]),
        "ai": row["ai"],
        "clipPath": row["clip_path"],
        "providerJob": row["provider_job"],
        "review": review,
        "refMode": bool(row["ref_mode"]),
        "refAssets": jloads(row["ref_assets"], []),
        "updatedAt": row["updated_at"],
    }


def row_to_material(row) -> dict:
    return {
        "id": row["id"],
        "label": row["label"],
        "kind": row["kind"],
        "dur": row["dur"],
        "bg": row["bg"],
        "wave": row["wave"],
    }
