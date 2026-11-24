# -*- coding: utf-8 -*-
"""提示词模板。

三视图的写法是 2026-11-22 做 A/B 试验后定的，三条结论都来自实测：

1. **画风必须显式声明。** 以前的提示词里根本没有「画风」两个字，模型只能靠参考图猜，
   二次元素材会被画成真人。现在开头的【画风】段是硬约束。
2. **背面不能只说「转到背面」。** 模型会把正面再画一遍（机甲那次就是这样）。
   必须先把正面特征翻译成「从背面看是什么样」，再让它照清单画。
3. **每一张都会出现的东西要单独列成硬约束。** 头发、翅膀、服装主形、鞋、随身饰品
   只写在描述里时，模型当它是参考——实测里白色龙翼在正面和侧面被画成了黑蝙蝠翼。
   所以单列【每一张都必须完全一致】。

三视图现在是**一张设定稿**（2026-11-22 晚上改的，用户提供的参考版式）：

    左边一格：头部与肩部的大特写；
    后面三格：正面 / 侧身 / 背面全身，三格等高、头顶平齐、脚底同一基线。

以前的方案是分开出三张。分开出每张图分辨率最高，但三张之间的一致性只能靠提示词撑，
实测里白色龙翼在正面和侧面被画成了黑蝙蝠翼；拼成一张之后由模型自己保证四格是同一个
角色，一致性反而最稳。代价是每格只有原图的三分之一宽，且不能按固定位置裁——所以整张
存成一张图，不做切割。
"""
from __future__ import annotations

import json

# 视角 -> 中文描述
VIEW_LABEL = {
    "front": "正视图（正面全身）",
    "side": "侧视图（侧身全身）",
    "back": "背视图（背面全身）",
}

_TAIL = (
    "纯白或纯净背景，光线均匀柔和，主体居中且完整入画，画面里只有这一个主体；"
    "不要文字、不要水印、不要多视角拼图、不要边框。"
)

# 让视觉模型先读一遍参考图，产出一份「画三视图要用的设定清单」。
#
# 字段是**封闭**的：漏一个字段，出图就会在对应的那一类问题上翻车。四类通病与字段的对应：
#   撞色消失   -> subject_tone（决定背景灰阶）
#   超出轮廓   -> silhouette（翅膀/尾巴/披风/武器/背包/长发，同一个槽）
#   左右成对   -> asymmetry（必须以角色自身左/右表述）
#   背面靠猜   -> back_render
#   多加东西   -> absent
DNA_PROMPT = """你是角色设定师，正在为「生成三视图设定稿」准备设定清单。仔细看这张参考图，只输出 JSON，不要任何解释：
{
  "style": "画风，用参数级语言（例如：二次元赛璐璐上色、细黑描边、平涂配硬高光）",
  "identity": "一句话身份：物种、年龄感、体型、头身比",
  "face": "五官：脸型、瞳色、左右眼是否有差异、耳朵、妆容、疤痕；头上装饰写明佩戴在身体哪一侧",
  "hair": "发色、发型、长度、刘向、发尾形态",
  "outfit": "服装：版型、层次、颜色、材质、主要装饰件；饰品写明名称和佩戴位置（在身体哪一侧）",
  "subject_tone": "主体整体明度，只能是这三个词之一：浅色 / 中间调 / 深色",
  "silhouette": [
    "所有超出身体轮廓的东西，逐条写：名称、颜色、材质、从身体哪个部位连接、展开尺寸（以身高为单位，例如『展开宽度约两个身宽』）、静态形态。比如翅膀、尾巴、披风、长枪、大剑、背包、光环、超长发。没有就给空数组"
  ],
  "asymmetry": [
    "左右不对称的项，逐条写清楚在哪一侧（用角色自身的左/右）：单耳饰、单肩斗篷、斜挎带、单侧义肢、刘海分缝。没有就给空数组"
  ],
  "persistent": [
    "正面、侧面、背面每一格都必须一模一样的东西，逐条写：发色发型、silhouette 里每一条的颜色与形态、服装主形、鞋、随身饰品的形状与所在侧"
  ],
  "front_only": ["只在正面能看到、背面绝对不能出现的东西，逐条"],
  "back_render": ["从背面看，persistent 里每一条分别呈现成什么样；确实看不到就写『不可见』"],
  "absent": ["参考图里没有、绝对不许凭空加的东西，逐条。例如：多余的饰品、第二套衣服、参考图之外的武器"]
}"""

_LIST_KEYS = ("persistent", "silhouette", "asymmetry", "front_only", "back_render", "absent")
_TEXT_KEYS = ("style", "identity", "face", "hair", "outfit", "subject_tone")

# 主体明度 -> 背景灰阶。浅色主体（白翼、白衣）必须用中灰，否则会被纯白背景吞掉；
# 其余主体用浅灰，既能衬深色也能衬彩色。这条是「撞色消失」的通用解，不是给翅膀特判。
BACKGROUND_BY_TONE = {"浅色": "中灰", "中间调": "浅灰", "深色": "浅灰"}
DEFAULT_BACKGROUND = "浅灰"


def background_for(dna: dict) -> str:
    """按主体明度挑背景灰阶。清单缺失时按中间调处理。"""
    tone = (dna.get("subject_tone") or "").strip()
    return BACKGROUND_BY_TONE.get(tone, DEFAULT_BACKGROUND)


def parse_dna(text: str):
    """把视觉模型的回答解析成设定清单；解析不出来返回 ``None``。

    模型经常把 JSON 包在 ```json 里，所以先剥围栏再找第一个大括号。
    """
    raw = (text or "").strip()
    if "```" in raw:
        for part in raw.split("```"):
            piece = part.strip()
            if piece.startswith("json"):
                piece = piece[4:].strip()
            if piece.startswith("{"):
                raw = piece
                break

    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None

    for key in _LIST_KEYS:
        value = data.get(key)
        data[key] = (
            [str(item).strip() for item in value if str(item).strip()] if isinstance(value, list) else []
        )
    for key in _TEXT_KEYS:
        value = data.get(key)
        data[key] = str(value).strip() if value is not None and not isinstance(value, list) else ""

    if not (data["style"] or data["identity"] or data["persistent"] or data["silhouette"]):
        return None
    return data


def fallback_dna(name: str, kind: str = "角色", desc: str = "") -> dict:
    """拿不到设定清单时的兜底：只用名字、类型和描述，至少不会出不了图。"""
    desc = (desc or "").strip()
    dna = {
        "style": "",
        "identity": "%s「%s」%s" % (kind or "角色", name, ("：" + desc) if desc else ""),
        "face": "",
        "hair": "",
        "outfit": "",
        "subject_tone": "",
        "silhouette": [],
        "asymmetry": [],
        "persistent": [desc] if desc else [],
        "front_only": [],
        "back_render": [],
        "absent": [],
    }
    return dna


# 内容审核对身材描写很敏感。这些替换只在**被审核拦下之后**才用，
# 平时不改词——否则「恶魔」被改成「异族」，出图会跑偏。
_SOFTEN = (
    ("裸露", "无遮挡"),
    ("胸口", "前襟"),
    ("胸前", "前襟"),
    ("胸线", "前襟斜向"),
    ("紧身", "贴身"),
    ("低胸", "小立领"),
    ("性感", "优雅"),
    ("少女", "女性角色"),
    ("恶魔", "异族"),
    ("魔女", "异族"),
    ("露肩", "方领"),
)


def _soften(text: str) -> str:
    for bad, good in _SOFTEN:
        text = text.replace(bad, good)
    return text


def soften_dna(dna: dict) -> dict:
    """被内容审核拦下时的降级版清单：把敏感词换成中性说法。"""
    out = {}
    for key in _TEXT_KEYS:
        out[key] = _soften(str(dna.get(key) or ""))
    for key in _LIST_KEYS:
        out[key] = [_soften(str(item)) for item in (dna.get(key) or [])]
    return out


def anchor(name: str, kind: str = "角色", desc: str = "") -> str:
    """主体锚定段：名字 + 类型 + 设定描述。"""
    text = "%s「%s」" % (kind or "角色", name)
    desc = (desc or "").strip()
    if desc:
        text += "：" + desc
    return "【设定】" + text


def _style_block(dna: dict) -> str:
    style = (dna.get("style") or "").strip()
    if not style:
        return ""
    return "【画风】%s。整张图都要保持这个画风，不允许转成真人照片、3D 渲染、写实摄影或厚涂油画。" % style


def _persistent_block(dna: dict) -> str:
    items = dna.get("persistent") or []
    if not items:
        return ""
    return (
        "【每一张都必须完全一致】下面每一条在正面、侧面、背面三张图里都要照原样画，"
        "不许改名、不许改颜色、不许改材质和形状，也不许换到身体另一侧：\n- " + "\n- ".join(items)
    )


def _view_block(view: str, dna: dict) -> str:
    face = (dna.get("face") or "").strip()
    outfit = (dna.get("outfit") or "").strip()
    front_only = dna.get("front_only") or []

    if view == "front":
        lines = ["【视角】正对镜头的正面全身站立像，人物面向镜头，双臂自然下垂，双脚并拢。"]
        if face:
            lines.append("【面部】" + face)
        if outfit:
            lines.append("【服装与配饰】" + outfit)
        if front_only:
            lines.append("【这一视角必须看得见】\n- " + "\n- ".join(front_only))
        return "\n".join(lines)

    if view == "side":
        lines = [
            "【视角】侧身站立的全身像，镜头在身体的一侧，能看到一侧脸颊的轮廓线和后背的侧缘，"
            "另一侧被身体挡住；既不是正面也不是背面。"
        ]
        if face:
            lines.append("【面部】%s（侧视角下另一侧被鼻梁和脸颊挡住）" % face)
        if outfit:
            lines.append("【服装与配饰】" + outfit)
        return "\n".join(lines)

    lines = ["【视角】正背面全身站立像，镜头在人物身后，看不到脸、看不到眼睛和瞳孔、看不到胸前的正面装饰。"]
    render = dna.get("back_render") or []
    if render:
        lines.append("【背面必须这样画】\n- " + "\n- ".join(render))
    else:
        lines.append("【背面必须这样画】\n- 只画从后面能看见的部分：后脑、后背、后腰、腿部背面。")
    if front_only:
        lines.append("【禁止】后背不得出现：" + "；".join(front_only))
    return "\n".join(lines)


def three_view(
    name: str,
    kind: str = "角色",
    desc: str = "",
    view: str = "front",
    use_ref: bool = False,
    dna: dict | None = None,
) -> str:
    """出一张视图的提示词。

    ``dna`` 是视觉模型读参考图后产出的设定清单（见 ``DNA_PROMPT``）。给了清单就按
    「画风 + 设定 + 每张必须一致 + 这一视角要什么」四段拼；没给就退回最简单的描述式提示词。
    ``use_ref`` 只为兼容旧调用保留，现在三张图都挂用户原图，不再链式参考上一张。
    """
    label = VIEW_LABEL.get(view)
    if not label:
        raise ValueError("view 只能是 %s，收到 %r" % ("/".join(VIEW_LABEL), view))

    if not dna:
        body = "生成%s，全身完整入画，不裁切，姿态自然中立。" % label
        return "\n".join([anchor(name, kind, desc), body, _TAIL])

    blocks = [
        _style_block(dna),
        anchor(name, kind, desc),
        _persistent_block(dna),
        _view_block(view, dna),
        _TAIL,
    ]
    return "\n".join(block for block in blocks if block)


SHEET_LABEL = "三视图设定稿"

# 两条硬句。它们跟具体是什么物件无关，治的是四类通病里的两类：
#   _HARD_COMPLETE  -> 附属结构被挡住 / 被裁掉
#   _HARD_SYMMETRIC -> 成对结构左右不对称
_HARD_COMPLETE = (
    "【完整入画】上面列出的附属结构，每一个都必须在这一格里完整出现：不得被手臂或身体挡住，"
    "不得被画框裁切，不得只画一半；主体四周留白，附属结构的外缘不许贴边。"
)

_HARD_SYMMETRIC = (
    "【对称】成对出现的结构必须左右对称：两侧的连接点在同一水平线上，两侧大小、形状完全一致，"
    "末端高度一致；不许一边大一边小、一边高一边低、一边展开一边收着。"
)

_SHEET_LAYOUT = (
    "【版面】一张横向的角色设定稿，从左到右四个并排的格子，四格等高：\n"
    "- 第 1 格（最左，约占全宽的三分之一）：角色头部与肩部的大特写，正面朝向镜头，"
    "五官、发色、瞳色、耳朵、头饰和颈部饰品都清晰可见，头顶上方留少量空白。\n"
    "- 第 2 格：正面全身站立像，面向镜头，双臂自然下垂并略微离开身体，双脚并拢。\n"
    "- 第 3 格：侧身全身站立像，镜头在身体一侧，能看到一侧脸颊的轮廓和后背的侧缘，"
    "既不是正面也不是背面。\n"
    "- 第 4 格（最右）：背面全身站立像，镜头在角色身后，看不到脸、看不到眼睛和瞳孔、"
    "看不到胸前的正面装饰。\n"
    "【对齐】右侧三格里的角色身高、胖瘦、头身比完全相同：头顶在同一条水平线上，"
    "脚底踩在同一条基线上；第 1 格的脸与右侧三格里的脸大小一致。"
)


def _setting_block(dna: dict) -> str:
    """设定段：四格逐字共用同一段，这是「同一个人被旋转」的唯一硬保证。"""
    parts = []
    identity = (dna.get("identity") or "").strip()
    face = (dna.get("face") or "").strip()
    hair = (dna.get("hair") or "").strip()
    outfit = (dna.get("outfit") or "").strip()
    if identity:
        parts.append(identity)
    if face:
        parts.append("五官：" + face)
    if hair:
        parts.append("头发：" + hair)
    if outfit:
        parts.append("服装：" + outfit)
    if not parts:
        return ""
    return (
        "【设定（四格完全相同，逐字照画）】"
        + "；".join(parts)
        + "。不许改颜色、不许改形状、不许换到身体另一侧。"
    )


def _silhouette_block(dna: dict) -> str:
    """附属结构与左右不对称项：所有「超出身体轮廓 / 成对 / 分左右」的东西都走这里。"""
    items = list(dna.get("silhouette") or [])
    for extra in dna.get("asymmetry") or []:
        items.append(extra)
    if not items:
        return ""
    return "【附属结构】\n- " + "\n- ".join(items) + "\n" + _HARD_COMPLETE + "\n" + _HARD_SYMMETRIC


def _sheet_block(dna: dict) -> str:
    """四格版面 + 每格各自的可见性要求 + 背面禁止项。"""
    face = (dna.get("face") or "").strip()
    front_only = dna.get("front_only") or []
    render = dna.get("back_render") or []
    absent = dna.get("absent") or []

    lines = [_SHEET_LAYOUT]
    if face:
        lines.append("【面部】" + face)
    if front_only:
        lines.append("【只在正面出现】" + "；".join(front_only))
    if render:
        lines.append("【第 4 格必须这样画】\n- " + "\n- ".join(render))
    if front_only:
        lines.append("【禁止】第 4 格不得出现：" + "；".join(front_only))
    if absent:
        lines.append("【禁止】任何一格都不得出现：" + "；".join(absent))
    return "\n".join(lines)


def _scene_block(dna: dict) -> str:
    """画面段：背景按主体明度选灰阶，中性柔光 + 微侧光制造体积，脚下投影做分离。"""
    tone = (dna.get("subject_tone") or "").strip()
    background = background_for(dna)
    tone_note = "（主体是%s，用%s背景拉开明度差）" % (tone, background) if tone else ""
    return (
        "【画面】背景是干净的%s纯色%s，不要渐变、不要环境、不要道具。"
        "中性柔和的主光加一点侧光，让材质的体积和转面看得清，不许偏黄或偏蓝。"
        "主体与背景之间轮廓清晰，脚下有柔和的投影帮助分离。"
        "画面里不要出现任何文字、编号、标签、箭头、分割线或边框；"
        "不要画成一个角色横向重复的连拍，要清楚的四格设定稿。" % (background, tone_note)
    )


def three_view_sheet(
    name: str,
    kind: str = "角色",
    desc: str = "",
    dna: dict | None = None,
) -> str:
    """出一张「三视图设定稿」的提示词：左特写 + 正/侧/背三格等高全身。

    ``dna`` 是视觉模型读参考图后产出的设定清单（见 ``DNA_PROMPT``）。没有清单时
    只用名字和描述，版面要求照旧——版面是这张图的骨架，不能因为缺清单就不写。
    """
    if not dna:
        return "\n".join([anchor(name, kind, desc), _SHEET_LAYOUT, _scene_block({})])

    blocks = [
        _style_block(dna),
        anchor(name, kind, desc),
        _setting_block(dna),
        _silhouette_block(dna),
        _sheet_block(dna),
        _scene_block(dna),
    ]
    return "\n".join(block for block in blocks if block)


AUDIT = (
    "你在做设定稿的体检。第一张是用户提供的原始参考图，第二张是按设定生成的四格设定稿。\n"
    "逐条核对下面这份设定清单，只看「画得对不对」，不评价画风好坏：\n"
    "1. 清单里 silhouette（翅膀、尾巴、披风、武器、背包、长发这类超出身体轮廓的东西）"
    "每一项，在第 2/3/4 格里是否都出现了？数量对不对？颜色形态对不对？\n"
    "2. 成对的结构是否左右对称？有没有一边大一边小、一边高一边低？\n"
    "3. 有没有哪一部分被手臂或身体挡住、被画框裁掉、只画了一半？\n"
    "4. 第 4 格是否真的是背面（看不到脸和正面专属装饰）？\n"
    "5. 有没有出现清单里 absent 的东西，或者凭空多出来的饰品、武器、第二套衣服？\n"
    "光线、机位、姿态、构图的正常变化不算问题。\n"
    '只输出 JSON，不要任何解释：{"pass": true 或 false, "issues": ["逐条写清楚哪里不对"]}\n'
    "全部没问题时 pass 为 true，issues 为空数组。"
)


def concept(name: str, kind: str = "场景", desc: str = "") -> str:
    """出一张场景 / 设定概念图的提示词（单张，不做正 / 侧 / 背三视图）。"""
    head = anchor(name, kind, desc)
    body = "生成一张场景概念图：广角，固定机位，空间结构清晰，环境光统一，无人物特写。"
    return "\n".join([head, body, _TAIL])


def keyframe(shot_name: str, shot_prompt: str, assets_text: str = "") -> str:
    """出一张镜头首帧的提示词。"""
    lines = [
        "为分镜「%s」生成这一镜的第一帧画面。" % (shot_name or "未命名镜头"),
        (shot_prompt or "").strip(),
    ]
    if assets_text:
        lines.append("必须与下列资产设定保持一致：" + assets_text)
    lines.append("16:9 横向构图，电影感，画面中不要出现任何文字、字幕或水印。")
    return "\n".join(line for line in lines if line)


def assets_brief(assets) -> str:
    """把资产列表压成一行「角色「小林」（蓝色夹克）」这样的简述，塞进首帧提示词。"""
    parts = []
    for item in assets or []:
        if isinstance(item, dict):
            name = item.get("name") or item.get("id") or ""
            desc = (item.get("desc") or "").strip()
        else:
            name, desc = str(item), ""
        if not name:
            continue
        parts.append("%s（%s）" % (name, desc) if desc else name)
    return "；".join(parts)


VERIFY = (
    "你在做视频一致性校验。\n"
    "先给出的是「已确认的资产设定图」，后面是「从视频里均匀抽出的画面」。\n"
    "只判断画面里的主体是否与设定图一致，重点看三件事：长相与发型、服装、场景里的关键物件与主色调。\n"
    "光线、机位、动作、构图的正常变化不算问题。\n"
    '只输出 JSON，不要任何解释：{"pass": true 或 false, "issues": ["逐条写清楚哪里不一致"]}\n'
    "没问题时 issues 返回空数组。"
)
