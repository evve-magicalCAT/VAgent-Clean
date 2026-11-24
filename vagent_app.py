#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vagent 启动入口。

  python vagent_app.py                # 127.0.0.1:8000
  python vagent_app.py --port 9000
  python vagent_app.py --host 0.0.0.0 --port 9000

应用代码在 vagent/ 包里：api/ 是接口，web/ 是前端，db.py 是存储，
contracts.py 是三个 Agent 之间的契约。
"""
from __future__ import annotations

import argparse

from vagent import config, create_app


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Vagent · 自然语言驱动的 AI 视频 Agent"
    )
    parser.add_argument("--host", default=config.DEFAULT_HOST,
                        help=f"绑定地址，默认 {config.DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=config.DEFAULT_PORT,
                        help=f"端口，默认 {config.DEFAULT_PORT}")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    app = create_app()
    print("")
    print("  Vagent · 自然语言驱动的 AI 视频 Agent")
    print(f"  访问地址：http://{args.host}:{args.port}")
    print(f"  接口总览：http://{args.host}:{args.port}/api/bootstrap")
    print(f"  数据库：{config.DB_PATH}")
    print("  Ctrl+C 停止服务")
    print("")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
