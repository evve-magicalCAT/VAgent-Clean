# -*- coding: utf-8 -*-
"""语言模型接入层：OpenAI 兼容的 Chat Completions 客户端。

只依赖标准库（urllib），不新增第三方包；密钥只从本地设置表读取。
所有外部失败都收敛成 LLMError，由 api/llm.py 统一转成 fail()，
错误码只使用 README 4.2 允许的取值。
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import config, images
from .db import load_settings, record_api_call
from .skills import rui_skill
from .providers import image as image_provider

DEFAULT_MODEL = "doubao-seed-2-1-lite-260915"
CHAT_HISTORY_LIMIT = 12
DEFAULT_TIMEOUT = 60

ASSET_TYPES = ("角色", "场景", "风格", "其他")
CLARIFY_SLOTS = ("subject", "scene", "action", "duration", "style")
CLARIFY_MAX = 2

IMAGE_HINTS = (
    "图片",
    "照片",
    "图像",
    "海报",
    "封面",
    "头像",
    "立绘",
    "插画",
    "设定图",
    "三视图",
    "参考图",
    "概念图",
    "画一张",
    "出图",
    "生图",
)
VIDEO_HINTS = ("视频", "短片", "影片", "成片", "动起来", "视频生成")
_NEG_IMAGE = re.compile(r"(不想要|不要|不用|不需要|别)(生成|做|画|出|来)?[^，。；\n]{0,8}(图片|照片|图像)")
_NEG_VIDEO = re.compile(r"(不想要|不要|不用|不需要|别)(生成|做|出|来)?[^，。；\n]{0,8}(视频|短片|影片)")


def detect_generation_need(text: str) -> dict:
    """判断这句话是否真的需要生成图片/视频；没有对应需求就不给对应工具。"""
    t = (text or "").strip()
    low = t.lower()
    image = any(word in t for word in IMAGE_HINTS) or any(
        word in low for word in ("image", "photo", "picture", "poster", "illustration")
    )
    video = any(word in t for word in VIDEO_HINTS) or any(word in low for word in ("video", "clip"))
    if _NEG_IMAGE.search(t):
        image = False
    if _NEG_VIDEO.search(t):
        video = False
    return {"image": bool(image), "video": bool(video)}


SYSTEM_PROMPT = """你是 Vagent 的主 Agent（A），负责和用户聊天、理解需求、规划分镜，需要时调用出图工具。
默认像聊天一样用简体中文自然地回答，简短直接，不要每句话都套模板。

当用户要你规划镜头、分镜或短片时，只输出一个 JSON 对象，不要解释、不要 Markdown 代码块。结构：
{
  "summary": "一句话概括你理解的画面（不超过 60 字）",
  "clarify": {
    "needed": true,
    "missing": ["subject|scene|action|duration|style"],
    "questions": [{"slot": "duration", "text": "需要用户确认的问题", "options": ["选项1", "选项2"]}]
  },
  "assets": [{"name": "设定名", "type": "角色|场景|风格|其他", "desc": "可复用的外观/场景描述", "locked": true}],
  "shots": [{"name": "镜头名", "prompt": "完整画面提示词，写明主体、动作、环境、光线、镜头语言", "dur": 3.0, "camera": "机位或运镜，可空"}]
}

规划规则：
1. shots 至少 1 个、最多 6 个；单镜 dur 在 0.5 到 10 秒之间。
2. assets 只放值得跨镜头复用的稳定设定（同一角色、同一场景、统一风格），最多 6 个。
3. 规划前先判断信息够不够：只有主体、场景、动作意图属于必要项。
4. 时长和风格一律不要追问，直接按默认值写进计划（时长 4 秒、风格冷调电影感），并填进 shots。
5. 上下文里已有的锁定设定直接复用，不要重复问。
6. 用户已经说过「你决定 / 随便」的槽位不再追问；同一个问题不要重复问。
7. clarify.questions 最多 2 个、只能围绕主体 / 场景 / 动作，每个必须带 2~3 个选项；
   不需要追问时 needed=false、questions=[]。
8. 聊天、出图请求不需要 clarify，只有规划分镜时才判断。

图片规则：
8. 用户明确要图片、照片、海报、头像、立绘、设定图或人物/场景形象时，必须先调用 generate_image 工具真正把图生成出来，
   可以有多次调用；工具返回后再根据情况回复或输出 JSON 计划，已生成的设定不要重复放进 assets。
   如果用户上传了参考图，描述要严格围绕参考图里的主体，保持长相、服装、配色一致。

视频规则：
9. 用户明确要视频、成片、让镜头动起来时，调用 generate_video 工具创建镜头并提交任务；
   提交后告诉用户去「视频」页查看生成进度。

三视图与资产规则：
10. 用户要求三视图、参考图、多角度设定图时，调用 generate_three_view_drawing（不要用 generate_image），
    并把从参考图里看到的外观细节写进 desc；没有上传参考图时先请用户上传。
11. 用户提到“这个角色/场景”并要视频时，先对照当前项目资产列表判断是否已有对应资产：
    - 已有：先说明找到的资产，并问“要不要先为它生成/更新三视图设定？”；用户确认后才调用三视图工具，
      然后再继续视频。一次只做一步，不要同时出三视图和视频。
    - 没有：先追问外观、服装、配色、风格等细节，不要直接生成视频或资产。
12. 三视图工具必须等用户明确确认后再调用；未确认不要自行生成。
12.1 【硬规则·不可绕过】固定资产优先：任何视频生成之前，这个项目必须已经有角色三视图
    和场景设定图（系统会在调用 generate_video 时直接拦截并返回错误）。被拦截时不要反复重试，
    也不要换个说法再调一次；直接告诉用户先出资产，并调用 generate_assets 或
    generate_three_view_drawing 把资产补上，用户确认后再回到视频。
13. 用户通过三项确认模块补充后，系统会先把用户提供的文字/图片转存为资产；
    “由你自动补全”的项要结合这些资产和上文补全，并调用出图工具生成结果返回，不要再追问。
14. 用户要做真人剧 / 3D 漫剧分镜、人物三视图或站位图时，先调用 use_rui_skills 读取工作流，
    再按工作流输出；该技能为非商业许可，商用前需确认授权。
15. 上一轮如果你问过是否生成三视图/设定图，用户回复“开工 / 确认 / 可以 / 好 / 开始”等短确认时，
    视为已确认：有参考图就直接调用 generate_three_view_drawing，没有参考图就调用 generate_image；
    不要只输出提示词，也不要声称“未接入出图工具”。
16. 图片/视频模型返回鉴权失败或“未开通”时，明确告诉用户具体是哪个模型、需要去火山方舟控制台开通
    或在「API 设置」里更换模型；不要只说“服务失败”，也不要要求用户给应用授权（应用无法代为授权）。
17. 用户回复“确认 / 好 / 开工”或点击“确认修改资产/镜头”按钮时，只执行对应的修改：
    资产 → 调用 generate_image/三视图（同名资产会更新描述与预览）；
    镜头 → 调用 update_shot_prompt。绝不要提交视频。
19. 用户明确说“不要改资产/角色，改镜头”或“改镜头提示词”时，禁止调用 propose_asset_change/update_asset，
    也不要输出资产变更方案；改为调用 update_shot_prompt 修改镜头提示词。
20. 修改对象不明确，或用户在资产、镜头、整片之间切换时，先调用 judge_modify_target 判断 target；
    再按 target 选择资产工具、update_shot_prompt 或视频工具，不要靠猜。
18. 用户对已有角色/场景的外观提出调整（加长、缩短、换色、加部件、改比例等）时，
    先调用 propose_asset_change 给出详细变更方案（name 用资产名，desc 直接写改版后的完整外观，
    具体到形状/比例/材质，不要写“保留/沿用上一版”等字样），不要立刻生成图片；
    等用户点“就这样生成”后再出图。
    只有用户明确要求直接覆盖时，才调用 update_asset。没有调用工具时不要声称已经生成。

其他情况（打招呼、闲聊、提问、对方案的修改意见）直接用自然语言回答，不要输出 JSON。"""


class LLMError(RuntimeError):
    """带错误码与 HTTP 状态的外部调用失败。"""

    def __init__(self, code: str, message: str, status: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def resolve_config() -> dict:
    """从设置表取当前语言模型配置，缺省值保证空配置也能给出可读错误。"""
    cfg = load_settings().get("llm") or {}
    base = (cfg.get("base_url") or "").strip()
    base = base.rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return {
        "base_url": base,
        "model": (cfg.get("model") or "").strip() or DEFAULT_MODEL,
        "api_key": (cfg.get("api_key") or "").strip(),
    }


def is_configured(cfg: dict | None = None) -> bool:
    cfg = cfg or resolve_config()
    return bool(cfg["api_key"])


def _http_message(detail: str) -> str:
    try:
        body = json.loads(detail)
    except ValueError:
        body = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:300]
        if isinstance(err, str) and err:
            return err[:300]
        if body.get("message"):
            return str(body["message"])[:300]
    return (detail or "").strip()[:300] or "未知错误"


def _post_json(url: str, payload: dict, api_key: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace") if err.fp else ""
        message = _http_message(detail)
        if err.code in (401, 403):
            raise LLMError("BAD_REQUEST", f"语言模型鉴权失败：{message}", 400) from None
        if err.code == 429:
            raise LLMError("INTERNAL_ERROR", f"语言模型限流，请稍后再试：{message}", 500) from None
        raise LLMError("INTERNAL_ERROR", f"语言模型返回 HTTP {err.code}：{message}", 500) from None
    except urllib.error.URLError as err:
        raise LLMError("INTERNAL_ERROR", f"无法连接语言模型服务：{err.reason}", 500) from None
    except TimeoutError:
        raise LLMError("INTERNAL_ERROR", "语言模型请求超时", 500) from None
    try:
        return json.loads(raw)
    except ValueError:
        raise LLMError("INTERNAL_ERROR", "语言模型返回了非 JSON 响应", 500) from None


def _completion(
    messages: list,
    *,
    cfg: dict | None = None,
    tools: list | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    temperature=0.4,
    tool_choice=None,
) -> dict:
    """一次 Chat Completions 调用，返回原始响应体（工具调用场景需要 message 本体）。"""
    cfg = cfg or resolve_config()
    if not cfg["api_key"]:
        raise LLMError("BAD_REQUEST", "还没有配置语言模型 API Key", 400)
    if not cfg["base_url"]:
        raise LLMError("BAD_REQUEST", "请在 API 设置中填写语言模型 Base URL", 400)
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
    body = _post_json(cfg["base_url"] + "/chat/completions", payload, cfg["api_key"], timeout)
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMError("INTERNAL_ERROR", "语言模型没有返回任何内容", 500)
    record_api_call("llm", cfg["model"])
    return body


def chat(messages: list, *, cfg: dict | None = None, timeout: int = DEFAULT_TIMEOUT, temperature=0.4) -> str:
    """一次 Chat Completions 调用，返回首条消息的文本。"""
    body = _completion(messages, cfg=cfg, timeout=timeout, temperature=temperature)
    message = body["choices"][0].get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMError("INTERNAL_ERROR", "语言模型返回了空内容", 500)
    return content.strip()


def _extract_json(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    start, end = s.find("{"), s.rfind("}")
    if start == -1 or end <= start:
        raise LLMError("INTERNAL_ERROR", "语言模型没有返回 JSON", 500)
    try:
        data = json.loads(s[start : end + 1])
    except ValueError:
        raise LLMError("INTERNAL_ERROR", "语言模型返回的 JSON 无法解析", 500) from None
    if not isinstance(data, dict):
        raise LLMError("INTERNAL_ERROR", "语言模型返回的 JSON 不是对象", 500)
    return data


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def normalize_plan(data) -> dict:
    """把模型输出收敛成 ShotPlan 形状，越界值一律夹到安全范围。"""
    if not isinstance(data, dict):
        raise LLMError("INTERNAL_ERROR", "语言模型返回的分镜不是对象", 500)
    summary = str(data.get("summary") or "").strip()[:200]

    assets = []
    for item in _as_list(data.get("assets"))[:6]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:30]
        if not name:
            continue
        asset_type = str(item.get("type") or "其他").strip()
        if asset_type not in ASSET_TYPES:
            asset_type = "其他"
        assets.append(
            {
                "name": name,
                "type": asset_type,
                "desc": str(item.get("desc") or "").strip()[:500],
                "locked": bool(item.get("locked", True)),
            }
        )

    shots = []
    for i, item in enumerate(_as_list(data.get("shots"))[:6]):
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or "").strip()[:800]
        if not prompt:
            continue
        try:
            dur = round(float(item.get("dur") or 3.0), 2)
        except (TypeError, ValueError):
            dur = 3.0
        shots.append(
            {
                "name": str(item.get("name") or f"镜头 {i + 1}").strip()[:30],
                "prompt": prompt,
                "dur": min(10.0, max(0.5, dur)),
                "camera": str(item.get("camera") or "").strip()[:40],
            }
        )

    clarify_in = data.get("clarify") if isinstance(data.get("clarify"), dict) else {}
    questions = _clarify_questions(clarify_in.get("questions")) or _clarify_questions(data.get("questions"))
    missing = []
    for slot in _as_list(clarify_in.get("missing")):
        slot = str(slot).strip()
        if slot in CLARIFY_SLOTS and slot not in missing:
            missing.append(slot)
    # 有具体问题才算需要追问；模型只标 needed 但没给问题时不打扰用户
    needed = bool(questions)

    return {
        "version": 1,
        "summary": summary,
        "assets": assets,
        "shots": shots,
        "questions": questions,
        "clarify": {"needed": needed, "missing": missing[:3], "questions": questions},
    }


def _clarify_questions(raw) -> list:
    """把追问收敛成最多两条、带选项、去重；没有有效问题就返回空列表。"""
    out = []
    seen = set()
    for item in _as_list(raw):
        if isinstance(item, str):
            text, options, slot = item, [], ""
        elif isinstance(item, dict):
            text = item.get("text") or item.get("q") or ""
            options = item.get("options") or []
            slot = str(item.get("slot") or "").strip()
        else:
            continue
        text = str(text).strip()[:200]
        if not text or text in seen:
            continue
        seen.add(text)
        entry = {
            "text": text,
            "options": [str(o).strip()[:20] for o in _as_list(options) if str(o).strip()][:3],
        }
        if slot in CLARIFY_SLOTS:
            entry["slot"] = slot
        out.append(entry)
        if len(out) >= CLARIFY_MAX:
            break
    return out


IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": "生成一张图片并保存到资产库。用户明确要图片、海报、设定图、人物或场景形象时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "完整的中文出图提示词，写清主体、外观、光线、镜头、背景",
                },
                "name": {"type": "string", "description": "资产名，简短，如「雨夜风衣女」"},
                "type": {"type": "string", "enum": list(ASSET_TYPES), "description": "资产类型"},
                "desc": {"type": "string", "description": "给资产库用的描述，可留空"},
            },
            "required": ["prompt"],
        },
    },
}


GENERATE_ASSETS_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_assets",
        "description": "生成角色三视图和场景概念图，作为后续视频的设定资产。可以为角色和场景指定清晰、稳定的名称。全自动模式下必须先调用它，再生成视频。",
        "parameters": {
            "type": "object",
            "properties": {
                "role_name": {
                    "type": "string",
                    "description": "角色在资产库中的名称，简短明确，如「红发恶魔少女」",
                },
                "role": {"type": "string", "description": "角色外观描述；留空则使用用户需求"},
                "scene_name": {
                    "type": "string",
                    "description": "场景在资产库中的名称，简短明确，如「青草原」",
                },
                "scene": {"type": "string", "description": "场景描述；留空则使用用户需求"},
            },
        },
    },
}


JUDGE_MODIFY_TOOL = {
    "type": "function",
    "function": {
        "name": "judge_modify_target",
        "description": "判断用户这句话要修改什么对象：asset（资产/角色/场景设定图）、shot（镜头提示词）、video（整片）、none（不确定）。修改对象不明确或用户在资产/镜头之间切换时先调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "用户原话"},
            },
        },
    },
}


PROPOSE_ASSET_TOOL = {
    "type": "function",
    "function": {
        "name": "propose_asset_change",
        "description": "用户要求修改资产时，先给出详细的变更方案（不生成图片），等用户确认后再生成。desc 直接写改版后的完整外观，不要写“保留/沿用上一版”等字样。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "已有资产名称"},
                "desc": {"type": "string", "description": "修改后的完整资产描述，供出图使用"},
                "changes": {"type": "string", "description": "用要点说明本次要改哪些地方"},
            },
            "required": ["name", "desc"],
        },
    },
}


UPDATE_ASSET_TOOL = {
    "type": "function",
    "function": {
        "name": "update_asset",
        "description": "修改已有资产的描述并重新生成设定图。用户对角色/场景外观提出调整时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "已有资产名称，必须与资产库一致"},
                "desc": {"type": "string", "description": "更新后的完整资产描述"},
            },
            "required": ["name", "desc"],
        },
    },
}


SHOT_UPDATE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_shot_prompt",
        "description": "用户确认修改镜头描述时，更新已有镜头的提示词。按镜头编号或名称定位。",
        "parameters": {
            "type": "object",
            "properties": {
                "shot_no": {"type": "string", "description": "镜头编号，如 01 / 02"},
                "prompt": {"type": "string", "description": "新的镜头提示词"},
            },
            "required": ["shot_no", "prompt"],
        },
    },
}


RUI_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "use_rui_skills",
        "description": (
            "读取 Rui-Skills 工作流：真人剧/3D 漫剧分镜、人物三视图、站位图。"
            "用户要做分镜、漫剧、人物三视图、站位图时调用，返回工作流与参考目录。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "可选子任务，如 分镜 / 三视图 / 站位图"},
                "reference": {
                    "type": "string",
                    "description": "可选参考文件名（不含 .md），如 character / lighting-design / space-and-blocking",
                },
            },
            "required": [],
        },
    },
}


THREE_VIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_three_view_drawing",
        "description": (
            "根据用户上传的参考图生成角色三视图：正面、侧面、背面三张分开生成，保持同一角色。"
            "用户要求三视图、参考图、多角度设定图时调用；必须先有一张参考图，"
            "并且必须先得到用户明确确认，未确认不要调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "资产名，简短"},
                "type": {"type": "string", "enum": list(ASSET_TYPES), "description": "资产类型，默认角色"},
                "desc": {
                    "type": "string",
                    "description": "从参考图读到的外观描述：发型、服装、配色、材质、神态，写详细",
                },
            },
            "required": [],
        },
    },
}


VIDEO_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_video",
        "description": "创建一段逐镜视频并提交异步生成任务。用户明确要视频、成片、让镜头动起来时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "这一镜的完整画面提示词，写明主体、动作、环境、光线",
                },
                "name": {"type": "string", "description": "镜头名，简短"},
                "dur": {"type": "number", "description": "时长秒，4 到 15"},
            },
            "required": ["prompt"],
        },
    },
}


def _data_uri(path) -> str:
    raw = Path(path).read_bytes()
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def _user_content(text: str, ref_image_path=None):
    """带参考图时，把文字 + 图片一起交给多模态模型；读不到图就退回纯文字。"""
    if not ref_image_path:
        return text
    try:
        image_url = _data_uri(ref_image_path)
    except OSError:
        return text
    return [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": image_url}},
    ]


def compose_video_prompt(text: str, modules=None, assets=None, ref_image_path=None) -> str:
    """把原需求、三模块确认和资产合并成最终视频提示词；只出提示词，不提交视频。"""
    cfg = resolve_config()
    if not cfg["api_key"]:
        raise LLMError("BAD_REQUEST", "还没有配置语言模型 API Key", 400)
    if not cfg["base_url"]:
        raise LLMError("BAD_REQUEST", "请在 API 设置中填写语言模型 Base URL", 400)
    lines = ["用户需求：%s" % text.strip()]
    for key, label in (("role", "角色"), ("scene", "场景"), ("style", "风格")):
        value = str(((modules or {}).get(key) or {}).get("text") or "").strip()
        if value:
            lines.append("%s：%s" % (label, value))
    if assets:
        lines.append("已确认资产：%s" % "、".join(str(item) for item in assets))
    system = (
        "你是视频提示词编辑。把用户需求、已确认的角色/场景/风格和资产合并成一段最终视频提示词。"
        "只输出提示词本身，不要解释、不要 Markdown。必须包含角色外观、场景、动作、镜头运动、风格；"
        "如果给了参考图，保持人物长相、发型、服装、配色一致。"
    )
    body = _completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": _user_content("\n".join(lines), ref_image_path)},
        ],
        cfg=cfg,
        tools=None,
        timeout=20,
        temperature=0.5,
    )
    content = (body["choices"][0].get("message") or {}).get("content") or ""
    content = content.strip().strip("`").strip()
    if not content:
        raise LLMError("INTERNAL_ERROR", "最终提示词为空", 500)
    return content[:2000]


def short_shot_title(prompt: str, index: int = 1) -> str:
    """从镜头提示词里取一个简短标题，用于镜头清单。"""
    text = str(prompt or "").strip()
    if not text:
        return "镜头 %d" % index
    first = re.split(r"[，。；、,.;:：\n]", text)[0].strip()
    first = re.sub(
        r"^(镜头|第?\s*\d+\s*[镜个]?)\s*[0-9一二三四五六七八九十]*\s*[：:、.\-]?\s*", "", first
    ).strip()
    if not first:
        first = "镜头 %d" % index
    return first[:14] + ("…" if len(first) > 14 else "")


def compose_video_plan(text: str, modules=None, assets=None, ref_image_path=None) -> dict:
    """让语言模型同时给出最终提示词和逐镜时长，返回 {prompt, shots:[{prompt, dur}]}。"""
    cfg = resolve_config()
    if not cfg["api_key"]:
        raise LLMError("BAD_REQUEST", "还没有配置语言模型 API Key", 400)
    if not cfg["base_url"]:
        raise LLMError("BAD_REQUEST", "请在 API 设置中填写语言模型 Base URL", 400)
    lines = ["用户需求：%s" % text.strip()]
    for key, label in (("role", "角色"), ("scene", "场景"), ("style", "风格")):
        value = str(((modules or {}).get(key) or {}).get("text") or "").strip()
        if value:
            lines.append("%s：%s" % (label, value))
    if assets:
        lines.append("已确认资产：%s" % "、".join(str(item) for item in assets))
    system = (
        "你是视频分镜与提示词编辑。根据用户需求、已确认的角色/场景/风格和资产，"
        '只输出 JSON：{"prompt":"完整最终提示词","shots":[{"title":"镜头小标题","prompt":"该镜提示词","dur":4}]}。'
        "不要解释、不要 Markdown。1-6 个镜头；title 为 6-14 字的镜头小标题，"
        "概括该镜画面/动作，不要重复原需求；dur 为整数秒，范围 4-10，"
        "按动作、台词、镜头运动复杂度判断，不要所有镜头都用同一个时长；"
        "每个 shot 的 prompt 要能独立提交给视频模型，包含角色/场景/动作/镜头/风格；"
        "有参考图时保持人物长相、发型、服装、配色一致。"
    )
    body = _completion(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": _user_content("\n".join(lines), ref_image_path)},
        ],
        cfg=cfg,
        tools=None,
        timeout=60,
        temperature=0.5,
    )
    content = (body["choices"][0].get("message") or {}).get("content") or ""
    data = _extract_json(content)
    prompt = str(data.get("prompt") or "").strip()
    shots = []
    for item in _as_list(data.get("shots")):
        if not isinstance(item, dict):
            continue
        shot_prompt = str(item.get("prompt") or "").strip()
        if not shot_prompt:
            continue
        try:
            shot_dur = int(round(float(item.get("dur") or 4)))
        except (TypeError, ValueError):
            shot_dur = 4
        title = str(item.get("title") or "").strip() or short_shot_title(shot_prompt, len(shots) + 1)
        shots.append(
            {
                "title": title[:16],
                "prompt": shot_prompt[:2000],
                "dur": min(15, max(4, shot_dur)),
            }
        )
        if len(shots) >= 6:
            break
    if not shots:
        if not prompt:
            raise LLMError("INTERNAL_ERROR", "最终提示词为空", 500)
        shots = [{"title": short_shot_title(prompt, 1), "prompt": prompt[:2000], "dur": 4}]
    if not prompt:
        prompt = "；".join(item["prompt"] for item in shots)
    return {"prompt": prompt[:2000], "shots": shots}


def _upload_url(path) -> str:
    try:
        rel = Path(path).resolve().relative_to(config.UPLOAD_DIR.resolve())
    except (ValueError, OSError):
        return ""
    return "/uploads/" + rel.as_posix()


def _run_three_view_tool(args: dict, ref_image_path=None, asset_refs=None):
    """三视图工具：必须有参考图，正/侧/背分开出，返回 3 条图片记录。"""
    ref = ref_image_path
    if not ref and asset_refs:
        ref = asset_refs.get(str(args.get("name") or "").strip())
    if not ref:
        return {"ok": False, "error": "需要先上传一张参考图"}, None
    cfg = image_provider.resolve_config()
    if not cfg.get("api_key"):
        return {"ok": False, "error": "还没有配置图片模型 API Key"}, None
    name = str(args.get("name") or "三视图设定").strip()[:30]
    asset_type = str(args.get("type") or "角色").strip()
    if asset_type not in ASSET_TYPES:
        asset_type = "角色"
    desc = str(args.get("desc") or "").strip()[:500]
    images.configure(
        mode="live", api_key=cfg["api_key"], image_model=cfg["model"], base_url=cfg.get("base_url", "")
    )
    tmp_id = "chat-" + uuid.uuid4().hex[:8]
    try:
        result = images.run(
            {
                "kind": "keyframe",
                "payload": {
                    "task": "asset_views",
                    "asset_id": tmp_id,
                    "name": name,
                    "type": asset_type,
                    "desc": desc,
                    "ref_images": [ref],
                },
            }
        )
    except (RuntimeError, ValueError) as err:
        return {"ok": False, "error": str(err)[:300]}, None
    views = [item for item in (result.get("views") or []) if item.get("url")]
    if len(views) < 3:
        return {"ok": False, "error": "三视图没有完整生成"}, None
    urls = [item["url"] for item in views]
    record = {
        "name": name,
        "type": asset_type,
        "desc": desc,
        "urls": urls,
        "ref": _upload_url(ref),
    }
    return {"ok": True, "views": urls, "name": name}, record


def _run_image_tool(args: dict, ref_image_path=None):
    """执行 generate_image，返回 (工具结果, 图片记录)。有参考图时走图生图。"""
    prompt = str(args.get("prompt") or "").strip()
    name = str(args.get("name") or "生成图").strip()[:30]
    asset_type = str(args.get("type") or "其他").strip()
    if asset_type not in ASSET_TYPES:
        asset_type = "其他"
    if not prompt:
        return {"ok": False, "error": "提示词为空"}, None
    refs = [ref_image_path] if ref_image_path else None
    try:
        generated = image_provider.generate(prompt, ref_images=refs)
    except image_provider.ImageError as err:
        return {"ok": False, "error": err.message}, None
    image = {
        "name": name,
        "type": asset_type,
        "desc": str(args.get("desc") or "").strip()[:500],
        "url": generated["url"],
    }
    return {"ok": True, "url": generated["url"]}, image


def _tool_args(call: dict) -> dict:
    raw = (call.get("function") or {}).get("arguments") or "{}"
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def chat_plan(
    text: str,
    history: list | None = None,
    context: str = "",
    ref_image_path=None,
    video_handler=None,
    asset_refs=None,
    need: dict | None = None,
    no_clarify: bool = False,
    shot_handler=None,
    asset_handler=None,
    assets_first: bool = False,
    asset_update_handler=None,
    force_asset_update: bool = False,
    asset_proposal_handler=None,
    force_asset_proposal: bool = False,
    force_shot_update: bool = False,
    modify_judge_handler=None,
    defer_generation: bool = False,
) -> dict:
    """一句用户输入 + 最近对话 → {plan, images, videos, reply}。

    普通聊天返回自然语言回复（plan 为空）；规划、出图、出视频时才有结构化结果。
    ``context`` 是当前项目资产（名称/类型/描述），用来判断角色/场景是否已存在。
    ``ref_image_path`` 是用户上传的参考图，会同时作为视觉输入和出图参考。
    ``video_handler`` 由调用方注入（负责建镜头 + 提交任务），保持本模块不碰数据库。
    ``need`` 是系统预判的意图（image / video），用来决定本轮暴露哪些工具。
    """
    cfg = resolve_config()
    need = need or {"image": True, "video": True}
    assets_done = False

    def build_tools() -> list:
        current = [RUI_SKILL_TOOL]
        if modify_judge_handler is not None:
            current.append(JUDGE_MODIFY_TOOL)
        if shot_handler is not None:
            current.append(SHOT_UPDATE_TOOL)
        if asset_handler is not None and (need.get("image") or need.get("video") or assets_first):
            current.append(GENERATE_ASSETS_TOOL)
        if asset_update_handler is not None and need.get("image"):
            current.append(UPDATE_ASSET_TOOL)
        if asset_proposal_handler is not None and need.get("image"):
            current.append(PROPOSE_ASSET_TOOL)
        blocked = assets_first and not assets_done
        if need.get("image") and not blocked:
            current.extend([IMAGE_TOOL, THREE_VIEW_TOOL])
        if video_handler is not None and need.get("video") and not blocked:
            current.append(VIDEO_TOOL)
        return current

    tools = build_tools()
    system = SYSTEM_PROMPT
    if context:
        system += "\n\n当前项目资产（判断角色/场景是否已存在时用，已有就不要再让用户重复描述）：" + context
    system += (
        "\n\n本轮意图判断（系统预判，优先遵守）：图片生成需求=%s；视频生成需求=%s。"
        "只有为“是”的对应工具才可用；为“否”时不要调用对应工具，也不要主动补出该类型的生成。"
        % ("是" if need.get("image") else "否", "是" if need.get("video") else "否")
    )
    if no_clarify:
        system += (
            "\n\n本轮用户已经做过三项确认，禁止再输出 questions / clarify，"
            "也不要再说“还需要确认”；直接调用需要的工具或给出最终结果。"
        )
    if assets_first:
        system += (
            "\n\n全自动模式必须先调用 generate_assets 生成角色三视图和场景概念图，"
            "调用时为角色和场景填写清晰稳定的 role_name / scene_name，"
            "成功后再调用 generate_video；禁止跳过资产直接出视频。"
        )
    if defer_generation:
        system += (
            "\n\n本轮虽然明确是视频需求，但现在处于设定确认阶段。"
            "只分析并整理用户提出的角色、场景、背景和风格设定，输出资产描述与追问；"
            "不要调用任何出图或视频工具，也不要假装已经生成。"
        )
    messages = [{"role": "system", "content": system}]
    for item in (history or [])[-CHAT_HISTORY_LIMIT:]:
        role = "assistant" if item.get("role") == "agent" else "user"
        content = str(item.get("text") or "").strip()
        if content:
            messages.append({"role": role, "content": content[:2000]})
    messages.append({"role": "user", "content": _user_content(text, ref_image_path)})
    images = []
    videos = []
    three_views = []
    asset_updates = []
    asset_proposals = []
    content = ""
    forced = (
        "update_asset"
        if force_asset_update
        else (
            "propose_asset_change"
            if force_asset_proposal
            else "update_shot_prompt" if force_shot_update else ""
        )
    )
    for _ in range(4):
        tools = build_tools()
        tool_choice = None
        if forced and any(tool["function"]["name"] == forced for tool in tools):
            tool_choice = {"type": "function", "function": {"name": forced}}
        forced = ""
        body = _completion(messages, cfg=cfg, tools=tools, temperature=0.3, tool_choice=tool_choice)
        message = body["choices"][0].get("message") or {}
        calls = message.get("tool_calls") or []
        content = (message.get("content") or "").strip()
        if not calls:
            break
        messages.append({"role": "assistant", "content": message.get("content") or "", "tool_calls": calls})
        for call in calls:
            name = (call.get("function") or {}).get("name") or ""
            args = _tool_args(call)
            if name == "use_rui_skills":
                result = rui_skill(str(args.get("reference") or ""))
            elif name == "judge_modify_target" and modify_judge_handler is not None:
                try:
                    result = modify_judge_handler(args)
                except Exception as err:  # noqa: BLE001
                    result = {"ok": False, "error": str(err)[:300]}
            elif name == "update_shot_prompt" and shot_handler is not None:
                try:
                    result = shot_handler(args)
                except Exception as err:  # noqa: BLE001
                    result = {"ok": False, "error": str(err)[:300]}
            elif name == "generate_assets" and asset_handler is not None:
                try:
                    result = asset_handler(args, ref_image_path)
                except Exception as err:  # noqa: BLE001
                    result = {"ok": False, "error": str(err)[:300]}
                if result.get("ok"):
                    assets_done = True
            elif name == "update_asset" and asset_update_handler is not None:
                try:
                    result = asset_update_handler(args, ref_image_path)
                except Exception as err:  # noqa: BLE001
                    result = {"ok": False, "error": str(err)[:300]}
                if result.get("ok") and result.get("asset"):
                    asset_updates.append(result["asset"])
            elif name == "propose_asset_change" and asset_proposal_handler is not None:
                try:
                    result = asset_proposal_handler(args)
                except Exception as err:  # noqa: BLE001
                    result = {"ok": False, "error": str(err)[:300]}
                if result.get("ok") and result.get("proposal"):
                    asset_proposals.append(result["proposal"])
            elif name == "generate_video" and video_handler is not None:
                try:
                    result = video_handler(args, ref_image_path)
                except Exception as err:  # noqa: BLE001 - 工具失败要回给模型，不能中断整轮
                    result = {"ok": False, "error": str(err)[:300]}
                if result.get("ok") and result.get("shot_id"):
                    videos.append({"shotId": result["shot_id"], "taskId": result.get("task_id", "")})
            elif name == "generate_three_view_drawing":
                result, three = _run_three_view_tool(args, ref_image_path, asset_refs=asset_refs)
                if three:
                    three_views.append(three)
            else:
                result, image = _run_image_tool(args, ref_image_path)
                if image:
                    images.append(image)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id") or "",
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        if asset_proposals:
            break

    if not content and asset_proposals:
        proposal = asset_proposals[0]
        content = "准备修改「%s」：%s" % (
            proposal.get("assetName", ""),
            proposal.get("changes") or proposal.get("desc", ""),
        )

    plan = normalize_plan({})
    reply = ""
    if content:
        try:
            plan = normalize_plan(_extract_json(content))
            reply = plan["summary"]
        except LLMError:
            reply = content.strip()[:2000]
    if not reply and plan["shots"]:
        reply = f"我拆成了 {len(plan['shots'])} 个镜头，确认后就能生成。"
    if not reply:
        if three_views:
            reply = "已生成三视图。"
        elif images:
            reply = "已生成设定图。"
        elif videos:
            reply = "已提交视频任务，可以在「视频」页查看生成进度。"
        else:
            reply = "我在。"
    if no_clarify:
        plan["questions"] = []
    return {
        "plan": plan,
        "images": images,
        "three_views": three_views,
        "videos": videos,
        "asset_updates": asset_updates,
        "asset_proposals": asset_proposals,
        "reply": reply,
        "contextUsage": {
            "input": (body.get("usage") or {}).get("prompt_tokens"),
            "limit": body.get("context_length") or body.get("context_window"),
            "model": cfg["model"],
            "base": cfg["base_url"],
        },
    }
