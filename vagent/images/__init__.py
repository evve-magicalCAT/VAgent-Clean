# -*- coding: utf-8 -*-
"""B（图片 Agent）的能力层。

对外只有这四样东西：

- ``run(job)``：执行一条任务，任务类型见 ``runner`` 的说明
- ``read_views(asset_id)``：读回已经存好的资产三视图
- ``configure(...)``：切 mock / live，注入 API key 和输出目录
- ``mode()``：现在是什么模式

``ark`` / ``frames`` / ``mock`` / ``prompts`` 是实现细节，别处不要直接 import。

两种产物别混：**资产三视图**存在 ``assets/<asset_id>/`` 的固定位置、长期有效；
**镜头首帧**属于某一镜，才对应 ``contracts.KeyframeResult``。
"""
from .runner import configure, mode, read_views, run

__all__ = ["configure", "mode", "read_views", "run"]
