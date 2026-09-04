#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
算法对比页（/compare，对应设计说明书 §3.6 M6 方案对比）。

多算法多次运行，输出指标对比表、收敛曲线与稳定性箱线图。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import api_client  # noqa: E402
import charts  # noqa: E402

st.set_page_config(page_title="算法对比", page_icon="📊", layout="wide")
st.title("📊 算法对比")

st.session_state.setdefault("schedule_ids", [])

try:
    instances = api_client.list_instances()
except api_client.ApiError as exc:
    st.error(str(exc))
    st.stop()

col1, col2, col3 = st.columns([2, 2, 1])
instance_name = col1.selectbox("算例", [m["name"] for m in instances])
algorithms = col2.multiselect(
    "算法", ["ga", "sa", "pso", "hybrid"],
    default=["ga", "pso", "hybrid"],
    format_func=lambda x: {"ga": "GA", "sa": "SA", "pso": "PSO", "hybrid": "Hybrid"}[x],
)
runs = col3.number_input("运行次数", 1, 10, 3)

if st.button("🚀 开始对比", type="primary"):
    if not algorithms:
        st.warning("请至少选择一个算法。")
        st.stop()

    results = []
    convergence = []
    progress = st.progress(0.0)
    total = len(algorithms) * runs
    done = 0

    for algo in algorithms:
        values = []
        best_run = None
        for i in range(runs):
            cfg = {"algorithm": algo, "random_seed": i * 17 + 1}
            r = api_client.solve(instance_name, cfg)
            values.append(r["schedule"]["makespan"])
            if best_run is None or r["schedule"]["makespan"] < best_run["schedule"]["makespan"]:
                best_run = r
            if r["schedule_id"] not in st.session_state["schedule_ids"]:
                st.session_state["schedule_ids"].append(r["schedule_id"])
            done += 1
            progress.progress(done / total)

        results.append({"name": algo.upper(), "values": values})
        convergence.append({
            "schedule_id": best_run["schedule_id"],
            "algorithm": algo.upper(),
            "history": best_run["history"],
            "avg_history": best_run["avg_history"],
        })

    # 指标对比表
    rows = []
    for r in results:
        rows.append({
            "算法": r["name"],
            "最优 Makespan": min(r["values"]),
            "平均 Makespan": round(sum(r["values"]) / len(r["values"]), 2),
            "最差 Makespan": max(r["values"]),
        })
    st.subheader("指标对比")
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(charts.boxplot_compare(results), use_container_width=True)
    with c2:
        st.plotly_chart(charts.compare_convergence(convergence), use_container_width=True)

    best_algo = min(results, key=lambda r: min(r["values"]))
    st.success(f"🏆 本次对比最优：{best_algo['name']}（Makespan = {min(best_algo['values']):g}）")
else:
    st.info("选择算例与多个算法，设置运行次数后点击「开始对比」。")
