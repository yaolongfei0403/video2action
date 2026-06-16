"""FastAPI 主入口."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 兼容 `python backend/main.py` 与 `uvicorn backend.main:app`
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api import register_routes
from backend.config import get_config
from backend.pipeline_registry import get_pipeline  # re-export for api modules
from backend.store import get_store
from backend.vector import get_vector_store

cfg = get_config()
logging.basicConfig(
    level=getattr(logging, cfg.runtime.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ============== 自定义 StaticFiles：开发期禁用缓存 ==============


class NoCacheStaticFiles(StaticFiles):
    """开发期禁用浏览器缓存 - 避免修改 CSS/JS 后看不到效果。"""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


# ============== App 工厂 ==============


def create_app() -> FastAPI:
    app = FastAPI(
        title="4D Action Knowledge Base API",
        version="2.4.1",
        description="4D 动作知识库系统后端 - 上游视频接入 → 粗精切 → 4D 重建 → 语义入库 → 文本检索",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册 API
    register_routes(app)

    # 静态资源（前端）- 用 NoCacheStaticFiles 禁用浏览器缓存
    frontend_dir = ROOT / "frontend"
    if frontend_dir.exists():
        # 优先：app/static 目录的打包资源
        static_dir = frontend_dir / "static"
        if static_dir.exists():
            app.mount("/static", NoCacheStaticFiles(directory=str(static_dir)), name="static")
        # 兼容：CSS/JS 在 frontend 根目录
        for sub in ["css", "js", "assets"]:
            sub_dir = frontend_dir / sub
            if sub_dir.exists():
                app.mount(f"/{sub}", NoCacheStaticFiles(directory=str(sub_dir)), name=sub)

    # 渲染视频 / 抽帧产物 (PRD 中对象存储替代 - 本地用文件系统)
    outputs_dir = Path(cfg.runtime.output_dir)
    if outputs_dir.exists():
        app.mount("/api/outputs", StaticFiles(directory=str(outputs_dir)), name="outputs")

    @app.get("/", include_in_schema=False)
    def root():
        index = frontend_dir / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return JSONResponse({
            "name": "4D Action Knowledge Base API",
            "version": "2.4.1",
            "docs": "/docs",
        })

    @app.get("/health")
    def health():
        return {"status": "ok", "version": "2.4.1"}

    @app.on_event("startup")
    def on_startup():
        # 初始化 store + vector store
        store = get_store()
        vec = get_vector_store()
        logger.info(f"Store: {len(store.list_videos(limit=1000))} videos, "
                    f"{store.count_clips()} clips, {store.count_assets()} assets")
        logger.info(f"VectorStore: {vec.__class__.__name__} with {vec.count()} entries")
        # Pipeline 预热（可选；启动慢但首请求快）
        logger.info("Pipelines ready (lazy init on first use)")

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = get_config()
    uvicorn.run(
        "backend.main:app",
        host=cfg.runtime.host,
        port=cfg.runtime.port,
        reload=False,
        log_level=cfg.runtime.log_level.lower(),
    )
