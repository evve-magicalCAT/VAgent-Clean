# -*- coding: utf-8 -*-
"""pytest 基座：每个用例一套独立的临时数据库与上传目录。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vagent import create_app  # noqa: E402


@pytest.fixture()
def app(tmp_path):
    application = create_app(
        db_path=str(tmp_path / "test.db"),
        upload_dir=str(tmp_path / "uploads"),
        testing=True,
    )
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


class API:
    """小包装：统一取 data，断言 ok。"""

    def __init__(self, client):
        self.client = client

    def get(self, url, **kw):
        res = self.client.get(url, **kw)
        return res

    def post(self, url, json=None):
        return self.client.post(url, json=json)

    def put(self, url, json=None):
        return self.client.put(url, json=json)

    def patch(self, url, json=None):
        return self.client.patch(url, json=json)

    def delete(self, url):
        return self.client.delete(url)

    @staticmethod
    def data(res):
        body = res.get_json()
        assert body and body["ok"] is True, body
        return body["data"]


@pytest.fixture()
def api(client):
    return API(client)
