#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
算法模块单元测试（对应《方案设计说明书》§8.2，UT-01 ~ UT-10）。

运行方式（在项目根目录 SmartFJSP/ 下）：
    python -m unittest discover -s tests -v
    # 或安装 pytest 后： pytest tests/

说明：
- 采用标准库 unittest 编写（设计说明书建议 Pytest，unittest 用例可被 Pytest 直接收集）。
- UT-01 中设计说明书"工序总数=26"为笔误，FT06 实际为 6×6=36 道工序（见
  data/preprocess.py 的 self_test 断言），此处按真实值 36 断言。
- UT-09（插单）、UT-10（CSV 导出）依赖后端/数据层模块（backend.reschedule、
  backend.export），相关模块开发后已补全为真实断言。
"""

import sys
import unittest
from pathlib import Path

# 使测试可导入项目包 fjsp 与 data/preprocess
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

import preprocess as pp  # noqa: E402  data/preprocess.py
from fjsp import (  # noqa: E402
    FJSPInstance,
    Job,
    Operation,
    SolverConfig,
    load_instance_by_name,
    decode,
    solve_ga,
    solve_sa,
    solve_pso,
    solve_hybrid,
)
from fjsp.ga import (  # noqa: E402
    _init_population,
    _random_sequence,
    _random_choices,
    _pox_crossover,
)


def _make_2x2_instance() -> FJSPInstance:
    """构造确定性 2 工件 × 2 设备实例（用于 UT-05 / UT-08 手算验证）。"""
    jobs = [
        Job(
            job_id=0,
            operations=[
                Operation(job_id=0, op_id=0, eligible_machines=[0], processing_times=[3.0]),
                Operation(job_id=0, op_id=1, eligible_machines=[1], processing_times=[4.0]),
            ],
        ),
        Job(
            job_id=1,
            due_date=4.0,                       # 交期 4，用于拖期断言
            operations=[
                Operation(job_id=1, op_id=0, eligible_machines=[1], processing_times=[2.0]),
                Operation(job_id=1, op_id=1, eligible_machines=[0], processing_times=[5.0]),
            ],
        ),
    ]
    return FJSPInstance(name="toy2x2", num_jobs=2, num_machines=2, jobs=jobs)


def _is_legal_sequence(instance: FJSPInstance, seq) -> bool:
    """合法工序排列：每个工件号出现的次数等于其工序数。"""
    for job in instance.jobs:
        if seq.count(job.job_id) != job.num_operations:
            return False
    return True


def _is_legal_choices(instance: FJSPInstance, seq, ch) -> bool:
    """合法设备选择：每个下标落在对应工序的可选设备数范围内。"""
    op_count = [0] * instance.num_jobs
    for pos, job_id in enumerate(seq):
        op = instance.get_operation(job_id, op_count[job_id])
        op_count[job_id] += 1
        if not (0 <= ch[pos] < op.num_choices):
            return False
    return True


class TestUT01InstanceParser(unittest.TestCase):
    """UT-01 算例解析器：加载 FT06。"""

    def test_ft06_meta(self):
        inst = load_instance_by_name("ft06")
        self.assertEqual(inst.num_jobs, 6)
        self.assertEqual(inst.num_machines, 6)
        self.assertEqual(inst.total_operations, 36)          # 设计文档"26"为笔误
        self.assertEqual(inst.known_best_makespan, 55)

    def test_ft06_parse_text(self):
        inst = pp.parse_text(pp._FT06, "jsp")
        self.assertEqual(inst.num_jobs, 6)
        self.assertEqual(inst.num_machines, 6)
        self.assertEqual(inst.total_operations, 36)


class TestUT02FormatError(unittest.TestCase):
    """UT-02 算例解析器：格式错误文件抛异常并提示行号。"""

    def test_odd_tokens_raises_with_line_no(self):
        # jsp 格式：工件行 token 数为奇数（工序对不完整）
        text = "1 2\n0 5 1\n"
        with self.assertRaises(ValueError) as cm:
            pp.parse_text(text, "jsp")
        self.assertIn("第 2 行", str(cm.exception))

    def test_incomplete_pairs_raises_with_line_no(self):
        # brandimarte 格式：k=2 却只有 1 组 (设备, 时间)
        text = "1 2\n1 2 1 3\n"
        with self.assertRaises(ValueError) as cm:
            pp.parse_text(text, "brandimarte")
        self.assertIn("第 2 行", str(cm.exception))


class TestUT03GAInit(unittest.TestCase):
    """UT-03 GA 初始化：种群大小正确，每个个体合法。"""

    def test_population_valid(self):
        inst = load_instance_by_name("ft06")
        import random
        cfg = SolverConfig(algorithm="ga", population_size=40, random_seed=42)
        pop = _init_population(inst, cfg, random.Random(42))
        self.assertEqual(len(pop), 40)
        for seq, ch, _ in pop:
            self.assertTrue(_is_legal_sequence(inst, seq))
            self.assertTrue(_is_legal_choices(inst, seq, ch))


class TestUT04POXCrossover(unittest.TestCase):
    """UT-04 POX 交叉：交叉后染色体合法。"""

    def test_crossover_legal(self):
        inst = load_instance_by_name("ft06")
        import random
        rng = random.Random(42)
        p1 = _random_sequence(inst, rng)
        p2 = _random_sequence(inst, rng)
        c1, c2 = _pox_crossover(p1, p2, rng)
        self.assertTrue(_is_legal_sequence(inst, c1))
        self.assertTrue(_is_legal_sequence(inst, c2))
        self.assertEqual(len(c1), inst.total_operations)
        self.assertEqual(len(c2), inst.total_operations)


class TestUT05Decode(unittest.TestCase):
    """UT-05 解码算法：已知简单案例 Makespan 正确，无工序重叠。"""

    def test_known_case_makespan(self):
        inst = _make_2x2_instance()
        sched = decode(inst, [0, 1, 0, 1], [0, 0, 0, 0])
        self.assertAlmostEqual(sched.makespan, 8.0)

    def test_no_machine_overlap(self):
        inst = _make_2x2_instance()
        sched = decode(inst, [0, 1, 0, 1], [0, 0, 0, 0])
        # 按机器分组，校验任意两工序时间段不重叠
        by_machine = {}
        for it in sched.items:
            by_machine.setdefault(it.machine_id, []).append(it)
        for machine, items in by_machine.items():
            items = sorted(items, key=lambda x: x.start_time)
            for a, b in zip(items, items[1:]):
                self.assertLessEqual(a.end_time, b.start_time,
                                     f"机器 {machine} 上工序重叠")

    def test_precedence_constraint(self):
        inst = _make_2x2_instance()
        sched = decode(inst, [0, 1, 0, 1], [0, 0, 0, 0])
        # 每工件内，后一道工序开始时间不早于前一道结束时间
        last = {}
        for it in sched.items:
            if it.job_id in last:
                self.assertGreaterEqual(it.start_time, last[it.job_id])
            last[it.job_id] = it.end_time


class TestUT06GASolve(unittest.TestCase):
    """UT-06 GA 求解：FT06 固定种子 Makespan ≤ 60，结果可复现。"""

    def test_ga_makespan_and_reproducible(self):
        inst = load_instance_by_name("ft06")
        cfg = SolverConfig(algorithm="ga", random_seed=42)
        r1 = solve_ga(inst, cfg)
        r2 = solve_ga(inst, cfg)
        self.assertLessEqual(r1.schedule.makespan, 60)
        self.assertEqual(r1.schedule.makespan, r2.schedule.makespan)
        self.assertEqual(r1.best_operation_sequence, r2.best_operation_sequence)


class TestUT07SASolve(unittest.TestCase):
    """UT-07 SA 求解：FT06 固定种子收敛曲线单调不增（最优值）。"""

    def test_sa_history_monotone(self):
        inst = load_instance_by_name("ft06")
        cfg = SolverConfig(algorithm="sa", random_seed=42)
        r = solve_sa(inst, cfg)
        self.assertGreater(len(r.history), 0)
        for a, b in zip(r.history, r.history[1:]):
            self.assertGreaterEqual(a, b)               # 最优值单调不增
        self.assertEqual(r.schedule.makespan, min(r.history))


class TestUT08Metrics(unittest.TestCase):
    """UT-08 指标计算：利用率、负载、拖期计算正确。"""

    def test_metrics(self):
        inst = _make_2x2_instance()
        sched = decode(inst, [0, 1, 0, 1], [0, 0, 0, 0])
        # 手算：m0 负载 3+5=8，m1 负载 2+4=6，makespan=8
        self.assertAlmostEqual(sched.machine_utilization[0], 8 / 8)
        self.assertAlmostEqual(sched.machine_utilization[1], 6 / 8)
        self.assertAlmostEqual(sched.max_load, 8.0)
        # job1 交期 4，完成于 8，拖期 = 4
        self.assertAlmostEqual(sched.total_tardiness, 4.0)


class TestUT09RescheduleInsert(unittest.TestCase):
    """UT-09 插单模块：冻结模式下已开工工序原样保留。"""

    def test_frozen_operations_unchanged(self):
        from backend.reschedule import _frozen_split, reschedule
        from backend.schemas import OperationIn, RescheduleJob, RescheduleRequest

        inst = load_instance_by_name("ft06")
        cfg = SolverConfig(algorithm="ga", random_seed=42, population_size=40,
                           max_iterations=60)
        result = solve_ga(inst, cfg)
        current_time = result.schedule.makespan / 2.0

        frozen, _ = _frozen_split(result.schedule, current_time)
        self.assertTrue(frozen, "时间中点前应有已开工（冻结）工序")

        stored = {
            "instance": inst, "instance_name": "ft06",
            "algorithm": "ga", "result": result,
        }
        request = RescheduleRequest(
            schedule_id="ut09",
            new_job=RescheduleJob(
                job_id=inst.num_jobs,
                operations=[OperationIn(eligible_machines=[0, 1],
                                        processing_times=[3.0, 4.0])],
            ),
            current_time=current_time,
            mode="freeze",
        )
        out = reschedule(stored, request)
        new_items = out["schedule"]["items"]

        # 冻结工序必须原样保留（job/op/设备/起止时间不变）
        new_map = {(it["job_id"], it["op_id"]):
                   (it["machine_id"], it["start_time"], it["end_time"])
                   for it in new_items}
        for it in frozen:
            key = (it.job_id, it.op_id)
            self.assertIn(key, new_map, f"冻结工序 {key} 丢失")
            nm, ns, ne = new_map[key]
            self.assertEqual(nm, it.machine_id)
            self.assertAlmostEqual(ns, it.start_time)
            self.assertAlmostEqual(ne, it.end_time)


class TestUT10CSVExport(unittest.TestCase):
    """UT-10 CSV 导出：导出后重新读取，明细条数与字段一致。"""

    def test_export_roundtrip(self):
        import csv
        import io

        from backend.export import export_csv

        inst = load_instance_by_name("ft06")
        cfg = SolverConfig(algorithm="ga", random_seed=42, population_size=40,
                           max_iterations=60)
        result = solve_ga(inst, cfg)

        content = export_csv(result.schedule)
        rows = list(csv.DictReader(io.StringIO(content)))
        self.assertEqual(len(rows), len(result.schedule.items))

        expected_fields = ["job_id", "operation_id", "machine_id",
                           "start_time", "end_time", "duration"]
        self.assertEqual(list(rows[0].keys()), expected_fields)
        # 每条记录的持续时长应等于起止时间之差（允许 0.001 舍入误差）
        for r in rows:
            dur = float(r["duration"])
            span = float(r["end_time"]) - float(r["start_time"])
            self.assertAlmostEqual(dur, span, delta=0.002)


if __name__ == "__main__":
    unittest.main(verbosity=2)
