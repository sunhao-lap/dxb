#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit 前端 —— FastAPI 客户端封装。

统一封装对后端 RESTful 接口（§3.9）的 HTTP 调用，前端页面不直接拼 URL。
后端地址可用环境变量 ``SMARTFJSP_API`` 覆盖，默认 ``http://127.0.0.1:8000``。
"""

from __future__ import annotations

import os
from typing import List, Optional

import requests

BASE_URL = os.environ.get("SMARTFJSP_API", "http://127.0.0.1:8000")


class ApiError(RuntimeError):
    """后端调用异常。"""


def _request(method: str, path: str, **kwargs):
    url = f"{BASE_URL}{path}"
    try:
        resp = requests.request(method, url, timeout=120, **kwargs)
    except requests.exceptions.ConnectionError:
        raise ApiError(f"无法连接后端服务 {BASE_URL}，请先启动：python run.py backend")
    if resp.status_code >= 400:
        detail = resp.text
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            pass
        raise ApiError(f"后端错误 {resp.status_code}: {detail}")
    return resp


# ---------------------------------------------------------------------------
# 算例管理（M1）
# ---------------------------------------------------------------------------


def list_instances() -> List[dict]:
    """列出可用算例。"""
    return _request("GET", "/api/instances").json()


def create_custom_instance(payload: dict) -> dict:
    """提交自定义算例。"""
    return _request("POST", "/api/instance/custom", json=payload).json()


# ---------------------------------------------------------------------------
# 调度求解（M2/M3/M4）
# ---------------------------------------------------------------------------


def solve(instance_name: str, config: dict) -> dict:
    """执行调度求解。"""
    return _request(
        "POST", "/api/solve",
        json={"instance_name": instance_name, "config": config},
    ).json()


def get_schedule(schedule_id: str) -> dict:
    """获取方案明细。"""
    return _request("GET", f"/api/schedule/{schedule_id}").json()


def compare(schedule_ids: List[str]) -> dict:
    """多方案对比。"""
    return _request("POST", "/api/compare", json={"schedule_ids": schedule_ids}).json()


# ---------------------------------------------------------------------------
# 插单重调度（M7）
# ---------------------------------------------------------------------------


def reschedule(payload: dict) -> dict:
    """插单重调度。"""
    return _request("POST", "/api/reschedule", json=payload).json()


# ---------------------------------------------------------------------------
# 结果导出（M8）
# ---------------------------------------------------------------------------


def export_url(schedule_id: str, fmt: str) -> str:
    """构造导出文件下载地址。"""
    return f"{BASE_URL}/api/export/{schedule_id}/{fmt}"


def export_content(schedule_id: str, fmt: str) -> bytes:
    """拉取导出文件内容。"""
    return _request("GET", f"/api/export/{schedule_id}/{fmt}").content
