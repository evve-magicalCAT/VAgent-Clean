# -*- coding: utf-8 -*-
"""Blueprint 装配：每个领域一个模块，只负责 HTTP 契约，不写业务逻辑。"""
from __future__ import annotations

from . import assets, bootstrap, export, llm, materials, messages, projects, settings, shots, upload
from . import auto_runs


def register_blueprints(app) -> None:
    for module in (
        bootstrap,
        projects,
        assets,
        shots,
        materials,
        messages,
        settings,
        upload,
        export,
        llm,
        auto_runs,
    ):
        app.register_blueprint(module.bp)
