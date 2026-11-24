# -*- coding: utf-8 -*-
"""抽帧校验接口 ``POST /api/shots/<id>/verify`` 的分支覆盖。

mock 模式下不花钱、也不需要 Key；接真模型时走的是同一条接口。
"""
import json
import subprocess

import pytest

from vagent import config
from vagent.api.assets import save_asset_views
from vagent.db import x
from vagent.images import frames as frames_mod


def _clip() -> tuple:
    """在 uploads 下造一条 2 秒测试视频，返回 (磁盘路径, /uploads 地址)。"""
    try:
        ffmpeg = frames_mod._tool("ffmpeg")
    except FileNotFoundError:
        pytest.skip("没有装 ffmpeg")
    path = config.UPLOAD_DIR / "gen" / "clips" / "s1.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=10",
            "-t",
            "2",
            str(path),
        ],
        check=True,
    )
    return path, "/uploads/gen/clips/s1.mp4"


def _setup(api) -> tuple:
    api.data(api.post("/api/projects", json={"name": "校验片场"}))
    asset = api.data(api.post("/api/assets", json={"name": "小林", "type": "角色", "desc": "短发"}))["asset"]
    shots = api.data(api.post("/api/shots", json={"prompt": "小林走进便利店", "name": "镜头 01"}))["shots"]
    shot = [item for item in shots if item["prompt"] == "小林走进便利店"][0]
    return asset["id"], shot["id"]


def test_verify_unknown_shot(api):
    res = api.post("/api/shots/nope/verify", json={})
    assert res.status_code == 404
    assert res.get_json()["error"]["code"] == "SHOT_NOT_FOUND"


@pytest.mark.parametrize("verdict", ["pass", "fail", "uncertain"])
def test_auto_video_reviews_without_browser(api, monkeypatch, verdict):
    from vagent.api import shots

    api.data(api.post("/api/projects", json={"name": "自动成片"}))
    (config.UPLOAD_DIR / "ref.png").write_bytes(b"reference")
    monkeypatch.setattr(shots.video_provider, "submit_reference", lambda *a, **kw: "job")
    monkeypatch.setattr(shots.video_provider, "query", lambda job: {"state": "succeeded", "url": "remote"})
    path, url = _clip()
    monkeypatch.setattr(shots.video_provider, "download", lambda remote: url)
    monkeypatch.setattr(shots.llm, "resolve_config", lambda: {"api_key": "test"})

    def judge(messages, **kwargs):
        parts = messages[-1]["content"]
        assert sum(part["type"] == "image_url" for part in parts) == 10
        assert any("分镜目标：回头" == part.get("text") for part in parts)
        return json.dumps({"summary": "镜头内人物回头", "verdict": verdict, "reason": "已比对转头动作"})

    monkeypatch.setattr(shots.llm, "chat", judge)
    shot = api.data(
        api.post(
            "/api/auto/video", json={"text": "回头", "attachment": {"kind": "图片", "stored": "ref.png"}}
        )
    )["shot"]
    shots._auto_process(shot["id"], "job")
    status = api.data(api.get("/api/shots/%s/video" % shot["id"]))
    assert status["state"] == "succeeded"
    assert status["shot"]["review"]["verdict"] == verdict
    assert status["shot"]["review"]["state"] == "done"


def test_manual_review_uses_clip(api, monkeypatch):
    from vagent.api import shots

    _, sid = _setup(api)
    endpoint = "/api/shots/%s/review" % sid
    assert api.post(endpoint, json={"mode": "manual"}).status_code == 400
    _, url = _clip()
    x("UPDATE shots SET clip_path = ? WHERE id = ?", (url, sid))
    monkeypatch.setattr(shots.llm, "resolve_config", lambda: {"api_key": "test"})
    monkeypatch.setattr(
        shots.llm,
        "chat",
        lambda *a, **kw: '{"summary":"人走进店里","verdict":"pass","reason":"进店动作一致"}',
    )
    result = api.data(api.post(endpoint, json={"mode": "manual"}))
    assert result["summary"] == "人走进店里"
    assert result["verdict"] == "pass"
    assert result["reason"] == "进店动作一致"


def test_verify_requires_clip(api):
    _aid, sid = _setup(api)
    res = api.post("/api/shots/%s/verify" % sid, json={})
    assert res.status_code == 400
    assert "还没有生成视频" in res.get_json()["error"]["message"]


def test_verify_requires_asset_image(api, monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    api.data(api.post("/api/projects", json={"name": "空资产片场"}))
    shots = api.data(api.post("/api/shots", json={"prompt": "空镜头"}))["shots"]
    shot = [item for item in shots if item["prompt"] == "空镜头"][0]
    _path, url = _clip()
    x("UPDATE shots SET clip_path = ? WHERE id = ?", (url, shot["id"]))
    res = api.post("/api/shots/%s/verify" % shot["id"], json={})
    assert res.status_code == 400
    assert "资产图" in res.get_json()["error"]["message"]


def test_verify_passes_in_mock(api, monkeypatch):
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    aid, sid = _setup(api)
    img = config.UPLOAD_DIR / "gen" / "assets" / aid / "front.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    save_asset_views(aid, [{"view": "front", "url": "/uploads/gen/assets/%s/front.png" % aid}])
    _path, url = _clip()
    x(
        "UPDATE shots SET clip_path = ?, ref_assets = ? WHERE id = ?",
        (url, json.dumps([aid]), sid),
    )
    got = api.data(api.post("/api/shots/%s/verify" % sid, json={}))
    assert got["pass"] is True
    assert got["issues"] == []
    assert len(got["frames"]) == 3
    assert got["frames"][0]["url"].startswith("/uploads/gen/verify/")
