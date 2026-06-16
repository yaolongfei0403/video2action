"""Pydantic 数据模型 - 对应 PRD 中的数据模型。

涵盖：VideoSource, Clip, ActionClip, Task, MaskAnnotation, FrameMask
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


def _id() -> str:
    return uuid.uuid4().hex[:16]


def _now() -> datetime:
    return datetime.utcnow()


# ============== 枚举 ==============


class TaskStatus(str, Enum):
    """任务状态机 (复现 PRD 4.1 节)"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    ROUGH_CUTTING = "rough_cutting"
    ROUGH_CUT = "rough_cut"
    FINE_CUT = "fine_cut"
    ANNOTATING = "annotating"
    MASK_PROPAGATING = "mask_propagating"
    FOUR_D_RECONSTRUCTING = "4d_reconstructing"
    SEMANTIC_TAGGING = "semantic_tagging"
    INDEXING = "indexing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskType(str, Enum):
    LOCAL_IMPORT = "local_import"
    GUID_BATCH = "guid_batch"
    PROCESS_VIDEO = "process_video"
    FOUR_D_RECONSTRUCT = "4d_reconstruct"
    VLM_TAG = "vlm_tag"
    INDEX = "index"


class VideoStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"


class ClipStatus(str, Enum):
    CANDIDATE = "candidate"        # 粗切候选
    APPROVED = "approved"          # 粗切通过 (待精切)
    REJECTED = "rejected"          # 粗切拒绝
    FINE_CUT = "fine_cut"          # 已精切 (待标注)
    ANNOTATED = "annotated"        # 已标注 (待 4D)
    FOUR_D_DONE = "4d_done"        # 4D 完成 (待打标)
    TAGGED = "tagged"              # 已打标 (待入库)
    INDEXED = "indexed"            # 已入库


# ============== 视频源 ==============


class VideoSource(BaseModel):
    """上游视频源 (复现 PRD 3.1.1 VideoSource)"""
    id: str = Field(default_factory=_id)
    guid: Optional[str] = None
    status: VideoStatus = VideoStatus.PENDING
    file_path: str = ""
    duration: float = 0.0
    resolution: tuple[int, int] = (0, 0)
    fps: float = 0.0
    total_frames: int = 0
    created_at: datetime = Field(default_factory=_now)
    meta: dict[str, Any] = Field(default_factory=dict)


# ============== 片段 ==============


class ClipCandidate(BaseModel):
    """粗切候选片段"""
    id: str = Field(default_factory=_id)
    video_id: str
    start_frame: int
    end_frame: int
    score: float = 0.0  # 0~1, 自动打分
    approved: bool = False
    rejected: bool = False
    reason: str = ""    # 入选理由 / 备注
    meta: dict[str, Any] = Field(default_factory=dict)


class Clip(BaseModel):
    """精切后的最终片段 (复现 PRD 3.2.3 Clip)"""
    id: str = Field(default_factory=_id)
    task_id: str
    video_id: str
    start_frame: int
    end_frame: int
    start_sec: float = 0.0
    end_sec: float = 0.0
    duration: float = 0.0
    status: ClipStatus = ClipStatus.CANDIDATE
    # 标注数据
    annotations: list["MaskAnnotation"] = Field(default_factory=list)
    # 4D 重建产物
    rendered_video_url: str = ""
    mesh_dir: str = ""
    # 标签
    keywords: str = ""
    summary: str = ""
    detail: str = ""
    rhythm: str = ""
    use_case: str = ""
    manual_tags: list[str] = Field(default_factory=list)
    quality_grade: str = "B"  # A / B / C
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    meta: dict[str, Any] = Field(default_factory=dict)


class MaskAnnotation(BaseModel):
    """单次点击标注 (复现 app.py on_click 逻辑)"""
    id: str = Field(default_factory=_id)
    obj_id: int
    frame_idx: int
    point_type: str = "positive"  # positive / negative
    x: int
    y: int


# ============== 任务 ==============


class Task(BaseModel):
    """通用任务 (复现 PRD 4.1 状态机)"""
    id: str = Field(default_factory=_id)
    type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    video_id: Optional[str] = None
    clip_id: Optional[str] = None
    current_stage: str = ""
    progress: float = 0.0  # 0~1
    message: str = ""
    error: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
    meta: dict[str, Any] = Field(default_factory=dict)


# ============== 资产 (入库条目) ==============


class ActionClip(BaseModel):
    """入库条目 (复现 PRD 3.3.3 Weaviate ActionClip schema)"""
    id: str = Field(default_factory=_id)
    clip_id: str
    guid: Optional[str] = None
    duration: float = 0.0
    keywords: str = ""
    summary: str = ""
    detail: str = ""
    rhythm: str = ""
    use_case: str = ""
    manual_tags: list[str] = Field(default_factory=list)
    quality_grade: str = "B"
    rendered_video_url: str = ""
    original_video_url: str = ""
    created_at: datetime = Field(default_factory=_now)
    # 向量在 VectorStore 中独立存储
    view_count: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)


# ============== 检索 ==============


class SearchHit(BaseModel):
    """检索命中"""
    id: str
    score: float
    payload: dict[str, Any] = Field(default_factory=dict)


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    threshold: float = 0.0
    filters: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    query: str
    results: list[SearchHit]
    total: int
    query_time_ms: float


# ============== Dashboard ==============


class DashboardMetrics(BaseModel):
    videos_today: int = 0
    actions_today: int = 0
    processing_tasks: int = 0
    success_rate: float = 0.0
    total_assets: int = 0
    gpu_idle: int = 0
    gpu_total: int = 0


# Resolve forward references
Clip.model_rebuild()
