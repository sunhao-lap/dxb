#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
求解服务与方案存储（模块 M1/M2/M3/M4 的后端封装）。

- 标准算例列表读取（data/processed/index.json）
- 标准 / 自定义算例加载
- 调度求解（封装 fjsp 算法包）
- 求解结果的内存存储与检索（供对比 / 插单 / 导出）
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from fjsp import (
    FJSPInstance,
    Job,
    Operation,
    SolverConfig,
    SolveResult,
    from_dict,
    load_instance,
    solve_ga,
    solve_sa,
    solve_pso,
    solve_hybrid,
)
from fjsp.models import Schedule

from .schemas import (
    CustomInstanceIn,
    InstanceMeta,
    ScheduleItemOut,
    ScheduleOut,
    SolveConfigIn,
    SolveResponse,
)

# 项目根（backend/ 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "processed"

_SOLVERS = {
    "ga": solve_ga,
    "sa": solve_sa,
    "pso": solve_pso,
    "hybrid": solve_hybrid,
}

# 自定义算例（内存注册，name -> FJSPInstance）
_custom_instances: Dict[str, FJSPInstance] = {}

# 已求解方案存储：schedule_id -> 完整上下文
_store: Dict[str, dict] = {}


# ---------------------------------------------------------------------------
# 算例管理（M1）
# ---------------------------------------------------------------------------


def list_instances() -> List[InstanceMeta]:
    """返回标准算例元信息列表（含自定义算例）。"""
    metas: List[InstanceMeta] = []
    idx_path = DATA_DIR / "index.json"
    if idx_path.exists():
        for item in json.loads(idx_path.read_text(encoding="utf-8")):
            metas.append(InstanceMeta(**item))

    for name, inst in _custom_instances.items():
        metas.append(
            InstanceMeta(
                name=name,
                num_jobs=inst.num_jobs,
                num_machines=inst.num_machines,
                total_operations=inst.total_operations,
                avg_flexibility=0.0,
                known_best_makespan=None,
            )
        )
    return metas


def load_instance_by_name(name: str) -> FJSPInstance:
    """加载算例：优先自定义，其次标准算例。"""
    if name in _custom_instances:
        return _custom_instances[name]
    path = DATA_DIR / f"{name.lower()}.json"
    if not path.exists():
        raise KeyError(f"算例 {name!r} 不存在")
    return load_instance(path)


def register_custom_instance(data: CustomInstanceIn) -> FJSPInstance:
    """注册自定义算例（0 基设备号），并做完整性校验。"""
    jobs: List[Job] = []
    for j in data.jobs:
        ops: List[Operation] = []
        for op_id, op in enumerate(j.operations):
            for m in op.eligible_machines:
                if not (0 <= m < data.num_machines):
                    raise ValueError(
                        f"工件 {j.job_id} 工序 {op_id} 设备号 {m} 越界"
                        f"（应为 0..{data.num_machines - 1}）"
                    )
            ops.append(
                Operation(
                    job_id=j.job_id,
                    op_id=op_id,
                    eligible_machines=list(op.eligible_machines),
                    processing_times=list(op.processing_times),
                )
            )
        jobs.append(Job(job_id=j.job_id, operations=ops, due_date=j.due_date))

    inst = FJSPInstance(
        name=data.name,
        num_jobs=data.num_jobs,
        num_machines=data.num_machines,
        jobs=jobs,
    )
    _custom_instances[data.name] = inst
    return inst


# ---------------------------------------------------------------------------
# 调度求解（M2/M3/M4）
# ---------------------------------------------------------------------------


def _schedule_to_out(schedule: Schedule) -> ScheduleOut:
    """把内部 Schedule 转换为响应模型。"""
    return ScheduleOut(
        items=[
            ScheduleItemOut(
                job_id=it.job_id,
                op_id=it.op_id,
                machine_id=it.machine_id,
                start_time=it.start_time,
                end_time=it.end_time,
                duration=it.end_time - it.start_time,
            )
            for it in schedule.items
        ],
        makespan=schedule.makespan,
        machine_utilization=schedule.machine_utilization,
        max_load=schedule.max_load,
        total_tardiness=schedule.total_tardiness,
    )


def solve(instance_name: str, config_in: SolveConfigIn) -> SolveResponse:
    """执行调度求解，存储结果并返回响应。"""
    instance = load_instance_by_name(instance_name)
    cfg = SolverConfig(**config_in.model_dump())
    result: SolveResult = _SOLVERS[cfg.algorithm](instance, cfg)

    schedule_id = uuid.uuid4().hex[:12]
    _store[schedule_id] = {
        "instance": instance,
        "instance_name": instance_name,
        "algorithm": cfg.algorithm,
        "result": result,
        "config": cfg,
    }

    return SolveResponse(
        schedule_id=schedule_id,
        instance_name=instance_name,
        algorithm=cfg.algorithm,
        makespan=result.schedule.makespan,
        elapsed=result.elapsed,
        history=result.history,
        avg_history=result.avg_history,
        schedule=_schedule_to_out(result.schedule),
    )


# ---------------------------------------------------------------------------
# 方案检索
# ---------------------------------------------------------------------------


def get_stored(schedule_id: str) -> dict:
    """按 ID 取已存储方案上下文，不存在则抛 KeyError。"""
    if schedule_id not in _store:
        raise KeyError(f"方案 {schedule_id!r} 不存在")
    return _store[schedule_id]


def get_schedule(schedule_id: str) -> Schedule:
    """取方案明细（Schedule 对象）。"""
    return get_stored(schedule_id)["result"].schedule


def get_schedule_out(schedule_id: str) -> ScheduleOut:
    """取方案明细（响应模型）。"""
    return _schedule_to_out(get_schedule(schedule_id))


def store_schedule(
    schedule_id: str,
    instance: FJSPInstance,
    algorithm: str,
    result: SolveResult,
    instance_name: str,
) -> None:
    """供插单模块存储重调度结果。"""
    _store[schedule_id] = {
        "instance": instance,
        "instance_name": instance_name,
        "algorithm": algorithm,
        "result": result,
        "config": None,
    }
