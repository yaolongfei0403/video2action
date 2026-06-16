"""VLMPipeline - 视频/图像 → 结构化动作描述

真实模式：Qwen2.5-VL-7B-Instruct
降级模式：基于关键词 + 启发式规则生成结构化 JSON
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from ..config import get_config
from ..store.models import ActionClip

logger = logging.getLogger(__name__)


class VLMPipeline:
    """VLM 描述生成 Pipeline。

    真实模式调用 Qwen-VL；降级模式使用关键词模板。
    """

    def __init__(self) -> None:
        self.cfg = get_config().vlm
        self._model = None
        self._processor = None
        self._templates: dict[str, Any] = {}
        self.mode = "stub"
        self._try_load_qwen_vl()
        self._load_templates()

    def _try_load_qwen_vl(self) -> None:
        try:
            import os
            if self.cfg.model_path and not os.path.exists(self.cfg.model_path):
                raise FileNotFoundError(f"Qwen-VL path missing: {self.cfg.model_path}")
            from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor

            logger.info(f"Loading Qwen-VL from {self.cfg.model_path}")
            self._processor = AutoProcessor.from_pretrained(self.cfg.model_path)
            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                self.cfg.model_path, device_map=self.cfg.device
            )
            self.mode = "real"
            logger.info("Qwen-VL loaded (real mode)")
        except Exception as e:
            logger.warning(f"Qwen-VL unavailable: {e}; using template fallback")
            self.mode = "stub"

    def _load_templates(self) -> None:
        try:
            with open(self.cfg.template_path, "r", encoding="utf-8") as f:
                self._templates = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load VLM templates: {e}")
            self._templates = {"fallback_templates": {}}

    # ============== 核心 API ==============

    def describe(
        self,
        video_path: str = "",
        keywords: str = "",
        frames: Optional[list[Any]] = None,
    ) -> dict[str, str]:
        """生成结构化描述。

        Args:
            video_path: 视频文件路径（stub 模式忽略）
            keywords: 用户提供的核心关键词
            frames: 抽帧图像列表（stub 模式忽略）

        Returns:
            {"summary": ..., "detail": ..., "rhythm": ..., "use_case": ...}
        """
        if self.mode == "real":
            try:
                return self._qwen_vl_describe(video_path, keywords, frames)
            except Exception as e:
                logger.warning(f"Qwen-VL inference failed ({e}); using template fallback")
        return self._template_describe(keywords)

    def describe_for_clip(
        self,
        clip_id: str,
        video_url: str = "",
        keywords: str = "",
    ) -> dict[str, str]:
        """便捷封装：返回结构化字段。"""
        result = self.describe(video_path=video_url, keywords=keywords)
        return result

    # ============== Stub 模板生成 ==============

    def _template_describe(self, keywords: str) -> dict[str, str]:
        """基于关键词模板生成描述。

        模板结构（configs/vlm_prompts.json）：
            fallback_templates[category] = {summary, detail, rhythm, use_case}
        """
        keywords = (keywords or "").strip()
        kws = [k.strip() for k in re.split(r"[,，、\s]+", keywords) if k.strip()]
        templates = self._templates.get("fallback_templates", {})
        default = templates.get("default", {})

        # 找到第一个匹配的类别
        chosen = default
        chosen_key = "default"
        for cat in templates:
            if cat == "default":
                continue
            if cat in kws or any(cat in k for k in kws):
                chosen = templates[cat]
                chosen_key = cat
                break

        # 提取动作名词（扣篮、投篮、转身等）
        action = next((k for k in kws if k not in ("篮球", "足球", "舞蹈", "拳击", "滑板")), "标准")

        def fill(tpl: str) -> str:
            return tpl.format(action=action, style=chosen_key)

        return {
            "summary": fill(chosen.get("summary", "{action}动作")),
            "detail": fill(chosen.get("detail", "动作完整，姿态标准。")),
            "rhythm": fill(chosen.get("rhythm", "节奏平稳。")),
            "use_case": fill(chosen.get("use_case", "通用动作参考。")),
        }

    # ============== Qwen-VL 真实推理 ==============

    def _qwen_vl_describe(
        self,
        video_path: str,
        keywords: str,
        frames: Optional[list[Any]],
    ) -> dict[str, str]:
        """调用 Qwen2.5-VL 生成结构化 JSON。"""
        import torch

        tpl = self._templates.get(
            "description_template",
            "请结合视频描述动作（关键词：{keywords}），输出 JSON 字段 summary/detail/rhythm/use_case。",
        )
        prompt = tpl.format(keywords=keywords or "无")

        # 构造 messages
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "video" if video_path else "text", "video": video_path} if video_path else {"type": "text"},
                    {"type": "text", "text": prompt},
                ],
            }
        ]
        text = self._processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self._processor(text=[text], return_tensors="pt").to(self.cfg.device)
        with torch.no_grad():
            generated_ids = self._model.generate(**inputs, max_new_tokens=512)
        output = self._processor.batch_decode(generated_ids[:, inputs.input_ids.shape[1]:], skip_special_tokens=True)[0]

        # 解析 JSON
        return self._parse_json_output(output)

    def _parse_json_output(self, text: str) -> dict[str, str]:
        """从模型输出中提取 JSON 字段。"""
        # 尝试直接解析
        try:
            data = json.loads(text)
            return {
                "summary": str(data.get("summary", "")),
                "detail": str(data.get("detail", "")),
                "rhythm": str(data.get("rhythm", "")),
                "use_case": str(data.get("use_case", "")),
            }
        except Exception:
            pass
        # 尝试从 ```json ... ``` 中提取
        m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                return {
                    "summary": str(data.get("summary", "")),
                    "detail": str(data.get("detail", "")),
                    "rhythm": str(data.get("rhythm", "")),
                    "use_case": str(data.get("use_case", "")),
                }
            except Exception:
                pass
        # 失败：降级
        logger.warning("Failed to parse VLM output as JSON")
        return {
            "summary": text[:200],
            "detail": "",
            "rhythm": "",
            "use_case": "",
        }
