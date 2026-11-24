# -*- coding: utf-8 -*-
"""SQLite 连接、建表、通用查询与设置持久化。"""
from __future__ import annotations
import copy
import json
import sqlite3
import threading
import time
from . import config


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT '概念片',
    status     TEXT NOT NULL DEFAULT '',
    desc       TEXT NOT NULL DEFAULT '',
    archived   INTEGER NOT NULL DEFAULT 0,
    cover      TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subs (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT '草稿',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    sub_id       TEXT NOT NULL DEFAULT '',
    name         TEXT NOT NULL,
    type         TEXT NOT NULL DEFAULT '角色',
    source       TEXT NOT NULL DEFAULT 'private',
    locked       INTEGER NOT NULL DEFAULT 0,
    desc         TEXT NOT NULL DEFAULT '',
    ai           TEXT NOT NULL DEFAULT 'none',
    preview      TEXT NOT NULL DEFAULT '[]',
    ref_image    TEXT NOT NULL DEFAULT '',
    ref_shots    TEXT NOT NULL DEFAULT '[]',
    tags         TEXT NOT NULL DEFAULT '[]',
    archived     INTEGER NOT NULL DEFAULT 0,
    from_project TEXT NOT NULL DEFAULT '',
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shots (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    sub_id     TEXT NOT NULL,
    name       TEXT NOT NULL,
    dur        REAL NOT NULL DEFAULT 3.0,
    status     TEXT NOT NULL DEFAULT 'pending',
    frame      TEXT NOT NULL DEFAULT 'street',
    locked     INTEGER NOT NULL DEFAULT 0,
    prompt     TEXT NOT NULL DEFAULT '',
    tones      TEXT NOT NULL DEFAULT '[]',
    progress   INTEGER NOT NULL DEFAULT 0,
    ai         TEXT NOT NULL DEFAULT '',
    clip_path  TEXT NOT NULL DEFAULT '',
    provider_job TEXT NOT NULL DEFAULT '',
    ref_mode   INTEGER NOT NULL DEFAULT 0,
    ref_assets TEXT NOT NULL DEFAULT '[]',
    review TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS auto_runs (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, sub_id TEXT NOT NULL,
    status TEXT NOT NULL, stage TEXT NOT NULL, data TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS auto_runs_active ON auto_runs(sub_id) WHERE status = 'running';
CREATE TABLE IF NOT EXISTS materials (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    sub_id     TEXT NOT NULL DEFAULT '',
    label      TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT '视频',
    dur        TEXT NOT NULL DEFAULT '',
    bg         TEXT NOT NULL DEFAULT '',
    wave       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL DEFAULT '',
    sub_id     TEXT NOT NULL DEFAULT '',
    role       TEXT NOT NULL,
    text       TEXT NOT NULL DEFAULT '',
    meta       TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    k TEXT PRIMARY KEY,
    v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_calls (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL DEFAULT '',
    ok         INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asset_enrichments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id   TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    base       TEXT NOT NULL DEFAULT '',
    prompt     TEXT NOT NULL DEFAULT '',
    model      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def conn() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(config.DB_PATH), timeout=15)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with _LOCK, conn() as c:
        c.executescript(SCHEMA)
        # 兼容旧库：补齐后加的列
        cols = [r["name"] for r in c.execute("PRAGMA table_info(assets)")]
        if "tags" not in cols:
            c.execute("ALTER TABLE assets ADD COLUMN tags TEXT NOT NULL DEFAULT '[]'")
        if "ref_image" not in cols:
            c.execute("ALTER TABLE assets ADD COLUMN ref_image TEXT NOT NULL DEFAULT ''")
        shot_cols = [r["name"] for r in c.execute("PRAGMA table_info(shots)")]
        if "review" not in shot_cols:
            c.execute("ALTER TABLE shots ADD COLUMN review TEXT NOT NULL DEFAULT '{}'")
        if "clip_path" not in shot_cols:
            c.execute("ALTER TABLE shots ADD COLUMN clip_path TEXT NOT NULL DEFAULT ''")
        if "provider_job" not in shot_cols:
            c.execute("ALTER TABLE shots ADD COLUMN provider_job TEXT NOT NULL DEFAULT ''")
        if "ref_mode" not in shot_cols:
            c.execute("ALTER TABLE shots ADD COLUMN ref_mode INTEGER NOT NULL DEFAULT 0")
        if "ref_assets" not in shot_cols:
            c.execute("ALTER TABLE shots ADD COLUMN ref_assets TEXT NOT NULL DEFAULT '[]'")
        # 自增计数器从已有数据接着走
        for table, prefix in (("projects", "p"), ("assets", "a"), ("materials", "m")):
            c.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (f"seq:{table}", "0"))
            mx = c.execute(
                f"SELECT COALESCE(MAX(CAST(SUBSTR(id, {len(prefix) + 1}) AS INTEGER)), 0) FROM {table}"
            ).fetchone()[0]
            c.execute(
                "UPDATE meta SET value = MAX(CAST(value AS INTEGER), ?) WHERE key = ?",
                (mx or 0, f"seq:{table}"),
            )
        row = c.execute("SELECT COUNT(*) AS n FROM settings").fetchone()
        if row["n"] == 0:
            for k, v in config.DEFAULT_SETTINGS.items():
                c.execute("INSERT INTO settings (k, v) VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))
        for key, val in (("current_project", ""), ("current_sub", ""), ("budget", "500")):
            c.execute("INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)", (key, val))


def q(sql: str, args: tuple = ()) -> list:
    with conn() as c:
        return c.execute(sql, args).fetchall()


def q1(sql: str, args: tuple = ()):
    with conn() as c:
        return c.execute(sql, args).fetchone()


def x(sql: str, args: tuple = ()) -> None:
    with _LOCK, conn() as c:
        c.execute(sql, args)


def meta_get(key: str, default: str = "") -> str:
    row = q1("SELECT value FROM meta WHERE key = ?", (key,))
    return row["value"] if row else default


def meta_set(key: str, value: str) -> None:
    x(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def load_settings() -> dict:
    out = {}
    for row in q("SELECT k, v FROM settings"):
        try:
            out[row["k"]] = json.loads(row["v"])
        except Exception:
            out[row["k"]] = {}
    for k, v in config.DEFAULT_SETTINGS.items():
        out.setdefault(k, copy.deepcopy(v))
    return out


def record_api_call(provider: str, model: str = "", ok: bool = True) -> None:
    """记一次模型调用，用于「API 用量」面板；只计数，不存请求内容。"""
    x(
        "INSERT INTO api_calls (provider, model, ok, created_at) VALUES (?,?,?,?)",
        (provider, model, 1 if ok else 0, now_text()),
    )


def api_call_stats() -> dict:
    rows = q("SELECT provider, model, ok, created_at FROM api_calls ORDER BY id DESC")
    today = now_text()[:10]
    groups = {key: {"calls": 0, "today": 0, "last": ""} for key in ("llm", "img", "video")}
    for row in rows:
        key = row["provider"]
        item = groups.setdefault(key, {"calls": 0, "today": 0, "last": ""})
        item["calls"] += 1
        if row["created_at"][:10] == today:
            item["today"] += 1
        if not item["last"]:
            item["last"] = row["created_at"]
    recent = [
        {"provider": row["provider"], "model": row["model"], "at": row["created_at"], "ok": bool(row["ok"])}
        for row in rows[:6]
    ]
    return {"groups": groups, "recent": recent, "total": len(rows)}


def save_settings(settings: dict) -> None:
    with _LOCK, conn() as c:
        for k, v in settings.items():
            c.execute(
                "INSERT INTO settings (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                (k, json.dumps(v, ensure_ascii=False)),
            )


_LOCK = threading.RLock()
