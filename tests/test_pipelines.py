"""端到端 Pipeline 单元测试（stub 模式）.

用法：
    cd /Users/yaolf/video2action
    PYTHONPATH=. pytest tests/ -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def temp_dirs(monkeypatch, tmp_path):
    """每个测试用临时目录隔离。"""
    monkeypatch.setenv("VECTOR_BACKEND", "stub")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    # 重新加载 config / store / vector
    import importlib
    from backend import config, store, vector
    importlib.reload(config)
    # 重置 store & vector 单例
    store._store = None
    vector._vector_store = None
    # 确保 data_dir 存在并清空
    import shutil
    data_dir = tmp_path / "data"
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True)
    yield tmp_path


# ============== 1. Store CRUD ==============


def test_store_crud(temp_dirs):
    from backend.store import (
        ActionClip,
        Clip,
        ClipCandidate,
        Task,
        TaskStatus,
        TaskType,
        VideoSource,
        VideoStatus,
        get_store,
    )

    store = get_store(db_path=str(temp_dirs / "test.db"))
    assert store.count_tasks() == 0

    # Create task
    t = Task(type=TaskType.LOCAL_IMPORT, status=TaskStatus.PENDING, message="test")
    store.create_task(t)
    assert store.count_tasks() == 1

    # Update
    store.update_task(t.id, status=TaskStatus.DOWNLOADED, progress=1.0, message="done")
    t2 = store.get_task(t.id)
    assert t2.status == TaskStatus.DOWNLOADED
    assert t2.progress == 1.0

    # Create video
    v = VideoSource(guid="vid_001", status=VideoStatus.DOWNLOADED, file_path="/tmp/x.mp4", duration=10.0, fps=30.0, total_frames=300)
    store.create_video(v)
    assert v.id in {x.id for x in store.list_videos()}

    # Add candidates
    cands = [ClipCandidate(video_id=v.id, start_frame=0, end_frame=150, score=0.85)]
    store.add_candidates(cands)
    listed = store.list_candidates(v.id)
    assert len(listed) == 1
    assert listed[0].score == 0.85

    # Upsert clip
    c = Clip(task_id=t.id, video_id=v.id, start_frame=0, end_frame=150, start_sec=0, end_sec=5, duration=5.0)
    store.upsert_clip(c)
    assert store.get_clip(c.id).duration == 5.0

    # Upsert asset
    a = ActionClip(clip_id=c.id, duration=5.0, summary="test", keywords="篮球")
    store.upsert_asset(a)
    assert store.count_assets() == 1
    assert store.get_asset(a.id).summary == "test"


# ============== 2. Vector Store (Stub) ==============


def test_vector_stub_upsert_and_search(temp_dirs):
    from backend.vector.stub_client import StubVectorStore
    from backend.vector import get_vector_store

    # 使用 tmp_path 隔离，避免污染真实 data/embeddings/
    vs = StubVectorStore(persist_dir=str(temp_dirs / "embeddings"))
    assert vs.count() == 0

    # Upsert
    vs.upsert("a1", "标准篮球扣篮动作，起跳充分出手点高", {"duration": 5.0, "quality_grade": "A"})
    vs.upsert("a2", "足球远射大力抽射", {"duration": 3.0, "quality_grade": "B"})
    vs.upsert("a3", "舞蹈旋转翻腾", {"duration": 8.0, "quality_grade": "A"})
    assert vs.count() == 3

    # Search
    hits = vs.search("扣篮跳跃", top_k=2)
    assert len(hits) > 0
    # cosine similarity in [-1, 1] range (cosine of L2-normalized vectors)
    assert all(-1 <= h.score <= 1 for h in hits)
    # 第一名应该相关性高
    assert hits[0].score > 0.1

    # Filter
    hits = vs.search("动作", top_k=10, filters={"quality_grade": ["A"]})
    assert all(h.payload.get("quality_grade") == "A" for h in hits)

    # Clear
    vs.clear()
    assert vs.count() == 0


# ============== 3. cap_consecutive_ones_by_iou ==============


def test_cap_consecutive_ones_by_iou():
    from backend.pipelines.fourd_pipeline import cap_consecutive_ones_by_iou

    # 0 → 1, 1s runs <= max_keep
    flag = [0, 1, 1, 0, 1, 1, 1, 0]
    iou = [0.0, 0.5, 0.7, 0.0, 0.3, 0.9, 0.6, 0.0]
    out = cap_consecutive_ones_by_iou(flag, iou, max_keep=2)
    # 位置 0/3/7 是 flag==0 → 1
    # [1,1] run of length 2, keep both
    # [1,1,1] run of length 3, keep top 2 IoU: 0.9 (idx 5), 0.6 (idx 6)
    assert out == [1, 1, 1, 1, 0, 1, 1, 1]


# ============== 4. Utils ==============


def test_utils_mask():
    from backend.utils import (
        bbox_from_mask,
        is_skinny_mask,
        is_super_long_or_wide,
        keep_largest_component,
        resize_mask_with_unique_label,
    )
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[20:80, 30:70] = 1
    out = keep_largest_component(mask)
    assert out.sum() == mask.sum()
    bb = bbox_from_mask(out)
    assert bb["w"] > 0 and bb["h"] > 0
    # skinny
    skinny = np.zeros((100, 100), dtype=np.uint8)
    skinny[40:60, 48:52] = 1
    assert is_skinny_mask(skinny)
    # super long: bbox 自身 h=1000/10=100, w=1/1000 ≈ 0, ar=100 > 4
    long_mask = np.zeros((10, 1000), dtype=np.uint8)
    long_mask[:, 0:1] = 1  # 仅第一列填满，bbox 高度 1000/10=100, w≈0
    assert is_super_long_or_wide(long_mask, obj_id=1, ratio=4.0)
    # resize
    resized = resize_mask_with_unique_label(mask, 200, 200, obj_id=5)
    assert resized.shape == (200, 200)
    assert resized.max() == 5


def test_utils_video(tmp_path):
    from backend.utils import read_video_metadata

    # 创建一个最简单的 mp4
    import cv2
    out_mp4 = tmp_path / "tiny.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(out_mp4), fourcc, 30.0, (320, 240))
    for _ in range(30):
        writer.write(np.zeros((240, 320, 3), dtype=np.uint8))
    writer.release()
    fps, total = read_video_metadata(str(out_mp4))
    assert fps > 0
    assert total > 0


# ============== 5. VLM Stub ==============


def test_vlm_template_describe():
    from backend.pipelines import VLMPipeline
    vlm = VLMPipeline()
    # Basketball + 扣篮
    out = vlm.describe(keywords="篮球, 扣篮")
    assert "summary" in out
    assert "detail" in out
    assert "rhythm" in out
    assert "use_case" in out
    assert "扣篮" in out["summary"] or "跳跃" in out["summary"]
    # No keywords
    out2 = vlm.describe(keywords="")
    assert all(k in out2 for k in ["summary", "detail", "rhythm", "use_case"])


# ============== 6. FastAPI 端到端 ==============


def test_api_endpoints(temp_dirs):
    """通过 TestClient 跑完整链路。"""
    from fastapi.testclient import TestClient
    from backend.main import create_app

    app = create_app()
    client = TestClient(app)

    # 1) health
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

    # 2) metrics
    r = client.get("/api/dashboard/metrics")
    assert r.status_code == 200
    m = r.json()
    assert "total_assets" in m

    # 3) GUID import
    r = client.post("/api/import/guid", json={"guids": ["g_001", "g_002"]})
    assert r.status_code == 200
    assert r.json()["total"] == 2

    # 4) Search (empty store)
    r = client.post("/api/search/text", json={"query": "test", "top_k": 5})
    assert r.status_code == 200
    assert r.json()["total"] == 0

    # 5) Tasks list
    r = client.get("/api/tasks")
    assert r.status_code == 200
    assert "tasks" in r.json()

    # 6) Reference for generation
    r = client.post("/api/search/reference", json={
        "generation_prompt": "扣篮动作",
        "duration_hint": 5.0,
        "top_k": 3,
    })
    assert r.status_code == 200
    assert "references" in r.json()
