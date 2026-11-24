# -*- coding: utf-8 -*-
"""三个 Agent 之间唯一的契约层（第 1 步只冻结结构，尚未被调用）。

约定：
  - LLM 主 Agent 只输出 ShotPlan；
  - 图片 Agent 只接受 KeyframeRequest，返回 KeyframeResult；
  - 视频 Agent 只接受 VideoRequest，返回 VideoResult。
任何一方都不得在自己的模块里改这些结构，变更需三人评审。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

JobKind = Literal["plan", "keyframe", "video", "stitch"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]


@dataclass
class AssetDraft:
    """LLM 识别出的、要沉淀进资产库的设定。"""

    name: str
    type: Literal["角色", "场景", "风格", "其他"]
    desc: str
    locked: bool = True


@dataclass
class ShotDraft:
    """LLM 拆出的单镜描述，尚未生成。"""

    name: str
    prompt: str
    dur: float = 3.0
    camera: str = ""
    asset_refs: list[str] = field(default_factory=list)


@dataclass
class Question:
    """需要用户拍板的追问。"""

    text: str
    options: list[str] = field(default_factory=list)


@dataclass
class ShotPlan:
    """LLM 主 Agent 的唯一输出。"""

    version: int
    summary: str
    assets: list[AssetDraft] = field(default_factory=list)
    shots: list[ShotDraft] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)


@dataclass
class KeyframeRequest:
    shot_id: str
    prompt: str
    ref_asset_ids: list[str] = field(default_factory=list)
    aspect: str = "16:9"


@dataclass
class KeyframeResult:
    shot_id: str
    first_frame: str
    last_frame: str
    cost: float = 0.0


@dataclass
class VideoRequest:
    shot_id: str
    prompt: str
    first_frame: str
    last_frame: str
    dur: float
    aspect: str = "16:9"


@dataclass
class VideoResult:
    shot_id: str
    clip_path: str
    dur: float
    cost: float = 0.0


@dataclass
class Job:
    """任务表的一行（第 2 步落库）。"""

    id: str
    kind: JobKind
    project_id: str
    payload: dict
    status: JobStatus = "queued"
    progress: int = 0
    attempts: int = 0
    provider_job: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None
