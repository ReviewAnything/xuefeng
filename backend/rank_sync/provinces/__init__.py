"""省级适配器注册表：一个省一个模块，模块里只有该省的发现逻辑与版式取数。

新增一个省的步骤（也是这个包存在的意义）：
1. 在 ``provinces/`` 建 ``<pinyin>.py``，暴露 PROVINCE / SITE / SCHEME / SUBJECTS /
   NOTICES / STATUS / ``parse(year) -> doc``；
2. 在下面的 ``_MODULES`` 里登记；
3. ``python -m rank_sync 该省`` 跑一遍，校验不过就整份拒收，不会半截落盘。

模块与「一键同步」的关系：管理端的按省同步按钮、CLI、测试，走的都是同一个
``parse(year)``——不存在第二条取数路径，避免「按钮能跑、脚本不能跑」的分裂。
"""
from __future__ import annotations

from . import (
    anhui, beijing, chongqing, guangdong, guangxi, heilongjiang, hubei, hunan, jiangxi,
    jilin, liaoning, neimenggu, ningxia, qinghai, shaanxi, shandong, shanghai, zhejiang,
)

_MODULES = (guangdong, shandong, zhejiang, hubei, hunan, shaanxi, anhui, chongqing,
            beijing, shanghai, liaoning, jiangxi, jilin, heilongjiang, guangxi, neimenggu,
            ningxia, qinghai)

REGISTRY: dict[str, object] = {m.PROVINCE: m for m in _MODULES}

__all__ = ["REGISTRY"]
