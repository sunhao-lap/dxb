#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟退火求解 FJSP（模块 M3，算法 §4.3）。

- 初始解：随机工序排列 + 随机设备分配。
- 邻域操作（等概率三选一）：交换 / 插入 / 设备重选。
- 接受准则：Metropolis（更优直接接受，更差以 exp(-Δ/T) 概率接受）。
- 冷却策略：T ← α·T，α=0.95。
- 终止条件：达到最大迭代次数，或连续 50 次无改进。

接口：``solve_sa(instance, config) -> SolveResult``。
收敛历史 ``history`` 记录当前最优值（单调不增）。
"""

from __future__ import annotations

import math
import random
import time
from typing import List, Sequence, Tuple

from .models import FJSPInstance, SolverConfig, SolveResult
from .decoder import decode
from .ga import _random_sequence, _random_choices, _remap_choices


def _neighbor(
    instance: FJSPInstance,
    seq: Sequence[int],
    ch: Sequence[int],
    rng: random.Random,
) -> Tuple[List[int], List[int]]:
    """等概率执行三种邻域操作之一，返回新解（不修改入参）。"""
    seq = list(seq)
    ch = list(ch)
    old_seq, old_ch = list(seq), list(ch)
    op = rng.randrange(3)

    if op == 0:                       # 交换：交换两个位置，设备选择按工序重映射
        i = rng.randrange(len(seq))
        j = rng.randrange(len(seq))
        seq[i], seq[j] = seq[j], seq[i]
        ch = _remap_choices(instance, old_seq, old_ch, seq)
    elif op == 1:                     # 插入：将某位置工序插入到另一位置，设备选择重映射
        i = rng.randrange(len(seq))
        x = seq.pop(i)
        j = rng.randrange(len(seq) + 1)
        seq.insert(j, x)
        ch = _remap_choices(instance, old_seq, old_ch, seq)
    else:                             # 设备重选：随机更换某道工序的分配设备
        pos = rng.randrange(len(seq))
        job_id = seq[pos]
        op_id = seq[:pos].count(job_id)
        op = instance.get_operation(job_id, op_id)
        ch[pos] = rng.randrange(op.num_choices)

    return seq, ch


def solve_sa(instance: FJSPInstance, config: SolverConfig) -> SolveResult:
    """模拟退火求解。"""
    rng = random.Random(config.random_seed)
    t0 = time.perf_counter()

    seq = _random_sequence(instance, rng)
    ch = _random_choices(instance, seq, rng)
    current = decode(instance, seq, ch).makespan

    best_seq, best_ch = list(seq), list(ch)
    best = current
    temperature = config.sa_initial_temp

    history: List[float] = []
    avg_history: List[float] = []
    no_improve = 0

    for _ in range(config.sa_max_iterations):
        nseq, nch = _neighbor(instance, seq, ch, rng)
        new_makespan = decode(instance, nseq, nch).makespan
        delta = new_makespan - current

        if delta <= 0 or rng.random() < math.exp(-delta / temperature):
            seq, ch, current = nseq, nch, new_makespan
            if current < best:
                best, best_seq, best_ch = current, list(seq), list(ch)
                no_improve = 0
            else:
                no_improve += 1
        else:
            no_improve += 1

        temperature *= config.sa_cooling_rate
        history.append(best)          # 当前最优（单调不增）
        avg_history.append(current)   # 当前解

        if no_improve >= 50:          # 连续 50 次无改进提前终止
            break

    schedule = decode(instance, best_seq, best_ch)
    elapsed = time.perf_counter() - t0
    return SolveResult(
        schedule=schedule,
        history=history,
        avg_history=avg_history,
        elapsed=elapsed,
        best_operation_sequence=best_seq,
        best_machine_choices=best_ch,
    )
