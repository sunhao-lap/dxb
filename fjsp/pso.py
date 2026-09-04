#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离散粒子群算法求解 FJSP（模块 M3，算法 §4.4）。

工序排列属于离散组合空间，采用「基于交叉的离散 PSO」：将标准速度更新式
``V = w·V + c1·r1·(pbest−X) + c2·r2·(gbest−X)`` 中「向 pbest/gbest 靠拢」的
位移项，离散化为与个体最优 / 全局最优的 POX 交叉，惯性项保留自身并辅以变异：

- 惯性（概率 ∝ w）：保留当前位置，并小概率变异。
- 认知（概率 ∝ c1）：与个体最优 pbest 做 POX 交叉。
- 社会（概率 ∝ c2）：与全局最优 gbest 做 POX 交叉。

设备选择层同理：惯性随机重选，认知 / 社会继承 pbest / gbest 的设备分配。
接口：``solve_pso(instance, config) -> SolveResult``。
"""

from __future__ import annotations

import math
import random
import time
from typing import List

from .models import FJSPInstance, SolverConfig, SolveResult
from .decoder import decode
from .ga import (
    _random_sequence,
    _random_choices,
    _pox_crossover,
    _swap_mutate,
    _machine_mutate,
    _remap_choices,
)


class _Particle:
    """一个粒子：当前位置 + 个体最优。"""

    __slots__ = ("seq", "ch", "makespan", "pbest_seq", "pbest_ch", "pbest")

    def __init__(self, seq, ch, makespan):
        self.seq = seq
        self.ch = ch
        self.makespan = makespan
        self.pbest_seq = list(seq)
        self.pbest_ch = list(ch)
        self.pbest = makespan


def _inherit_choices(
    instance: FJSPInstance,
    seq,
    ch,
    donor_seq,
    donor_ch,
    prob: float,
    rng: random.Random,
) -> None:
    """对 seq 每道工序，以 prob 概率用 donor 的对应工序设备选择替换 ch（就地）。"""
    donor_count = [0] * instance.num_jobs
    donor_by_op = {}
    for pos, job_id in enumerate(donor_seq):
        op_id = donor_count[job_id]
        donor_count[job_id] += 1
        donor_by_op[(job_id, op_id)] = donor_ch[pos]

    op_count = [0] * instance.num_jobs
    for pos, job_id in enumerate(seq):
        op_id = op_count[job_id]
        op_count[job_id] += 1
        if rng.random() < prob:
            ch[pos] = donor_by_op[(job_id, op_id)]


def _move(
    instance: FJSPInstance,
    p: _Particle,
    gbest_seq: List[int],
    gbest_ch: List[int],
    w: float,
    c1: float,
    c2: float,
    rng: random.Random,
    mutation_rate: float,
):
    """按惯性 / 认知 / 社会三种方式之一更新粒子位置，返回 (新排列, 新设备选择)。"""
    total = w + c1 + c2
    r = rng.random() * total

    if r < w:                                   # 惯性：保留自身，轻微变异
        nseq = p.seq[:]
        nch = p.ch[:]
        if rng.random() < mutation_rate:
            _swap_mutate(instance, nseq, nch, rng)
        if rng.random() < mutation_rate:
            _machine_mutate(instance, nseq, nch, rng)
    elif r < w + c1:                            # 认知：向个体最优靠拢
        nseq, _ = _pox_crossover(p.seq, p.pbest_seq, rng)
        nch = _remap_choices(instance, p.seq, p.ch, nseq)
        _inherit_choices(instance, nseq, nch, p.pbest_seq, p.pbest_ch, 0.5, rng)
    else:                                       # 社会：向全局最优靠拢
        nseq, _ = _pox_crossover(p.seq, gbest_seq, rng)
        nch = _remap_choices(instance, p.seq, p.ch, nseq)
        _inherit_choices(instance, nseq, nch, gbest_seq, gbest_ch, 0.5, rng)

    return nseq, nch


def solve_pso(instance: FJSPInstance, config: SolverConfig) -> SolveResult:
    """离散 PSO 求解。"""
    rng = random.Random(config.random_seed)
    t0 = time.perf_counter()

    swarm_size = config.population_size
    w = config.pso_inertia
    c1 = config.pso_cognitive
    c2 = config.pso_social

    # 初始化粒子群
    particles: List[_Particle] = []
    gbest_seq: List[int] = []
    gbest_ch: List[int] = []
    gbest = math.inf

    for _ in range(swarm_size):
        seq = _random_sequence(instance, rng)
        ch = _random_choices(instance, seq, rng)
        makespan = decode(instance, seq, ch).makespan
        p = _Particle(seq, ch, makespan)
        particles.append(p)
        if makespan < gbest:
            gbest = makespan
            gbest_seq, gbest_ch = list(seq), list(ch)

    history: List[float] = []
    avg_history: List[float] = []

    for _ in range(config.max_iterations):
        gen_best = math.inf
        gen_sum = 0.0

        for p in particles:
            nseq, nch = _move(
                instance, p, gbest_seq, gbest_ch, w, c1, c2, rng, config.mutation_rate
            )
            nm = decode(instance, nseq, nch).makespan

            p.seq, p.ch, p.makespan = nseq, nch, nm
            if nm < p.pbest:
                p.pbest = nm
                p.pbest_seq = list(nseq)
                p.pbest_ch = list(nch)

            if nm < gen_best:
                gen_best = nm
            gen_sum += nm

        # 更新全局最优
        for p in particles:
            if p.pbest < gbest:
                gbest = p.pbest
                gbest_seq = list(p.pbest_seq)
                gbest_ch = list(p.pbest_ch)

        history.append(gen_best)
        avg_history.append(gen_sum / swarm_size)

    schedule = decode(instance, gbest_seq, gbest_ch)
    elapsed = time.perf_counter() - t0
    return SolveResult(
        schedule=schedule,
        history=history,
        avg_history=avg_history,
        elapsed=elapsed,
        best_operation_sequence=gbest_seq,
        best_machine_choices=gbest_ch,
    )
