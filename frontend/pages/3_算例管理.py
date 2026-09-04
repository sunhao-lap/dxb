#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
算例管理页（/instance，对应设计说明书 §3.5 M1 算例管理）。

展示标准 + 自定义算例清单，并支持通过工艺矩阵文本新建自定义算例。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import api_client  # noqa: E402

st.set_page_config(page_title="算例管理", page_icon="📚", layout="wide")
st.title("📚 算例管理")

tab_list, tab_custom = st.tabs(["算例清单", "新建自定义算例"])

with tab_list:
    try:
        instances = api_client.list_instances()
    except api_client.ApiError as exc:
        st.error(str(exc))
        st.stop()

    rows = []
    for m in instances:
        rows.append({
            "算例": m["name"],
            "工件数": m["num_jobs"],
            "设备数": m["num_machines"],
            "工序总数": m["total_operations"],
            "平均柔性": m.get("avg_flexibility", 0.0),
            "已知最优 Makespan": m.get("known_best_makespan", "—"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True)

with tab_custom:
    st.markdown("**工艺矩阵格式说明**")
    st.markdown(
        "- 每行代表一个工件，行号即工件号（0 基）；\n"
        "- 同一工件的多道工序用 `|` 分隔（工序按顺序编号）；\n"
        "- 每道工序内用 `设备:时间` 对表示可选设备及加工时间，多个设备用 `,` 分隔。\n"
        "> 例：`0:3,1:4 | 2:5` 表示该工件有 2 道工序：\n"
        "> 工序0 可选设备 0（耗时3）/设备1（耗时4），工序1 只在设备2（耗时5）。"
    )

    name = st.text_input("算例名称", "custom01")
    num_machines = st.number_input("设备数", 1, 50, 3)
    text = st.text_area(
        "工艺矩阵（每行一个工件）",
        "0:3,1:4 | 2:5\n1:4 | 0:3,2:6\n0:5,2:3 | 1:4",
        height=160,
    )

    if st.button("✅ 注册算例", type="primary"):
        jobs = []
        parse_ok = True
        for jid, line in enumerate(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            ops = []
            for op_id, seg in enumerate(line.split("|")):
                machines, times = [], []
                for pair in seg.replace("，", ",").split(","):
                    pair = pair.strip()
                    if not pair:
                        continue
                    try:
                        m, t = pair.split(":")
                        machines.append(int(m))
                        times.append(float(t))
                    except ValueError:
                        st.error(
                            f"工件 {jid} 工序 {op_id} 片段 {pair!r} 格式错误，"
                            f"应为 `设备:时间`。"
                        )
                        parse_ok = False
                        break
                if not parse_ok:
                    break
                if machines:
                    ops.append({"eligible_machines": machines, "processing_times": times})
            if not parse_ok:
                break
            if ops:
                jobs.append({"job_id": jid, "operations": ops})

        if not parse_ok:
            st.stop()
        if not jobs:
            st.error("未解析到任何工件，请检查工艺矩阵。")
            st.stop()

        # 校验设备号越界
        for j in jobs:
            for op_id, op in enumerate(j["operations"]):
                for m in op["eligible_machines"]:
                    if not (0 <= m < num_machines):
                        st.error(
                            f"工件 {j['job_id']} 工序 {op_id} 设备号 {m} 越界"
                            f"（应为 0..{num_machines - 1}）。"
                        )
                        st.stop()

        payload = {
            "name": name,
            "num_jobs": len(jobs),
            "num_machines": num_machines,
            "jobs": jobs,
        }
        try:
            meta = api_client.create_custom_instance(payload)
        except api_client.ApiError as exc:
            st.error(str(exc))
        else:
            st.success(
                f"算例 {meta['name']!r} 已注册："
                f"{meta['num_jobs']} 个工件 / {meta['num_machines']} 台设备 / "
                f"{meta['total_operations']} 道工序。可在调度工作台选择该算例求解。"
            )
