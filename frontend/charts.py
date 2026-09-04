#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit 前端 —— 图表渲染（模块 M5 可视化）。

基于 Plotly 提供交互式甘特图、收敛曲线与多算法对比图。
"""

from __future__ import annotations

from typing import List, Optional

import plotly.graph_objects as go

# 工件配色（循环使用）
_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
]


def gantt_chart(items: List[dict], num_machines: int, makespan: float,
                title: str = "甘特图") -> go.Figure:
    """渲染交互式甘特图（纵轴设备、横轴时间、颜色按工件）。"""
    fig = go.Figure()
    for it in items:
        job_id = it["job_id"]
        fig.add_trace(
            go.Bar(
                x=[it["duration"]],
                y=[f"设备 {it['machine_id']}"],
                base=it["start_time"],
                orientation="h",
                marker_color=_COLORS[job_id % len(_COLORS)],
                customdata=[[
                    job_id, it["op_id"], it["machine_id"],
                    it["start_time"], it["end_time"], it["duration"],
                ]],
                hovertemplate=(
                    "工件 %{customdata[0]} 工序 %{customdata[1]}<br>"
                    "设备 %{customdata[2]}<br>"
                    "开始 %{customdata[3]:.2f} 结束 %{customdata[4]:.2f}<br>"
                    "时长 %{customdata[5]:.2f}<extra></extra>"
                ),
                showlegend=False,
            )
        )
    fig.update_layout(
        barmode="overlay",
        title=f"{title}（Makespan = {makespan:g}）",
        xaxis_title="时间",
        yaxis_title="设备",
        height=max(420, num_machines * 55),
        margin=dict(l=80, r=20, t=50, b=40),
    )
    return fig


def convergence_chart(history: List[float], avg_history: Optional[List[float]] = None,
                      title: str = "收敛曲线") -> go.Figure:
    """渲染收敛曲线（最优 + 平均）。"""
    fig = go.Figure()
    x = list(range(len(history)))
    fig.add_trace(go.Scatter(x=x, y=history, mode="lines", name="最优",
                             line=dict(color="#1f77b4", width=2)))
    if avg_history:
        fig.add_trace(go.Scatter(x=x, y=avg_history, mode="lines", name="平均",
                                 line=dict(color="#ff7f0e", dash="dash")))
    fig.update_layout(
        title=title, xaxis_title="迭代次数", yaxis_title="Makespan",
        height=360, margin=dict(l=60, r=20, t=50, b=40),
    )
    return fig


def compare_convergence(convergence: List[dict]) -> go.Figure:
    """渲染多方案收敛曲线对比。"""
    fig = go.Figure()
    for c in convergence:
        x = list(range(len(c["history"])))
        fig.add_trace(go.Scatter(
            x=x, y=c["history"], mode="lines",
            name=f"{c['algorithm']} ({c['schedule_id'][:6]})",
        ))
    fig.update_layout(
        title="收敛曲线对比", xaxis_title="迭代次数", yaxis_title="Makespan",
        height=400, margin=dict(l=60, r=20, t=50, b=40),
    )
    return fig


def boxplot_compare(results: List[dict]) -> go.Figure:
    """渲染多算法多次运行的 Makespan 箱线图（对比稳定性）。"""
    fig = go.Figure()
    for r in results:
        fig.add_trace(go.Box(y=r["values"], name=r["name"]))
    fig.update_layout(
        title="算法稳定性对比（多次运行 Makespan 分布）",
        yaxis_title="Makespan", height=420,
    )
    return fig
