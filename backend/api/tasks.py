"""/api/tasks - 任务中心"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..store import Task, TaskStatus, TaskType, get_store

router = APIRouter()


class TaskCreate(BaseModel):
    type: TaskType
    video_id: Optional[str] = None
    clip_id: Optional[str] = None
    message: str = ""


@router.get("")
def list_tasks(status: Optional[TaskStatus] = None, limit: int = 100) -> dict:
    """获取任务列表 - 复现 HTML 任务中心表格。"""
    store = get_store()
    tasks = store.list_tasks(status=status, limit=limit)
    return {
        "tasks": [_task_to_dict(t) for t in tasks],
        "total": len(tasks),
    }


@router.post("", response_model=dict)
def create_task(req: TaskCreate) -> dict:
    """创建任务。"""
    store = get_store()
    task = Task(
        type=req.type,
        video_id=req.video_id,
        clip_id=req.clip_id,
        status=TaskStatus.PENDING,
        message=req.message,
    )
    store.create_task(task)
    return _task_to_dict(task)


@router.get("/{task_id}")
def get_task(task_id: str) -> dict:
    """获取单个任务详情。"""
    store = get_store()
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    return _task_to_dict(task)


@router.post("/{task_id}/advance")
def advance_task(task_id: str, status: TaskStatus, message: str = "", progress: float = 0.0) -> dict:
    """推进任务状态 - 内部用 API, 也可被前端手动触发。"""
    store = get_store()
    updated = store.update_task(
        task_id,
        status=status,
        progress=progress,
        message=message,
        current_stage=status.value,
    )
    if updated is None:
        raise HTTPException(404, "Task not found")
    return _task_to_dict(updated)


@router.delete("/{task_id}")
def delete_task(task_id: str) -> dict:
    """删除任务（仅做软删除标记）。"""
    store = get_store()
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Task not found")
    task.meta["deleted"] = True
    store.update_task(task_id, meta_update=task.meta)
    return {"ok": True}


def _task_to_dict(t: Task) -> dict:
    return {
        "id": t.id,
        "type": t.type.value,
        "status": t.status.value,
        "video_id": t.video_id,
        "clip_id": t.clip_id,
        "current_stage": t.current_stage,
        "progress": t.progress,
        "message": t.message,
        "error": t.error,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
        "meta": t.meta,
    }
