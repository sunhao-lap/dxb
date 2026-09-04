#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
遗传算法求解 FJSP（模块 M3，算法 §4.2）。

- 编码：双层染色体 —— 工序排列（基于操作，工件号重复出现）+ 设备选择下标。
- 初始化：60% 随机，40% 启发式（SPT 最短加工时间优先）。
- 选择：锦标赛选择（k=3）。
- 交叉：工序层 POX（Precedence Operation Crossover），设备层均匀交叉。
- 变异：工序层交换变异，设备层在可选设备集合内随机重选。
- 适应度：1 / Makespan。精英保留前 10%。

接口：``solve_ga(instance, config) -> SolveResult``。
"""

from __future__ import annotations

import random
import time
from typing import List, Sequence, Tuple

from .models import FJSPInstance, Schedule, SolverConfig, SolveResult
from .decoder import decode

# 个体 = (工序排列, 设备选择下标, makespan)
_Individual = Tuple[List[int], List[int], float]


def _random_sequence(instance: FJSPInstance, rng: random.Random) -> List[int]:
    """生成随机工序排列：每个工件号出现 num_operations 次。"""
    seq: List[int] = []
    for job in instance.jobs:
        seq.extend([job.job_id] * job.num_operations)
    rng.shuffle(seq)
    return seq


def _random_choices(instance: FJSPInstance, seq: Sequence[int], rng: random.Random) -> List[int]:
    """为给定排列随机选择设备（每个工序在可选设备中随机选一个下标）。"""
    op_count = [0] * instance.num_jobs
    choices: List[int] = []
    for job_id in seq:
        op = instance.get_operation(job_id, op_count[job_id])
        op_count[job_id] += 1
        choices.append(rng.randrange(op.num_choices))
    return choices


def _spt_sequence(instance: FJSPInstance) -> List[int]:
    """SPT 启发式排列：按各工序最短加工时间升序排列工件号。"""
    entries: List[Tuple[float, int]] = []
    for job in instance.jobs:
        for op in job.operations:
            entries.append((min(op.processing_times), job.job_id))
    entries.sort(key=lambda x: x[0])
    return [job_id for _, job_id in entries]


def _init_population(
    instance: FJSPInstance,
    config: SolverConfig,
    rng: random.Random,
    decode_fn=decode,
) -> List[_Individual]:
    """60% 随机 + 40% SPT 启发式初始化。"""
    pop: List[_Individual] = []
    n_heuristic = int(config.population_size * 0.4)
    spt_seq = _spt_sequence(instance)

    for i in range(config.population_size):
        if i < n_heuristic:
            seq = list(spt_seq)
            rng.shuffle(seq)  # 轻微扰动，保持启发式基调
        else:
            seq = _random_sequence(instance, rng)
        ch = _random_choices(instance, seq, rng)
        makespan = decode_fn(instance, seq, ch).makespan
        pop.append((seq, ch, makespan))

    return pop


def _tournament_select(pop: Sequence[_Individual], k: int, rng: random.Random) -> _Individual:
    """锦标赛选择：随机取 k 个，返回 makespan 最小者。"""
    best = rng.choice(pop)
    for _ in range(k - 1):
        cand = rng.choice(pop)
        if cand[2] < best[2]:
            best = cand
    return best


def _pox_crossover(
    p1: Sequence[int], p2: Sequence[int], rng: random.Random
) -> Tuple[List[int], List[int]]:
    """
    POX 交叉：随机划分工件集合为 J1，子代中 J1 元素继承父 1 的位置，
    其余元素按父 2 顺序填入；另一子代对称。
    """
    jobs = list(range(max(p1) + 1))
    rng.shuffle(jobs)
    split = rng.randint(1, len(jobs) - 1)
    j1 = set(jobs[:split])

    def pox(a: Sequence[int], b: Sequence[int]) -> List[int]:
        child = [-1] * len(a)
        for i, x in enumerate(a):
            if x in j1:
                child[i] = x
        fill = [x for x in b if x not in j1]
        idx = 0
        for i in range(len(child)):
            if child[i] == -1:
                child[i] = fill[idx]
                idx += 1
        return child

    return pox(p1, p2), pox(p2, p1)


def _swap_mutate(instance: FJSPInstance, seq: List[int], ch: List[int], rng: random.Random) -> None:
    """交换变异：交换两个位置后，按工序重映射设备选择。

    交换会改变被交换工件的「出现次序」（op_id），因此不能简单同步交换
    ``ch``，而须以「工序 -> 设备选择」为纽带整体重映射。
    """
    old_seq = list(seq)
    old_ch = list(ch)
    i = rng.randrange(len(seq))
    j = rng.randrange(len(seq))
    seq[i], seq[j] = seq[j], seq[i]
    ch[:] = _remap_choices(instance, old_seq, old_ch, seq)


def _machine_mutate(instance: FJSPInstance, seq: Sequence[int], ch: List[int], rng: random.Random) -> None:
    """设备变异：随机选一个工序，在其可选设备集合内随机重选。"""
    pos = rng.randrange(len(seq))
    job_id = seq[pos]
    # 统计该位置对应的 op_id（第几次出现）
    op_id = seq[:pos].count(job_id)
    op = instance.get_operation(job_id, op_id)
    ch[pos] = rng.randrange(op.num_choices)


def _remap_choices(
    instance: FJSPInstance,
    parent_seq: Sequence[int],
    parent_ch: Sequence[int],
    child_seq: Sequence[int],
) -> List[int]:
    """把父代的设备选择按工序继承并重映射到子代排列上。

    POX 交叉改变了工序顺序，而设备选择应跟随工序（而非位置），
    故按 ``(job_id, op_id)`` 建映射，再按子代顺序重排，保证 ``ch[i]`` 对
    ``child_seq[i]`` 的工序始终合法。
    """
    op_count = [0] * instance.num_jobs
    choice_by_op = {}
    for pos, job_id in enumerate(parent_seq):
        op_id = op_count[job_id]
        op_count[job_id] += 1
        choice_by_op[(job_id, op_id)] = parent_ch[pos]

    op_count = [0] * instance.num_jobs
    child_ch: List[int] = []
    for job_id in child_seq:
        op_id = op_count[job_id]
        op_count[job_id] += 1
        child_ch.append(choice_by_op[(job_id, op_id)])
    return child_ch


def _machine_crossover(
    instance: FJSPInstance,
    seq1: Sequence[int],
    ch1: List[int],
    seq2: Sequence[int],
    ch2: List[int],
    rng: random.Random,
) -> None:
    """设备层均匀交叉：按工序（job_id, op_id）配对，0.5 概率交换两个体的选择。

    由于 seq1 与 seq2 是同一问题的合法排列，包含相同的工序多重集，
    先建立 seq2 的「工序 -> 位置」映射，再对 seq1 每道工序配对交换。
    """
    op_count2 = [0] * instance.num_jobs
    pos2_by_op = {}
    for pos, job_id in enumerate(seq2):
        op_id = op_count2[job_id]
        op_count2[job_id] += 1
        pos2_by_op[(job_id, op_id)] = pos

    op_count1 = [0] * instance.num_jobs
    for pos, job_id in enumerate(seq1):
        op_id = op_count1[job_id]
        op_count1[job_id] += 1
        pos2 = pos2_by_op[(job_id, op_id)]
        if rng.random() < 0.5:
            ch1[pos], ch2[pos2] = ch2[pos2], ch1[pos]


def solve_ga(instance: FJSPInstance, config: SolverConfig, decode_fn=decode) -> SolveResult:
    """遗传算法求解，返回最优方案与收敛历史。

    可通过 ``decode_fn`` 注入带约束（如插单冻结）的自定义解码器。
    """
    rng = random.Random(config.random_seed)
    t0 = time.perf_counter()

    population = _init_population(instance, config, rng, decode_fn)
    best = min(population, key=lambda x: x[2])

    history: List[float] = []
    avg_history: List[float] = []
    elite_n = max(1, int(config.population_size * config.elite_rate))

    for _ in range(config.max_iterations):
        # 精英保留
        population.sort(key=lambda x: x[2])
        offspring: List[_Individual] = population[:elite_n]

        while len(offspring) < config.population_size:
            p1 = _tournament_select(population, k=3, rng=rng)
            p2 = _tournament_select(population, k=3, rng=rng)

            if rng.random() < config.crossover_rate:
                seq1, seq2 = _pox_crossover(p1[0], p2[0], rng)
                # 设备选择跟随工序重映射，再做工序级均匀交叉
                ch1 = _remap_choices(instance, p1[0], p1[1], seq1)
                ch2 = _remap_choices(instance, p2[0], p2[1], seq2)
                _machine_crossover(instance, seq1, ch1, seq2, ch2, rng)
            else:
                seq1, seq2 = p1[0][:], p2[0][:]
                ch1, ch2 = p1[1][:], p2[1][:]

            # 工序层变异
            if rng.random() < config.mutation_rate:
                _swap_mutate(instance, seq1, ch1, rng)
            if rng.random() < config.mutation_rate:
                _swap_mutate(instance, seq2, ch2, rng)
            # 设备层变异
            if rng.random() < config.mutation_rate:
                _machine_mutate(instance, seq1, ch1, rng)
            if rng.random() < config.mutation_rate:
                _machine_mutate(instance, seq2, ch2, rng)

            m1 = decode_fn(instance, seq1, ch1).makespan
            m2 = decode_fn(instance, seq2, ch2).makespan
            offspring.append((seq1, ch1, m1))
            offspring.append((seq2, ch2, m2))

        offspring = offspring[: config.population_size]
        population = offspring
        candidate = min(population, key=lambda x: x[2])
        if candidate[2] < best[2]:
            best = candidate

        gen_best = min(x[2] for x in population)
        gen_avg = sum(x[2] for x in population) / len(population)
        history.append(gen_best)
        avg_history.append(gen_avg)

    schedule = decode_fn(instance, best[0], best[1])
    elapsed = time.perf_counter() - t0
    return SolveResult(
        schedule=schedule,
        history=history,
        avg_history=avg_history,
        elapsed=elapsed,
        best_operation_sequence=best[0],
        best_machine_choices=best[1],
    )
