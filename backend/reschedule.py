#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
插单重调度模块（M7，对应设计说明书 §3.7）。

两种模式：
- ``freeze`` 冻结重排：当前时间点之前已开工的工序保持不动，仅对未开工工序
  与新工单工序在冻结占用之后的空间内重调度（稳定性优先）。
- ``full``   完全重排：不冻结，把新工单并入原算例整体重新求解。

输出新方案，并给出与原方案的差异（新增工序 / 移动工序 / 受影响设备）。
"""

from __future__ import annotations

import math
import time
import uuid
from typing import Callable, Dict, List, Tuple

from fjsp import FJSPInstance, Job, Operation, Schedule, ScheduleItem, SolverConfig
from fjsp.decoder import _find_earliest_slot
from fjsp.ga import solve_ga

from .schemas import RescheduleJob, RescheduleRequest


def _frozen_split(
    schedule: Schedule, current_time: float
) -> Tuple[List[ScheduleItem], List[ScheduleItem]]:
    """把方案按当前时间拆分为「冻结」与「待重排」两组。"""
    frozen = [it for it in schedule.items if it.start_time < current_time]
    pending = [it for it in schedule.items if it.start_time >= current_time]
    return frozen, pending


def _build_instance(
    instance: FJSPInstance,
    new_job: RescheduleJob,
    frozen: List[ScheduleItem],
    current_time: float,
) -> Tuple[FJSPInstance, Dict[int, int], Dict[int, float]]:
    """
    构造重排子问题实例（仅含未冻结工序 + 新工单），返回：
        (新实例, 新 job_id -> 原 job_id 映射, 新 job_id -> 就绪时间)
    """
    # 每个原工件的冻结工序数（前序约束保证冻结的是前缀）
    frozen_count: Dict[int, int] = {}
    frozen_end: Dict[int, float] = {}
    for it in frozen:
        frozen_count[it.job_id] = max(frozen_count.get(it.job_id, 0), it.op_id + 1)
        frozen_end[it.job_id] = max(frozen_end.get(it.job_id, 0.0), it.end_time)

    new_jobs: List[Job] = []
    job_map: Dict[int, int] = {}
    job_ready: Dict[int, float] = {}
    new_job_id = 0

    for job in instance.jobs:
        k = frozen_count.get(job.job_id, 0)
        if k >= job.num_operations:
            continue                       # 该工件已全部冻结，无需重排
        ops = [
            Operation(
                job_id=new_job_id,
                op_id=op.op_id,            # 保留原 op_id，便于差异比对
                eligible_machines=list(op.eligible_machines),
                processing_times=list(op.processing_times),
            )
            for op in job.operations[k:]
        ]
        new_jobs.append(Job(job_id=new_job_id, operations=ops, due_date=job.due_date))
        job_map[new_job_id] = job.job_id
        job_ready[new_job_id] = max(frozen_end.get(job.job_id, 0.0), current_time)
        new_job_id += 1

    # 新工单（job_id 用其自带的 id，映射时保持原样）
    new_ops = [
        Operation(
            job_id=new_job_id,
            op_id=i,
            eligible_machines=list(op.eligible_machines),
            processing_times=list(op.processing_times),
        )
        for i, op in enumerate(new_job.operations)
    ]
    new_jobs.append(Job(job_id=new_job_id, operations=new_ops, due_date=new_job.due_date))
    job_map[new_job_id] = new_job.job_id
    job_ready[new_job_id] = current_time

    new_instance = FJSPInstance(
        name=instance.name + "-resched",
        num_jobs=len(new_jobs),
        num_machines=instance.num_machines,
        jobs=new_jobs,
    )
    return new_instance, job_map, job_ready


def _make_frozen_decoder(
    instance: FJSPInstance,
    frozen: List[ScheduleItem],
    job_ready: Dict[int, float],
) -> Callable[[FJSPInstance, List[int], List[int]], Schedule]:
    """构造带冻结占用与就绪时间的解码器闭包。"""
    frozen_intervals: List[List[Tuple[float, float]]] = [
        [] for _ in range(instance.num_machines)
    ]
    for it in frozen:
        frozen_intervals[it.machine_id].append((it.start_time, it.end_time))
    for iv in frozen_intervals:
        iv.sort()
    frozen_max_end = max((it.end_time for it in frozen), default=0.0)

    def decode_frozen(_inst, seq, ch) -> Schedule:
        intervals = [list(iv) for iv in frozen_intervals]
        job_last_finish = [job_ready.get(j, 0.0) for j in range(_inst.num_jobs)]
        job_op_count = [0] * _inst.num_jobs
        job_finish = [0.0] * _inst.num_jobs
        items: List[ScheduleItem] = []
        machine_load = [0.0] * _inst.num_machines

        for pos, job_id in enumerate(seq):
            op_id = job_op_count[job_id]
            job_op_count[job_id] += 1
            op = _inst.get_operation(job_id, op_id)
            choice = ch[pos]
            machine = op.eligible_machines[choice]
            duration = op.processing_times[choice]
            start = _find_earliest_slot(intervals[machine], job_last_finish[job_id], duration)
            end = start + duration
            intervals[machine].append((start, end))
            intervals[machine].sort()
            items.append(
                ScheduleItem(
                    job_id=job_id, op_id=op_id, machine_id=machine,
                    start_time=start, end_time=end,
                )
            )
            job_last_finish[job_id] = end
            job_finish[job_id] = end
            machine_load[machine] += duration

        makespan = max([it.end_time for it in items] + [frozen_max_end])
        machine_utilization = [
            load / makespan if makespan > 0 else 0.0 for load in machine_load
        ]
        return Schedule(
            items=items,
            makespan=makespan,
            machine_utilization=machine_utilization,
            max_load=max(machine_load, default=0.0),
            total_tardiness=0.0,
        )

    return decode_frozen


def _diff(
    original: Schedule,
    new_items: List[ScheduleItem],
    job_map: Dict[int, int],
    new_job_original_id: int,
) -> dict:
    """生成差异说明：新增 / 移动工序、受影响设备。"""
    # 原工序键 -> (machine, start, end)
    old_by_key = {
        (it.job_id, it.op_id): (it.machine_id, it.start_time, it.end_time)
        for it in original.items
    }

    new_operations: List[dict] = []
    moved_operations: List[dict] = []
    affected_machines = set()

    for it in new_items:
        orig_job = job_map.get(it.job_id, it.job_id)
        if orig_job == new_job_original_id:
            new_operations.append(
                {"job_id": orig_job, "op_id": it.op_id, "machine_id": it.machine_id,
                 "start_time": it.start_time, "end_time": it.end_time}
            )
            continue

        key = (orig_job, it.op_id)
        if key in old_by_key:
            old_m, old_s, old_e = old_by_key[key]
            if old_m != it.machine_id or abs(old_s - it.start_time) > 1e-9:
                moved_operations.append(
                    {"job_id": orig_job, "op_id": it.op_id,
                     "machine_id": (old_m, it.machine_id),
                     "start_time": (old_s, it.start_time)}
                )
                affected_machines.update((old_m, it.machine_id))

    summary = (
        f"插入新工单（job_id={new_job_original_id}，{len(new_operations)} 道工序），"
        f"移动 {len(moved_operations)} 道工序，"
        f"受影响设备 {len(affected_machines)} 台。"
    )
    return {
        "summary": summary,
        "new_operations": new_operations,
        "moved_operations": moved_operations,
        "affected_machines": sorted(affected_machines),
    }


def reschedule(stored: dict, request: RescheduleRequest) -> dict:
    """执行插单重调度，返回新方案与差异。"""
    instance: FJSPInstance = stored["instance"]
    original: Schedule = stored["result"].schedule
    new_job = request.new_job

    t0 = time.perf_counter()
    if request.mode == "full":
        # 完全重排：新工单并入原算例整体求解
        merged_jobs = list(instance.jobs) + [
            Job(
                job_id=instance.num_jobs,
                operations=[
                    Operation(job_id=instance.num_jobs, op_id=i,
                              eligible_machines=list(op.eligible_machines),
                              processing_times=list(op.processing_times))
                    for i, op in enumerate(new_job.operations)
                ],
                due_date=new_job.due_date,
            )
        ]
        merged = FJSPInstance(
            name=instance.name + "-merged", num_jobs=instance.num_jobs + 1,
            num_machines=instance.num_machines, jobs=merged_jobs,
        )
        cfg = SolverConfig(algorithm="ga", population_size=60, max_iterations=150,
                           random_seed=42)
        result = solve_ga(merged, cfg)
        new_items = result.schedule.items
        job_map = {j: j for j in range(merged.num_jobs)}
        new_job_original_id = instance.num_jobs
        makespan = result.schedule.makespan
    else:
        # 冻结重排
        frozen, _pending = _frozen_split(original, request.current_time)
        new_inst, job_map, job_ready = _build_instance(
            instance, new_job, frozen, request.current_time
        )
        # 每个原工件的冻结工序数（解码器按出现位置重排 op_id，需据此还原原编号）
        frozen_count: Dict[int, int] = {}
        for it in frozen:
            frozen_count[it.job_id] = max(frozen_count.get(it.job_id, 0), it.op_id + 1)

        decoder = _make_frozen_decoder(instance, frozen, job_ready)
        cfg = SolverConfig(algorithm="ga", population_size=60, max_iterations=150,
                           random_seed=42)
        result = solve_ga(new_inst, cfg, decode_fn=decoder)
        # 合并冻结工序 + 新排工序，并把 job_id / op_id 映射回原始编号
        mapped_items: List[ScheduleItem] = []
        for it in result.schedule.items:
            orig_job = job_map.get(it.job_id, it.job_id)
            if orig_job == new_job.job_id:
                op_id = it.op_id                       # 新工单保持 0 基编号
            else:
                op_id = it.op_id + frozen_count.get(orig_job, 0)
            mapped_items.append(
                ScheduleItem(
                    job_id=orig_job, op_id=op_id,
                    machine_id=it.machine_id,
                    start_time=it.start_time, end_time=it.end_time,
                )
            )
        new_items = frozen + mapped_items
        makespan = max(it.end_time for it in new_items)
        new_job_original_id = new_job.job_id

    elapsed = time.perf_counter() - t0
    diff = _diff(original, new_items, job_map, new_job_original_id)

    # 合并后重算指标
    machine_load = [0.0] * instance.num_machines
    for it in new_items:
        machine_load[it.machine_id] += it.duration
    util = [load / makespan if makespan > 0 else 0.0 for load in machine_load]

    schedule_id = uuid.uuid4().hex[:12]
    from .service import store_schedule
    # 存储重排方案（instance 用原实例引用即可，供后续导出）
    store_schedule(schedule_id, instance, "reschedule", result, stored["instance_name"])

    return {
        "schedule_id": schedule_id,
        "instance_name": stored["instance_name"],
        "mode": request.mode,
        "makespan": makespan,
        "elapsed": elapsed,
        "schedule": {
            "items": [
                {"job_id": it.job_id, "op_id": it.op_id, "machine_id": it.machine_id,
                 "start_time": it.start_time, "end_time": it.end_time,
                 "duration": it.duration}
                for it in new_items
            ],
            "makespan": makespan,
            "machine_utilization": util,
            "max_load": max(machine_load, default=0.0),
            "total_tardiness": 0.0,
        },
        "diff": diff,
    }
