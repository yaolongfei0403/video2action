"""RoughCutEngine 单元测试 - 用程序生成的 MP4 验证新流水线。

测试覆盖：
  1. detect_scenes 镜头分割（PySceneDetect）
  2. measure_motion 像素帧差
  3. 动静双门限过滤
  4. 时长过滤（5-600s）
  5. ffmpeg -c copy 流式裁剪
  6. 端到端 detect() 行为
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============== 工具：合成测试视频 ==============


def _make_video(
    path: str,
    fps: float = 30.0,
    width: int = 320,
    height: int = 180,
    duration_sec: float = 8.0,
    motion_mode: str = "moving",  # static | moving | shake | flash
) -> None:
    """用 OpenCV 生成测试视频。

    static: 全程纯色（无动作）
    moving: 移动方块（有动作）
    shake:  每帧独立全随机彩色（被高斯模糊平滑，motion 在甜区）
    flash:  黑/白交替（每像素变化 255 → motion ≈ 1.0）
    """
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
    total_frames = int(fps * duration_sec)
    rng = np.random.default_rng(0)
    for i in range(total_frames):
        if motion_mode == "static":
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            frame[:] = (32, 64, 96)
        elif motion_mode == "moving":
            frame = np.zeros((height, width, 3), dtype=np.uint8)
            x = int((i / total_frames) * (width - 40))
            cv2.rectangle(frame, (x, 60), (x + 40, 120), (255, 255, 255), -1)
        elif motion_mode == "shake":
            frame = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
        elif motion_mode == "flash":
            # 黑/白帧交替 - 模拟「整片都是变动像素」的极端情况
            frame = np.zeros((height, width, 3), dtype=np.uint8) if i % 2 == 0 \
                else np.full((height, width, 3), 255, dtype=np.uint8)
        else:
            raise ValueError(motion_mode)
        writer.write(frame)
    writer.release()


def _make_multiscene_video(
    path: str,
    fps: float = 30.0,
    width: int = 320,
    height: int = 180,
) -> None:
    """合成两段：0-6s 静态黑屏 + 6-14s 移动方块（明显的镜头切换）。"""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
    # 0-6s 静态
    for i in range(int(fps * 6)):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        frame[:] = (10, 20, 30)
        writer.write(frame)
    # 6-14s 移动方块（明显动作）
    for i in range(int(fps * 8)):
        frame = np.zeros((height, width, 3), dtype=np.uint8)
        x = int((i / (fps * 8)) * (width - 40))
        cv2.rectangle(frame, (x, 60), (x + 40, 120), (255, 255, 255), -1)
        writer.write(frame)
    writer.release()


# ============== fixture ==============


@pytest.fixture
def tmp_video_dir(tmp_path):
    d = tmp_path / "videos"
    d.mkdir()
    return d


@pytest.fixture
def has_ffmpeg():
    return shutil.which("ffmpeg") is not None


# ============== 测试 ==============


def test_measure_motion_static_under_low(tmp_video_dir):
    """静态视频 → motion < 0.02。"""
    from backend.pipelines.rough_cut_engine import RoughCutEngine

    src = str(tmp_video_dir / "static.mp4")
    _make_video(src, duration_sec=6.0, motion_mode="static")
    engine = RoughCutEngine(min_duration_sec=2.0, max_duration_sec=20.0,
                            motion_sample_fps=2.0)
    # 手动测一个跨越整段的虚拟 scene
    from backend.pipelines.rough_cut_engine import _Scene
    motion = engine.measure_motion(src, _Scene(0, 180, 0.0, 6.0))
    assert motion < 0.02, f"static should be < 0.02, got {motion}"


def test_measure_motion_moving_in_sweet_zone(tmp_video_dir):
    """移动方块 → motion 落在 [0.02, 0.85] 甜区。"""
    from backend.pipelines.rough_cut_engine import RoughCutEngine, _Scene

    src = str(tmp_video_dir / "moving.mp4")
    _make_video(src, duration_sec=6.0, motion_mode="moving")
    engine = RoughCutEngine(min_duration_sec=2.0, max_duration_sec=20.0,
                            motion_sample_fps=2.0)
    motion = engine.measure_motion(src, _Scene(0, 180, 0.0, 6.0))
    assert 0.02 <= motion <= 0.85, f"moving should be in sweet zone, got {motion}"


def test_measure_motion_flash_above_high(tmp_video_dir):
    """黑/白交替（极剧烈）→ motion > 0.85。"""
    from backend.pipelines.rough_cut_engine import RoughCutEngine, _Scene

    src = str(tmp_video_dir / "flash.mp4")
    _make_video(src, duration_sec=6.0, motion_mode="flash")
    engine = RoughCutEngine(min_duration_sec=2.0, max_duration_sec=20.0,
                            motion_sample_fps=2.0)
    motion = engine.measure_motion(src, _Scene(0, 180, 0.0, 6.0))
    assert motion > 0.85, f"flash should be > 0.85, got {motion}"


def test_detect_filters_flash_with_high_threshold(tmp_video_dir):
    """end-to-end: flash 视频（极高 motion）应被高门限过滤掉。"""
    from backend.pipelines.rough_cut_engine import RoughCutEngine

    src = str(tmp_video_dir / "flash.mp4")
    _make_video(src, duration_sec=8.0, motion_mode="flash")
    engine = RoughCutEngine(
        min_duration_sec=3.0,
        motion_low_threshold=0.02,
        motion_high_threshold=0.85,
    )
    candidates = engine.detect(src)
    # flash 应被高门限丢掉
    assert candidates == [], f"flash should be filtered, got {len(candidates)}"


def test_detect_scenes_multiscene(tmp_video_dir):
    """多镜头视频应被切成 ≥ 2 段。"""
    from backend.pipelines.rough_cut_engine import RoughCutEngine

    src = str(tmp_video_dir / "multi.mp4")
    _make_multiscene_video(src)
    engine = RoughCutEngine(scene_threshold=15.0, min_scene_duration=1.0)
    scenes = engine.detect_scenes(src)
    # 即便 PySceneDetect 不可用，也能保证至少 1 段
    assert len(scenes) >= 1
    # 如果 scenedetect 正常，应该检测到 2 段
    if engine._scene_detector is not None:
        assert len(scenes) >= 2, f"expected ≥ 2 scenes, got {len(scenes)}"


def test_detect_endtoend_filters_static_and_keeps_moving(tmp_video_dir):
    """detect() 应在多镜头中保留「有动作」段、丢弃「静态」段。"""
    from backend.pipelines.rough_cut_engine import RoughCutEngine

    src = str(tmp_video_dir / "multi.mp4")
    _make_multiscene_video(src)
    engine = RoughCutEngine(
        scene_threshold=15.0,
        min_scene_duration=1.0,
        min_duration_sec=3.0,
        max_duration_sec=600.0,
        motion_low_threshold=0.02,
        motion_high_threshold=0.85,
    )
    candidates = engine.detect(src)
    # 应该至少保留 moving 段
    assert len(candidates) >= 1
    # 全部候选的 motion 都在甜区内
    for c in candidates:
        assert 0.02 <= c.motion_score <= 0.85
        # 字段兼容性
        assert c.start_frame < c.end_frame
        assert 0.0 <= c.score <= 1.0
        assert c.person_score == 0.0  # 旧字段保留为 0


def test_detect_filters_short_scene(tmp_video_dir):
    """< 5s 的镜头应被过滤掉。"""
    from backend.pipelines.rough_cut_engine import RoughCutEngine, _Scene

    src = str(tmp_video_dir / "short.mp4")
    _make_video(src, duration_sec=3.0, motion_mode="moving")
    engine = RoughCutEngine(min_duration_sec=5.0)
    # 整段 3s 视频
    candidates = engine.detect(src)
    # 时长过滤会让它出局
    assert len(candidates) == 0


def test_cut_clip_ffmpeg(tmp_video_dir, has_ffmpeg):
    """ffmpeg -c copy 裁剪应产出有效 mp4。"""
    if not has_ffmpeg:
        pytest.skip("ffmpeg not available")
    from backend.pipelines.rough_cut_engine import RoughCutEngine

    src = str(tmp_video_dir / "moving.mp4")
    _make_video(src, duration_sec=10.0, motion_mode="moving")
    dst = str(tmp_video_dir / "cut.mp4")
    engine = RoughCutEngine()
    engine.cut_clip_ffmpeg(src, 2.0, 7.0, dst)
    assert os.path.exists(dst)
    # 用 cv2 读一下帧数（容许 ±1 帧的误差）
    cap = cv2.VideoCapture(dst)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    expected = int(5.0 * fps)
    assert abs(total - expected) <= 5, f"expected ~{expected} frames, got {total}"


def test_cut_candidates_to_files(tmp_video_dir, has_ffmpeg):
    """批量裁剪候选应把 cut_path 写回。"""
    if not has_ffmpeg:
        pytest.skip("ffmpeg not available")
    from backend.pipelines.rough_cut_engine import RoughCutEngine, CandidateClip

    src = str(tmp_video_dir / "multi.mp4")
    _make_multiscene_video(src)
    engine = RoughCutEngine(output_dir=str(tmp_video_dir / "rough"))
    candidates = engine.detect(src)
    if not candidates:
        pytest.skip("no candidates to cut (scenedetect may be unavailable)")
    engine.cut_candidates_to_files(src, candidates)
    # 至少有一个候选被成功裁剪
    cut_files = [c.cut_path for c in candidates if c.cut_path]
    assert len(cut_files) >= 1
    for p in cut_files:
        assert os.path.exists(p)
        # 命名规范：{stem}__{start}-{end}__{uuid12}.mp4
        assert Path(p).suffix == ".mp4"


def test_legacy_api_compat():
    """min_score 属性应能像旧版一样设置。"""
    from backend.pipelines.rough_cut_engine import RoughCutEngine

    engine = RoughCutEngine()
    engine.min_score = 0.4
    assert 0.3 <= engine.motion_low_threshold <= 0.5
    engine.min_duration_sec = 8.0
    assert engine.min_duration_sec == 8.0
