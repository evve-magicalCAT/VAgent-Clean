# -*- coding: utf-8 -*-
"""Flask 应用装配：模板/静态资源、蓝图、错误出口。

只做装配，不放业务代码。数据库路径可通过 create_app(db_path=...) 覆盖，
方便测试与多实例。
"""
from __future__ import annotations
from pathlib import Path
from flask import Flask, render_template, request
from . import config, db
from .api import register_blueprints
from .responses import fail


PKG_DIR = Path(__file__).resolve().parent
WEB_DIR = PKG_DIR / "web"

__version__ = "0.2.0"


def create_app(db_path=None, upload_dir=None, testing: bool = False) -> Flask:
    config.configure(db_path=db_path, upload_dir=upload_dir)
    app = Flask(
        __name__,
        template_folder=str(WEB_DIR / "templates"),
        static_folder=str(WEB_DIR / "static"),
        static_url_path="/static",
    )
    app.json.ensure_ascii = False
    app.json.sort_keys = False
    app.config["TESTING"] = testing
    # 开发期不缓存静态资源，改完刷新即生效
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    db.init_db()
    register_blueprints(app)
    register_error_handlers(app)
    if not testing:
        from .api.shots import resume_auto_reviews

        resume_auto_reviews()
        from .api.auto_runs import resume_runs

        resume_runs()

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    return app


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def handle_404(err):
        if request.path.startswith("/api/"):
            return fail("NOT_FOUND", "接口不存在", 404)
        return "<meta charset='utf-8'>页面不存在", 404

    @app.errorhandler(405)
    def handle_405(err):
        if request.path.startswith("/api/"):
            return fail("METHOD_NOT_ALLOWED", "该接口不支持此请求方法", 405)
        return "<meta charset='utf-8'>方法不被允许", 405

    @app.errorhandler(500)
    def handle_500(err):
        if request.path.startswith("/api/"):
            return fail("INTERNAL_ERROR", "服务端内部错误", 500)
        return "<meta charset='utf-8'>服务端内部错误", 500
