"""FineCutEngine 单元测试。

覆盖：
  1. ffprobe_duration 真实时长
  2. keep_clip 相对 → 绝对时间换算
  3. 0.05s 容忍 → skipped=True
  4. 边界校验（负数 / 反向 / 超出源片 / < MIN_DURATION）
  5. 源片优先 / fallback
  6. kept/ 目录命名规范
  7. 旧版 trim() 向后兼容
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ============== 工具：合成测试视频 ==============


def _make_video(path: str, duration_sec: float = 20.0, fps: float = 25.0,
                width: int = 320, height: int = 180) -> None:
    """生成一段纯色视频（带时间码便于排查）。"""
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (width, height))
    total = int(fps * duration_sec)
    for i in range(total):
        # 整段渐变色，便于人眼看出 cut 区间
        v = int(255 * i / total)
        frame = np.full((height, width, 3), v, dtype=np.uint8)
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


# ============== 工具测试 ==============


def test_ffprobe_duration_matches_cv2(tmp_video_dir, has_ffmpeg):
    """ffprobe 拿到的时长与 cv2 一致。"""
    if not has_ffmpeg:
        pytest.skip("ffmpeg not available")
    from backend.pipelines.fine_cut_engine import FineCutEngine

    src = str(tmp_video_dir / "src.mp4")
    _make_video(src, duration_sec=10.0, fps=25.0)
    d = FineCutEngine.ffprobe_duration(src)
    assert 9.5 <= d <= 10.5, f"expected ~10s, got {d}"


def test_ffprobe_missing_file_returns_zero(tmp_video_dir):
    from backend.pipelines.fine_cut_engine import FineCutEngine

    assert FineCutEngine.ffprobe_duration(str(tmp_video_dir / "missing.mp4")) == 0.0


# ============== keep_clip 测试 ==============


def test_keep_clip_relative_to_absolute(tmp_video_dir, has_ffmpeg):
    """相对偏移 → 源片绝对时间。"""
    if not has_ffmpeg:
        pytest.skip("ffmpeg not available")
    from backend.pipelines.fine_cut_engine import FineCutEngine

    src = str(tmp_video_dir / "src.mp4")
    _make_video(src, duration_sec=20.0, fps=25.0)
    engine = FineCutEngine(output_dir=str(tmp_video_dir / "out"))
    result = engine.keep_clip(
        source_video=src,
        source_duration=20.0,
        candidate_start=2.0,     # 候选在 [2, 15]
        candidate_end=15.0,
        relative_start=1.5,      # 精切 → 相对偏移 [1.5, 8.0]
        relative_end=8.0,
        clip_id="abc123def456",
    )
    assert result["trimmed"] is True
    assert result["skipped"] is False
    assert abs(result["start_time"] - 3.5) < 1e-3     # 2 + 1.5
    assert abs(result["end_time"] - 10.0) < 1e-3     # 2 + 8
    assert abs(result["duration"] - 6.5) < 1e-3
    assert result["output_path"].endswith(".mp4")
    # 命名规范：{stem}__trim{start_ms}-{end_ms}_{clip_id8}.mp4
    name = Path(result["output_path"]).name
    assert name.startswith("src__trim001500-008000_abc123de.mp4")
    assert os.path.exists(result["output_path"])


def test_keep_clip_within_tolerance_skips(tmp_video_dir, has_ffmpeg):
    """0.05s 容忍：用户没怎么动 → skipped=True，ffmpeg 不被调用。"""
    if not has_ffmpeg:
        pytest.skip("ffmpeg not available")
    from backend.pipelines.fine_cut_engine import FineCutEngine

    src = str(tmp_video_dir / "src.mp4")
    _make_video(src, duration_sec=20.0, fps=25.0)
    engine = FineCutEngine(output_dir=str(tmp_video_dir / "out"))
    result = engine.keep_clip(
        source_video=src,
        source_duration=20.0,
        candidate_start=5.0,
        candidate_end=12.0,
        relative_start=0.02,    # 0 < 0.05 → 在容忍内
        relative_end=6.98,      # candidate_duration - 0.02 → 在容忍内
        clip_id="tolerance",
    )
    assert result["skipped"] is True
    assert result["trimmed"] is False
    # 跳过时不该落新文件
    assert not os.path.exists(result["output_path"])
    # 但返回的 start_time/end_time 仍按用户输入
    assert abs(result["start_time"] - 5.02) < 1e-3
    assert abs(result["end_time"] - 11.98) < 1e-3


def test_keep_clip_at_candidate_boundary(tmp_video_dir, has_ffmpeg):
    """relative_end == candidate_duration 是允许的（在容忍内）。"""
    if not has_ffmpeg:
        pytest.skip("ffmpeg not available")
    from backend.pipelines.fine_cut_engine import FineCutEngine

    src = str(tmp_video_dir / "src.mp4")
    _make_video(src, duration_sec=20.0, fps=25.0)
    engine = FineCutEngine(output_dir=str(tmp_video_dir / "out"))
    result = engine.keep_clip(
        source_video=src, source_duration=20.0,
        candidate_start=5.0, candidate_end=12.0,
        relative_start=0.0, relative_end=7.0,  # candidate_duration
        clip_id="boundary",
    )
    assert result["skipped"] is True


def test_keep_clip_rejects_negative(tmp_video_dir):
    from backend.pipelines.fine_cut_engine import FineCutEngine

    engine = FineCutEngine(output_dir=str(tmp_video_dir / "out"))
    with pytest.raises(ValueError, match="非法 trim 范围"):
        engine.keep_clip(
            source_video="missing.mp4",
            source_duration=20.0,
            candidate_start=5.0, candidate_end=12.0,
            relative_start=-0.1, relative_end=5.0,
        )


def test_keep_clip_rejects_reversed(tmp_video_dir):
    from backend.pipelines.fine_cut_engine import FineCutEngine

    engine = FineCutEngine(output_dir=str(tmp_video_dir / "out"))
    with pytest.raises(ValueError, match="非法 trim 范围"):
        engine.keep_clip(
            source_video="missing.mp4",
            source_duration=20.0,
            candidate_start=5.0, candidate_end=12.0,
            relative_start=5.0, relative_end=3.0,
        )


def test_keep_clip_rejects_beyond_source(tmp_video_dir):
    """精切终点超出源片 → 400。"""
    from backend.pipelines.fine_cut_engine import FineCutEngine

    engine = FineCutEngine(output_dir=str(tmp_video_dir / "out"))
    # candidate 5-20 长度 15，相对偏移 0-15 → 绝对 [5, 20] 超过 source_duration=15
    with pytest.raises(ValueError, match="超出源片"):
        engine.keep_clip(
            source_video="x.mp4",
            source_duration=15.0,
            candidate_start=5.0, candidate_end=20.0,
            relative_start=0.0, relative_end=15.0,  # 5+15=20 > 15
        )


def test_keep_clip_rejects_too_short(tmp_video_dir):
    """裁剪后 < MIN_DURATION (5s) → 拒绝。"""
    from backend.pipelines.fine_cut_engine import FineCutEngine

    engine = FineCutEngine(output_dir=str(tmp_video_dir / "out"))
    with pytest.raises(ValueError, match="最小"):
        engine.keep_clip(
            source_video="x.mp4",
            source_duration=20.0,
            candidate_start=5.0, candidate_end=12.0,
            relative_start=0.0, relative_end=1.0,  # 1s < 5s
        )


def test_keep_clip_source_missing_uses_fallback(tmp_video_dir, has_ffmpeg):
    """源片不可用时回退到 fallback_path。"""
    if not has_ffmpeg:
        pytest.skip("ffmpeg not available")
    from backend.pipelines.fine_cut_engine import FineCutEngine

    fallback = str(tmp_video_dir / "fallback.mp4")
    _make_video(fallback, duration_sec=20.0, fps=25.0)
    engine = FineCutEngine(output_dir=str(tmp_video_dir / "out"))
    result = engine.keep_clip(
        source_video=str(tmp_video_dir / "missing.mp4"),
        source_duration=20.0,
        candidate_start=5.0, candidate_end=12.0,
        relative_start=0.0, relative_end=5.0,
        clip_id="fb",
        fallback_path=fallback,
    )
    assert result["trimmed"] is True
    assert "fallback" in result["ffmpeg_src"]
    assert os.path.exists(result["output_path"])


def test_keep_clip_source_and_fallback_missing(tmp_video_dir):
    """源片和兜底都不可用 → FileNotFoundError。"""
    from backend.pipelines.fine_cut_engine import FineCutEngine

    engine = FineCutEngine(output_dir=str(tmp_video_dir / "out"))
    with pytest.raises(FileNotFoundError, match="源片不可用"):
        engine.keep_clip(
            source_video=str(tmp_video_dir / "nope1.mp4"),
            source_duration=20.0,
            candidate_start=5.0, candidate_end=12.0,
            relative_start=0.0, relative_end=5.0,
        )


def test_keep_clip_writes_to_kept_dir(tmp_video_dir, has_ffmpeg):
    """产物必须落在 <output_dir>/kept/。"""
    if not has_ffmpeg:
        pytest.skip("ffmpeg not available")
    from backend.pipelines.fine_cut_engine import FineCutEngine

    src = str(tmp_video_dir / "src.mp4")
    _make_video(src, duration_sec=20.0, fps=25.0)
    out = tmp_video_dir / "out"
    engine = FineCutEngine(output_dir=str(out))
    result = engine.keep_clip(
        source_video=src, source_duration=20.0,
        candidate_start=5.0, candidate_end=12.0,
        relative_start=0.0, relative_end=5.0, clip_id="k1",
    )
    assert Path(result["output_path"]).parent == out / "kept"
    # kept/ 目录在 __init__ 时已建好
    assert (out / "kept").exists()


# ============== 旧版 trim() 向后兼容 ==============


def test_legacy_trim_still_works(tmp_video_dir, has_ffmpeg):
    """旧版 /api/fine-cut/trim 用的 trim() 仍能跑。"""
    if not has_ffmpeg:
        pytest.skip("ffmpeg not available")
    from backend.pipelines.fine_cut_engine import FineCutEngine

    src = str(tmp_video_dir / "src.mp4")
    _make_video(src, duration_sec=20.0, fps=25.0)
    engine = FineCutEngine(output_dir=str(tmp_video_dir / "out"))
    result = engine.trim(src, 5.0, 10.0)
    assert os.path.exists(result["path"])
    assert result["duration"] == 5.0
