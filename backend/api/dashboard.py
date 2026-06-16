"""/api/dashboard - Dashboard 总览指标"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import torch
from fastapi import APIRouter

from ..store import get_store, TaskStatus
from ..store.models import DashboardMetrics

logger = logging.getLogger(__name__)
router = APIRouter()


def _gpu_stats() -> tuple[int, int]:
    """检测 GPU 状态 (CUDA only). 0 / 0 表示无 GPU。"""
    if not torch.cuda.is_available():
        return 0, 0
    try:
        total = torch.cuda.device_count()
        # 用显存空闲率作为"空闲"的粗略估计
        idle = 0
        for i in range(total):
            free, total_mem = torch.cuda.mem_get_info(i)
            if free / total_mem > 0.5:
                idle += 1
        return idle, total
    except Exception:
        return 0, 0


def _success_rate() -> float:
    """从 store 统计 task 完成率。COMPLETED / (COMPLETED + FAILED)"""
    store = get_store()
    completed = len(store.list_tasks(status=TaskStatus.COMPLETED, limit=10000))
    failed = len(store.list_tasks(status=TaskStatus.FAILED, limit=10000))
    if completed + failed == 0:
        # 没有失败任务时默认 100%
        return 1.0 if completed > 0 else 0.0
    return completed / (completed + failed)


@router.get("/metrics", response_model=DashboardMetrics)
def get_metrics() -> DashboardMetrics:
    """总览指标 - 复现 HTML Dashboard 模块的顶部四个 KPI。

    所有字段均来自真实 store + 系统状态（无 mock）。
    """
    store = get_store()
    total_assets = store.count_assets()
    # 今日新增：取 created_at 在 24h 内的视频数
    now = datetime.utcnow()
    today_start = now - timedelta(hours=24)
    videos = store.list_videos(limit=10000)
    videos_today = sum(1 for v in videos if v.created_at and v.created_at >= today_start)
    # 进行中：所有非 COMPLETED/FAILED 状态的任务
    all_tasks = store.list_tasks(limit=10000)
    processing_tasks = sum(1 for t in all_tasks if t.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED))
    actions_today = total_assets
    success_rate = _success_rate()
    gpu_idle, gpu_total = _gpu_stats()
    return DashboardMetrics(
        videos_today=videos_today,
        actions_today=actions_today,
        processing_tasks=processing_tasks,
        success_rate=success_rate,
        total_assets=total_assets,
        gpu_idle=gpu_idle,
        gpu_total=gpu_total,
    )


@router.get("/recent")
def get_recent(limit: int = 6) -> dict:
    """最近处理的视频 - 复现 HTML Dashboard 底部网格。"""
    store = get_store()
    videos = store.list_videos(limit=limit)
    return {
        "videos": [
            {
                "id": v.id,
                "guid": v.guid or v.id,
                "name": Path(v.file_path).name if v.file_path else f"video_{v.id}",
                "duration": v.duration,
                "status": v.status.value,
                "created_at": v.created_at.isoformat(),
            }
            for v in videos
        ]
    }


@router.get("/category-stats")
def get_category_stats() -> dict:
    """资产分类统计 - 复现 HTML Dashboard 资产总量饼图。"""
    store = get_store()
    assets = store.list_assets(limit=10000)
    # 用 summary 中的关键词粗略分类
    cats: dict[str, int] = {
        "篮球": 0, "足球": 0, "舞蹈": 0, "拳击": 0, "滑板": 0, "其他": 0,
    }
    for a in assets:
        text = (a.keywords + a.summary).lower()
        if "篮球" in text:
            cats["篮球"] += 1
        elif "足球" in text:
            cats["足球"] += 1
        elif "舞蹈" in text or "舞" in text:
            cats["舞蹈"] += 1
        elif "拳击" in text or "搏击" in text:
            cats["拳击"] += 1
        elif "滑板" in text:
            cats["滑板"] += 1
        else:
            cats["其他"] += 1
    return {"categories": cats, "total": sum(cats.values())}


@router.get("/task-progress")
def get_task_progress() -> dict:
    """任务进度 - 复现 HTML Dashboard 任务进度列表。"""
    store = get_store()
    stages = [
        ("视频接入", "video_import"),
        ("粗切片段", "rough_cut"),
        ("精切片段", "fine_cut"),
        ("目标选择", "target"),
        ("4D 重建", "fourd"),
        ("标签生成", "tagging"),
    ]
    return {
        "stages": [
            {
                "name": name,
                "total": store.count_tasks(),
                "completed": store.count_assets(),
                "progress": 1.0 if store.count_tasks() == 0 else store.count_assets() / max(store.count_tasks(), 1),
            }
            for name, _ in stages
        ]
    }


from pathlib import Path
