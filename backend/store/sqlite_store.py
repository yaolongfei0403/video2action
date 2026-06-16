"""SQLite-based persistent store (零外部依赖).

为简化本地启动：默认用 SQLite 替代 PRD 中的 PostgreSQL。
提供 tasks / videos / clips / assets 四个表的 CRUD + 状态机驱动。
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

from .models import (
    ActionClip,
    Clip,
    ClipCandidate,
    Task,
    TaskStatus,
    TaskType,
    VideoSource,
    VideoStatus,
)

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    status TEXT NOT NULL,
    video_id TEXT,
    clip_id TEXT,
    current_stage TEXT,
    progress REAL DEFAULT 0,
    message TEXT,
    error TEXT,
    created_at TEXT,
    updated_at TEXT,
    meta TEXT  -- JSON
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    guid TEXT,
    status TEXT NOT NULL,
    file_path TEXT,
    duration REAL,
    width INTEGER,
    height INTEGER,
    fps REAL,
    total_frames INTEGER,
    created_at TEXT,
    meta TEXT
);

CREATE TABLE IF NOT EXISTS clip_candidates (
    id TEXT PRIMARY KEY,
    video_id TEXT NOT NULL,
    start_frame INTEGER,
    end_frame INTEGER,
    score REAL,
    approved INTEGER,
    rejected INTEGER DEFAULT 0,
    reason TEXT,
    meta TEXT
);

CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    task_id TEXT,
    video_id TEXT,
    start_frame INTEGER,
    end_frame INTEGER,
    start_sec REAL,
    end_sec REAL,
    duration REAL,
    status TEXT,
    keywords TEXT,
    summary TEXT,
    detail TEXT,
    rhythm TEXT,
    use_case TEXT,
    manual_tags TEXT,
    quality_grade TEXT,
    rendered_video_url TEXT,
    mesh_dir TEXT,
    annotations TEXT,
    created_at TEXT,
    updated_at TEXT,
    meta TEXT
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    clip_id TEXT,
    guid TEXT,
    duration REAL,
    keywords TEXT,
    summary TEXT,
    detail TEXT,
    rhythm TEXT,
    use_case TEXT,
    manual_tags TEXT,
    quality_grade TEXT,
    rendered_video_url TEXT,
    original_video_url TEXT,
    view_count INTEGER DEFAULT 0,
    created_at TEXT,
    meta TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_clips_video ON clips(video_id);
CREATE INDEX IF NOT EXISTS idx_assets_grade ON assets(quality_grade);
"""


class SQLiteStore:
    """线程安全的 SQLite 封装。

    用法：
        store = SQLiteStore("./data/system.db")
        store.create_task(...)
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def _cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.cursor()
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._cursor() as cur:
            cur.executescript(_SCHEMA)
            # 迁移：老库没有 rejected 列 → 补上
            try:
                cur.execute("ALTER TABLE clip_candidates ADD COLUMN rejected INTEGER DEFAULT 0")
            except Exception:
                pass  # 列已存在

    # ============== Tasks ==============

    def create_task(self, task: Task) -> Task:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO tasks
                (id, type, status, video_id, clip_id, current_stage, progress, message, error, created_at, updated_at, meta)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task.id, task.type.value, task.status.value, task.video_id, task.clip_id,
                    task.current_stage, task.progress, task.message, task.error,
                    task.created_at.isoformat(), task.updated_at.isoformat(),
                    json.dumps(task.meta, ensure_ascii=False),
                ),
            )
        return task

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        current_stage: Optional[str] = None,
        meta_update: Optional[dict[str, Any]] = None,
    ) -> Optional[Task]:
        existing = self.get_task(task_id)
        if existing is None:
            return None
        if status is not None:
            existing.status = status
        if progress is not None:
            existing.progress = progress
        if message is not None:
            existing.message = message
        if error is not None:
            existing.error = error
        if current_stage is not None:
            existing.current_stage = current_stage
        if meta_update:
            existing.meta.update(meta_update)
        existing.updated_at = datetime.utcnow()
        with self._cursor() as cur:
            cur.execute(
                """UPDATE tasks SET status=?, progress=?, message=?, error=?,
                   current_stage=?, updated_at=?, meta=? WHERE id=?""",
                (
                    existing.status.value, existing.progress, existing.message,
                    existing.error, existing.current_stage,
                    existing.updated_at.isoformat(),
                    json.dumps(existing.meta, ensure_ascii=False),
                    task_id,
                ),
            )
        return existing

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        return self._row_to_task(row)

    def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        limit: int = 100,
    ) -> list[Task]:
        with self._cursor() as cur:
            if status is not None:
                rows = cur.execute(
                    "SELECT * FROM tasks WHERE status=? ORDER BY created_at DESC LIMIT ?",
                    (status.value, limit),
                ).fetchall()
            else:
                rows = cur.execute(
                    "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task(
            id=row["id"],
            type=TaskType(row["type"]),
            status=TaskStatus(row["status"]),
            video_id=row["video_id"],
            clip_id=row["clip_id"],
            current_stage=row["current_stage"] or "",
            progress=row["progress"] or 0.0,
            message=row["message"] or "",
            error=row["error"] or "",
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.utcnow(),
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else datetime.utcnow(),
            meta=json.loads(row["meta"] or "{}"),
        )

    # ============== Videos ==============

    def create_video(self, video: VideoSource) -> VideoSource:
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO videos
                (id, guid, status, file_path, duration, width, height, fps, total_frames, created_at, meta)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    video.id, video.guid, video.status.value, video.file_path,
                    video.duration, video.resolution[0], video.resolution[1],
                    video.fps, video.total_frames, video.created_at.isoformat(),
                    json.dumps(video.meta, ensure_ascii=False),
                ),
            )
        return video

    def get_video(self, video_id: str) -> Optional[VideoSource]:
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        if not row:
            return None
        return VideoSource(
            id=row["id"],
            guid=row["guid"],
            status=VideoStatus(row["status"]),
            file_path=row["file_path"] or "",
            duration=row["duration"] or 0.0,
            resolution=(row["width"] or 0, row["height"] or 0),
            fps=row["fps"] or 0.0,
            total_frames=row["total_frames"] or 0,
            created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.utcnow(),
            meta=json.loads(row["meta"] or "{}"),
        )

    def update_video_status(self, video_id: str, status: VideoStatus) -> None:
        with self._cursor() as cur:
            cur.execute("UPDATE videos SET status=? WHERE id=?", (status.value, video_id))

    def list_videos(self, limit: int = 50) -> list[VideoSource]:
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM videos ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            VideoSource(
                id=r["id"],
                guid=r["guid"],
                status=VideoStatus(r["status"]),
                file_path=r["file_path"] or "",
                duration=r["duration"] or 0.0,
                resolution=(r["width"] or 0, r["height"] or 0),
                fps=r["fps"] or 0.0,
                total_frames=r["total_frames"] or 0,
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.utcnow(),
                meta=json.loads(r["meta"] or "{}"),
            )
            for r in rows
        ]

    # ============== Clip Candidates ==============

    def add_candidates(self, candidates: list[ClipCandidate]) -> None:
        with self._cursor() as cur:
            cur.executemany(
                """INSERT OR REPLACE INTO clip_candidates
                (id, video_id, start_frame, end_frame, score, approved, rejected, reason, meta)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        c.id, c.video_id, c.start_frame, c.end_frame,
                        c.score, int(c.approved), int(c.rejected), c.reason,
                        json.dumps(c.meta, ensure_ascii=False),
                    )
                    for c in candidates
                ],
            )

    def get_candidate(self, candidate_id: str) -> Optional[ClipCandidate]:
        """按 id 取单个粗切候选（精切 decide 流程需要）。"""
        with self._cursor() as cur:
            row = cur.execute(
                "SELECT * FROM clip_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
        if not row:
            return None
        return ClipCandidate(
            id=row["id"],
            video_id=row["video_id"],
            start_frame=row["start_frame"],
            end_frame=row["end_frame"],
            score=row["score"] or 0.0,
            approved=bool(row["approved"]),
            rejected=bool(row["rejected"]),
            reason=row["reason"] or "",
            meta=json.loads(row["meta"] or "{}"),
        )

    def list_candidates(self, video_id: str) -> list[ClipCandidate]:
        with self._cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM clip_candidates WHERE video_id=? ORDER BY start_frame",
                (video_id,),
            ).fetchall()
        return [
            ClipCandidate(
                id=r["id"],
                video_id=r["video_id"],
                start_frame=r["start_frame"],
                end_frame=r["end_frame"],
                score=r["score"] or 0.0,
                approved=bool(r["approved"]),
                rejected=bool(r["rejected"]),
                reason=r["reason"] or "",
                meta=json.loads(r["meta"] or "{}"),
            )
            for r in rows
        ]

    def update_candidate(
        self,
        candidate_id: str,
        approved: Optional[bool] = None,
        rejected: Optional[bool] = None,
    ) -> None:
        """更新候选状态。approved / rejected 任一非 None 即更新对应字段。"""
        sets: list[str] = []
        vals: list[Any] = []
        if approved is not None:
            sets.append("approved=?")
            vals.append(int(approved))
        if rejected is not None:
            sets.append("rejected=?")
            vals.append(int(rejected))
        if not sets:
            return
        vals.append(candidate_id)
        with self._cursor() as cur:
            cur.execute(
                f"UPDATE clip_candidates SET {', '.join(sets)} WHERE id=?",
                vals,
            )

    # ============== Clips ==============

    def upsert_clip(self, clip: Clip) -> Clip:
        clip.updated_at = datetime.utcnow()
        with self._cursor() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO clips
                (id, task_id, video_id, start_frame, end_frame, start_sec, end_sec, duration,
                 status, keywords, summary, detail, rhythm, use_case, manual_tags, quality_grade,
                 rendered_video_url, mesh_dir, annotations, created_at, updated_at, meta)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    clip.id, clip.task_id, clip.video_id,
                    clip.start_frame, clip.end_frame, clip.start_sec, clip.end_sec, clip.duration,
                    clip.status.value, clip.keywords, clip.summary, clip.detail,
                    clip.rhythm, clip.use_case,
                    json.dumps(clip.manual_tags, ensure_ascii=False),
                    clip.quality_grade, clip.rendered_video_url, clip.mesh_dir,
                    json.dumps([a.model_dump() for a in clip.annotations], ensure_ascii=False),
                    clip.created_at.isoformat(), clip.updated_at.isoformat(),
                    json.dumps(clip.meta, ensure_ascii=False),
                ),
            )
        return clip

    def get_clip(self, clip_id: str) -> Optional[Clip]:
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
        if not row:
            return None
        return self._row_to_clip(row)

    def list_clips(self, video_id: Optional[str] = None, limit: int = 100) -> list[Clip]:
        with self._cursor() as cur:
            if video_id:
                rows = cur.execute(
                    "SELECT * FROM clips WHERE video_id=? ORDER BY created_at DESC LIMIT ?",
                    (video_id, limit),
                ).fetchall()
            else:
                rows = cur.execute(
                    "SELECT * FROM clips ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_clip(r) for r in rows]

    def _row_to_clip(self, r: sqlite3.Row) -> Clip:
        from .models import ClipStatus, MaskAnnotation
        return Clip(
            id=r["id"],
            task_id=r["task_id"] or "",
            video_id=r["video_id"] or "",
            start_frame=r["start_frame"] or 0,
            end_frame=r["end_frame"] or 0,
            start_sec=r["start_sec"] or 0.0,
            end_sec=r["end_sec"] or 0.0,
            duration=r["duration"] or 0.0,
            status=ClipStatus(r["status"]) if r["status"] else ClipStatus.CANDIDATE,
            keywords=r["keywords"] or "",
            summary=r["summary"] or "",
            detail=r["detail"] or "",
            rhythm=r["rhythm"] or "",
            use_case=r["use_case"] or "",
            manual_tags=json.loads(r["manual_tags"] or "[]"),
            quality_grade=r["quality_grade"] or "B",
            rendered_video_url=r["rendered_video_url"] or "",
            mesh_dir=r["mesh_dir"] or "",
            annotations=[MaskAnnotation(**a) for a in json.loads(r["annotations"] or "[]")],
            created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.utcnow(),
            updated_at=datetime.fromisoformat(r["updated_at"]) if r["updated_at"] else datetime.utcnow(),
            meta=json.loads(r["meta"] or "{}"),
        )

    # ============== Assets ==============

    def upsert_asset(self, asset: ActionClip) -> ActionClip:
        with self._cursor() as cur:
            cur.execute(
                """INSERT OR REPLACE INTO assets
                (id, clip_id, guid, duration, keywords, summary, detail, rhythm, use_case,
                 manual_tags, quality_grade, rendered_video_url, original_video_url,
                 view_count, created_at, meta)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    asset.id, asset.clip_id, asset.guid, asset.duration,
                    asset.keywords, asset.summary, asset.detail, asset.rhythm, asset.use_case,
                    json.dumps(asset.manual_tags, ensure_ascii=False),
                    asset.quality_grade,
                    asset.rendered_video_url, asset.original_video_url,
                    asset.view_count, asset.created_at.isoformat(),
                    json.dumps(asset.meta, ensure_ascii=False),
                ),
            )
        return asset

    def list_assets(
        self,
        limit: int = 50,
        quality_grades: Optional[list[str]] = None,
    ) -> list[ActionClip]:
        with self._cursor() as cur:
            if quality_grades:
                placeholders = ",".join("?" * len(quality_grades))
                rows = cur.execute(
                    f"SELECT * FROM assets WHERE quality_grade IN ({placeholders}) "
                    "ORDER BY created_at DESC LIMIT ?",
                    (*quality_grades, limit),
                ).fetchall()
            else:
                rows = cur.execute(
                    "SELECT * FROM assets ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_asset(r) for r in rows]

    def get_asset(self, asset_id: str) -> Optional[ActionClip]:
        with self._cursor() as cur:
            row = cur.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            return None
        return self._row_to_asset(row)

    def _row_to_asset(self, r: sqlite3.Row) -> ActionClip:
        return ActionClip(
            id=r["id"],
            clip_id=r["clip_id"] or "",
            guid=r["guid"],
            duration=r["duration"] or 0.0,
            keywords=r["keywords"] or "",
            summary=r["summary"] or "",
            detail=r["detail"] or "",
            rhythm=r["rhythm"] or "",
            use_case=r["use_case"] or "",
            manual_tags=json.loads(r["manual_tags"] or "[]"),
            quality_grade=r["quality_grade"] or "B",
            rendered_video_url=r["rendered_video_url"] or "",
            original_video_url=r["original_video_url"] or "",
            view_count=r["view_count"] or 0,
            created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else datetime.utcnow(),
            meta=json.loads(r["meta"] or "{}"),
        )

    # ============== 统计 ==============

    def count_tasks(self, status: Optional[TaskStatus] = None) -> int:
        with self._cursor() as cur:
            if status is not None:
                row = cur.execute("SELECT COUNT(*) as c FROM tasks WHERE status=?", (status.value,)).fetchone()
            else:
                row = cur.execute("SELECT COUNT(*) as c FROM tasks").fetchone()
        return int(row["c"]) if row else 0

    def count_assets(self) -> int:
        with self._cursor() as cur:
            row = cur.execute("SELECT COUNT(*) as c FROM assets").fetchone()
        return int(row["c"]) if row else 0

    def count_clips(self) -> int:
        with self._cursor() as cur:
            row = cur.execute("SELECT COUNT(*) as c FROM clips").fetchone()
        return int(row["c"]) if row else 0
