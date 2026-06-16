r"""URL/path 工具。

后端用 Path 拼接时，Windows 下会得到 ``outputs\uploads\xxx.mp4`` 这种带反斜杠的路径。
直接把这种路径拼到 URL 里会 404（HTTP URL 必须用正斜杠，且不能有反斜杠）。
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote


def file_path_to_url(file_path: str | None, *, base: str = "/api/outputs") -> str:
    """把磁盘路径转成可通过 /api/outputs/... 访问的 URL。

    处理：
      - 反斜杠 → 正斜杠
      - 去掉 `./` 前缀
      - 去掉 `outputs/` 前缀（输出目录已挂载到 /api/outputs/）
      - 保留子目录结构（如 `uploads/xxx.mp4` → `/api/outputs/uploads/xxx.mp4`）
      - URL 编码空格、中文等

    Examples
    --------
    >>> file_path_to_url("outputs\\\\uploads\\\\8776e33f.mp4")
    '/api/outputs/uploads/8776e33f.mp4'
    >>> file_path_to_url("./outputs/kept/foo.mp4")
    '/api/outputs/kept/foo.mp4'
    >>> file_path_to_url("")
    ''
    """
    if not file_path:
        return ""

    # 1. 归一化反斜杠
    rel = file_path.replace("\\", "/")

    # 2. 去 ./ 前缀
    if rel.startswith("./"):
        rel = rel[2:]

    # 3. 去 outputs/ 前缀（/api/outputs/ 已挂载 outputs/）
    if rel.startswith("outputs/"):
        rel = rel[len("outputs/"):]

    if not rel:
        return ""

    # 4. URL 编码（保留 / 不编码；编码空格、中文等）
    parts = [quote(p, safe="") for p in rel.split("/") if p]
    if not parts:
        return ""
    return f"{base}/" + "/".join(parts)


__all__ = ["file_path_to_url"]
