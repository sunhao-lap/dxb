#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
插单重调度页（/reschedule，对应设计说明书 §3.7 M7）。

加载已有方案，输入新工单，执行冻结重排 / 完全重排，展示新方案与差异。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

import api_client  # noqa: E402
import charts  # noqa: E402

st.set_page_config(page_title="插单重调度", page_icon="🔧", layout="wide")
st.title("🔧 插单重调度")

st.session_state.setdefault("schedule_ids", [])


def _num_machines(items):
    return max((it["machine_id"] for it in items), default=0) + 1


# 方案选择
col1, col2 = st.columns([2, 1])
if st.session_state["schedule_ids"]:
    schedule_id = col1.selectbox("选择已求解方案", st.session_state["schedule_ids"])
else:
    schedule_id = col1.text_input("方案 ID（请先在调度工作台求解）")

if schedule_id:
    try:
        detail = api_client.get_schedule(schedule_id)
        original = detail["schedule"]
        n_machines = _num_machines(original["items"])
        st.subheader("原方案")
        st.plotly_chart(
            charts.gantt_chart(original["items"], n_machines, original["makespan"],
                               title="原方案甘特图"),
            use_container_width=True,
        )
    except api_client.ApiError as exc:
        st.error(str(exc))
        st.stop()

    st.markdown("---")
    st.subheader("新工单（插单）")
    default_job_id = max((it["job_id"] for it in original["items"]), default=0) + 1
    new_job_id = st.number_input("新工单工件号", 0, 999, default_job_id)

    n_ops = st.number_input("新工单工序数", 1, 20, 2)
    ops = []
    for i in range(int(n_ops)):
        c1, c2 = st.columns(2)
        machines_str = c1.text_input(
            f"工序 {i} 可选设备（逗号分隔，0 基）", "0,1", key=f"m{i}")
        times_str = c2.text_input(
            f"工序 {i} 加工时间（逗号分隔）", "3,4", key=f"t{i}")
        try:
            machines = [int(x) for x in machines_str.replace("，", ",").split(",") if x.strip()]
            times = [float(x) for x in times_str.replace("，", ",").split(",") if x.strip()]
            if len(machines) != len(times):
                st.error(f"工序 {i} 设备数({len(machines)})与时间数({len(times)})不一致")
                st.stop()
            ops.append({"eligible_machines": machines, "processing_times": times})
        except ValueError:
            st.error(f"工序 {i} 输入格式错误，请用逗号分隔数字。")
            st.stop()

    col1, col2 = st.columns(2)
    current_time = col1.number_input("当前时间点（此前已开工工序将冻结）", 0.0, 100000.0, 0.0)
    mode = col2.selectbox("重调度模式", ["freeze", "full"],
                          format_func=lambda x: "冻结重排（稳定性优先）" if x == "freeze" else "完全重排")

    if st.button("🔧 执行重调度", type="primary"):
        with st.spinner("正在重调度..."):
            result = api_client.reschedule({
                "schedule_id": schedule_id,
                "new_job": {"job_id": new_job_id, "operations": ops},
                "current_time": current_time,
                "mode": mode,
            })

        st.success(result["diff"]["summary"])
        st.subheader("重调度后方案")
        new_items = result["schedule"]["items"]
        st.plotly_chart(
            charts.gantt_chart(new_items, _num_machines(new_items),
                               result["schedule"]["makespan"], title="新方案甘特图"),
            use_container_width=True,
        )

        d = result["diff"]
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**新增工序**（{len(d['new_operations'])}）")
            if d["new_operations"]:
                st.dataframe(d["new_operations"], use_container_width=True)
            else:
                st.caption("无")
        with c2:
            st.markdown(f"**移动工序**（{len(d['moved_operations'])}）")
            if d["moved_operations"]:
                st.dataframe(d["moved_operations"], use_container_width=True)
            else:
                st.caption("无")
        st.markdown(f"**受影响设备**：{', '.join(f'设备{x}' for x in d['affected_machines']) or '无'}")
