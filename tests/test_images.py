# -*- coding: utf-8 -*-
"""图片能力层的单元测试：不联网、不花钱、不碰真数据库。"""

import hashlib
import json
import struct
import subprocess
from pathlib import Path

import pytest

from vagent import config
from vagent.images import frames as frames_mod
from vagent.images import prompts, runner
from vagent.images import read_views, run
from vagent.images.ark import ArkError, ArkImage, parse_size, parse_verdict
from vagent.images.mock import VIEWS, render_views, write_png


@pytest.fixture
def out_dir(tmp_path, monkeypatch):
    """把模块级状态锁在 mock + 临时目录。

    monkeypatch 会记住改动前的值（包括「原来没有」的情况）并在测试结束后还原，
    断言失败也照样还原——手写 try/finally 很容易漏。
    """
    monkeypatch.setitem(runner._STATE, "mode", "mock")
    monkeypatch.setitem(runner._STATE, "api_key", "")
    monkeypatch.setitem(runner._STATE, "out_dir", tmp_path)
    monkeypatch.setattr(runner, "_CLIENTS", {"image": None, "vision": None})
    return tmp_path


def _digest(path):
    return hashlib.sha1(path.read_bytes()).hexdigest()


def test_write_png_header(tmp_path):
    path = write_png(tmp_path / "x.png", 8, 4, bytes(8 * 4 * 3))

    raw = path.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert raw[12:16] == b"IHDR"
    width, height = struct.unpack(">II", raw[16:24])
    assert (width, height) == (8, 4)
    assert raw[24] == 8  # 位深
    assert raw[25] == 2  # 颜色类型：真彩色 RGB


def test_write_png_rejects_wrong_pixel_count(tmp_path):
    with pytest.raises(ValueError):
        write_png(tmp_path / "x.png", 8, 4, bytes(10))


def test_render_views_three_distinct_files(out_dir):
    paths = render_views("a1", out_dir, size=64)

    assert [p.name for p in paths] == ["a1-front.png", "a1-side.png", "a1-back.png"]
    assert len({_digest(p) for p in paths}) == 3


def test_render_views_is_deterministic(tmp_path):
    first = render_views("a1", tmp_path / "one", size=64)
    second = render_views("a1", tmp_path / "two", size=64)

    assert [_digest(p) for p in first] == [_digest(p) for p in second]


def test_render_views_differs_by_asset(tmp_path):
    one = render_views("a1", tmp_path / "one", size=64)
    other = render_views("a2", tmp_path / "two", size=64)

    assert _digest(one[0]) != _digest(other[0])


def test_run_asset_views(out_dir):
    got = run(
        {
            "kind": "keyframe",
            "payload": {"task": "asset_views", "asset_id": "a9", "name": "小林", "desc": "短发，藏青夹克"},
        }
    )

    assert got["task"] == "asset_views"
    assert got["asset_id"] == "a9"
    assert [item["view"] for item in got["views"]] == list(VIEWS)
    for item in got["views"]:
        assert item["bytes"] > 0
        assert Path(item["path"]).exists()
        # 资产图存在资产自己的固定目录里，不是某次任务的临时产物
        assert Path(item["path"]).parent == out_dir / "assets" / "a9"


def test_asset_views_survive_rerun(out_dir):
    first = run({"kind": "keyframe", "payload": {"task": "asset_views", "asset_id": "a1"}})
    second = run({"kind": "keyframe", "payload": {"task": "asset_views", "asset_id": "a1"}})

    # 重跑覆盖同一批文件，不会越积越多
    assert [item["path"] for item in first["views"]] == [item["path"] for item in second["views"]]
    assert len(list((out_dir / "assets" / "a1").iterdir())) == len(VIEWS)


def test_read_views_roundtrip(out_dir):
    assert read_views("never-generated") == []

    run({"kind": "keyframe", "payload": {"task": "asset_views", "asset_id": "a5"}})
    saved = read_views("a5")

    assert [item["view"] for item in saved] == list(VIEWS)
    assert all(Path(item["path"]).exists() for item in saved)


def test_asset_views_and_keyframe_do_not_mix(out_dir):
    views = run({"kind": "keyframe", "payload": {"task": "asset_views", "asset_id": "a3"}})
    frame = run({"kind": "keyframe", "payload": {"shot_id": "s3", "prompt": "推门"}})

    # 三视图是资产级产物；首帧才是镜头级、才对应 KeyframeResult
    assert "views" in views and "first_frame" not in views
    assert "first_frame" in frame and "views" not in frame
    assert Path(frame["first_frame"]).parent == out_dir / "shots"


def test_run_keyframe_without_task_field(out_dir):
    got = run({"kind": "keyframe", "payload": {"shot_id": "s1", "prompt": "推门"}})

    assert got["task"] == "keyframe"
    assert got["shot_id"] == "s1"
    assert got["first_frame"].endswith("s1-first.png")


def test_run_asset_views_requires_asset_id(out_dir):
    with pytest.raises(ValueError):
        run({"kind": "keyframe", "payload": {"task": "asset_views"}})


def test_run_unknown_task(out_dir):
    with pytest.raises(ValueError):
        run({"kind": "keyframe", "payload": {"task": "nope"}})


def test_url_maps_into_uploads(out_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path)
    runner.configure(out_dir=tmp_path / "gen")

    got = run({"kind": "keyframe", "payload": {"shot_id": "u9", "prompt": "测试"}})

    assert got["url"] == "/uploads/gen/shots/u9-first.png"
    assert (tmp_path / "gen" / "shots" / "u9-first.png").exists()


def test_output_outside_uploads_has_no_url(out_dir):
    got = run({"kind": "keyframe", "payload": {"shot_id": "z1", "prompt": "测试"}})

    assert got["url"] == ""


def test_parse_verdict_plain_json():
    assert parse_verdict('{"pass": true, "issues": []}') == {"pass": True, "issues": []}


def test_parse_verdict_strips_code_fence():
    text = '```json\n{"pass": false, "issues": ["衣服颜色不一致"]}\n```'
    assert parse_verdict(text) == {"pass": False, "issues": ["衣服颜色不一致"]}


def test_parse_verdict_garbage_fails_closed():
    got = parse_verdict("我觉得还行")

    assert got["pass"] is False
    assert got["issues"]


def test_parse_size():
    assert parse_size("2560x1440") == (2560, 1440)
    with pytest.raises(ValueError):
        parse_size("1080p")


def test_size_guard_fires_before_network():
    # 尺寸太小时必须在本地就拦住，不能先发请求再报错（那会白花钱）
    with pytest.raises(ValueError):
        ArkImage("fake-key", "fake-model").generate("x", size="1024x1024")


def test_configure_rejects_unknown_mode(out_dir):
    with pytest.raises(ValueError):
        runner.configure(mode="production")


def test_run_asset_image_single_concept(out_dir):
    got = run(
        {
            "kind": "keyframe",
            "payload": {"task": "asset_image", "asset_id": "a7", "type": "场景", "desc": "雨夜街道"},
        }
    )

    assert got["task"] == "asset_image"
    assert [item["view"] for item in got["views"]] == ["concept"]
    assert Path(got["views"][0]["path"]).parent == out_dir / "assets" / "a7"
    assert got["views"][0]["bytes"] > 0


def test_verify_mock_chain(out_dir, tmp_path):
    try:
        ffmpeg = frames_mod._tool("ffmpeg")
    except FileNotFoundError:
        pytest.skip("没有装 ffmpeg")

    clip = tmp_path / "clip.mp4"
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
            str(clip),
        ],
        check=True,
    )

    got = run({"kind": "keyframe", "payload": {"task": "verify", "clip": str(clip), "prefix": "v"}})

    assert got["task"] == "verify"
    assert got["pass"] is True
    assert len(got["frames"]) == 3


# ---------- 三视图的提示词：画风 / 每张必须一致 / 背面清单 ----------

_DNA = {
    "style": "二次元赛璐璐上色，细黑描边",
    "identity": "红发恶魔少女",
    "face": "红色长发，左眼金色右眼紫色",
    "outfit": "白色短裙，腰侧红宝石腰饰",
    "persistent": ["白色半透明龙翼", "红色长发"],
    "front_only": ["胸前菱形红宝石"],
    "back_render": ["龙翼从背后看得到完整翼膜", "胸前的红宝石不可见"],
}


def test_parse_dna_strips_code_fence():
    text = '好的，清单如下：\n```json\n{"style": "赛璐璐", "persistent": ["龙翼"]}\n```\n以上。'

    dna = prompts.parse_dna(text)

    assert dna["style"] == "赛璐璐"
    assert dna["persistent"] == ["龙翼"]
    assert dna["front_only"] == []  # 缺的键补成空表，模板里好判断


def test_parse_dna_rejects_garbage():
    assert prompts.parse_dna("我不知道该怎么写") is None
    assert prompts.parse_dna("{不是合法 json}") is None
    assert prompts.parse_dna('{"foo": 1}') is None  # 没有画风和设定，等于没答


def test_fallback_dna_keeps_description():
    dna = prompts.fallback_dna("小林", "角色", "黑色短发，藏青工装夹克")

    assert "小林" in dna["identity"]
    assert dna["persistent"] == ["黑色短发，藏青工装夹克"]
    assert dna["back_render"] == []


def test_three_view_front_locks_style_and_persistent():
    text = prompts.three_view("阿露", "角色", "", "front", dna=_DNA)

    assert "【画风】二次元赛璐璐上色" in text
    assert "不允许转成真人照片" in text  # 动漫被画成真人的那条锁
    assert "【每一张都必须完全一致】" in text
    assert "白色半透明龙翼" in text  # 翅膀被画成黑蝙蝠翼的那条锁
    assert "【这一视角必须看得见】" in text


def test_three_view_back_uses_back_render_and_forbids_front_only():
    text = prompts.three_view("阿露", "角色", "", "back", dna=_DNA)

    assert "【背面必须这样画】" in text
    assert "龙翼从背后看得到完整翼膜" in text
    assert "【禁止】后背不得出现：胸前菱形红宝石" in text
    # 背面不能把正面的五官再写一遍，否则模型照着画回来
    assert "左眼金色右眼紫色" not in text


def test_three_view_side_does_not_hard_require_ninety_degrees():
    text = prompts.three_view("阿露", "角色", "", "side", dna=_DNA)

    assert "侧身站立" in text
    assert "90" not in text  # 侧视角不做硬性 90° 要求


def test_three_view_without_dna_matches_legacy_shape():
    text = prompts.three_view("小林", "角色", "蓝色夹克", "front")

    assert text.startswith("【设定】")
    assert "【画风】" not in text


# ---------- 设定稿：附属结构 / 对称 / 背景明度 / 体检 ----------

_SHEET_DNA = {
    "style": "二次元赛璐璐上色",
    "identity": "红发恶魔少女，偏瘦，七头身",
    "face": "左眼金色右眼紫色",
    "hair": "红色长发及腰，发尾外卷",
    "outfit": "白色短裙，腰侧红宝石腰饰",
    "subject_tone": "浅色",
    "silhouette": ["白色半透明龙翼：从背部肩胛伸出，展开宽度约两个身宽，静止时向后下方张开"],
    "asymmetry": ["右手腕：一条细银链"],
    "persistent": ["白色半透明龙翼", "红色长发"],
    "front_only": ["胸前菱形红宝石"],
    "back_render": ["龙翼从背后看得到完整翼膜", "胸前的红宝石不可见"],
    "absent": ["第二套衣服", "参考图之外的武器"],
}


def test_sheet_hard_rules_cover_crop_and_symmetry():
    text = prompts.three_view_sheet("阿露", "角色", "", dna=_SHEET_DNA)

    # 硬句 A：附属结构不许被挡、被裁
    assert "【完整入画】" in text and "不得被画框裁切" in text
    # 硬句 B：成对结构必须对称
    assert "【对称】" in text and "末端高度一致" in text
    assert "白色半透明龙翼：从背部肩胛伸出" in text
    assert "右手腕：一条细银链" in text  # 左右不对称项也走同一段


def test_sheet_background_follows_subject_tone():
    light = prompts.three_view_sheet("阿露", "角色", "", dna=_SHEET_DNA)
    assert "背景是干净的中灰纯色" in light  # 白翼 + 白底 = 消失，所以浅色主体用中灰

    dark = prompts.three_view_sheet("阿露", "角色", "", dna=dict(_SHEET_DNA, subject_tone="深色"))
    assert "背景是干净的浅灰纯色" in dark

    unknown = prompts.three_view_sheet("阿露", "角色", "", dna=dict(_SHEET_DNA, subject_tone=""))
    assert "背景是干净的浅灰纯色" in unknown


def test_sheet_back_panel_forbids_front_only_and_absent():
    text = prompts.three_view_sheet("阿露", "角色", "", dna=_SHEET_DNA)

    assert "【第 4 格必须这样画】" in text
    assert "【禁止】第 4 格不得出现：胸前菱形红宝石" in text
    assert "【禁止】任何一格都不得出现：第二套衣服" in text


def test_sheet_without_dna_still_has_layout_and_background():
    text = prompts.three_view_sheet("小林", "角色", "蓝色夹克")

    assert "【版面】" in text and "第 4 格" in text
    assert "背景是干净的浅灰纯色" in text


def test_parse_dna_keeps_new_fields():
    payload = json.dumps(_SHEET_DNA, ensure_ascii=False)

    dna = prompts.parse_dna("```json\n" + payload + "\n```")

    assert dna["subject_tone"] == "浅色"
    assert dna["silhouette"][0].startswith("白色半透明龙翼")


class _FakeImage:
    """记录每次出图收到的提示词和参考图，不联网。"""

    def __init__(self):
        self.calls = []

    def save(self, prompt, path, ref_images=None, size=None, seed=None):
        self.calls.append({"prompt": prompt, "ref_images": list(ref_images or []), "size": size})
        Path(path).with_suffix(".png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
        return {"path": str(Path(path).with_suffix(".png")), "bytes": 24, "usage": {"generated_images": 1}}


class _FakeVision:
    def __init__(self, answer=""):
        self.answer = answer
        self.calls = []

    def ask(self, image_paths, prompt):
        self.calls.append({"images": list(image_paths), "prompt": prompt})
        return self.answer


def test_asset_views_live_uses_dna_and_only_user_reference(out_dir, monkeypatch, tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)

    image = _FakeImage()
    vision = _FakeVision(json.dumps(_DNA, ensure_ascii=False))
    monkeypatch.setitem(runner._STATE, "mode", "live")
    monkeypatch.setattr(runner, "_CLIENTS", {"image": image, "vision": vision})

    got = run(
        {
            "kind": "keyframe",
            "payload": {"task": "asset_views", "asset_id": "a9", "name": "阿露", "ref_images": [str(ref)]},
        }
    )

    assert [item["view"] for item in got["views"]] == ["sheet"]
    assert len(vision.calls) == 2  # 一次读设定清单，一次做体检
    assert len(image.calls) == 1  # 四格画在一张图里
    # 只挂用户原图，不挂上一张
    assert image.calls[0]["ref_images"] == [str(ref)]
    prompt = image.calls[0]["prompt"]
    assert "【画风】" in prompt and "【第 4 格必须这样画】" in prompt and "四格等高" in prompt
    # 第 4 格必须写明「看不到脸」，这是背面不再等于正面的关键
    assert "看不到脸" in prompt
    assert (out_dir / "assets" / "a9" / "dna.json").exists()


def test_asset_views_live_falls_back_when_vision_fails(out_dir, monkeypatch, tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)

    image = _FakeImage()
    vision = _FakeVision("抱歉，我无法回答")
    monkeypatch.setitem(runner._STATE, "mode", "live")
    monkeypatch.setattr(runner, "_CLIENTS", {"image": image, "vision": vision})

    got = run(
        {
            "kind": "keyframe",
            "payload": {
                "task": "asset_views",
                "asset_id": "a9",
                "name": "阿露",
                "desc": "红发少女",
                "ref_images": [str(ref)],
            },
        }
    )

    assert len(got["views"]) == 1  # 清单解析失败也要出图
    assert "红发少女" in image.calls[0]["prompt"]


def test_soften_dna_replaces_body_words_and_keeps_original():
    dna = dict(_DNA, back_render=["从背面可见露肩设计的后背裸露区域"])

    soft = prompts.soften_dna(dna)

    assert "裸露" not in soft["back_render"][0] and "无遮挡" in soft["back_render"][0]
    assert "露肩" not in soft["back_render"][0]
    assert dna["back_render"][0].startswith("从背面可见露肩")  # 原清单不被就地改掉


class _ModerationImage(_FakeImage):
    """带敏感词的请求会被「审核」拦下，其余照常出图。"""

    def __init__(self):
        super().__init__()
        self.blocked = 0

    def save(self, prompt, path, ref_images=None, size=None, seed=None):
        if "裸露" in prompt:
            self.blocked += 1
            raise ArkError('HTTP 400: {"error":{"code":"InputTextSensitiveContentDetected"}}')
        return super().save(prompt, path, ref_images=ref_images, size=size)


def test_asset_views_retries_with_softened_prompt_after_moderation(out_dir, monkeypatch, tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)

    image = _ModerationImage()
    vision = _FakeVision(json.dumps(dict(_DNA, back_render=["后背裸露区域"]), ensure_ascii=False))
    monkeypatch.setitem(runner._STATE, "mode", "live")
    monkeypatch.setattr(runner, "_CLIENTS", {"image": image, "vision": vision})

    got = run(
        {
            "kind": "keyframe",
            "payload": {"task": "asset_views", "asset_id": "a9", "name": "阿露", "ref_images": [str(ref)]},
        }
    )

    assert image.blocked == 1  # 设定稿被拦一次后降级重试
    assert len(got["views"]) == 1
    assert "裸露" not in image.calls[-1]["prompt"]


def test_audit_sheet_reports_gaps(monkeypatch, tmp_path):
    sheet = tmp_path / "sheet.png"
    sheet.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)

    class _Vision:
        def ask(self, images, prompt):
            assert len(images) == 2  # 原图 + 设定稿
            assert "设定清单" in prompt
            return '{"pass": false, "issues": ["左翼尖出画", "两翼高度差约一个头"]}'

    monkeypatch.setitem(runner._STATE, "mode", "live")
    monkeypatch.setattr(runner, "_CLIENTS", {"image": _FakeImage(), "vision": _Vision()})

    got = runner.audit_sheet(sheet, tmp_path / "ref.png", _SHEET_DNA)

    assert got["pass"] is False
    assert got["gaps"] == ["左翼尖出画", "两翼高度差约一个头"]


def test_audit_sheet_never_raises(monkeypatch, tmp_path):
    sheet = tmp_path / "sheet.png"
    sheet.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)

    class _Boom:
        def ask(self, images, prompt):
            raise RuntimeError("网络断了")

    monkeypatch.setitem(runner._STATE, "mode", "live")
    monkeypatch.setattr(runner, "_CLIENTS", {"image": _FakeImage(), "vision": _Boom()})

    got = runner.audit_sheet(sheet, None, _SHEET_DNA)

    assert got["pass"] is None and "网络断了" in got["error"]


def test_asset_views_does_not_swallow_other_errors(out_dir, monkeypatch, tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)

    class _Boom(_FakeImage):
        def save(self, prompt, path, ref_images=None, size=None, seed=None):
            raise ArkError("HTTP 400: image size must be at least 3686400 pixels")

    monkeypatch.setitem(runner._STATE, "mode", "live")
    monkeypatch.setattr(runner, "_CLIENTS", {"image": _Boom(), "vision": _FakeVision("{}")})

    with pytest.raises(ArkError):
        run(
            {
                "kind": "keyframe",
                "payload": {"task": "asset_views", "asset_id": "a9", "ref_images": [str(ref)]},
            }
        )
