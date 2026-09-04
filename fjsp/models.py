#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FJSP 核心数据结构与算例加载（模块 M1 算例管理）。

与《方案设计说明书》§5.1 对应，提供：
- 数据类：Operation / Job / FJSPInstance / ScheduleItem / Schedule
- 算例加载：从 data/processed/*.json 读取统一 JSON 并重建对象
- 求解配置：SolverConfig（对应 §3.2 默认参数）
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence


# ---------------------------------------------------------------------------
# 核心数据类（§5.1）
# ---------------------------------------------------------------------------


@dataclass
class Operation:
    """一道工序：可选设备编号列表 + 对应加工时间列表（按下标对齐，设备 0 基）。"""

    job_id: int
    op_id: int
    eligible_machines: List[int]
    processing_times: List[float]

    @property
    def num_choices(self) -> int:
        """可选设备数（柔性）。"""
        return len(self.eligible_machines)


@dataclass
class Job:
    """一个工件：由若干道工序按工艺顺序组成。"""

    job_id: int
    operations: List[Operation]
    due_date: float = float("inf")          # 交期（可选，默认无穷大）

    @property
    def num_operations(self) -> int:
        return len(self.operations)


@dataclass
class FJSPInstance:
    """一个 FJSP 算例。"""

    name: str
    num_jobs: int
    num_machines: int
    jobs: List[Job]
    known_best_makespan: Optional[float] = None

    @property
    def total_operations(self) -> int:
        return sum(j.num_operations for j in self.jobs)

    def get_operation(self, job_id: int, op_id: int) -> Operation:
        """按工件号与工序号取工序。"""
        return self.jobs[job_id].operations[op_id]


@dataclass
class ScheduleItem:
    """一道已排程工序。"""

    job_id: int
    op_id: int
    machine_id: int
    start_time: float
    end_time: float

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


@dataclass
class Schedule:
    """一个排程方案（§3.4 输出）。"""

    items: List[ScheduleItem]
    makespan: float
    machine_utilization: List[float]
    max_load: float
    total_tardiness: float


@dataclass
class SolveResult:
    """一次求解的完整结果（§3.3 输出：方案 + 收敛曲线 + 耗时）。"""

    schedule: Schedule
    history: List[float]                    # 每代（轮）最优 Makespan
    avg_history: List[float]                # 每代（轮）平均 Makespan
    elapsed: float                          # 求解耗时（秒）
    best_operation_sequence: List[int] = field(default_factory=list)
    best_machine_choices: List[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 求解配置（§3.2 默认参数）
# ---------------------------------------------------------------------------


@dataclass
class SolverConfig:
    """智能优化算法求解参数。"""

    algorithm: str = "ga"                   # ga / sa / pso / hybrid
    population_size: int = 100              # GA 种群数 / PSO 粒子数
    max_iterations: int = 200               # 迭代次数
    crossover_rate: float = 0.8             # GA 交叉概率
    mutation_rate: float = 0.1              # GA 变异概率
    sa_initial_temp: float = 1000.0         # SA 初始温度
    sa_cooling_rate: float = 0.95           # SA 冷却系数
    sa_max_iterations: int = 1000           # SA 迭代次数（§4.3）
    pso_inertia: float = 0.7                # PSO 惯性权重
    pso_cognitive: float = 1.5              # PSO 认知因子 c1
    pso_social: float = 1.5                 # PSO 社会因子 c2
    hybrid_sa_steps: int = 20               # 混合算法精英局部搜索步数
    elite_rate: float = 0.1                 # 精英保留比例
    random_seed: int = 42                   # 随机种子
    objective: str = "makespan"             # 优化目标（当前仅支持 makespan）


# ---------------------------------------------------------------------------
# 算例加载（从 processed/*.json）
# ---------------------------------------------------------------------------


def from_dict(data: dict) -> FJSPInstance:
    """由预处理 JSON 字典重建 FJSPInstance。"""
    jobs: List[Job] = []
    for j in data["jobs"]:
        ops: List[Operation] = []
        for k, op in enumerate(j["operations"]):
            ops.append(
                Operation(
                    job_id=j["job_id"],
                    op_id=k,
                    eligible_machines=list(op["eligible_machines"]),
                    processing_times=list(op["processing_times"]),
                )
            )
        jobs.append(Job(job_id=j["job_id"], operations=ops))
    return FJSPInstance(
        name=data["name"],
        num_jobs=data["num_jobs"],
        num_machines=data["num_machines"],
        jobs=jobs,
        known_best_makespan=data.get("known_best_makespan"),
    )


def load_instance(path: str | Path) -> FJSPInstance:
    """从统一 JSON 文件加载算例。"""
    with open(path, encoding="utf-8") as f:
        return from_dict(json.load(f))


def load_instance_by_name(name: str, data_dir: str | Path = "data/processed") -> FJSPInstance:
    """按算例名（如 ``mk01``、``ft06``）从 processed 目录加载。"""
    p = Path(data_dir) / f"{name.lower()}.json"
    return load_instance(p)
