"""file_path_to_url 单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def test_windows_backslash_path():
    from backend.utils import file_path_to_url
    # Windows: 实际存储的是反斜杠
    result = file_path_to_url("outputs\\uploads\\8776e33f.mp4")
    assert result == "/api/outputs/uploads/8776e33f.mp4", f"got {result!r}"


def test_posix_path():
    from backend.utils import file_path_to_url
    result = file_path_to_url("outputs/uploads/abc.mp4")
    assert result == "/api/outputs/uploads/abc.mp4"


def test_dot_prefix():
    from backend.utils import file_path_to_url
    result = file_path_to_url("./outputs/kept/foo.mp4")
    assert result == "/api/outputs/kept/foo.mp4"


def test_kept_subdir():
    from backend.utils import file_path_to_url
    result = file_path_to_url("outputs\\kept\\abc__trim001000-008000_xx.mp4")
    assert result == "/api/outputs/kept/abc__trim001000-008000_xx.mp4"


def test_empty_path():
    from backend.utils import file_path_to_url
    assert file_path_to_url("") == ""
    assert file_path_to_url(None) == ""


def test_chinese_filename():
    from backend.utils import file_path_to_url
    # 中文文件名应被 URL 编码
    result = file_path_to_url("outputs\\uploads\\扬州.mp4")
    assert result.startswith("/api/outputs/uploads/")
    assert "扬州" not in result  # 已编码
    assert "%E6%89%AC" in result  # 扬的 URL 编码


def test_no_outputs_prefix():
    from backend.utils import file_path_to_url
    # 如果路径不含 outputs/ 前缀，原样使用
    result = file_path_to_url("some/other/path.mp4")
    assert result == "/api/outputs/some/other/path.mp4"


def test_custom_base():
    from backend.utils import file_path_to_url
    result = file_path_to_url("outputs\\uploads\\x.mp4", base="/static")
    assert result == "/static/uploads/x.mp4"
