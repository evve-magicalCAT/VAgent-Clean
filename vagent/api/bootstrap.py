# -*- coding: utf-8 -*-
from __future__ import annotations
from flask import Blueprint, request
from .. import config
from ..llm import CHAT_HISTORY_LIMIT
from .auto_runs import latest_run
from ..config import DEFAULT_ASSET_SCOPE
from ..db import api_call_stats, meta_get
from ..repository import (
    current_ids,
    current_materials,
    current_messages,
    current_shots,
    current_summary,
    ensure_current,
    project_list,
    scope_assets,
    scope_stats,
    usage_payload,
)
from ..responses import ok, public_settings


bp = Blueprint("bootstrap", __name__)


@bp.get("/api/bootstrap")
def api_bootstrap():
    ensure_current()
    scope = request.args.get("scope") or DEFAULT_ASSET_SCOPE
    scope = "project" if scope in ("current", "project") else scope
    pid, sid = current_ids()
    assets = scope_assets(scope, pid, sid)
    usage = usage_payload()
    return ok(
        {
            "account": {},
            "apiUsage": api_call_stats(),
            "currentProject": current_summary(),
            "projects": project_list(),
            "assets": assets,
            "assetStats": scope_stats(assets),
            "shots": current_shots(),
            "materials": current_materials(),
            "messages": current_messages(),
            "historyLimit": CHAT_HISTORY_LIMIT,
            "autoRun": latest_run(pid, sid),
            "usage": {
                "total": usage["total"],
                "budget": usage["budget"],
                "usedPct": usage["usedPct"],
                "remaining": usage["remaining"],
                "generatedShots": usage["generatedShots"],
                "quotaLeftPct": 100,
            },
            "spend": usage["spend"],
            "settings": {"api": public_settings()},
            "ui": {"assetScope": "project", "defaultShotId": "", "defaultAssetId": ""},
            "savedAt": meta_get("saved_at", ""),
            "db": str(config.DB_PATH),
        }
    )
