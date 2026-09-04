#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
混合遗传算法求解 FJSP（模块 M3，算法 §4.5）。

以遗传算法为主框架（选择 / POX 交叉 / 变异 / 精英保留），每一代对精英前
``elite_rate`` 的个体追加模拟退火局部搜索（``hybrid_sa_steps`` 步 Metropolis
邻域探索），兼顾 GA 的全局搜索与 SA 的局部求精能力。

接口：``solve_hybrid(instance, config) -> SolveResult``。
"""

from __future__ import annotations

import math
import random
import time
from typing import List, Sequence, Tuple

from .models import FJSPInstance, SolverConfig, SolveResult
from .decoder import decode
from .ga import (
    _random_sequence,
    _random_choices,
    _spt_sequence,
    _init_population,
    _tournament_select,
    _pox_crossover,
    _swap_mutate,
    _machine_mutate,
    _remap_choices,
    _machine_crossover,
)
from .sa import _neighbor

# 个体 = (工序排列, 设备选择下标, makespan)
_Individual = Tuple[List[int], List[int], float]


def _local_search(
    instance: FJSPInstance,
    seq: Sequence[int],
    ch: Sequence[int],
    config: SolverConfig,
    rng: random.Random,
) -> _Individual:
    """对单个精英个体做 SA 局部搜索，返回（可能）改进后的个体。"""
    cur_seq, cur_ch = list(seq), list(ch)
    cur = decode(instance, cur_seq, cur_ch).makespan
    best_seq, best_ch, best = cur_seq, cur_ch, cur
    temperature = config.sa_initial_temp

    for _ in range(config.hybrid_sa_steps):
        nseq, nch = _neighbor(instance, cur_seq, cur_ch, rng)
        nm = decode(instance, nseq, nch).makespan
        delta = nm - cur
        if delta <= 0 or rng.random() < math.exp(-delta / temperature):
            cur_seq, cur_ch, cur = nseq, nch, nm
            if cur < best:
                best_seq, best_ch, best = list(cur_seq), list(cur_ch), cur
        temperature *= config.sa_cooling_rate

    return best_seq, best_ch, best


def solve_hybrid(instance: FJSPInstance, config: SolverConfig) -> SolveResult:
    """混合遗传算法求解。"""
    rng = random.Random(config.random_seed)
    t0 = time.perf_counter()

    population = _init_population(instance, config, rng)
    best = min(population, key=lambda x: x[2])

    history: List[float] = []
    avg_history: List[float] = []
    elite_n = max(1, int(config.population_size * config.elite_rate))
    local_n = max(1, int(config.population_size * config.elite_rate))

    for _ in range(config.max_iterations):
        # 精英保留
        population.sort(key=lambda x: x[2])
        offspring: List[_Individual] = population[:elite_n]

        while len(offspring) < config.population_size:
            p1 = _tournament_select(population, k=3, rng=rng)
            p2 = _tournament_select(population, k=3, rng=rng)

            if rng.random() < config.crossover_rate:
                seq1, seq2 = _pox_crossover(p1[0], p2[0], rng)
                ch1 = _remap_choices(instance, p1[0], p1[1], seq1)
                ch2 = _remap_choices(instance, p2[0], p2[1], seq2)
                _machine_crossover(instance, seq1, ch1, seq2, ch2, rng)
            else:
                seq1, seq2 = p1[0][:], p2[0][:]
                ch1, ch2 = p1[1][:], p2[1][:]

            if rng.random() < config.mutation_rate:
                _swap_mutate(instance, seq1, ch1, rng)
            if rng.random() < config.mutation_rate:
                _swap_mutate(instance, seq2, ch2, rng)
            if rng.random() < config.mutation_rate:
                _machine_mutate(instance, seq1, ch1, rng)
            if rng.random() < config.mutation_rate:
                _machine_mutate(instance, seq2, ch2, rng)

            m1 = decode(instance, seq1, ch1).makespan
            m2 = decode(instance, seq2, ch2).makespan
            offspring.append((seq1, ch1, m1))
            offspring.append((seq2, ch2, m2))

        offspring = offspring[: config.population_size]
        population = offspring

        # 对精英前 local_n 个追加 SA 局部搜索
        population.sort(key=lambda x: x[2])
        for i in range(local_n):
            population[i] = _local_search(instance, population[i][0], population[i][1], config, rng)

        candidate = min(population, key=lambda x: x[2])
        if candidate[2] < best[2]:
            best = candidate

        gen_best = min(x[2] for x in population)
        gen_avg = sum(x[2] for x in population) / len(population)
        history.append(gen_best)
        avg_history.append(gen_avg)

    schedule = decode(instance, best[0], best[1])
    elapsed = time.perf_counter() - t0
    return SolveResult(
        schedule=schedule,
        history=history,
        avg_history=avg_history,
        elapsed=elapsed,
        best_operation_sequence=best[0],
        best_machine_choices=best[1],
    )
