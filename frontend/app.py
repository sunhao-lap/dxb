#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调度工作台（首页，对应设计说明书 §6.2）。

左侧控制面板：算例选择、算法选择、参数配置、运行求解；
右侧结果区：指标卡、甘特图、收敛曲线。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st  # noqa: E402

import api_client  # noqa: E402
import charts  # noqa: E402

st.set_page_config(page_title="SmartFJSP 调度工作台", page_icon="🏭", layout="wide")
st.title("🏭 柔性车间调度工作台")
st.caption("基于智能优化算法的柔性作业车间调度系统")

# 跨页面共享的求解记录（方案 ID 列表，供对比 / 导出页面使用）
st.session_state.setdefault("schedule_ids", [])
st.session_state.setdefault("last_result", None)


# ---------------------------------------------------------------------------
# 左侧控制面板
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ 控制面板")

    try:
        instances = api_client.list_instances()
    except api_client.ApiError as exc:
        st.error(str(exc))
        st.stop()

    names = [m["name"] for m in instances]
    instance_name = st.selectbox("算例", names)

    algorithm = st.selectbox("算法", ["ga", "sa", "pso", "hybrid"],
                             format_func=lambda x: {"ga": "遗传算法 GA",
                                                    "sa": "模拟退火 SA",
                                                    "pso": "粒子群 PSO",
                                                    "hybrid": "混合算法 GA+SA"}[x])

    st.markdown("**参数配置**")
    config = {"algorithm": algorithm}
    config["random_seed"] = st.number_input("随机种子", 0, 9999, 42)

    if algorithm in ("ga", "hybrid"):
        config["population_size"] = st.number_input("种群规模", 10, 500, 100)
        config["max_iterations"] = st.number_input("迭代次数", 10, 1000, 200)
        config["crossover_rate"] = st.slider("交叉概率", 0.0, 1.0, 0.8, 0.05)
        config["mutation_rate"] = st.slider("变异概率", 0.0, 1.0, 0.1, 0.05)
    if algorithm == "hybrid":
        config["hybrid_sa_steps"] = st.number_input("精英局部搜索步数", 1, 100, 20)
    if algorithm == "sa":
        config["sa_initial_temp"] = st.number_input("初始温度", 10.0, 100000.0, 1000.0)
        config["sa_cooling_rate"] = st.slider("冷却系数", 0.5, 0.999, 0.95, 0.001)
        config["sa_max_iterations"] = st.number_input("迭代次数", 10, 10000, 1000)
    if algorithm == "pso":
        config["population_size"] = st.number_input("粒子数", 10, 500, 50)
        config["max_iterations"] = st.number_input("迭代次数", 10, 1000, 200)
        config["pso_inertia"] = st.slider("惯性权重 w", 0.0, 1.5, 0.7, 0.05)
        config["pso_cognitive"] = st.slider("认知因子 c1", 0.0, 3.0, 1.5, 0.1)
        config["pso_social"] = st.slider("社会因子 c2", 0.0, 3.0, 1.5, 0.1)

    run = st.button("🚀 运行求解", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# 右侧结果区
# ---------------------------------------------------------------------------
if run:
    with st.spinner("正在求解..."):
        try:
            result = api_client.solve(instance_name, config)
        except api_client.ApiError as exc:
            st.error(str(exc))
            st.stop()

    # 记录方案 ID，供对比 / 导出页面使用
    if result["schedule_id"] not in st.session_state["schedule_ids"]:
        st.session_state["schedule_ids"].append(result["schedule_id"])
    st.session_state["last_result"] = result

    schedule = result["schedule"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Makespan", f"{schedule['makespan']:g}")
    c2.metric("算法", result["algorithm"].upper())
    c3.metric("最大负载", f"{schedule['max_load']:g}")
    c4.metric("求解耗时", f"{result['elapsed']:.2f}s")

    tab_gantt, tab_conv, tab_metric = st.tabs(["甘特图", "收敛曲线", "指标明细"])

    with tab_gantt:
        meta = next((m for m in instances if m["name"] == instance_name), None)
        n_machines = meta["num_machines"] if meta else 1
        st.plotly_chart(
            charts.gantt_chart(schedule["items"], n_machines, schedule["makespan"]),
            use_container_width=True,
        )

    with tab_conv:
        st.plotly_chart(
            charts.convergence_chart(result["history"], result["avg_history"]),
            use_container_width=True,
        )

    with tab_metric:
        st.markdown("**设备利用率**")
        util = schedule["machine_utilization"]
        st.bar_chart({f"设备{i}": u for i, u in enumerate(util)})
        st.markdown(f"- 最大负载：{schedule['max_load']:g}")
        st.markdown(f"- 总拖期：{schedule['total_tardiness']:g}")
        st.caption(f"方案 ID：`{result['schedule_id']}`（已保存，可用于对比与导出）")
else:
    st.info("👈 在左侧选择算例与算法，点击「运行求解」开始。")
