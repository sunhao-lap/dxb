#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主动调度解码与指标计算（模块 M4 方案解码）。

将染色体（工序排列 + 设备选择）转换为可执行的排程方案，并计算评估指标
（Makespan / 设备利用率 / 最大负载 / 总拖期）。算法见《方案设计说明书》§4.6。

染色体约定（与 §4.2 一致）：
- ``operation_sequence``：基于操作的排列，长度为总工序数，每个元素是工件号（0 基），
  工件号出现的次数等于该工件的工序数；按出现顺序即工序顺序。
- ``machine_choices``：长度同为总工序数，第 i 个元素是 operation_sequence[i]
  对应工序在「可选设备列表」中的下标（choice index），而非绝对设备号。
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from .models import FJSPInstance, Schedule, ScheduleItem


def _find_earliest_slot(
    intervals: Sequence[Tuple[float, float]], earliest: float, duration: float
) -> float:
    """
    在已排时间段 ``intervals``（按 start 升序）中，为时长为 ``duration`` 的工序
    寻找不早于 ``earliest`` 的最早可插入空闲时段的起始时间（主动调度）。
    """
    start = earliest
    for s, e in intervals:
        if start + duration <= s:
            return start          # 当前空隙放得下
        if start < e:
            start = e             # 与 (s, e) 重叠，右移到该段之后
    return start


def decode(
    instance: FJSPInstance,
    operation_sequence: Sequence[int],
    machine_choices: Sequence[int],
) -> Schedule:
    """
    主动调度解码：按工序排列顺序逐道工序，在分配设备上寻找最早可插入空闲时段。

    返回含调度明细与各项指标的 ``Schedule``。
    """
    n = instance.num_jobs
    m = instance.num_machines

    # 每台设备已排时间段（按 start 升序），用于空隙插入
    machine_intervals: List[List[Tuple[float, float]]] = [[] for _ in range(m)]
    # 每个工件上一道工序的完成时间（前序约束）
    job_last_finish = [0.0] * n
    # 每个工件已排到的工序计数（把 job_id 出现映射为具体 op_id）
    job_op_count = [0] * n
    # 每个工件的最后完成时间（用于交期/拖期）
    job_finish = [0.0] * n

    items: List[ScheduleItem] = []
    machine_load = [0.0] * m

    for pos, job_id in enumerate(operation_sequence):
        op_id = job_op_count[job_id]
        job_op_count[job_id] += 1

        op = instance.get_operation(job_id, op_id)
        choice = machine_choices[pos]
        machine = op.eligible_machines[choice]
        duration = op.processing_times[choice]

        earliest = job_last_finish[job_id]
        start = _find_earliest_slot(machine_intervals[machine], earliest, duration)
        end = start + duration

        # 插入并保持按 start 升序
        intervals = machine_intervals[machine]
        intervals.append((start, end))
        intervals.sort()

        items.append(
            ScheduleItem(
                job_id=job_id, op_id=op_id, machine_id=machine,
                start_time=start, end_time=end,
            )
        )
        job_last_finish[job_id] = end
        job_finish[job_id] = end
        machine_load[machine] += duration

    makespan = max((it.end_time for it in items), default=0.0)
    machine_utilization = [
        load / makespan if makespan > 0 else 0.0 for load in machine_load
    ]
    max_load = max(machine_load, default=0.0)

    total_tardiness = 0.0
    for job in instance.jobs:
        finish = job_finish[job.job_id]
        total_tardiness += max(0.0, finish - job.due_date)

    return Schedule(
        items=items,
        makespan=makespan,
        machine_utilization=machine_utilization,
        max_load=max_load,
        total_tardiness=total_tardiness,
    )
