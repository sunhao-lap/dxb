#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SmartFJSP —— 数据预处理脚本
===========================

功能
----
1. 解析标准 **FJSP 算例**（Brandimarte / 设计说明书两种文本格式）；
2. 解析经典 **JSP 算例**（FT06 / FT10 / LA01-LA40），并统一转换为 FJSP 格式
   （每道工序仅一台可选设备，即 flexibility = 1）；
3. 对解析结果做**数据完整性校验**（工序可选设备非空、设备编号合法、加工时间 > 0、
   同一工件工序顺序不重复等）；
4. 计算每个算例的**规模指标**（工件数、设备数、工序总数、平均柔性、加工时间范围）；
5. 输出**统一 JSON 格式**的预处理数据文件与索引 `index.json` 到 `data/processed/`。

运行方式
--------
    # 处理 data/raw/ 下所有算例（递归查找 *.fjs / *.txt）
    python data/preprocess.py

    # 只处理单个文件
    python data/preprocess.py --input data/raw/brandimarte/Mk01.fjs

    # 强制指定算例格式（brandimarte / header / jsp / auto）
    python data/preprocess.py --format brandimarte

    # 指定输出目录
    python data/preprocess.py --output data/processed

文本格式说明（见 data/README.md）
--------------------------------
- ``brandimarte`` : 第 1 行 ``工件数 设备数 [平均柔性]``，之后每行一个工件，
  工序按「可选设备数 k，随后 k 组 (设备号, 加工时间)」连续书写，设备号从 1 开始。
- ``header``      : 设计说明书 §5.2 格式，每行开头多了 ``工件号 工序数`` 两个字段。
- ``jsp``         : 经典 JSP 格式，第 1 行 ``工件数 设备数``，之后每行是每个工件
  全部工序按顺序的 ``(设备号, 加工时间)`` 对，设备号可能从 0 或 1 开始（自动识别）。

所有输出均统一为 **0 基设备编号**（机器 1 -> 索引 0），与代码内部
``FJSPInstance`` 数据结构保持一致。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterator, List, Sequence, Tuple

# ---------------------------------------------------------------------------
# 1. 内部数据结构（与方案设计说明书 §5.1 对应）
# ---------------------------------------------------------------------------


@dataclass
class Operation:
    """一道工序：可选设备编号列表 + 对应加工时间列表（两列表按下标对齐）。"""

    eligible_machines: List[int]      # 0 基设备编号
    processing_times: List[int]       # 与 eligible_machines 一一对应

    def to_dict(self) -> dict:
        return {
            "eligible_machines": self.eligible_machines,
            "processing_times": self.processing_times,
        }


@dataclass
class Job:
    """一个工件：由若干道工序按工艺顺序组成。"""

    job_id: int
    operations: List[Operation]

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "num_operations": len(self.operations),
            "operations": [op.to_dict() for op in self.operations],
        }


@dataclass
class FJSPInstance:
    """一个 FJSP 算例。"""

    name: str
    num_jobs: int
    num_machines: int
    jobs: List[Job]
    avg_flexibility: float = 0.0          # 平均每道工序可选设备数
    known_best_makespan: int | None = None

    @property
    def total_operations(self) -> int:
        return sum(len(j.operations) for j in self.jobs)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "num_jobs": self.num_jobs,
            "num_machines": self.num_machines,
            "total_operations": self.total_operations,
            "avg_flexibility": round(self.avg_flexibility, 4),
            "known_best_makespan": self.known_best_makespan,
            "jobs": [j.to_dict() for j in self.jobs],
        }


# ---------------------------------------------------------------------------
# 2. 已知最优 / 最优上界 Makespan 参考表
#    用于算法求解后快速比对解质量。FT/LA 为经典 JSP 最优值；
#    MK 为 Brandimarte FJSP 已知最优上界（UB）。
# ---------------------------------------------------------------------------

KNOWN_BEST: dict = {
    # 经典 JSP（Fisher & Thompson / Lawrence）
    "ft06": 55, "ft10": 930, "ft20": 1165,
    "la01": 666, "la02": 655, "la03": 597, "la04": 590, "la05": 593,
    "la06": 926, "la07": 890, "la08": 863, "la09": 951, "la10": 958,
    "la11": 1222, "la12": 1039, "la13": 1150, "la14": 1292, "la15": 1207,
    "la16": 945, "la17": 784, "la18": 848, "la19": 842, "la20": 902,
    "la21": 1046, "la22": 927, "la23": 1032, "la24": 935, "la25": 977,
    "la26": 1218, "la27": 1235, "la28": 1216, "la29": 1152, "la30": 1355,
    "la31": 1784, "la32": 1850, "la33": 1719, "la34": 1721, "la35": 1888,
    "la36": 1268, "la37": 1397, "la38": 1196, "la39": 1233, "la40": 1222,
    # Brandimarte FJSP（n 工件 × m 设备，已知最优上界 UB）
    "mk01": 40, "mk02": 26, "mk03": 204, "mk04": 60, "mk05": 172,
    "mk06": 57, "mk07": 139, "mk08": 523, "mk09": 307, "mk10": 197,
}


# ---------------------------------------------------------------------------
# 3. 解析器
# ---------------------------------------------------------------------------


def _tokens(line: str) -> List[str]:
    """按空白切分一行，忽略空串（兼容注释 ``#`` 开头行由调用方剔除）。"""
    return line.strip().split()


def parse_brandimarte(lines: Sequence[str]) -> FJSPInstance:
    """
    Brandimarte 原始格式（IDSIA / Monaldo / Lei-Kun 仓库通用）。

    第 1 行：``工件数 设备数 [平均柔性]``
    之后每行一个工件：``工序数  k1 m1 t1 ... m_{k1} t_{k1}  k2 ...``
    即每行开头是该工件的**工序数**（无独立工件号，工件按行序编号），
    随后各工序连续书写，每道工序 = ``可选设备数 k  + k 组(设备号, 加工时间)``。
    设备号 1 基，解析时转为 0 基。
    """
    it = iter(lines)
    header = _tokens(next(it))
    n, m = int(header[0]), int(header[1])

    jobs: List[Job] = []
    for job_id in range(n):
        raw = _tokens(next(it))
        num_ops = int(raw[0])
        ops = _parse_ops_greedy(raw[1:])
        if len(ops) != num_ops:
            raise ValueError(
                f"工件 {job_id + 1} 声明工序数 {num_ops}，实际解析到 {len(ops)}"
            )
        jobs.append(Job(job_id=job_id, operations=ops))

    return FJSPInstance(name="", num_jobs=n, num_machines=m, jobs=jobs)


def _parse_ops_greedy(raw: Sequence[str]) -> List[Operation]:
    """贪心解析一道接一道的工序：读 k，再读 k 组 (设备, 时间)。"""
    ops: List[Operation] = []
    i = 0
    while i < len(raw):
        k = int(raw[i])
        i += 1
        if k <= 0:
            raise ValueError(f"工序可选设备数必须 > 0，得到 {k}")
        machines: List[int] = []
        times: List[int] = []
        for _ in range(k):
            if i + 1 >= len(raw):
                raise ValueError("工序 (设备, 时间) 对不完整，请检查文本格式")
            machines.append(int(raw[i]) - 1)   # 1 基 -> 0 基
            times.append(int(raw[i + 1]))
            i += 2
        ops.append(Operation(eligible_machines=machines, processing_times=times))
    return ops


def parse_with_header(lines: Sequence[str]) -> FJSPInstance:
    """
    设计说明书 §5.2 格式：每行开头有 ``工件号 工序数`` 两个字段。

    例：``1 3 2 1 3 2 5 1 3 4 1 2 6``
        = 工件1，3 道工序；工序1: 2台 {机1(3),机2(5)}；工序2: 1台 {机3(4)}；工序3: 1台 {机2(6)}。
    """
    it = iter(lines)
    header = _tokens(next(it))
    n, m = int(header[0]), int(header[1])

    jobs: List[Job] = []
    for _ in range(n):
        raw = _tokens(next(it))
        job_id = int(raw[0]) - 1            # 文件中工件号 1 基
        num_ops = int(raw[1])
        ops = _parse_ops_greedy(raw[2:])
        if len(ops) != num_ops:
            raise ValueError(
                f"工件 {job_id + 1} 声明工序数 {num_ops}，实际解析到 {len(ops)}"
            )
        jobs.append(Job(job_id=job_id, operations=ops))

    return FJSPInstance(name="", num_jobs=n, num_machines=m, jobs=jobs)


def parse_jsp(lines: Sequence[str]) -> FJSPInstance:
    """
    经典 JSP 格式：第 1 行 ``n m``，之后每行 n 个工件，每个工件 m 道工序，
    按顺序给出 ``(设备号, 加工时间)`` 对。设备号 0/1 基自动识别。
    转换为 FJSP：每道工序仅 1 台可选设备（flexibility=1）。
    """
    it = iter(lines)
    header = _tokens(next(it))
    n, m = int(header[0]), int(header[1])

    # 先收集所有设备号，判断是否 0 基（出现 0 即 0 基）。
    all_rows: List[List[Tuple[int, int]]] = []
    min_machine = 10 ** 9
    for _ in range(n):
        raw = _tokens(next(it))
        pairs: List[Tuple[int, int]] = []
        for i in range(0, len(raw), 2):
            machine = int(raw[i])
            duration = int(raw[i + 1])
            pairs.append((machine, duration))
            min_machine = min(min_machine, machine)
        if len(pairs) != m:
            raise ValueError(f"工件行工序对数量 {len(pairs)} != 设备数 {m}")
        all_rows.append(pairs)

    zero_based = min_machine == 0

    jobs: List[Job] = []
    for job_id, pairs in enumerate(all_rows):
        ops = [
            Operation(
                eligible_machines=[(machine if zero_based else machine - 1)],
                processing_times=[duration],
            )
            for machine, duration in pairs
        ]
        jobs.append(Job(job_id=job_id, operations=ops))

    return FJSPInstance(name="", num_jobs=n, num_machines=m, jobs=jobs)


def parse_text(text: str, fmt: str = "auto") -> FJSPInstance:
    """
    解析算例文本。``fmt`` 取值：
        "brandimarte" / "header" / "jsp" / "auto"（默认自动识别）。
    """
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]

    if fmt == "brandimarte":
        inst = parse_brandimarte(lines)
    elif fmt == "header":
        inst = parse_with_header(lines)
    elif fmt == "jsp":
        inst = parse_jsp(lines)
    elif fmt == "auto":
        inst = _auto_detect(lines)
    else:
        raise ValueError(f"未知格式 {fmt!r}，可选 brandimarte/header/jsp/auto")

    return inst


def _auto_detect(lines: Sequence[str]) -> FJSPInstance:
    """根据第 2 行起结构自动识别格式。"""
    header = _tokens(lines[0])
    n = int(header[0])
    m = int(header[1])
    job_lines = [ln for ln in lines[1:1 + n]]

    # header（设计说明书）格式：每行开头是顺序工件号 1..n
    if len(job_lines) == n:
        try:
            first_tokens = [int(_tokens(ln)[0]) for ln in job_lines]
            if first_tokens == list(range(1, n + 1)):
                return parse_with_header(lines)
        except (ValueError, IndexError):
            pass

    # jsp（经典）格式：每行 token 数恰好 = 2 * 设备数（m 组 (设备,时间) 对）
    if all(len(_tokens(ln)) == 2 * m for ln in job_lines):
        return parse_jsp(lines)

    # 默认 Brandimarte 格式（每行开头是工序数）
    return parse_brandimarte(lines)


# ---------------------------------------------------------------------------
# 4. 校验
# ---------------------------------------------------------------------------


def validate(inst: FJSPInstance) -> List[str]:
    """返回校验错误列表（空列表表示通过）。"""
    errors: List[str] = []
    if inst.num_jobs <= 0 or inst.num_machines <= 0:
        errors.append("工件数 / 设备数必须为正")
    if len(inst.jobs) != inst.num_jobs:
        errors.append(f"工件数不匹配：声明 {inst.num_jobs}，实际 {len(inst.jobs)}")

    for job in inst.jobs:
        if not job.operations:
            errors.append(f"工件 {job.job_id} 无任何工序")
        for op_idx, op in enumerate(job.operations):
            if len(op.eligible_machines) != len(op.processing_times):
                errors.append(
                    f"工件 {job.job_id} 工序 {op_idx} 设备列表与时间列表长度不一致"
                )
            if not op.eligible_machines:
                errors.append(f"工件 {job.job_id} 工序 {op_idx} 无可选设备")
            for m, t in zip(op.eligible_machines, op.processing_times):
                if not (0 <= m < inst.num_machines):
                    errors.append(
                        f"工件 {job.job_id} 工序 {op_idx} 设备号 {m} 越界"
                        f"（应为 0..{inst.num_machines - 1}）"
                    )
                if t <= 0:
                    errors.append(f"工件 {job.job_id} 工序 {op_idx} 加工时间 {t} 非正")
            # 同一工序可选设备去重检查
            if len(set(op.eligible_machines)) != len(op.eligible_machines):
                errors.append(f"工件 {job.job_id} 工序 {op_idx} 可选设备出现重复")
    return errors


def compute_stats(inst: FJSPInstance) -> None:
    """就地计算平均柔性等统计指标。"""
    total_ops = inst.total_operations
    total_choices = sum(len(op.eligible_machines) for j in inst.jobs for op in j.operations)
    inst.avg_flexibility = total_choices / total_ops if total_ops else 0.0


# ---------------------------------------------------------------------------
# 5. 主流程
# ---------------------------------------------------------------------------


def process_file(path: Path, fmt: str) -> FJSPInstance:
    """读取并解析单个算例文件，赋名并统计。"""
    text = path.read_text(encoding="utf-8", errors="ignore")
    inst = parse_text(text, fmt)
    inst.name = path.stem.lower()
    compute_stats(inst)

    # 附上已知最优值（若在参考表内）
    key = inst.name.lower()
    inst.known_best_makespan = KNOWN_BEST.get(key)

    return inst


def iter_instance_files(root: Path) -> Iterator[Path]:
    """递归查找 raw 目录下所有算例文件。"""
    for suffix in (".fjs", ".txt", ".dat"):
        yield from root.rglob(f"*{suffix}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SmartFJSP 数据预处理")
    parser.add_argument("--input", "-i", type=Path, default=None,
                        help="单个算例文件；缺省则处理 data/raw/ 下全部文件")
    parser.add_argument("--raw-dir", type=Path, default=None,
                        help="算例目录（默认 <脚本目录>/raw）")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="输出目录（默认 <脚本目录>/processed）")
    parser.add_argument("--format", "-f", default="auto",
                        choices=["auto", "brandimarte", "header", "jsp"],
                        help="算例文本格式（默认 auto 自动识别）")
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parent
    raw_dir = args.raw_dir or (base / "raw")
    out_dir = args.output or (base / "processed")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 确定待处理文件
    if args.input:
        files = [args.input]
    else:
        if not raw_dir.exists():
            print(f"[错误] 未找到原始数据目录：{raw_dir}", file=sys.stderr)
            print("       请先按 data/raw/README.md 下载算例并放入对应子目录。",
                  file=sys.stderr)
            return 1
        files = sorted(iter_instance_files(raw_dir))

    if not files:
        print("[提示] 未找到任何算例文件。", file=sys.stderr)
        return 1

    index: List[dict] = []
    for path in files:
        try:
            inst = process_file(path, args.format)
            errors = validate(inst)
            if errors:
                print(f"[跳过] {path.name} 校验失败：")
                for e in errors:
                    print(f"        - {e}")
                continue

            out_path = out_dir / f"{inst.name}.json"
            out_path.write_text(
                json.dumps(inst.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            index.append({
                "name": inst.name,
                "num_jobs": inst.num_jobs,
                "num_machines": inst.num_machines,
                "total_operations": inst.total_operations,
                "avg_flexibility": round(inst.avg_flexibility, 4),
                "known_best_makespan": inst.known_best_makespan,
            })
            print(f"[完成] {inst.name:<8} {inst.num_jobs:>2}工件×{inst.num_machines:>2}设备 "
                  f"工序{inst.total_operations:>3} 平均柔性{inst.avg_flexibility:.2f} "
                  f"最优{inst.known_best_makespan}")

        except Exception as exc:  # noqa: BLE001 —— 预处理阶段尽量不中断
            print(f"[失败] {path.name}: {exc}", file=sys.stderr)

    # 写出索引
    idx_path = out_dir / "index.json"
    idx_path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n共处理 {len(index)} 个算例，索引已写入 {idx_path}")
    return 0


# ---------------------------------------------------------------------------
# 6. 自测（内置 FT06 经典算例，最优 Makespan=55）
# ---------------------------------------------------------------------------

_FT06 = """6 6
2 1 0 3 1 6 3 7 5 3 4 6
1 8 2 5 4 10 5 10 0 10 3 4
2 5 3 4 5 8 0 9 1 1 4 7
1 5 0 5 2 5 3 3 4 8 5 9
2 9 1 3 4 5 5 4 0 3 3 1
1 3 3 3 5 9 0 10 4 4 2 1
"""


def self_test() -> bool:
    """用 FT06 校验解析器与校验逻辑是否正常工作。"""
    inst = parse_text(_FT06, "jsp")
    inst.name = "ft06"
    compute_stats(inst)
    assert inst.num_jobs == 6, inst.num_jobs
    assert inst.num_machines == 6, inst.num_machines
    assert inst.total_operations == 36, inst.total_operations
    assert not validate(inst), validate(inst)
    print("[自测通过] FT06 -> 6 工件 × 6 设备，36 道工序，无校验错误。")
    return True


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(0 if self_test() else 1)
    raise SystemExit(main())
