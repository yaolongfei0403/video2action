"""/api/import - 视频接入 (本地 + GUID 批量)"""
from __future__ import annotations

import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

import cv2
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..config import get_config
from ..store import (
    Task,
    TaskStatus,
    TaskType,
    VideoSource,
    VideoStatus,
    get_store,
)
from ..utils import read_video_metadata, file_path_to_url

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}


def _background_rough_cut(video_id: str, file_path: str,
                          min_dur: float = 3.0, min_motion: float = 0.0,
                          min_score: float = 0.1) -> None:
    """上传后自动入队 → 后台线程池执行粗切。

    状态机: PENDING → ROUGH_CUTTING → ROUGH_CUT (成功) / FAILED

    用 threading.Thread 避免 FastAPI BackgroundTasks 串行阻塞。
    """
    import threading
    from ..pipeline_registry import get_pipeline
    from ..store.models import ClipCandidate

    def _run():
        store = get_store()
        rough_task = Task(
            type=TaskType.PROCESS_VIDEO,
            video_id=video_id,
            status=TaskStatus.ROUGH_CUTTING,
            current_stage="rough_cutting",
            progress=0.0,
            message="自动粗切中…",
        )
        store.create_task(rough_task)
        t0 = time.time()
        try:
            engine = get_pipeline("rough_cut")
            engine.min_duration_sec = min_dur
            engine.min_motion = min_motion
            engine.min_score = min_score
            cands = engine.detect(file_path, progress_cb=lambda i, total: store.update_task(
                rough_task.id, progress=min(0.95, i / max(total, 1))
            ))
            models = [
                ClipCandidate(
                    video_id=video_id,
                    start_frame=c.start_frame,
                    end_frame=c.end_frame,
                    score=c.score,
                    meta={
                        "motion_score": c.motion_score,
                        "person_score": c.person_score,
                        "rough_task_id": rough_task.id,
                    },
                )
                for c in cands
            ]
            store.add_candidates(models)
            store.update_task(
                rough_task.id,
                status=TaskStatus.ROUGH_CUT,
                progress=1.0,
                current_stage="rough_cut",
                message=f"完成 · {len(cands)} 个候选 · {time.time() - t0:.1f}s",
            )
            logger.info(f"[auto-rough-cut] {video_id} done: {len(cands)} candidates")
        except Exception as e:
            logger.exception(f"[auto-rough-cut] {video_id} failed: {e}")
            store.update_task(
                rough_task.id, status=TaskStatus.FAILED, error=str(e),
                message=f"粗切失败: {e}",
            )

    t = threading.Thread(target=_run, daemon=True, name=f"rough-cut-{video_id[:8]}")
    t.start()


class GUIDImportRequest(BaseModel):
    """GUID 批量导入请求。

    实际下载逻辑需要对接上游 CDN（不在本系统范围内）；
    本系统为演示，把每个 GUID 视作占位（创建 pending 视频源）。
    """
    guids: list[str]
    auto_retry: bool = True
    dedup: bool = True


@router.post("/local")
async def import_local(file: UploadFile = File(...), background_tasks: BackgroundTasks = None) -> dict:
    """上传本地视频文件。

    上传成功后自动入队粗切（BackgroundTasks），无需手动触发。
    """
    store = get_store()
    cfg = get_config()

    # 检查扩展名
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Unsupported video format: {ext}")

    # 保存
    upload_dir = Path(cfg.runtime.output_dir) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{uuid.uuid4().hex[:12]}{ext}"
    dst = upload_dir / safe_name
    with dst.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    # 读元信息
    try:
        fps, total = read_video_metadata(str(dst))
        cap = cv2.VideoCapture(str(dst))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
    except Exception as e:
        raise HTTPException(400, f"Failed to read video: {e}")

    # 入库
    video = VideoSource(
        guid=Path(file.filename).stem,
        status=VideoStatus.DOWNLOADED,
        file_path=str(dst),
        duration=total / fps if fps else 0,
        resolution=(w, h),
        fps=fps,
        total_frames=total,
    )
    store.create_video(video)

    # 创建主任务 (imported) + 粗切任务 (queued)
    task = Task(
        type=TaskType.LOCAL_IMPORT,
        video_id=video.id,
        status=TaskStatus.DOWNLOADED,
        current_stage="imported",
        progress=1.0,
        message=f"Imported {file.filename}",
    )
    store.create_task(task)

    # 后台自动执行粗切
    if background_tasks is not None:
        background_tasks.add_task(_background_rough_cut, video.id, str(dst))

    return {
        "video": _video_to_dict(video),
        "task": task.id,
        "auto_rough_cut": True,  # 提示前端自动粗切已入队
    }


@router.post("/guid")
def import_guid(req: GUIDImportRequest) -> dict:
    """GUID 批量导入 (演示版：创建 pending 视频源，待人工下载)。"""
    store = get_store()
    cfg = get_config()

    # 去重
    guids = req.guids
    if req.dedup:
        existing = {v.guid for v in store.list_videos(limit=10000) if v.guid}
        guids = [g for g in guids if g not in existing]

    created: list[dict] = []
    for g in guids:
        video = VideoSource(
            guid=g,
            status=VideoStatus.PENDING,
            file_path="",
            meta={"auto_retry": req.auto_retry},
        )
        store.create_video(video)
        # 关联任务
        task = Task(
            type=TaskType.GUID_BATCH,
            video_id=video.id,
            status=TaskStatus.PENDING,
            message=f"Pending GUID: {g}",
        )
        store.create_task(task)
        created.append({"guid": g, "video_id": video.id, "task_id": task.id})

    return {
        "created": created,
        "total": len(created),
    }


@router.get("/history")
def import_history(limit: int = 20) -> dict:
    """导入历史。"""
    store = get_store()
    videos = store.list_videos(limit=limit)
    return {
        "videos": [_video_to_dict(v) for v in videos],
    }


@router.get("/video/{video_id}")
def get_video(video_id: str) -> dict:
    """获取视频详情。"""
    store = get_store()
    video = store.get_video(video_id)
    if video is None:
        raise HTTPException(404, "Video not found")
    return _video_to_dict(video)


def _video_to_dict(v: VideoSource) -> dict:
    # URL: outputs/ 已被挂载到 /api/outputs/
    # file_path 可能是 outputs/uploads/xxx.mp4, outputs/{task_id}/clips/xxx.mp4 等
    # 统一通过 file_path_to_url 归一化反斜杠、./ 前缀、outputs/ 前缀
    url = file_path_to_url(v.file_path)
    return {
        "id": v.id,
        "guid": v.guid,
        "status": v.status.value,
        "file_path": v.file_path,
        "url": url,
        "duration": v.duration,
        "resolution": list(v.resolution),
        "fps": v.fps,
        "total_frames": v.total_frames,
        "created_at": v.created_at.isoformat() if v.created_at else None,
    }
