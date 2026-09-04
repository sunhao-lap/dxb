#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SmartFJSP 算法核心包。

模块划分（对应《方案设计说明书》）：
- models   ：M1 算例管理（数据结构 + 加载 + 配置）
- decoder  ：M4 方案解码（主动调度 + 指标计算）
- ga / sa / pso / hybrid ：M3 优化求解
"""

from .models import (
    FJSPInstance,
    Job,
    Operation,
    Schedule,
    ScheduleItem,
    SolveResult,
    SolverConfig,
    from_dict,
    load_instance,
    load_instance_by_name,
)
from .decoder import decode
from .ga import solve_ga
from .sa import solve_sa
from .pso import solve_pso
from .hybrid import solve_hybrid

__all__ = [
    "FJSPInstance",
    "Job",
    "Operation",
    "Schedule",
    "ScheduleItem",
    "SolveResult",
    "SolverConfig",
    "from_dict",
    "load_instance",
    "load_instance_by_name",
    "decode",
    "solve_ga",
    "solve_sa",
    "solve_pso",
    "solve_hybrid",
]
