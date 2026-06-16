"""backend.api - 11 个模块的 REST 路由注册"""
from fastapi import FastAPI

from .assets import router as assets_router
from .clip_queue import router as clip_queue_router
from .completed import router as completed_router
from .dashboard import router as dashboard_router
from .fine_cut import router as fine_cut_router
from .fourd import router as fourd_router
from .rough_cut import router as rough_cut_router
from .search import router as search_router
from .tagging import router as tagging_router
from .target import router as target_router
from .tasks import router as tasks_router
from .video_import import router as video_import_router


def register_routes(app: FastAPI) -> None:
    """挂载所有 API 路由到 FastAPI app。"""
    app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])
    app.include_router(tasks_router, prefix="/api/tasks", tags=["tasks"])
    app.include_router(video_import_router, prefix="/api/import", tags=["import"])
    app.include_router(rough_cut_router, prefix="/api/rough-cut", tags=["rough-cut"])
    app.include_router(fine_cut_router, prefix="/api/fine-cut", tags=["fine-cut"])
    app.include_router(clip_queue_router, prefix="/api/clips", tags=["clip-queue"])
    app.include_router(target_router, prefix="/api/target", tags=["target"])
    app.include_router(fourd_router, prefix="/api/4d", tags=["4d"])
    app.include_router(tagging_router, prefix="/api/tagging", tags=["tagging"])
    app.include_router(assets_router, prefix="/api/assets", tags=["assets"])
    app.include_router(search_router, prefix="/api/search", tags=["search"])
    app.include_router(completed_router, prefix="/api/completed", tags=["completed"])
