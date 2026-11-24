# -*- coding: utf-8 -*-
from __future__ import annotations
import re
import time
from pathlib import Path
from flask import Blueprint, request, send_from_directory
from .. import config
from ..responses import fail, ok


bp = Blueprint("upload", __name__)


@bp.post("/api/upload")
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return fail("BAD_REQUEST", "没有收到文件")
    safe = re.sub(r"[^A-Za-z0-9._\u4e00-\u9fa5-]", "_", Path(f.filename).name)
    stored = f"{int(time.time() * 1000)}_{safe}"
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    f.save(str(config.UPLOAD_DIR / stored))
    size = (config.UPLOAD_DIR / stored).stat().st_size
    return ok(
        {
            "name": f.filename,
            "stored": stored,
            "size": size,
            "url": f"/uploads/{stored}",
            "kind": "图片" if f.mimetype.startswith("image/") else "文件",
        }
    )


@bp.get("/uploads/<path:name>")
def uploaded(name):
    return send_from_directory(str(config.UPLOAD_DIR), name)
