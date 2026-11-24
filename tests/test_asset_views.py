# -*- coding: utf-8 -*-
"""三视图落库：Agent 出完图之后，由调用方把结果写回资产记录。"""
import pytest

from vagent.api.assets import save_asset_views


def _make_asset(api, name="小林"):
    api.post("/api/projects", json={"name": "测试片场"})
    return api.data(api.post("/api/assets", json={"name": name, "type": "角色", "desc": "短发"}))["asset"]


def _views(*triples):
    return [{"view": view, "url": url, "path": "x/%s.jpg" % view, "bytes": 100} for view, url in triples]


def test_save_asset_views_writes_preview(api):
    asset = _make_asset(api)

    updated = save_asset_views(
        asset["id"],
        _views(
            ("front", "/uploads/gen/assets/a1/front.jpg"),
            ("side", "/uploads/gen/assets/a1/side.jpg"),
            ("back", "/uploads/gen/assets/a1/back.jpg"),
        ),
    )

    assert [item["kind"] for item in updated["preview"]] == ["img", "img", "img"]
    assert [item["label"] for item in updated["preview"]] == ["正面", "侧面", "背面"]
    assert updated["preview"][0]["url"] == "/uploads/gen/assets/a1/front.jpg"


def test_saved_preview_is_visible_through_api(api):
    asset = _make_asset(api)
    save_asset_views(asset["id"], _views(("front", "/uploads/gen/assets/a1/front.jpg")))

    listed = api.data(api.get("/api/assets?scope=all"))["assets"]
    got = [item for item in listed if item["id"] == asset["id"]][0]

    assert got["preview"][0]["url"] == "/uploads/gen/assets/a1/front.jpg"


def test_save_asset_views_skips_unreachable_urls(api):
    asset = _make_asset(api)

    updated = save_asset_views(
        asset["id"],
        [
            {"view": "front", "url": "/uploads/gen/assets/a1/front.jpg", "path": "x"},
            {"view": "side", "url": "", "path": "tmp/side.png"},
        ],
    )

    assert [item["label"] for item in updated["preview"]] == ["正面"]


def test_save_asset_views_unknown_asset_raises(api):
    api.post("/api/projects", json={"name": "测试片场"})

    with pytest.raises(LookupError):
        save_asset_views("a404", _views(("front", "/uploads/x.jpg")))
