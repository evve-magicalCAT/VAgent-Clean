# -*- coding: utf-8 -*-
"""接口契约回归：覆盖所有端点与关键分支。

这些用例就是拆分前那份单文件的行为基线；重构不允许改动它们。
"""
import io


# ---------------------------------------------------------------- 启动 / 项目
def test_bootstrap_empty(api):
    d = api.data(api.get("/api/bootstrap"))
    assert d["projects"] == []
    assert d["assets"] == [] and d["shots"] == []
    assert d["currentProject"]["projectId"] == ""
    assert set(
        [
            "account",
            "projects",
            "assets",
            "shots",
            "usage",
            "spend",
            "settings",
            "ui",
            "materials",
            "messages",
        ]
    ).issubset(d)


def test_project_create_auto_sub_and_switch(api):
    d = api.data(api.post("/api/projects", json={"name": "测试片场", "kind": "概念片"}))
    assert d["projectId"] and d["subId"]
    boot = api.data(api.get("/api/bootstrap"))
    assert boot["currentProject"]["projectId"] == d["projectId"]
    assert boot["projects"][0]["subsCount"] == 1
    assert boot["projects"][0]["members"] == []


def test_project_cover_uses_latest_asset(api):
    import json as jsonlib

    from vagent.db import now_text, x

    api.post("/api/projects", json={"name": "封面项目", "desc": "项目概括文字"})
    asset = api.data(api.post("/api/assets", json={"name": "六足战斗机器人", "type": "角色"}))["asset"]
    x(
        "UPDATE assets SET preview = ?, updated_at = ? WHERE id = ?",
        (
            jsonlib.dumps([{"kind": "img", "url": "/uploads/gen/assets/a/cover.png", "label": "正面"}]),
            now_text(),
            asset["id"],
        ),
    )
    boot = api.data(api.get("/api/bootstrap"))
    project = boot["projects"][0]
    assert project["cover"]["image"].startswith("/uploads/gen/assets/a/cover.png?v=")
    assert project["cover"]["summary"] == "项目概括文字"


def test_project_crud(api):
    pid = api.data(api.post("/api/projects", json={"name": "A"}))["projectId"]
    assert api.data(api.get(f"/api/projects/{pid}"))["isCurrent"] is True

    patched = api.data(api.patch(f"/api/projects/{pid}", json={"name": "B", "archived": True}))["project"]
    assert patched["name"] == "B" and patched["archived"] is True
    patched = api.data(api.patch(f"/api/projects/{pid}", json={"archived": False}))["project"]
    assert patched["archived"] is False

    assert api.data(api.get("/api/projects"))["total"] == 1
    assert api.data(api.delete(f"/api/projects/{pid}"))["deleted"] == pid
    assert api.get(f"/api/projects/{pid}").status_code == 404


def test_sub_project_crud(api):
    pid = api.data(api.post("/api/projects", json={"name": "A"}))["projectId"]
    sid = api.data(api.post(f"/api/projects/{pid}/subs", json={"name": "第 2 集"}))["subId"]
    sub = api.data(api.patch(f"/api/subs/{sid}", json={"name": "第 2 集 · 改名", "status": "进行中"}))["sub"]
    assert sub["name"].endswith("改名") and sub["status"] == "进行中"
    assert (
        api.data(api.post("/api/switch", json={"projectId": pid, "subId": sid}))["currentProject"]["subId"]
        == sid
    )
    assert api.data(api.delete(f"/api/subs/{sid}"))["deleted"] == sid


# ---------------------------------------------------------------- 资产
def test_asset_crud_and_tags(api):
    api.post("/api/projects", json={"name": "A"})
    a = api.data(
        api.post("/api/assets", json={"name": "角色甲", "type": "角色", "desc": "短发", "locked": True})
    )["asset"]
    assert a["locked"] is True and a["tags"] == []

    a = api.data(api.patch(f"/api/assets/{a['id']}", json={"prompt": "改过的描述"}))["asset"]
    assert a["desc"] == "改过的描述"
    a = api.data(api.patch(f"/api/assets/{a['id']}", json={"tags": ["冷调", "雨夜"]}))["asset"]
    assert a["tags"] == ["冷调", "雨夜"]
    a = api.data(api.patch(f"/api/assets/{a['id']}", json={"locked": False}))["asset"]
    assert a["locked"] is False

    copy = api.data(api.post(f"/api/assets/{a['id']}/copy", json={}))["asset"]
    assert copy["id"] != a["id"] and copy["name"].endswith("副本")

    assert api.data(api.delete(f"/api/assets/{a['id']}"))["deleted"] == a["id"]
    assert api.patch(f"/api/assets/{a['id']}", json={"prompt": "x"}).status_code == 404


def test_asset_scopes(api):
    api.post("/api/projects", json={"name": "A"})
    api.data(api.post("/api/assets", json={"name": "私有", "type": "角色", "desc": "x"}))
    api.data(
        api.post("/api/assets", json={"name": "继承", "type": "场景", "desc": "y", "scopeLevel": "inherit"})
    )

    current = api.data(api.get("/api/assets?scope=current"))
    inherit = api.data(api.get("/api/assets?scope=inherit"))
    every = api.data(api.get("/api/assets?scope=all"))
    assert current["total"] == 2
    assert [a["name"] for a in inherit["assets"]] == ["继承"]
    assert every["total"] == 2
    assert inherit["stats"]["inherit"] == 1


def test_asset_validation(api):
    api.post("/api/projects", json={"name": "A"})
    assert api.post("/api/assets", json={"name": ""}).status_code == 400
    aid = api.data(api.post("/api/assets", json={"name": "x"}))["asset"]["id"]
    assert api.patch(f"/api/assets/{aid}", json={"prompt": "   "}).status_code == 400
    assert api.patch(f"/api/assets/{aid}", json={}).status_code == 400


def test_asset_migrate_copy_and_move(api):
    p1 = api.data(api.post("/api/projects", json={"name": "源项目"}))["projectId"]
    a = api.data(api.post("/api/assets", json={"name": "迁移资产", "type": "角色", "desc": "d"}))["asset"]
    p2 = api.data(api.post("/api/projects", json={"name": "目标项目"}))["projectId"]
    api.post("/api/switch", json={"projectId": p1})

    res = api.data(
        api.post(
            "/api/assets/migrate",
            json={"ids": [a["id"]], "targetProjectId": p2, "mode": "copy", "conflicts": {}},
        )
    )
    assert res["copied"] == 1 and res["moved"] == 0

    api.post("/api/switch", json={"projectId": p2})
    moved_in = api.data(api.get("/api/bootstrap"))["assets"]
    assert any(x["name"] == "迁移资产" and x["from"] == "源项目" for x in moved_in)

    api.post("/api/switch", json={"projectId": p1})
    res = api.data(
        api.post(
            "/api/assets/migrate",
            json={"ids": [a["id"]], "targetProjectId": p2, "mode": "move", "conflicts": {}},
        )
    )
    assert res["moved"] == 1
    left = api.data(api.get("/api/assets?scope=current"))["assets"]
    assert all(x["id"] != a["id"] for x in left)


# ---------------------------------------------------------------- 镜头
def test_shot_lifecycle(api):
    api.post("/api/projects", json={"name": "A"})
    s1 = api.data(api.post("/api/shots", json={"name": "镜头 A", "dur": 3.0, "prompt": "p1"}))["shot"]
    s2 = api.data(api.post("/api/shots", json={"name": "镜头 B", "dur": 2.0, "prompt": "p2"}))["shot"]

    shots = api.data(api.get("/api/shots"))
    assert shots["total"] == 2 and abs(shots["totalDur"] - 5.0) < 0.01
    assert [s["no"] for s in shots["shots"]] == ["01", "02"]

    assert (
        api.data(api.patch(f"/api/shots/{s2['id']}", json={"prompt": "改过", "status": "modified"}))["shot"][
            "status"
        ]
        == "modified"
    )

    split = api.data(api.post(f"/api/shots/{s1['id']}/split", json={"ratio": 0.5}))
    assert len(split["shots"]) == 3

    snapshot = api.data(api.get("/api/shots"))["shots"]
    bulk = api.data(api.put("/api/shots/bulk", json={"shots": snapshot[:2]}))
    assert len(bulk["shots"]) == 2

    gen = api.data(api.post("/api/shots/generate", json={}))
    assert gen["count"] == 2 and all(s["status"] == "confirmed" for s in gen["shots"])

    assert api.data(api.delete(f"/api/shots/{s2['id']}"))["deleted"] == s2["id"]
    assert api.patch(f"/api/shots/{s2['id']}", json={"prompt": "x"}).status_code == 404


def test_shot_validation(api):
    api.post("/api/projects", json={"name": "A"})
    sid = api.data(api.post("/api/shots", json={"name": "x"}))["shot"]["id"]
    assert api.patch(f"/api/shots/{sid}", json={"prompt": ""}).status_code == 400
    assert api.patch(f"/api/shots/{sid}", json={"progress": "abc"}).status_code == 400
    assert api.put("/api/shots/bulk", json={"shots": "no"}).status_code == 400


# ---------------------------------------------------------------- 素材 / 对话
def test_materials(api):
    api.post("/api/projects", json={"name": "A"})
    m = api.data(api.post("/api/materials", json={"label": "雨滴", "kind": "视频", "dur": "2.0s"}))[
        "material"
    ]
    assert api.data(api.get("/api/materials"))["materials"][0]["label"] == "雨滴"
    assert api.data(api.delete(f"/api/materials/{m['id']}"))["deleted"] == m["id"]


def test_messages(api):
    api.post("/api/projects", json={"name": "A"})
    d = api.data(api.post("/api/messages", json={"role": "user", "text": "一个镜头", "meta": {}}))
    assert d["id"] > 0 and len(d["messages"]) == 1
    assert api.post("/api/messages", json={"role": "user", "text": "  "}).status_code == 400
    assert api.data(api.delete("/api/messages"))["messages"] == []


# ---------------------------------------------------------------- 设置
def test_settings_mask_and_reset(api):
    masked = api.data(api.get("/api/settings/api"))["api"]["llm"]["api_key"]
    assert masked == ""

    d = api.data(
        api.put(
            "/api/settings/api",
            json={
                "api": {
                    "llm": {
                        "api_key": "sk-test-1234567890abcd",
                        "base_url": "https://x.test/v1",
                        "model": "gpt-4o",
                    }
                }
            },
        )
    )
    shown = d["api"]["llm"]["api_key"]
    assert "•" in shown and shown.endswith("abcd")

    # 掩码回写不应覆盖明文
    api.put("/api/settings/api", json={"api": {"llm": {"api_key": shown}}})
    assert api.data(api.get("/api/settings/api"))["api"]["llm"]["api_key"] == shown

    reset = api.data(api.post("/api/settings/api/reset", json={}))["api"]
    assert reset["llm"]["api_key"] == ""


def test_settings_put_validation(api):
    assert api.put("/api/settings/api", json=["no"]).status_code == 400
    assert api.put("/api/settings/api", json={"api": {"nope": {}}}).status_code == 400


def test_settings_test_local_only(api):
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-abcdefgh1234", "base_url": "https://x.test/v1"}}},
    )
    d = api.data(api.post("/api/settings/api/test", json={"group": "llm"}))
    assert d["ok"] is True and "未发起真实请求" in d["message"]


# ---------------------------------------------------------------- 上传 / 导出
def test_upload_and_serve(api, client):
    res = client.post(
        "/api/upload",
        data={"file": (io.BytesIO(b"hello vagent"), "ref.txt")},
        content_type="multipart/form-data",
    )
    d = api.data(res)
    assert d["size"] == 12
    assert client.get(d["url"]).status_code == 200
    assert client.post("/api/upload", data={}).status_code == 400


def test_export_manifest_and_srt(api, client):
    api.post("/api/projects", json={"name": "A"})
    api.data(api.post("/api/shots", json={"name": "镜头", "dur": 2.0, "prompt": "街道"}))
    manifest = client.get("/api/export/manifest")
    assert manifest.status_code == 200
    assert manifest.get_json()["shots"][0]["name"] == "镜头"

    srt = client.get("/api/export/subtitles.srt")
    assert srt.status_code == 200 and "-->" in srt.data.decode("utf-8")


# ---------------------------------------------------------------- 错误出口
def test_error_envelopes(api, client):
    assert client.get("/api/nope").status_code == 404
    assert client.get("/api/nope").get_json()["error"]["code"] == "NOT_FOUND"

    api.post("/api/projects", json={"name": "A"})
    sid = api.data(api.post("/api/shots", json={"name": "x"}))["shot"]["id"]
    res = client.get(f"/api/shots/{sid}")
    assert res.status_code == 405 and res.get_json()["error"]["code"] == "METHOD_NOT_ALLOWED"
    assert client.get("/api/projects/zzz").status_code == 404


# ---------------------------------------------------------------- 持久化
def test_persistence_across_app_instances(tmp_path):
    from vagent import create_app

    db = tmp_path / "persist.db"
    app1 = create_app(db_path=str(db), upload_dir=str(tmp_path / "up"), testing=True)
    c1 = app1.test_client()
    pid = c1.post("/api/projects", json={"name": "持久化"}).get_json()["data"]["projectId"]
    c1.post("/api/assets", json={"name": "资产", "type": "角色", "desc": "d"})

    app2 = create_app(db_path=str(db), upload_dir=str(tmp_path / "up"), testing=True)
    c2 = app2.test_client()
    boot = c2.get("/api/bootstrap").get_json()["data"]
    assert boot["currentProject"]["projectId"] == pid
    assert boot["projects"][0]["name"] == "持久化"
    assert len(boot["assets"]) == 1


# ---------------------------------------------------------------- 语言模型
def test_llm_plan_requires_config(api):
    api.post("/api/projects", json={"name": "A"})
    assert api.post("/api/llm/plan", json={"text": "  "}).status_code == 400
    res = api.post("/api/llm/plan", json={"text": "雨夜街道"})
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "BAD_REQUEST"


def test_llm_plan_normalizes_output(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={
            "api": {
                "llm": {
                    "api_key": "sk-test",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-chat",
                }
            }
        },
    )
    content = """```json
    {
      "summary": "雨夜街道上的女人",
      "assets": [{"name": "雨夜街道", "type": "场景", "desc": "湿滑路面", "locked": true}],
      "shots": [
        {"name": "远景", "prompt": "街道远景，雨", "dur": 30, "camera": "35mm"},
        {"name": "空镜", "prompt": "", "dur": "x"}
      ],
      "questions": [{"text": "要不要给她一把伞？", "options": ["要", "不要"]}]
    }
    ```"""
    monkeypatch.setattr(
        "vagent.llm._post_json",
        lambda *args, **kwargs: {"choices": [{"message": {"content": content}}]},
    )
    plan = api.data(api.post("/api/llm/plan", json={"text": "雨夜，一个女人停下"}))["plan"]
    assert plan["version"] == 1
    assert plan["summary"] == "雨夜街道上的女人"
    assert plan["assets"][0]["type"] == "场景" and plan["assets"][0]["locked"] is True
    assert [s["name"] for s in plan["shots"]] == ["远景"]  # 空 prompt 的镜头被丢弃
    assert plan["shots"][0]["dur"] == 10.0  # 超长时长夹到上限
    assert plan["questions"][0]["options"] == ["要", "不要"]


def test_llm_plan_upstream_error(api, monkeypatch):
    from vagent.llm import LLMError

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://api.deepseek.com"}}},
    )

    def boom(*args, **kwargs):
        raise LLMError("INTERNAL_ERROR", "语言模型返回 HTTP 500：upstream", 500)

    monkeypatch.setattr("vagent.llm._post_json", boom)
    res = api.post("/api/llm/plan", json={"text": "雨夜街道"})
    assert res.status_code == 500
    assert res.get_json()["error"]["code"] == "INTERNAL_ERROR"


# ---------------------------------------------------------------- 图片 / 视频 provider
def test_asset_preview_requires_config(api):
    api.post("/api/projects", json={"name": "A"})
    aid = api.data(api.post("/api/assets", json={"name": "角色甲", "type": "角色", "desc": "短发"}))["asset"][
        "id"
    ]
    res = api.post(f"/api/assets/{aid}/preview", json={})
    assert res.status_code == 400
    assert res.get_json()["error"]["code"] == "BAD_REQUEST"
    assert api.post("/api/assets/zzz/preview", json={}).status_code == 404


def _three_views(url_prefix="/uploads/gen/assets/a1"):
    return {
        "views": [
            {"view": "front", "url": f"{url_prefix}/front.jpg", "path": "x/front.jpg", "bytes": 1},
            {"view": "side", "url": f"{url_prefix}/side.jpg", "path": "x/side.jpg", "bytes": 1},
            {"view": "back", "url": f"{url_prefix}/back.jpg", "path": "x/back.jpg", "bytes": 1},
        ]
    }


def test_asset_preview_saves_three_views(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"img": {"api_key": "ark-test", "base_url": "https://x.test/api/v3"}}},
    )
    aid = api.data(api.post("/api/assets", json={"name": "角色甲", "type": "角色", "desc": "短发"}))["asset"][
        "id"
    ]
    monkeypatch.setattr("vagent.images.run", lambda job: _three_views("/uploads/gen/assets/" + aid))
    d = api.data(api.post(f"/api/assets/{aid}/preview", json={}))
    assert [item["kind"] for item in d["asset"]["preview"]] == ["img", "img", "img"]
    assert [item["label"] for item in d["asset"]["preview"]] == ["正面", "侧面", "背面"]
    assert d["image"]["url"].endswith("/front.jpg")


def test_asset_preview_scene_single_concept(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"img": {"api_key": "ark-test", "base_url": "https://x.test/api/v3"}}},
    )
    aid = api.data(api.post("/api/assets", json={"name": "雨夜街道", "type": "场景", "desc": "湿滑路面"}))[
        "asset"
    ]["id"]
    seen = {}

    def fake_run(job):
        seen.update(job)
        return {
            "views": [
                {"view": "concept", "url": f"/uploads/gen/assets/{aid}/concept.jpg", "path": "x", "bytes": 1}
            ]
        }

    monkeypatch.setattr("vagent.images.run", fake_run)
    d = api.data(api.post(f"/api/assets/{aid}/preview", json={}))
    assert seen["payload"]["task"] == "asset_image"
    assert [item["label"] for item in d["asset"]["preview"]] == ["概念图"]
    assert len(d["asset"]["preview"]) == 1


def test_llm_three_view_tool_uses_reference(api, monkeypatch):
    import json as jsonlib

    from vagent import config

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={
            "api": {
                "llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"},
                "img": {"api_key": "ark-test", "base_url": "https://service.test/v1"},
            }
        },
    )
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / "ref.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    rounds = {"n": 0}

    def fake_completion(messages, **kwargs):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "tv-1",
                                    "type": "function",
                                    "function": {
                                        "name": "generate_three_view_drawing",
                                        "arguments": jsonlib.dumps(
                                            {"name": "红发少女", "type": "角色", "desc": "红发异瞳，白裙"},
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "已生成三视图"}}]}

    seen = {}

    def fake_run(job):
        seen.update(job)
        return {
            "views": [
                {"view": "front", "url": "/uploads/gen/assets/chat-x/front.jpg"},
                {"view": "side", "url": "/uploads/gen/assets/chat-x/side.jpg"},
                {"view": "back", "url": "/uploads/gen/assets/chat-x/back.jpg"},
            ]
        }

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    monkeypatch.setattr("vagent.images.run", fake_run)
    d = api.data(
        api.post(
            "/api/llm/plan",
            json={"text": "按这张图生成三视图", "attachment": {"stored": "ref.png", "kind": "图片"}},
        )
    )
    assert len(d["images"]) == 3
    assert len({item["assetId"] for item in d["images"]}) == 1
    assert str(seen["payload"]["ref_images"][0]).endswith("ref.png")

    asset = api.data(api.get("/api/assets?scope=all"))["assets"][0]
    assert asset["refImage"] == "/uploads/ref.png"
    assert [item["label"] for item in asset["preview"]] == ["正面", "侧面", "背面"]


def test_three_view_tool_falls_back_to_asset_reference(api, monkeypatch):
    import json as jsonlib

    from vagent import config
    from vagent.repository import add_asset_with_views

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={
            "api": {
                "llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"},
                "img": {"api_key": "ark-test", "base_url": "https://service.test/v1"},
            }
        },
    )
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / "ref.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    add_asset_with_views("红发少女", "角色", "红发异瞳", ["/uploads/ref.png"], ref_url="/uploads/ref.png")

    rounds = {"n": 0}

    def fake_completion(messages, **kwargs):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "tv-1",
                                    "type": "function",
                                    "function": {
                                        "name": "generate_three_view_drawing",
                                        "arguments": jsonlib.dumps({"name": "红发少女"}, ensure_ascii=False),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "已生成"}}]}

    seen = {}

    def fake_run(job):
        seen.update(job)
        return {
            "views": [
                {"view": "front", "url": "/uploads/gen/assets/chat-y/front.jpg"},
                {"view": "side", "url": "/uploads/gen/assets/chat-y/side.jpg"},
                {"view": "back", "url": "/uploads/gen/assets/chat-y/back.jpg"},
            ]
        }

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    monkeypatch.setattr("vagent.images.run", fake_run)
    d = api.data(api.post("/api/llm/plan", json={"text": "确认，生成三视图"}))
    assert len(d["images"]) == 3
    assert str(seen["payload"]["ref_images"][0]).endswith("ref.png")


def test_detect_generation_need():
    from vagent.llm import detect_generation_need

    assert detect_generation_need("我想要一个龙娘对我微笑的照片") == {"image": True, "video": False}
    assert detect_generation_need("这个角色在风中对镜头微笑的视频") == {"image": False, "video": True}
    assert detect_generation_need("帮我规划一个三镜头分镜") == {"image": False, "video": False}
    assert detect_generation_need("生成三视图") == {"image": True, "video": False}
    assert detect_generation_need("不要图片，只要视频") == {"image": False, "video": True}
    assert detect_generation_need("给这张 photo 配上旁白") == {"image": True, "video": False}


def test_plan_tools_gated_by_intent(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    seen = []

    def fake_completion(messages, **kwargs):
        seen.append(kwargs.get("tools") or [])
        return {"choices": [{"message": {"content": "好的"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    photo = api.data(api.post("/api/llm/plan", json={"text": "我想要一个龙娘对我微笑的照片"}))
    names = [tool["function"]["name"] for tool in seen[-1]]
    assert "generate_image" in names and "generate_video" not in names
    assert photo["intent"] == {"image": True, "video": False}

    video = api.data(api.post("/api/llm/plan", json={"text": "这个角色在风中微笑的视频", "auto": True}))
    names = [tool["function"]["name"] for tool in seen[-1]]
    assert "generate_assets" in names and "generate_video" not in names
    assert video["intent"] == {"image": False, "video": True}

    chat = api.data(api.post("/api/llm/plan", json={"text": "帮我写一段旁白"}))
    names = [tool["function"]["name"] for tool in seen[-1]]
    assert "generate_image" not in names and "generate_video" not in names
    assert "use_rui_skills" in names
    assert chat["intent"] == {"image": False, "video": False}
    assert api.data(api.post("/api/intent", json={"text": "生成三视图"})) == {
        "image": True,
        "video": False,
    }


def test_rui_skill_installed():
    from vagent.skills import rui_skill

    d = rui_skill()
    assert d["ok"] is True
    assert d["version"]
    assert "分镜" in d["skill"]
    assert d["references"]
    ref = rui_skill("character")
    assert ref["reference"] == "character" and ref["reference_text"]


def test_final_prompt_force_expand_without_llm_fails(api):
    api.post("/api/projects", json={"name": "A"})
    r = api.post(
        "/api/video/final-prompt",
        json={
            "text": "六足机器人战斗视频",
            "modules": {"role": {"mode": "auto"}, "scene": {"mode": "auto"}, "style": {"mode": "auto"}},
            "force_expand": True,
        },
    )
    d = r.get_json()
    assert d["ok"] is False
    assert "扩写" in d["error"]["message"]
    assert api.data(api.get("/api/shots"))["shots"] == []


def test_final_prompt_uses_agent_shot_durations(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )

    def fake_completion(messages, **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": jsonlib.dumps(
                            {
                                "prompt": "完整最终提示词",
                                "shots": [
                                    {"title": "机器人起步", "prompt": "镜头一：机器人起步", "dur": 5},
                                    {"title": "开火爆发", "prompt": "镜头二：开火爆发", "dur": 8},
                                ],
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(
        api.post(
            "/api/video/final-prompt",
            json={"text": "六足机器人战斗视频", "modules": {"role": {"mode": "auto"}}},
        )
    )
    assert [shot["dur"] for shot in d["shots"]] == [5, 8]
    assert [shot["name"] for shot in d["shots"]] == ["机器人起步", "开火爆发"]
    assert d["dur"] == 5


def test_auto_mode_generates_assets_before_video(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={
            "api": {
                "llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"},
                "img": {"api_key": "ark-test", "base_url": "https://service.test/v1"},
            }
        },
    )

    def fake_run(job):
        task = job["payload"]["task"]
        if task == "asset_views":
            return {
                "views": [
                    {"view": "front", "url": "/uploads/gen/auto/front.jpg"},
                    {"view": "side", "url": "/uploads/gen/auto/side.jpg"},
                    {"view": "back", "url": "/uploads/gen/auto/back.jpg"},
                ]
            }
        return {"views": [{"view": "concept", "url": "/uploads/gen/auto/concept.jpg"}]}

    monkeypatch.setattr("vagent.images.run", fake_run)
    rounds = {"n": 0}
    seen = []

    def fake_completion(messages, **kwargs):
        rounds["n"] += 1
        seen.append([tool["function"]["name"] for tool in (kwargs.get("tools") or [])])
        if rounds["n"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "assets-1",
                                    "type": "function",
                                    "function": {"name": "generate_assets", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "已完成"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    api.data(api.post("/api/llm/plan", json={"text": "做一个六足机器人战斗视频", "auto": True}))
    assert "generate_assets" in seen[0]
    assert "generate_video" not in seen[0]
    assert "generate_video" in seen[1]
    assets = api.data(api.get("/api/assets?scope=all"))["assets"]
    assert {asset["name"] for asset in assets} == {"角色·最终设定", "场景·最终设定"}
    assert all(asset["preview"] for asset in assets)


def test_final_assets_generates_role_and_scene(api, monkeypatch):
    from vagent import config

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"img": {"api_key": "ark-test", "base_url": "https://service.test/v1"}}},
    )
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / "final-ref.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    def fake_run(job):
        task = job["payload"]["task"]
        if task == "asset_views":
            return {
                "views": [
                    {"view": "front", "url": "/uploads/gen/assets/final/front.jpg"},
                    {"view": "side", "url": "/uploads/gen/assets/final/side.jpg"},
                    {"view": "back", "url": "/uploads/gen/assets/final/back.jpg"},
                ]
            }
        return {"views": [{"view": "concept", "url": "/uploads/gen/assets/final/concept.jpg"}]}

    class SyncThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr("vagent.images.run", fake_run)
    monkeypatch.setattr("vagent.api.llm.threading.Thread", SyncThread)
    d = api.data(
        api.post(
            "/api/video/final-assets",
            json={
                "prompt": "雨夜赛博战场里的六足机器人",
                "modules": {"role": {"mode": "image"}, "scene": {"mode": "auto"}},
                "ref": "/uploads/final-ref.png",
            },
        )
    )
    assert d["generating"] is True
    assert len(d["assets"]) == 2
    assets = api.data(api.get("/api/assets?scope=all"))["assets"]
    role = next(item for item in assets if item["type"] == "角色")
    scene = next(item for item in assets if item["type"] == "场景")
    assert [item["label"] for item in role["preview"]] == ["正面", "侧面", "背面"]
    assert len(scene["preview"]) == 1
    assert role["refImage"] == "/uploads/final-ref.png"


def test_compose_video_prompt_uses_llm(api, monkeypatch):
    from vagent.llm import compose_video_prompt

    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    seen = {}

    def fake_completion(messages, **kwargs):
        seen["system"] = messages[0]["content"]
        return {"choices": [{"message": {"content": "红发龙娘在蓝天下微笑，电影感，中景推近"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    prompt = compose_video_prompt("龙娘视频", {"scene": {"text": "蓝天"}}, ["角色·参考图"])
    assert "红发龙娘" in prompt
    assert "视频提示词编辑" in seen["system"]


def test_final_prompt_creates_draft_without_video(api, monkeypatch):
    from vagent import config

    api.post("/api/projects", json={"name": "A"})
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / "ref.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)

    def boom(*args, **kwargs):
        raise AssertionError("最终提示词阶段不应该提交视频")

    monkeypatch.setattr("vagent.providers.video.submit_reference", boom)
    monkeypatch.setattr("vagent.providers.video.submit", boom)
    d = api.data(
        api.post(
            "/api/video/final-prompt",
            json={
                "text": "我需要一个龙娘在蓝天下微笑的视频",
                "modules": {
                    "role": {"mode": "image"},
                    "scene": {"mode": "text", "text": "蓝天，微风"},
                    "style": {"mode": "auto"},
                },
                "assets": ["角色·参考图", "场景·蓝天"],
                "attachment": {"stored": "ref.png", "kind": "图片"},
            },
        )
    )
    shot = d["shot"]
    assert shot["providerJob"] == ""
    assert shot["status"] == "pending"
    assert all(item["name"] and not item["name"].startswith("我想要") for item in d["shots"])
    assert "蓝天" in d["prompt"]
    assert len(d["shots"]) >= 2
    for item in d["shots"]:
        assert item["providerJob"] == ""
        assert item["status"] == "pending"
    first = config.UPLOAD_DIR / "gen" / "shots" / (shot["id"] + "-first.png")
    assert first.is_file()
    assert len(api.data(api.get("/api/shots"))["shots"]) == len(d["shots"])


def test_judge_modify_target_classifies_asset_shot_none():
    from vagent.api.llm import _classify_modification

    history = [
        {
            "role": "agent",
            "text": "准备修改「六足机器人」",
            "meta": {"assetProposals": [{"assetId": "a1"}]},
        }
    ]
    assert _classify_modification("这个再改一下", history, {})["target"] == "asset"
    assert _classify_modification("炮塔还是大", history, {})["target"] == "asset"
    assert _classify_modification("改镜头", history, {})["target"] == "shot"
    assert _classify_modification("不要改角色，改镜头", history, {})["target"] == "shot"
    assert _classify_modification("不要改镜头", history, {})["target"] == "none"
    assert _classify_modification("改视频", history, {})["target"] == "video"


def test_explicit_switch_to_shot_stops_asset_proposal(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    asset = api.data(api.post("/api/assets", json={"name": "角色·参考图", "type": "角色", "desc": "旧"}))[
        "asset"
    ]
    shot = api.data(api.post("/api/shots", json={"name": "镜头 01", "dur": 4, "prompt": "旧镜头"}))["shot"]
    api.post(
        "/api/messages",
        json={
            "role": "agent",
            "text": "准备修改「角色·参考图」",
            "meta": {"assetProposals": [{"assetId": asset["id"], "assetName": asset["name"]}]},
        },
    )
    seen = {}

    def fake_completion(messages, **kwargs):
        seen["tools"] = kwargs.get("tools") or []
        seen["tool_choice"] = kwargs.get("tool_choice")
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "shot-upd",
                                "type": "function",
                                "function": {
                                    "name": "update_shot_prompt",
                                    "arguments": jsonlib.dumps(
                                        {"shot_no": shot["no"], "prompt": "机器人开火，镜头缓慢推进"},
                                        ensure_ascii=False,
                                    ),
                                },
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(api.post("/api/llm/plan", json={"text": "不要改角色，改镜头"}))
    names = [tool["function"]["name"] for tool in seen["tools"]]
    assert "update_shot_prompt" in names
    assert "judge_modify_target" in names
    assert "propose_asset_change" not in names
    assert not d["assetProposals"]
    fresh = api.data(api.get("/api/shots"))["shots"][0]
    assert fresh["prompt"] == "机器人开火，镜头缓慢推进"


def test_asset_session_followup_always_proposes(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    asset = api.data(api.post("/api/assets", json={"name": "六足战斗机器人", "type": "角色", "desc": "旧"}))[
        "asset"
    ]
    api.post(
        "/api/messages",
        json={
            "role": "agent",
            "text": "准备修改「六足战斗机器人」：炮塔收窄",
            "meta": {"assetProposals": [{"assetId": asset["id"], "assetName": asset["name"]}]},
        },
    )
    api.post("/api/messages", json={"role": "agent", "text": "请继续补充修改意见。"})
    seen = {}

    def fake_completion(messages, **kwargs):
        seen["tool_choice"] = kwargs.get("tool_choice")
        seen["tools"] = kwargs.get("tools") or []
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "p3",
                                "type": "function",
                                "function": {
                                    "name": "propose_asset_change",
                                    "arguments": jsonlib.dumps(
                                        {"name": asset["name"], "desc": "更低矮", "changes": "继续低矮化"},
                                        ensure_ascii=False,
                                    ),
                                },
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(
        api.post(
            "/api/llm/plan",
            json={"text": "炮塔还是大，机炮还是短，整体造型要更加低矮，侵略性"},
        )
    )
    names = [tool["function"]["name"] for tool in seen["tools"]]
    assert "propose_asset_change" in names
    assert (seen["tool_choice"] or {}).get("function", {}).get("name") == "propose_asset_change"
    assert d["assetProposals"]


def test_asset_edit_falls_back_to_proposal_when_llm_skips_tool(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    asset = api.data(api.post("/api/assets", json={"name": "六足战斗机器人", "type": "角色", "desc": "旧"}))[
        "asset"
    ]
    api.post(
        "/api/messages",
        json={
            "role": "agent",
            "text": "准备修改「六足战斗机器人」：炮塔收窄",
            "meta": {"assetProposals": [{"assetId": asset["id"], "assetName": asset["name"]}]},
        },
    )

    def fake_completion(messages, **kwargs):
        return {"choices": [{"message": {"content": "好的，我记下了"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(api.post("/api/llm/plan", json={"text": "炮塔还是大，整体再低矮一点"}))
    assert d["assetProposals"]
    assert d["assetProposals"][0]["assetName"] == "六足战斗机器人"
    assert d["assetProposals"][0]["changes"] == "炮塔还是大，整体再低矮一点"


def test_asset_followup_after_proposal_still_proposes(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    asset = api.data(api.post("/api/assets", json={"name": "六足战斗机器人", "type": "角色", "desc": "旧"}))[
        "asset"
    ]
    api.post(
        "/api/messages",
        json={
            "role": "agent",
            "text": "准备修改「六足战斗机器人」：[炮塔收窄]",
            "meta": {
                "assetProposals": [
                    {"assetId": asset["id"], "assetName": asset["name"], "type": "角色", "desc": "新"}
                ]
            },
        },
    )
    seen = {}

    def fake_completion(messages, **kwargs):
        seen["tools"] = kwargs.get("tools") or []
        seen["tool_choice"] = kwargs.get("tool_choice")
        return {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "p2",
                                "type": "function",
                                "function": {
                                    "name": "propose_asset_change",
                                    "arguments": jsonlib.dumps(
                                        {"name": asset["name"], "desc": "新方案", "changes": "继续调整"},
                                        ensure_ascii=False,
                                    ),
                                },
                            }
                        ],
                    }
                }
            ]
        }

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(api.post("/api/llm/plan", json={"text": "继续调整：激光炮炮管改成开槽轨道"}))
    names = [tool["function"]["name"] for tool in seen["tools"]]
    assert "propose_asset_change" in names
    assert (seen["tool_choice"] or {}).get("function", {}).get("name") == "propose_asset_change"
    assert d["assetProposals"]


def test_asset_edit_message_proposes_before_generating(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    api.post("/api/assets", json={"name": "六足战斗机器人", "type": "角色", "desc": "旧描述"})
    api.post(
        "/api/messages",
        json={"role": "agent", "text": "「六足战斗机器人」的资产描述已按这个方向更新，去资产库看设定图。"},
    )
    seen = {}

    def fake_completion(messages, **kwargs):
        if not seen:
            seen["tools"] = kwargs.get("tools") or []
            seen["tool_choice"] = kwargs.get("tool_choice")
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "proposal-1",
                                    "type": "function",
                                    "function": {
                                        "name": "propose_asset_change",
                                        "arguments": jsonlib.dumps(
                                            {
                                                "name": "六足战斗机器人",
                                                "desc": "加长炮管、压低底盘的六足机器人",
                                                "changes": "加长激光炮轨道；炮塔压低",
                                            },
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "方案如上"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(
        api.post(
            "/api/llm/plan",
            json={"text": "炮塔太大，机炮炮管太短，激光炮太细了"},
        )
    )
    names = [tool["function"]["name"] for tool in seen["tools"]]
    assert "propose_asset_change" in names
    assert "generate_video" not in names
    assert (seen["tool_choice"] or {}).get("function", {}).get("name") == "propose_asset_change"
    assert d["assetProposals"] and d["assetProposals"][0]["assetName"] == "六足战斗机器人"
    assert d["intent"] == {"image": True, "video": False}


def test_asset_draft_does_not_overwrite_until_save(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"img": {"api_key": "ark-test", "base_url": "https://service.test/v1"}}},
    )
    asset = api.data(
        api.post("/api/assets", json={"name": "六足战斗机器人", "type": "角色", "desc": "旧描述"})
    )["asset"]

    seen = {}

    def fake_run(job):
        seen["desc"] = job["payload"].get("desc", "")
        return {
            "views": [
                {"view": "front", "url": "/uploads/gen/draft/front.jpg"},
                {"view": "side", "url": "/uploads/gen/draft/side.jpg"},
                {"view": "back", "url": "/uploads/gen/draft/back.jpg"},
            ]
        }

    monkeypatch.setattr("vagent.images.run", fake_run)
    d = api.data(
        api.post(
            f"/api/assets/{asset['id']}/draft",
            json={"desc": "加长炮管、压低底盘的新设定", "changes": "炮塔再矮一半、炮管再加长"},
        )
    )
    assert "必须明显改版" in seen["desc"]
    assert "炮塔再矮一半" in seen["desc"]
    assert d["previews"] and len(d["previews"]) == 3
    current = api.data(api.get("/api/assets?scope=all"))["assets"][0]
    assert current["desc"] == "旧描述"
    api.data(
        api.post(
            f"/api/assets/{asset['id']}/draft/save",
            json={"desc": "加长炮管、压低底盘的新设定", "previews": d["previews"]},
        )
    )
    saved = api.data(api.get("/api/assets?scope=all"))["assets"][0]
    assert saved["desc"] == "加长炮管、压低底盘的新设定"
    assert len(saved["preview"]) == 3


def test_update_asset_tool_regenerates_selected_asset(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={
            "api": {
                "llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"},
                "img": {"api_key": "ark-test", "base_url": "https://service.test/v1"},
            }
        },
    )
    api.post("/api/assets", json={"name": "六足战斗机器人", "type": "角色", "desc": "旧描述"})

    def fake_run(job):
        return {
            "views": [
                {"view": "front", "url": "/uploads/gen/upd/front.jpg"},
                {"view": "side", "url": "/uploads/gen/upd/side.jpg"},
                {"view": "back", "url": "/uploads/gen/upd/back.jpg"},
            ]
        }

    monkeypatch.setattr("vagent.images.run", fake_run)
    rounds = {"n": 0}

    def fake_completion(messages, **kwargs):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "upd-1",
                                    "type": "function",
                                    "function": {
                                        "name": "update_asset",
                                        "arguments": jsonlib.dumps(
                                            {
                                                "name": "六足战斗机器人",
                                                "desc": "加长炮管、压低底盘的六足机器人",
                                            },
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "已更新"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(
        api.post(
            "/api/llm/plan",
            json={"text": "确认修改资产描述", "confirm_kind": "asset"},
        )
    )
    assert d["assetUpdates"] and len(d["assetUpdates"][0]["previews"]) == 3
    asset = next(
        item
        for item in api.data(api.get("/api/assets?scope=all"))["assets"]
        if item["name"] == "六足战斗机器人"
    )
    assert asset["desc"] == "加长炮管、压低底盘的六足机器人"
    assert len(asset["preview"]) == 3


def test_confirm_kind_asset_blocks_video(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    seen = {}

    def fake_completion(messages, **kwargs):
        seen["tools"] = kwargs.get("tools") or []
        return {"choices": [{"message": {"content": "好的"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(api.post("/api/llm/plan", json={"text": "确认修改资产描述", "confirm_kind": "asset"}))
    names = [tool["function"]["name"] for tool in seen["tools"]]
    assert "generate_image" in names
    assert "generate_video" not in names
    assert d["intent"] == {"image": True, "video": False}


def test_confirm_kind_shot_updates_prompt(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    shot = api.data(api.post("/api/shots", json={"name": "镜头 01", "dur": 4, "prompt": "旧提示词"}))["shot"]
    rounds = {"n": 0}
    seen = {}

    def fake_completion(messages, **kwargs):
        rounds["n"] += 1
        seen["tools"] = kwargs.get("tools") or []
        if rounds["n"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "shot-1",
                                    "type": "function",
                                    "function": {
                                        "name": "update_shot_prompt",
                                        "arguments": jsonlib.dumps(
                                            {"shot_no": shot["no"], "prompt": "新提示词"},
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "已更新"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    api.data(api.post("/api/llm/plan", json={"text": "确认修改镜头描述", "confirm_kind": "shot"}))
    names = [tool["function"]["name"] for tool in seen["tools"]]
    assert "update_shot_prompt" in names
    assert "generate_video" not in names
    fresh = api.data(api.get("/api/shots"))["shots"][0]
    assert fresh["prompt"] == "新提示词"


def test_short_confirm_follows_agent_question_not_initial_video(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    api.post("/api/messages", json={"role": "user", "text": "做一个机器人战斗视频"})
    api.post(
        "/api/messages",
        json={
            "role": "agent",
            "text": "按这个方向重新出设定图吗？确认后我就更新资产描述并重新生成。",
        },
    )
    api.post("/api/messages", json={"role": "user", "text": "确认"})
    seen = {}

    def fake_completion(messages, **kwargs):
        seen["tools"] = kwargs.get("tools") or []
        return {"choices": [{"message": {"content": "好的"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(api.post("/api/llm/plan", json={"text": "确认"}))
    names = [tool["function"]["name"] for tool in seen["tools"]]
    assert "generate_image" in names
    assert "generate_video" not in names
    assert d["intent"] == {"image": True, "video": False}


def test_short_confirm_keeps_image_intent_and_reference(api, monkeypatch):
    import json as jsonlib

    from vagent import config

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={
            "api": {
                "llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"},
                "img": {"api_key": "ark-test", "base_url": "https://service.test/v1"},
            }
        },
    )
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / "confirm-ref.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    api.post(
        "/api/messages",
        json={
            "role": "user",
            "text": "我需要她的设定图",
            "meta": {
                "attachment": {
                    "name": "confirm-ref.png",
                    "stored": "confirm-ref.png",
                    "kind": "图片",
                    "url": "/uploads/confirm-ref.png",
                }
            },
        },
    )
    api.post("/api/messages", json={"role": "user", "text": "开工"})

    rounds = {"n": 0}
    seen = {}

    def fake_completion(messages, **kwargs):
        rounds["n"] += 1
        seen["tools"] = kwargs.get("tools") or []
        seen["system"] = messages[0]["content"]
        if rounds["n"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "tv-confirm",
                                    "type": "function",
                                    "function": {
                                        "name": "generate_three_view_drawing",
                                        "arguments": jsonlib.dumps(
                                            {"name": "龙娘", "type": "角色", "desc": "红发"},
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "已生成三视图"}}]}

    def fake_run(job):
        seen["ref"] = job["payload"]["ref_images"][0]
        return {
            "views": [
                {"view": "front", "url": "/uploads/gen/assets/chat-z/front.jpg"},
                {"view": "side", "url": "/uploads/gen/assets/chat-z/side.jpg"},
                {"view": "back", "url": "/uploads/gen/assets/chat-z/back.jpg"},
            ]
        }

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    monkeypatch.setattr("vagent.images.run", fake_run)
    d = api.data(api.post("/api/llm/plan", json={"text": "开工"}))
    names = [tool["function"]["name"] for tool in seen["tools"]]
    assert "generate_three_view_drawing" in names and "generate_image" in names
    assert "禁止再输出 questions" in seen["system"]
    assert str(seen["ref"]).endswith("confirm-ref.png")
    assert len(d["images"]) == 3


def test_video_request_forces_clarify_unless_auto(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    calls = []

    def fake_completion(messages, **kwargs):
        calls.append(kwargs.get("tools") or [])
        return {"choices": [{"message": {"content": "好的"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    normal = api.data(api.post("/api/llm/plan", json={"text": "我需要一个龙娘在蓝天下微笑的视频"}))
    assert calls == []
    assert normal["intent"] == {"image": False, "video": True}
    assert normal["videos"] == []
    assert len(normal["plan"]["questions"]) == 3

    auto = api.data(
        api.post("/api/llm/plan", json={"text": "我需要一个龙娘在蓝天下微笑的视频", "auto": True})
    )
    assert len(calls) == 1
    names = [tool["function"]["name"] for tool in calls[0]]
    assert "generate_assets" in names
    assert "generate_video" not in names
    assert auto["plan"]["questions"] == []


def test_confirm_keeps_original_intent_and_blocks_questions(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    api.post("/api/messages", json={"role": "user", "text": "我想要一个龙娘对我微笑的照片"})
    confirm = (
        "已转存资产：角色·参考图。角色：已上传参考图；场景：由你自动补全；风格：由你自动补全。"
        "三项已确认，请直接继续，不要再追问。"
    )
    api.post("/api/messages", json={"role": "user", "text": confirm})
    seen = {}

    def fake_completion(messages, **kwargs):
        seen["tools"] = kwargs.get("tools") or []
        seen["system"] = messages[0]["content"]
        return {
            "choices": [
                {
                    "message": {
                        "content": jsonlib.dumps(
                            {
                                "summary": "好的",
                                "shots": [],
                                "assets": [],
                                "clarify": {
                                    "needed": True,
                                    "questions": [{"text": "角色是谁？", "options": ["A", "B"]}],
                                },
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(api.post("/api/llm/plan", json={"text": confirm}))
    names = [tool["function"]["name"] for tool in seen["tools"]]
    assert "generate_image" in names and "generate_video" not in names
    assert "禁止再输出 questions" in seen["system"]
    assert d["intent"] == {"image": True, "video": False}
    assert d["plan"]["questions"] == []


def test_auto_video_submits_reference_without_llm(api, monkeypatch):
    from vagent import config

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"video": {"api_key": "mm-test", "base_url": "https://service.test/v1"}}},
    )
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / "ref.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    seen = {}

    def fake_submit(prompt, refs, duration=5, **kwargs):
        seen.update({"prompt": prompt, "refs": refs, "duration": duration})
        return "task-auto-1"

    monkeypatch.setattr("vagent.providers.video.submit_reference", fake_submit)
    d = api.data(
        api.post(
            "/api/auto/video",
            json={
                "text": "5秒，红发少女在风中回头微笑",
                "attachment": {"stored": "ref.png", "kind": "图片"},
            },
        )
    )
    assert d["taskId"] == "task-auto-1"
    assert d["shot"]["providerJob"] == "task-auto-1"
    assert seen["duration"] == 5
    assert str(seen["refs"][0]).startswith("data:image/")
    assert api.post("/api/auto/video", json={"text": "没有参考图"}).status_code == 400


def test_submit_reference_builds_reference_role(api, monkeypatch):
    from vagent.providers import video as video_provider

    api.put(
        "/api/settings/api",
        json={
            "api": {
                "video": {"api_key": "mm-test", "base_url": "https://service.test/v1", "model": "MiniMax-H3"}
            }
        },
    )
    seen = {}

    def fake_post(url, body, key, timeout):
        seen.update({"url": url, "body": body})
        return {"task_id": "t-ref-1"}

    monkeypatch.setattr(video_provider, "post_json", fake_post)
    task = video_provider.submit_reference("女孩回头", ["data:image/png;base64,xxx"], duration=6)
    assert task == "t-ref-1"
    assert seen["url"].endswith("/v2/video_generation")
    assert seen["body"]["model"] == "MiniMax-H3"
    assert seen["body"]["content"][1]["role"] == "reference_image"
    assert seen["body"]["duration"] == 6


def test_three_view_tool_requires_reference():
    from vagent.llm import _run_three_view_tool

    result, record = _run_three_view_tool({}, None)
    assert result["ok"] is False
    assert record is None


def test_asset_preview_uses_stored_reference(api, monkeypatch):
    from vagent import config
    from vagent.repository import add_asset_with_views

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"img": {"api_key": "ark-test", "base_url": "https://service.test/v1"}}},
    )
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / "ref.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    (config.UPLOAD_DIR / "front.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 32)
    asset = add_asset_with_views("角色甲", "角色", "短发", ["/uploads/front.jpg"], ref_url="/uploads/ref.png")
    seen = {}

    def fake_run(job):
        seen.update(job)
        return {"views": [{"view": "front", "url": "/uploads/gen/assets/a1/front.jpg"}]}

    monkeypatch.setattr("vagent.images.run", fake_run)
    api.data(api.post(f"/api/assets/{asset['id']}/preview", json={}))
    assert str(seen["payload"]["ref_images"][0]).endswith("ref.png")


def test_asset_preview_enriches_prompt_with_llm(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={
            "api": {
                "llm": {"api_key": "sk-test", "base_url": "https://x.test"},
                "img": {"api_key": "ark-test", "base_url": "https://service.test/v1"},
            }
        },
    )
    aid = api.data(api.post("/api/assets", json={"name": "角色甲", "type": "角色", "desc": "短发"}))["asset"][
        "id"
    ]
    monkeypatch.setattr(
        "vagent.llm.chat", lambda *args, **kwargs: "深色风衣，湿发贴额，冷白路灯侧光，哑光面料"
    )
    seen = {}
    monkeypatch.setattr(
        "vagent.images.run",
        lambda job: seen.update(job) or _three_views(),
    )
    d = api.data(api.post(f"/api/assets/{aid}/preview", json={}))
    assert d["enriched"] is True
    assert d["prompt"] == "深色风衣，湿发贴额，冷白路灯侧光，哑光面料"
    assert seen["payload"]["desc"] == d["prompt"]
    assert seen["payload"]["asset_id"] == aid


def test_asset_preview_falls_back_when_llm_fails(api, monkeypatch):
    from vagent.llm import LLMError

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={
            "api": {
                "llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"},
                "img": {"api_key": "ark-test", "base_url": "https://service.test/v1"},
            }
        },
    )
    aid = api.data(api.post("/api/assets", json={"name": "角色甲", "type": "角色", "desc": "短发"}))["asset"][
        "id"
    ]

    def boom(*args, **kwargs):
        raise LLMError("INTERNAL_ERROR", "boom", 500)

    monkeypatch.setattr("vagent.llm.chat", boom)
    seen = {}
    monkeypatch.setattr(
        "vagent.images.run",
        lambda job: seen.update(job) or _three_views(),
    )
    d = api.data(api.post(f"/api/assets/{aid}/preview", json={}))
    assert d["enriched"] is False
    assert seen["payload"]["desc"] == "短发"


def test_asset_enrich_uses_main_agent_and_records(api, monkeypatch):
    api.post("/api/projects", json={"name": "雨夜片", "kind": "概念片"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://x.test"}}},
    )
    aid = api.data(api.post("/api/assets", json={"name": "机器人", "type": "角色", "desc": "六足机器人"}))[
        "asset"
    ]["id"]
    seen = {}

    def fake_chat(messages, **kwargs):
        seen["messages"] = messages
        return "金属质感六足仿生机器人，关节结构清晰，机身带红蓝状态灯，冷白环境光"

    monkeypatch.setattr("vagent.llm.chat", fake_chat)
    d = api.data(api.post(f"/api/assets/{aid}/enrich", json={}))
    assert d["prompt"].startswith("金属质感")
    assert d["base"] == "六足机器人"
    user = [m["content"] for m in seen["messages"] if m["role"] == "user"][0]
    assert "项目「雨夜片」" in user and "六足机器人" in user

    from vagent.db import q1

    row = q1("SELECT * FROM asset_enrichments WHERE asset_id = ?", (aid,))
    assert row["prompt"] == d["prompt"]


def test_asset_enrich_rejects_locked_and_missing_config(api):
    api.post("/api/projects", json={"name": "A"})
    locked = api.data(api.post("/api/assets", json={"name": "L", "desc": "x", "locked": True}))["asset"]["id"]
    assert api.post(f"/api/assets/{locked}/enrich", json={}).status_code == 400
    open_id = api.data(api.post("/api/assets", json={"name": "U", "desc": "y"}))["asset"]["id"]
    assert api.post(f"/api/assets/{open_id}/enrich", json={}).status_code == 400
    assert api.post("/api/assets/zzz/enrich", json={}).status_code == 404


def test_asset_from_image_copies_without_model(api, monkeypatch):
    from vagent import config

    api.post("/api/projects", json={"name": "A"})
    folder = config.UPLOAD_DIR / "gen"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "chat.jpg").write_bytes(b"\xff\xd8\xff" + b"0" * 32)
    image = "/uploads/gen/chat.jpg"

    def boom(*args, **kwargs):
        raise AssertionError("转存不应该调用图片模型")

    monkeypatch.setattr("vagent.providers.image.generate", boom)

    first = api.data(
        api.post(
            "/api/assets/from-image",
            json={"url": image, "name": "六足机器人", "type": "角色", "desc": "锈蚀六足机器人"},
        )
    )
    assert first["created"] is True
    assert first["asset"]["preview"][0] == {"kind": "img", "url": image, "label": "生成图"}
    assert first["asset"]["desc"] == "锈蚀六足机器人"
    assert first["asset"]["locked"] is False

    again = api.data(api.post("/api/assets/from-image", json={"url": image, "name": "另一个名字"}))
    assert again["created"] is False and again["asset"]["id"] == first["asset"]["id"]
    assert len(api.data(api.get("/api/assets?scope=all"))["assets"]) == 1

    assert api.post("/api/assets/from-image", json={"url": "/uploads/gen/nope.jpg"}).status_code == 400
    assert api.post("/api/assets/from-image", json={"url": "/etc/passwd"}).status_code == 400


def test_shot_video_submit_and_poll(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"video": {"api_key": "mm-test", "base_url": "https://api.minimax.cn/v2"}}},
    )
    sid = api.data(api.post("/api/shots", json={"name": "镜头", "dur": 3.0, "prompt": "雨夜街道"}))["shot"][
        "id"
    ]

    # 首帧模式必须先出首帧并确认，视频接口不再自动补图
    assert api.post(f"/api/shots/{sid}/video", json={}).status_code == 400
    frame = api.data(api.post(f"/api/shots/{sid}/keyframe", json={}))
    assert frame["confirmed"] is False
    assert api.post(f"/api/shots/{sid}/video", json={}).status_code == 400
    assert api.data(api.post(f"/api/shots/{sid}/keyframe", json={"confirm": True}))["confirmed"] is True

    monkeypatch.setattr("vagent.providers.video.submit", lambda *args, **kwargs: "task-1")
    d = api.data(api.post(f"/api/shots/{sid}/video", json={}))
    assert d["taskId"] == "task-1"
    assert d["shot"]["status"] == "redraw" and d["shot"]["providerJob"] == "task-1"

    monkeypatch.setattr(
        "vagent.providers.video.query",
        lambda *args, **kwargs: {"state": "running", "url": "", "error": ""},
    )
    d = api.data(api.get(f"/api/shots/{sid}/video"))
    assert d["state"] == "running"

    monkeypatch.setattr(
        "vagent.providers.video.query",
        lambda *args, **kwargs: {"state": "succeeded", "url": "https://x.test/a.mp4", "error": ""},
    )
    monkeypatch.setattr("vagent.providers.video.download", lambda *args, **kwargs: "/uploads/generated/a.mp4")
    d = api.data(api.get(f"/api/shots/{sid}/video"))
    assert d["state"] == "succeeded" and d["clipUrl"] == "/uploads/generated/a.mp4"
    assert d["shot"]["status"] == "confirmed" and d["shot"]["clipPath"] == "/uploads/generated/a.mp4"


def test_shot_ref_assets_auto_and_reference_submit(api, monkeypatch):
    import json as jsonlib

    from vagent import config
    from vagent.db import now_text, x

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"video": {"api_key": "mm-test", "base_url": "https://api.minimax.cn/v2"}}},
    )
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / "shot-asset.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    asset = api.data(
        api.post("/api/assets", json={"name": "六足机器人", "type": "角色", "desc": "重型装甲"})
    )["asset"]
    x(
        "UPDATE assets SET preview = ? WHERE id = ?",
        (
            jsonlib.dumps(
                [{"kind": "img", "url": "/uploads/shot-asset.png", "label": "正面"}],
                ensure_ascii=False,
            ),
            asset["id"],
        ),
    )
    sid = api.data(api.post("/api/shots", json={"name": "镜头", "dur": 4.0, "prompt": "六足机器人开火"}))[
        "shot"
    ]["id"]
    d = api.data(api.post(f"/api/shots/{sid}/ref-assets/auto", json={}))
    assert d["assetIds"] == [asset["id"]]
    assert d["shot"]["refMode"] is True

    seen = {}

    def fake_submit_reference(prompt, refs, duration=5):
        seen["prompt"] = prompt
        seen["refs"] = refs
        return "task-ref-1"

    def boom(*args, **kwargs):
        raise AssertionError("涉及资产模式不应走首帧提交")

    monkeypatch.setattr("vagent.providers.video.submit_reference", fake_submit_reference)
    monkeypatch.setattr("vagent.providers.video.submit", boom)
    got = api.data(api.post(f"/api/shots/{sid}/video", json={}))
    assert got["mode"] == "assets"
    assert got["taskId"] == "task-ref-1"
    assert "六足机器人" in seen["prompt"] and "重型装甲" in seen["prompt"]
    assert seen["refs"] and seen["refs"][0].startswith("data:image/png;base64,")


def test_shot_video_status_without_job(api):
    api.post("/api/projects", json={"name": "A"})
    sid = api.data(api.post("/api/shots", json={"name": "镜头", "dur": 3.0, "prompt": "x"}))["shot"]["id"]
    res = api.get(f"/api/shots/{sid}/video")
    assert res.status_code == 400
    assert api.get("/api/shots/zzz/video").status_code == 404


# ---------------------------------------------------------------- 工具调用 / API 用量
def test_llm_tool_generates_image_and_asset(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://x.test"}}},
    )
    rounds = {"n": 0}

    def fake_completion(messages, **kwargs):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "generate_image",
                                        "arguments": jsonlib.dumps(
                                            {"prompt": "雨夜街道，冷调", "name": "雨夜街道", "type": "场景"},
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "content": jsonlib.dumps(
                            {"summary": "已生成雨夜街道设定图", "assets": [], "shots": [], "questions": []},
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    monkeypatch.setattr(
        "vagent.providers.image.generate",
        lambda *args, **kwargs: {"url": "/uploads/generated/t.png", "model": "test"},
    )
    d = api.data(api.post("/api/llm/plan", json={"text": "给我一张雨夜街道的图"}))
    assert d["reply"] == "已生成雨夜街道设定图"
    assert d["images"][0]["url"] == "/uploads/generated/t.png"
    assert d["images"][0]["assetId"]
    boot = api.data(api.get("/api/bootstrap"))
    assert any(
        a["name"] == "雨夜街道" and a["preview"][0]["url"] == "/uploads/generated/t.png"
        for a in boot["assets"]
    )


def test_llm_chat_uses_history_and_plain_reply(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://x.test"}}},
    )
    api.post("/api/messages", json={"role": "user", "text": "我叫小林"})
    seen = {}

    def fake_post(url, payload, api_key, timeout=60):
        seen["messages"] = payload["messages"]
        return {"choices": [{"message": {"content": "你叫小林，我们刚聊过。"}}]}

    monkeypatch.setattr("vagent.llm._post_json", fake_post)
    d = api.data(api.post("/api/llm/plan", json={"text": "我叫什么？"}))
    assert d["reply"] == "你叫小林，我们刚聊过。"
    assert d["plan"]["shots"] == [] and d["plan"]["assets"] == []
    assert any(m["role"] == "user" and m["content"] == "我叫小林" for m in seen["messages"])
    assert seen["messages"][-1] == {"role": "user", "content": "我叫什么？"}


def test_llm_plan_parses_clarify_questions(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://x.test"}}},
    )
    content = jsonlib.dumps(
        {
            "summary": "雨夜追车",
            "clarify": {
                "needed": True,
                "missing": ["duration", "bogus"],
                "questions": [
                    {"slot": "duration", "text": "这一镜多长？", "options": ["3 秒", "5 秒"]},
                    {"slot": "duration", "text": "这一镜多长？", "options": ["3 秒"]},
                    {"slot": "style", "text": "什么风格？", "options": ["冷调", "暖调"]},
                ],
            },
            "assets": [],
            "shots": [{"name": "镜头", "prompt": "雨夜", "dur": 3}],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        "vagent.llm._post_json",
        lambda *args, **kwargs: {"choices": [{"message": {"content": content}}]},
    )
    plan = api.data(api.post("/api/llm/plan", json={"text": "帮我规划雨夜追车"}))["plan"]
    assert plan["clarify"]["needed"] is True
    assert plan["clarify"]["missing"] == ["duration"]
    assert [q["text"] for q in plan["clarify"]["questions"]] == ["这一镜多长？", "什么风格？"]
    assert plan["clarify"]["questions"][0]["slot"] == "duration"


def test_llm_plan_clarify_derived_from_legacy_questions(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://x.test"}}},
    )
    content = jsonlib.dumps(
        {
            "summary": "一段画面",
            "questions": [{"text": "时长？", "options": ["3 秒", "5 秒"]}],
            "shots": [{"name": "镜头", "prompt": "画面", "dur": 3}],
        },
        ensure_ascii=False,
    )
    monkeypatch.setattr(
        "vagent.llm._post_json",
        lambda *args, **kwargs: {"choices": [{"message": {"content": content}}]},
    )
    plan = api.data(api.post("/api/llm/plan", json={"text": "拍一段"}))["plan"]
    assert plan["clarify"]["needed"] is True
    assert plan["clarify"]["questions"][0]["text"] == "时长？"


def test_llm_plan_passes_locked_assets_context(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://x.test"}}},
    )
    api.post("/api/assets", json={"name": "小林", "type": "角色", "desc": "蓝夹克", "locked": True})
    seen = {}

    def fake_post(url, payload, api_key, timeout=60):
        seen["system"] = payload["messages"][0]["content"]
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"summary":"好","clarify":{"needed":false,"missing":[],"questions":[]},"shots":[]}'
                    }
                }
            ]
        }

    monkeypatch.setattr("vagent.llm._post_json", fake_post)
    api.data(api.post("/api/llm/plan", json={"text": "规划一镜"}))
    assert "当前项目资产" in seen["system"] and "小林" in seen["system"]


def test_llm_plan_sends_attachment_as_vision(api, monkeypatch):
    from vagent import config

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://x.test"}}},
    )
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (config.UPLOAD_DIR / "ref.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    seen = {}

    def fake_post(url, payload, api_key, timeout=60):
        seen["messages"] = payload["messages"]
        return {"choices": [{"message": {"content": "看到了这张参考图"}}]}

    monkeypatch.setattr("vagent.llm._post_json", fake_post)
    d = api.data(
        api.post(
            "/api/llm/plan",
            json={
                "text": "按这张图补全设定",
                "attachment": {"stored": "ref.png", "kind": "图片"},
            },
        )
    )
    assert d["reply"] == "看到了这张参考图"
    content = seen["messages"][-1]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "按这张图补全设定"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_image_provider_passes_reference(api, monkeypatch, tmp_path):
    from vagent.providers import image as image_provider

    api.put(
        "/api/settings/api",
        json={"api": {"img": {"api_key": "ark-test", "base_url": "https://service.test/v1"}}},
    )
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    seen = {}

    def fake_post(url, payload, api_key, timeout):
        seen["body"] = payload
        return {"data": [{"url": "https://x.test/a.png"}]}

    monkeypatch.setattr("vagent.providers.image.post_json", fake_post)
    monkeypatch.setattr("vagent.providers.image.download_media", lambda *a, **k: "/uploads/x.png")
    out = image_provider.generate("保持主体一致", ref_images=[ref])
    assert out["url"] == "/uploads/x.png"
    assert seen["body"]["image"].startswith("data:image/png;base64,")


def test_llm_video_tool_creates_shot(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    # 固定资产硬闸：没有角色三视图就不许出视频，所以先放一个已出图的角色资产
    api.post(
        "/api/assets",
        json={
            "name": "雨夜风衣女",
            "type": "角色",
            "preview": [{"kind": "img", "url": "/uploads/gen/ready.png", "label": "三视图"}],
        },
    )
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://x.test"}}},
    )
    rounds = {"n": 0}

    def fake_completion(messages, **kwargs):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-v1",
                                    "type": "function",
                                    "function": {
                                        "name": "generate_video",
                                        "arguments": jsonlib.dumps(
                                            {"prompt": "雨夜街头，女人回头", "name": "回头", "dur": 4},
                                            ensure_ascii=False,
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"content": "视频任务已提交"}}]}

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    monkeypatch.setattr("vagent.providers.video.submit", lambda prompt, dur, **kw: "task-v1")
    d = api.data(api.post("/api/llm/plan", json={"text": "把这一镜做成视频", "auto": True}))
    assert d["videos"][0]["taskId"] == "task-v1"
    shots = api.data(api.get("/api/shots"))["shots"]
    assert len(shots) == 1
    assert shots[0]["providerJob"] == "task-v1" and shots[0]["status"] == "redraw"


def test_video_tool_blocked_until_assets_have_images(api, monkeypatch):
    """硬闸：没出过设定图的项目，视频工具必须拒绝，并且不真的提交任务。"""
    api.post("/api/projects", json={"name": "B"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://x.test"}}},
    )
    api.post("/api/assets", json={"name": "还没出图的角色", "type": "角色"})
    submitted = {"n": 0}

    def fake_submit(prompt, dur, **kw):
        submitted["n"] += 1
        return "task-should-not-exist"

    monkeypatch.setattr("vagent.providers.video.submit", fake_submit)

    from vagent.api.llm import _fixed_assets_ready, _video_tool

    gate = _fixed_assets_ready(api.data(api.get("/api/projects"))["projects"][0]["id"])
    assert gate["ok"] is False and "还没有设定图" in gate["reason"]

    out = _video_tool({"prompt": "雨夜街头", "name": "偷跑", "dur": 4})
    assert out["ok"] is False and "先为这个项目生成角色三视图" in out["error"]
    assert submitted["n"] == 0
    assert api.data(api.get("/api/shots"))["shots"] == []


def test_export_chat_markdown(api, client):
    api.post("/api/projects", json={"name": "A"})
    api.post("/api/messages", json={"role": "user", "text": "你好"})
    api.post("/api/messages", json={"role": "agent", "text": "你好呀"})
    res = client.get("/api/export/chat.md")
    assert res.status_code == 200
    assert "text/markdown" in res.headers["Content-Type"]
    body = res.get_data(as_text=True)
    assert "## 我" in body and "你好" in body
    assert "## 主 Agent" in body and "你好呀" in body


def test_api_usage_counts_calls(api):
    from vagent.db import record_api_call

    record_api_call("img", "test-img")
    record_api_call("llm", "test-llm")
    boot = api.data(api.get("/api/bootstrap"))
    usage = boot["apiUsage"]
    assert usage["groups"]["img"]["calls"] == 1
    assert usage["groups"]["llm"]["calls"] == 1
    assert usage["total"] == 2
    assert usage["recent"][0]["provider"] == "llm"
    assert boot["account"] == {}


# ---------------------------------------------------------------- C · 首帧生视频（追加）
def test_shot_keyframe_get_and_generate(api):
    api.post("/api/projects", json={"name": "A"})
    sid = api.data(api.post("/api/shots", json={"name": "镜头", "dur": 3.0, "prompt": "跳舞"}))["shot"]["id"]

    d = api.data(api.get(f"/api/shots/{sid}/keyframe"))
    assert d["exists"] is False and d["url"] == "" and d["confirmed"] is False
    assert api.post(f"/api/shots/{sid}/keyframe", json={"confirm": True}).status_code == 400

    d = api.data(api.post(f"/api/shots/{sid}/keyframe", json={}))
    assert d["exists"] is True and d["url"].startswith("/uploads/gen/shots/")
    assert d["confirmed"] is False
    d = api.data(api.post(f"/api/shots/{sid}/keyframe", json={"confirm": True}))
    assert d["confirmed"] is True
    assert api.data(api.get(f"/api/shots/{sid}/keyframe"))["confirmed"] is True

    # 重抽会清掉确认，必须重新确认
    d = api.data(api.post(f"/api/shots/{sid}/keyframe", json={"force": True}))
    assert d["exists"] is True and d["confirmed"] is False
    assert api.get("/api/shots/zzz/keyframe").status_code == 404


def test_shot_first_frame_confirmation_invalidated_by_prompt(api):
    api.post("/api/projects", json={"name": "A"})
    sid = api.data(api.post("/api/shots", json={"name": "镜头", "dur": 3.0, "prompt": "雨夜街道"}))["shot"][
        "id"
    ]
    api.post(f"/api/shots/{sid}/keyframe", json={})
    api.post(f"/api/shots/{sid}/keyframe", json={"confirm": True})
    assert api.data(api.get(f"/api/shots/{sid}/keyframe"))["confirmed"] is True
    api.patch(f"/api/shots/{sid}", json={"prompt": "白天街道"})
    assert api.data(api.get(f"/api/shots/{sid}/keyframe"))["confirmed"] is False


def test_shot_video_submit_passes_first_frame(api, monkeypatch):
    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"video": {"api_key": "mm-test", "base_url": "https://service.test/v1"}}},
    )
    sid = api.data(api.post("/api/shots", json={"name": "镜头", "dur": 3.0, "prompt": "跳舞"}))["shot"]["id"]
    assert api.post(f"/api/shots/{sid}/video", json={}).status_code == 400
    assert api.data(api.post(f"/api/shots/{sid}/keyframe", json={}))["confirmed"] is False
    assert api.post(f"/api/shots/{sid}/video", json={}).status_code == 400
    api.post(f"/api/shots/{sid}/keyframe", json={"confirm": True})
    seen = {}

    def fake_submit(prompt, duration, **kwargs):
        seen["prompt"] = prompt
        seen["duration"] = duration
        seen["first_frame"] = kwargs.get("first_frame", "")
        return "task-2"

    monkeypatch.setattr("vagent.providers.video.submit", fake_submit)
    d = api.data(api.post(f"/api/shots/{sid}/video", json={}))
    assert d["taskId"] == "task-2"
    assert seen["first_frame"].startswith("data:image/")
    assert seen["duration"] == 3.0
    assert d["firstFrame"].startswith("/uploads/gen/shots/")


def test_video_asset_context_uses_llm_before_clarify(api, monkeypatch):
    import json as jsonlib

    api.post("/api/projects", json={"name": "A"})
    api.put(
        "/api/settings/api",
        json={"api": {"llm": {"api_key": "sk-test", "base_url": "https://service.test/v1"}}},
    )
    seen = {}

    def fake_completion(messages, **kwargs):
        seen["tools"] = kwargs.get("tools") or []
        return {
            "choices": [
                {
                    "message": {
                        "content": jsonlib.dumps(
                            {
                                "summary": "先确认角色、场景和风格，再生成日常视频。",
                                "assets": [
                                    {"name": "红发女孩", "type": "角色", "desc": "红发，白衣，温柔"},
                                    {"name": "城市街道", "type": "场景", "desc": "白天的城市街道"},
                                ],
                                "shots": [],
                                "clarify": {"needed": False, "questions": []},
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr("vagent.llm._completion", fake_completion)
    d = api.data(api.post("/api/llm/plan", json={"text": "以她为主角，我想要一段关于她日常生活的视频"}))
    names = [tool["function"]["name"] for tool in seen["tools"]]
    assert "generate_video" not in names and "generate_image" not in names
    assert d["plan"]["questions"]
    assets = api.data(api.get("/api/assets?scope=all"))["assets"]
    assert {asset["name"] for asset in assets} == {"红发女孩", "城市街道"}
    assert all(asset["desc"] for asset in assets)
