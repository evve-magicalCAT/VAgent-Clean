# -*- coding: utf-8 -*-
"""全局配置：路径、默认设置、封面/镜头素材常量。
测试或多实例时通过 configure() 覆盖数据库与上传目录，不要在别处改模块常量。
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"

DEFAULT_PORT = 8000

MASK_DOTS = 12

MASK_KEEP_TAIL = 4

DEFAULT_ASSET_SCOPE = "current"

BASE_DIR = Path(__file__).resolve().parent.parent

DB_PATH = Path(os.environ.get("VAGENT_DB", str(BASE_DIR / "vagent.db")))

UPLOAD_DIR = BASE_DIR / "uploads"

DEFAULT_SETTINGS = {
    "llm": {
        "label": "主 Agent · 语言模型",
        "icon": "sparkles",
        "provider": "火山方舟",
        "providers": ["火山方舟", "DeepSeek", "OpenAI 兼容", "自建网关"],
        "api_key": "",
        "base_url": "",
        "model": "doubao-seed-2-1-lite-260915",
        "models": ["doubao-seed-2-1-lite-260915", "doubao-seed-2-1-pro-260915", "deepseek-chat"],
        "status": {"text": "未配置", "warn": True},
        "note": "密钥只保存在本地，不会上传",
    },
    "img": {
        "label": "图片模型",
        "icon": "image",
        "provider": "火山方舟",
        "providers": ["火山方舟", "即梦", "自定义"],
        "api_key": "",
        "base_url": "",
        "model": "doubao-seedream-5-5-261028",
        "models": ["doubao-seedream-5-5-261028", "doubao-seedream-5-0-260128", "seedream-5.0-pro"],
        "concurrency": 3,
        "status": {"text": "未配置", "warn": True},
        "note": "密钥只保存在本地，不会上传",
    },
    "video": {
        "label": "视频模型",
        "icon": "film",
        "provider": "MiniMax",
        "providers": ["MiniMax", "可灵 AI · 自定义", "即梦视频", "Runway"],
        "api_key": "",
        "base_url": "",
        "model": "MiniMax-H3",
        "models": ["MiniMax-H3", "MiniMax-H3-Max", "kling-v2-master"],
        "max_duration": "10 秒",
        "status": {"text": "未配置", "warn": True},
        "note": "还没有测试过连接",
    },
}

FRAMES = ["street", "push", "door", "shelf", "counter", "bell"]

TONES = [
    ["#2C343C", "#2A323A", "#252C34"],
    ["#2A3139", "#262D35"],
    ["#343C44", "#2F373F", "#2B333B"],
    ["#2B323A", "#252C34"],
    ["#2F373F", "#36322C"],
    ["#2A3139", "#232A31"],
]

COVER_ARTS = ["city", "sun", "frame", "neon", "boxes", "bw"]

COVER_GRADS = [
    "linear-gradient(115deg,#1D2C38 0%,#0B1116 100%)",
    "linear-gradient(115deg,#7A5222 0%,#241708 100%)",
    "linear-gradient(115deg,#55524A 0%,#17150F 100%)",
    "linear-gradient(115deg,#25402F 0%,#0A1310 100%)",
    "linear-gradient(115deg,#4A3128 0%,#150D0A 100%)",
    "linear-gradient(115deg,#3E3E3E 0%,#0B0B0B 100%)",
]

COVER_INKS = ["#8FA8BC", "#E8C08A", "#F0EBDE", "#9CB8A4", "#C9A38C", "#D6D6D6"]


def configure(db_path=None, upload_dir=None) -> None:
    """覆盖数据库 / 上传目录（测试与多实例用）。"""
    global DB_PATH, UPLOAD_DIR
    if db_path:
        DB_PATH = Path(db_path).resolve()
    if upload_dir:
        UPLOAD_DIR = Path(upload_dir).resolve()
