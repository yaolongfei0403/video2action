"""GPU profiling decorator (rebuilt from app.py usage)."""
from __future__ import annotations

import functools
import logging
import time
from typing import Any, Callable

import torch

logger = logging.getLogger(__name__)


def gpu_profile(fn: Callable) -> Callable:
    """对函数计时并记录 GPU 显存（如果可用）。

    用法：
        @gpu_profile
        def heavy(...): ...
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs) -> Any:
        if torch.cuda.is_available():
            torch.cuda.synchronize()
            mem_before = torch.cuda.memory_allocated() / 1024 ** 2
        else:
            mem_before = 0.0
        t0 = time.time()
        try:
            return fn(*args, **kwargs)
        finally:
            elapsed = time.time() - t0
            if torch.cuda.is_available():
                torch.cuda.synchronize()
                mem_after = torch.cuda.memory_allocated() / 1024 ** 2
                peak = torch.cuda.max_memory_allocated() / 1024 ** 2
                logger.info(
                    f"[GPU] {fn.__name__} took {elapsed:.2f}s | "
                    f"mem {mem_before:.1f}->{mem_after:.1f} MB | "
                    f"peak {peak:.1f} MB"
                )
            else:
                logger.info(f"[CPU] {fn.__name__} took {elapsed:.2f}s")

    return wrapper
