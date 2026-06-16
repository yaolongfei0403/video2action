"""端到端 API 集成测试 - 跑通完整业务链路.

需要先安装 pytest 与 httpx:
    pip install pytest httpx

运行：
    cd /Users/yaolf/video2action
    PYTHONPATH=. pytest tests/test_api.py -v
"""
from __future__ import annotations

import io
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def reset_state(monkeypatch, tmp_path):
    """每个测试隔离 store + vector。"""
    monkeypatch.setenv("VECTOR_BACKEND", "stub")
    import importlib
    from backend import config, store, vector
    importlib.reload(config)
    store._store = None
    vector._vector_store = None
    yield tmp_path


def _create_test_video(path: Path, n_frames: int = 60, fps: float = 30.0, w: int = 320, h: int = 240) -> None:
    """生成一个简单的 mp4 测试视频（黑底白块模拟人体）。"""
    import cv2
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, fps, (w, h))
    for i in range(n_frames):
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        # 画一个移动的白色方块（模拟人体）
        x = int((i / n_frames) * (w - 60)) + 30
        cv2.rectangle(frame, (x, 80), (x + 40, 180), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()


def test_full_pipeline_e2e(reset_state):
    """端到端：上传 → 粗切 → 精切 → 标注 → 4D → 标签 → 检索。"""
    from fastapi.testclient import TestClient
    from backend.main import create_app

    tmp = reset_state
    test_video = tmp / "test.mp4"
    _create_test_video(test_video, n_frames=60)

    app = create_app()
    client = TestClient(app)
    # 清空向量库（避免之前测试的残留）
    from backend.vector import get_vector_store
    get_vector_store().clear()

    # 1. 上传
    with open(test_video, "rb") as f:
        r = client.post(
            "/api/import/local",
            files={"file": ("test.mp4", f, "video/mp4")},
        )
    assert r.status_code == 200, r.text
    video = r.json()["video"]
    video_id = video["id"]
    assert video["total_frames"] == 60
    assert video["fps"] > 0

    # 2. 粗切
    r = client.post("/api/rough-cut/run", json={
        "video_id": video_id,
        "min_duration_sec": 1.0,  # 短视频用小阈值
        "min_score": 0.0,
    })
    assert r.status_code == 200, r.text
    rc = r.json()
    print(f"Rough-cut found {rc['total']} candidates")

    # 3. 精切 (用视频中部 1s)
    r = client.post("/api/fine-cut/trim", json={
        "video_id": video_id,
        "start_sec": 0.5,
        "end_sec": 1.5,
    })
    assert r.status_code == 200, r.text
    clip = r.json()["clip"]
    clip_id = clip["id"]

    # 4. 标注 (新流程: 忠实复现 app.py on_click + add_target)
    # 4a. clickTarget: 实时 mask 预览 (不持久化, 不改 status)
    r = client.post("/api/target/click", json={
        "clip_id": clip_id,
        "obj_id": 1,
        "frame_idx": 0,
        "x": 160, "y": 120,
        "point_type": "positive",
        "frame_width": 320, "frame_height": 240,
        "points": [{"x": 160, "y": 120, "point_type": "positive"}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["point_count"] == 1

    # 4b. clickTarget 第 2 次: 累积多点击 (新式 points 字段)
    r = client.post("/api/target/click", json={
        "clip_id": clip_id,
        "obj_id": 1,
        "frame_idx": 5,
        "x": 200, "y": 130,
        "point_type": "negative",
        "frame_width": 320, "frame_height": 240,
        "points": [{"x": 200, "y": 130, "point_type": "negative"}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["point_count"] == 1

    # 4c. annotateClip: 持久化全量标注 (前端是 source of truth)
    r = client.post(f"/api/clips/{clip_id}/annotate", json={
        "annotations": [
            {"obj_id": 1, "frame_idx": 0, "x": 160, "y": 120, "point_type": "positive"},
            {"obj_id": 1, "frame_idx": 5, "x": 200, "y": 130, "point_type": "negative"},
        ]
    })
    assert r.status_code == 200, r.text
    assert r.json()["annotation_count"] == 2
    # 注: 状态不变 (仍是 FINE_CUT), 因为还没有 add_target
    assert r.json()["status"] == "fine_cut"

    # 4d. add_target: 提交事务边界, 推进 status FINE_CUT → ANNOTATED
    r = client.post("/api/target/add", json={"clip_id": clip_id})
    assert r.status_code == 200, r.text
    assert r.json()["clip_status"] == "annotated"
    assert r.json()["obj_id"] == 2  # 下一个 obj_id (1 已被占用)

    # 5. 4D 重建
    r = client.post("/api/4d/reconstruct", json={"clip_id": clip_id})
    assert r.status_code == 200, r.text
    fourd = r.json()
    print(f"4D: {fourd['total_frames']} frames, mode={fourd['mode']}")
    assert fourd["output_video_url"]
    task_id = fourd["task_id"]

    # 6. VLM 标签
    r = client.post("/api/tagging/vlm", json={
        "clip_id": clip_id,
        "keywords": "篮球, 扣篮, 跳跃",
    })
    assert r.status_code == 200, r.text
    desc = r.json()["description"]
    assert desc["summary"]

    # 7. 入库
    r = client.post(f"/api/tagging/index?clip_id={clip_id}")
    assert r.status_code == 200, r.text
    assert r.json()["vector_count"] == 1

    # 8. 检索
    r = client.post("/api/search/text", json={"query": "扣篮", "top_k": 5})
    assert r.status_code == 200
    hits = r.json()["results"]
    assert len(hits) >= 1
    assert "扣篮" in hits[0]["payload"]["summary"] or "扣篮" in hits[0]["payload"].get("keywords", "")

    # 9. 完成页
    r = client.get(f"/api/completed/{task_id}")
    assert r.status_code == 200
    assert r.json()["rendered_videos"] >= 1

    print("\n✓ E2E 流程通过：上传 → 粗切 → 精切 → 标注 → 4D → 标签 → 入库 → 检索 → 完成")
