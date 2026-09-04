#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 服务入口（模块 M9，对应设计说明书 §3.9 接口清单）。

启动：``uvicorn backend.main:app --host 127.0.0.1 --port 8000``
接口文档：http://127.0.0.1:8000/docs
"""

from __future__ import annotations

from typing import List

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from . import export, reschedule, service
from .schemas import (
    CompareRequest,
    CustomInstanceIn,
    InstanceMeta,
    RescheduleRequest,
    SolveRequest,
    SolveResponse,
)

app = FastAPI(
    title="SmartFJSP 调度服务",
    description="基于智能优化算法的柔性作业车间调度系统 —— RESTful API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/instances", response_model=List[InstanceMeta], tags=["算例管理"])
def list_instances():
    """列出可用算例（标准 + 自定义）。"""
    return service.list_instances()


@app.post("/api/instance/custom", response_model=InstanceMeta, tags=["算例管理"])
def create_custom_instance(payload: CustomInstanceIn):
    """提交自定义算例（0 基设备号），注册后可用于求解。"""
    try:
        inst = service.register_custom_instance(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return InstanceMeta(
        name=inst.name,
        num_jobs=inst.num_jobs,
        num_machines=inst.num_machines,
        total_operations=inst.total_operations,
    )


@app.post("/api/solve", response_model=SolveResponse, tags=["调度求解"])
def solve(request: SolveRequest):
    """执行调度求解，返回方案 ID、收敛历史与排程明细。"""
    try:
        return service.solve(request.instance_name, request.config)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/api/schedule/{schedule_id}", tags=["方案检索"])
def get_schedule(schedule_id: str):
    """获取指定排程方案的明细。"""
    try:
        stored = service.get_stored(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "schedule_id": schedule_id,
        "instance_name": stored["instance_name"],
        "algorithm": stored["algorithm"],
        "makespan": stored["result"].schedule.makespan,
        "elapsed": stored["result"].elapsed,
        "schedule": service.get_schedule_out(schedule_id),
    }


@app.post("/api/compare", tags=["方案对比"])
def compare(request: CompareRequest):
    """多方案指标并排对比与收敛曲线。"""
    schedules = []
    convergence = []
    for sid in request.schedule_ids:
        try:
            stored = service.get_stored(sid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        result = stored["result"]
        schedules.append({
            "schedule_id": sid,
            "instance_name": stored["instance_name"],
            "algorithm": stored["algorithm"],
            "makespan": result.schedule.makespan,
            "elapsed": result.elapsed,
        })
        convergence.append({
            "schedule_id": sid,
            "algorithm": stored["algorithm"],
            "history": result.history,
            "avg_history": result.avg_history,
        })
    return {"schedules": schedules, "convergence": convergence}


@app.post("/api/reschedule", tags=["插单重调度"])
def reschedule_request(request: RescheduleRequest):
    """在已有方案中插入新工单并重调度，返回新方案与差异。"""
    try:
        stored = service.get_stored(request.schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        return reschedule.reschedule(stored, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/export/{schedule_id}/{format}", tags=["结果导出"])
def export_result(schedule_id: str, format: str):
    """导出方案为 csv / png / html。"""
    try:
        stored = service.get_stored(schedule_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    schedule = stored["result"].schedule
    instance = stored["instance"]
    result = stored["result"]
    fmt = format.lower()

    if fmt == "csv":
        content = export.export_csv(schedule)
        return Response(
            content=content, media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{schedule_id}.csv"'},
        )
    if fmt == "png":
        png = export.export_gantt_png(schedule, instance)
        return Response(content=png, media_type="image/png")
    if fmt == "html":
        html = export.export_html_report(schedule, instance, result)
        return Response(content=html, media_type="text/html")
    raise HTTPException(status_code=400, detail="format 必须为 csv/png/html")
