#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果导出模块（M8，对应设计说明书 §3.8 / §5.4）。

支持三种导出格式：
- ``csv``  ：工序明细表（job_id / op_id / machine_id / start / end / duration）
- ``png``  ：甘特图图片（matplotlib 离屏渲染）
- ``html`` ：性能分析报告（Plotly 交互甘特图 + 指标表 + 收敛曲线）
"""

from __future__ import annotations

import csv
import io
from typing import List

import matplotlib
matplotlib.use("Agg")                       # 无界面后端，保证服务器可用
import matplotlib.pyplot as plt
import plotly.graph_objects as go

from fjsp import FJSPInstance, Schedule, SolveResult


# ---------------------------------------------------------------------------
# CSV 导出（§5.4）
# ---------------------------------------------------------------------------


def schedule_rows(schedule: Schedule) -> List[dict]:
    """把排程明细整理为行字典列表。"""
    return [
        {
            "job_id": it.job_id,
            "operation_id": it.op_id,
            "machine_id": it.machine_id,
            "start_time": round(it.start_time, 3),
            "end_time": round(it.end_time, 3),
            "duration": round(it.duration, 3),
        }
        for it in sorted(schedule.items, key=lambda x: (x.start_time, x.machine_id))
    ]


def export_csv(schedule: Schedule) -> str:
    """导出工序明细为 CSV 文本。"""
    rows = schedule_rows(schedule)
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=["job_id", "operation_id", "machine_id",
                    "start_time", "end_time", "duration"],
    )
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PNG 甘特图（matplotlib）
# ---------------------------------------------------------------------------


def export_gantt_png(schedule: Schedule, instance: FJSPInstance) -> bytes:
    """渲染甘特图并返回 PNG 字节。"""
    fig, ax = plt.subplots(figsize=(12, max(3, instance.num_machines * 0.7)))
    cmap = plt.get_cmap("tab20")
    for it in schedule.items:
        color = cmap(it.job_id % 20)
        ax.barh(
            it.machine_id, it.duration, left=it.start_time,
            color=color, edgecolor="black", linewidth=0.4,
        )
        ax.text(
            it.start_time + it.duration / 2, it.machine_id,
            f"J{it.job_id}O{it.op_id}", ha="center", va="center", fontsize=7,
        )

    ax.set_yticks(range(instance.num_machines))
    ax.set_yticklabels([f"M{i}" for i in range(instance.num_machines)])
    ax.set_xlabel("Time")
    ax.set_ylabel("Machine")
    ax.set_title(f"Gantt Chart - {instance.name} (makespan={schedule.makespan:g})")
    ax.invert_yaxis()
    ax.grid(axis="x", linestyle="--", alpha=0.3)

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# HTML 性能报告（Plotly）
# ---------------------------------------------------------------------------


def _gantt_figure(schedule: Schedule, instance: FJSPInstance) -> go.Figure:
    """构造 Plotly 交互甘特图（横条按设备分组）。"""
    fig = go.Figure()
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
              "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf"]
    for it in schedule.items:
        fig.add_trace(
            go.Bar(
                x=[it.duration],
                y=[f"M{it.machine_id}"],
                base=it.start_time,
                orientation="h",
                marker_color=colors[it.job_id % len(colors)],
                name=f"J{it.job_id}-O{it.op_id}",
                customdata=[[
                    it.job_id, it.op_id, it.machine_id,
                    it.start_time, it.end_time, it.duration,
                ]],
                hovertemplate=(
                    "Job %{customdata[0]} Op %{customdata[1]}<br>"
                    "Machine %{customdata[2]}<br>"
                    "Start %{customdata[3]:.2f} End %{customdata[4]:.2f}<br>"
                    "Duration %{customdata[5]:.2f}<extra></extra>"
                ),
                showlegend=False,
            )
        )
    fig.update_layout(
        barmode="overlay",
        title=f"Gantt Chart - {instance.name} (makespan={schedule.makespan:g})",
        xaxis_title="Time",
        yaxis_title="Machine",
        height=max(400, instance.num_machines * 60),
    )
    return fig


def _convergence_figure(result: SolveResult) -> go.Figure:
    """构造收敛曲线图（最优 + 平均）。"""
    fig = go.Figure()
    x = list(range(len(result.history)))
    fig.add_trace(go.Scatter(x=x, y=result.history, mode="lines",
                             name="Best", line=dict(color="#1f77b4")))
    if result.avg_history:
        fig.add_trace(go.Scatter(x=x, y=result.avg_history, mode="lines",
                                 name="Average", line=dict(color="#ff7f0e", dash="dash")))
    fig.update_layout(
        title="Convergence Curve",
        xaxis_title="Iteration",
        yaxis_title="Makespan",
        height=350,
    )
    return fig


def export_html_report(
    schedule: Schedule, instance: FJSPInstance, result: SolveResult
) -> str:
    """生成性能分析报告 HTML（甘特图 + 收敛曲线 + 指标表）。"""
    gantt = _gantt_figure(schedule, instance).to_html(full_html=False, include_plotlyjs="cdn")
    conv = _convergence_figure(result).to_html(full_html=False, include_plotlyjs=False)

    metrics_rows = "".join(
        f"<tr><td>M{i}</td><td>{u:.3f}</td></tr>"
        for i, u in enumerate(schedule.machine_utilization)
    )
    return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8"><title>SmartFJSP 报告 - {instance.name}</title></head>
<body>
<h1>调度性能报告 - {instance.name}</h1>
<table border="1" cellpadding="6" style="border-collapse:collapse">
  <tr><th>指标</th><th>数值</th></tr>
  <tr><td>Makespan</td><td>{schedule.makespan:g}</td></tr>
  <tr><td>最大负载</td><td>{schedule.max_load:g}</td></tr>
  <tr><td>总拖期</td><td>{schedule.total_tardiness:g}</td></tr>
  <tr><td>求解耗时(s)</td><td>{result.elapsed:.3f}</td></tr>
</table>
<h2>设备利用率</h2>
<table border="1" cellpadding="6" style="border-collapse:collapse">
  <tr><th>设备</th><th>利用率</th></tr>
  {metrics_rows}
</table>
<h2>甘特图</h2>
{gantt}
<h2>收敛曲线</h2>
{conv}
</body>
</html>"""
