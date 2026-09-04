#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pydantic 数据模型（模块 M9 API 服务，对应设计说明书 §3.9 / §5.3）。

定义 RESTful 接口的请求体与响应体结构，并做基础参数校验（§3.2）。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# 自定义算例（M1）
# ---------------------------------------------------------------------------


class OperationIn(BaseModel):
    """一道自定义工序：可选设备列表 + 对应加工时间。"""

    eligible_machines: List[int]
    processing_times: List[float]

    @field_validator("processing_times")
    @classmethod
    def _times_positive(cls, v):
        if any(t <= 0 for t in v):
            raise ValueError("加工时间必须为正")
        return v


class JobIn(BaseModel):
    """一个自定义工件。"""

    job_id: int
    operations: List[OperationIn]
    due_date: float = float("inf")


class CustomInstanceIn(BaseModel):
    """自定义算例提交体。"""

    name: str
    num_jobs: int
    num_machines: int
    jobs: List[JobIn]

    @field_validator("jobs")
    @classmethod
    def _jobs_align(cls, v):
        for j in v:
            for k, op in enumerate(j.operations):
                if len(op.eligible_machines) != len(op.processing_times):
                    raise ValueError(
                        f"工件 {j.job_id} 工序 {k} 设备列表与时间列表长度不一致"
                    )
        return v


# ---------------------------------------------------------------------------
# 求解配置（M2）
# ---------------------------------------------------------------------------


class SolveConfigIn(BaseModel):
    """算法求解参数（§3.2 默认参数）。"""

    algorithm: str = "ga"                       # ga / sa / pso / hybrid
    population_size: int = 100
    max_iterations: int = 200
    crossover_rate: float = 0.8
    mutation_rate: float = 0.1
    sa_initial_temp: float = 1000.0
    sa_cooling_rate: float = 0.95
    sa_max_iterations: int = 1000
    pso_inertia: float = 0.7
    pso_cognitive: float = 1.5
    pso_social: float = 1.5
    hybrid_sa_steps: int = 20
    elite_rate: float = 0.1
    random_seed: int = 42
    objective: str = "makespan"

    @field_validator("algorithm")
    @classmethod
    def _algo(cls, v):
        if v not in ("ga", "sa", "pso", "hybrid"):
            raise ValueError("algorithm 必须为 ga/sa/pso/hybrid")
        return v

    @field_validator("population_size")
    @classmethod
    def _pop(cls, v):
        if not (10 <= v <= 500):
            raise ValueError("population_size 须在 10~500")
        return v

    @field_validator("max_iterations")
    @classmethod
    def _iter(cls, v):
        if not (10 <= v <= 10000):
            raise ValueError("max_iterations 须在 10~10000")
        return v


class SolveRequest(BaseModel):
    """求解请求体。"""

    instance_name: str
    config: SolveConfigIn = Field(default_factory=SolveConfigIn)


# ---------------------------------------------------------------------------
# 排程方案（M4）
# ---------------------------------------------------------------------------


class ScheduleItemOut(BaseModel):
    """一道已排工序。"""

    job_id: int
    op_id: int
    machine_id: int
    start_time: float
    end_time: float
    duration: float


class ScheduleOut(BaseModel):
    """排程方案及指标。"""

    items: List[ScheduleItemOut]
    makespan: float
    machine_utilization: List[float]
    max_load: float
    total_tardiness: float


class SolveResponse(BaseModel):
    """求解响应体。"""

    schedule_id: str
    instance_name: str
    algorithm: str
    makespan: float
    elapsed: float
    history: List[float]                    # 每代最优 Makespan
    avg_history: List[float]                # 每代平均 Makespan
    schedule: ScheduleOut


# ---------------------------------------------------------------------------
# 方案对比 / 插单 / 导出
# ---------------------------------------------------------------------------


class CompareRequest(BaseModel):
    """多方案对比请求体。"""

    schedule_ids: List[str]


class RescheduleJob(BaseModel):
    """插单新工件：job_id 从 num_jobs 起，逐道工序指定可选设备与时间。"""

    job_id: int
    due_date: float = float("inf")
    operations: List[OperationIn]


class RescheduleRequest(BaseModel):
    """插单重调度请求体。"""

    schedule_id: str
    new_job: RescheduleJob
    current_time: float = 0.0               # 当前时间点，之前已开工工序冻结
    mode: str = "freeze"                    # freeze 冻结重排 / full 完全重排

    @field_validator("mode")
    @classmethod
    def _mode(cls, v):
        if v not in ("freeze", "full"):
            raise ValueError("mode 必须为 freeze/full")
        return v


class InstanceMeta(BaseModel):
    """算例元信息（列表项）。"""

    name: str
    num_jobs: int
    num_machines: int
    total_operations: int
    avg_flexibility: float = 0.0
    known_best_makespan: Optional[float] = None
