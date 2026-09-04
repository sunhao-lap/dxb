#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
结果导出页（/export，对应设计说明书 §3.8 M8 结果导出）。

导出已求解方案为 CSV 明细 / PNG 甘特图 / HTML 性能报告，支持预览与下载。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import io  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import api_client  # noqa: E402

st.set_page_config(page_title="结果导出", page_icon="📥", layout="wide")
st.title("📥 结果导出")

st.session_state.setdefault("schedule_ids", [])

col1, col2 = st.columns([2, 1])
if st.session_state["schedule_ids"]:
    schedule_id = col1.selectbox("选择方案", st.session_state["schedule_ids"])
else:
    schedule_id = col1.text_input("方案 ID（请先在调度工作台求解）")

fmt = col2.selectbox(
    "导出格式", ["csv", "png", "html"],
    format_func=lambda x: {"csv": "CSV 工序明细", "png": "PNG 甘特图",
                           "html": "HTML 性能报告"}[x],
)

if st.button("📥 生成导出", type="primary"):
    if not schedule_id:
        st.warning("请先选择方案。")
        st.stop()
    try:
        content = api_client.export_content(schedule_id, fmt)
    except api_client.ApiError as exc:
        st.error(str(exc))
        st.stop()

    if fmt == "csv":
        st.download_button(
            "⬇️ 下载 CSV", content, file_name=f"{schedule_id}.csv",
            mime="text/csv",
        )
        try:
            df = pd.read_csv(io.BytesIO(content))
            st.dataframe(df, use_container_width=True)
        except Exception:
            st.code(content.decode("utf-8", errors="ignore"), language="text")
    elif fmt == "png":
        st.image(content, caption=f"方案 {schedule_id} 甘特图", use_container_width=True)
        st.download_button(
            "⬇️ 下载 PNG", content, file_name=f"{schedule_id}.png", mime="image/png",
        )
    else:  # html
        st.download_button(
            "⬇️ 下载 HTML", content, file_name=f"{schedule_id}.html", mime="text/html",
        )
        st.components.v1.html(content.decode("utf-8"), height=720, scrolling=True)
else:
    st.info("选择方案与格式后点击「生成导出」。")
