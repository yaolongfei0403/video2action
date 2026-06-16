"""SAM-3D-Body Pipeline (含 stub 降级).

真实模式：调用 SAM-3D-Body 模型 (mhr + fov) 进行 3D 人体估计
降级模式：返回占位 SMPL mesh + 简单骨骼点
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

import numpy as np

logger = logging.getLogger(__name__)


class SAM3DBodyPipeline:
    """3D 人体估计 Pipeline.

    输出：每个目标在每帧的 mesh + 关键点。
    """

    # 标准 24-关节 SMPL 骨骼结构
    SMPL_JOINTS = [
        "pelvis", "left_hip", "right_hip", "spine1", "left_knee", "right_knee",
        "spine2", "left_ankle", "right_ankle", "spine3", "left_foot", "right_foot",
        "neck", "left_collar", "right_collar", "head", "left_shoulder", "right_shoulder",
        "left_elbow", "right_elbow", "left_wrist", "right_wrist", "left_hand", "right_hand",
    ]

    def __init__(self) -> None:
        self._model = None
        self._model_cfg = None
        self._fov_estimator = None
        self._faces: Optional[np.ndarray] = None
        self.mode = "stub"
        self._try_load()

    def _try_load(self) -> None:
        try:
            from ..config import get_config

            cfg = get_config().sam_3d_body
            if not all(os.path.exists(p) for p in [cfg.ckpt_path, cfg.mhr_path, cfg.fov_path]):
                raise FileNotFoundError("SAM-3D-Body checkpoints missing")
            from models.sam_3d_body.sam_3d_body import load_sam_3d_body  # type: ignore
            from models.sam_3d_body.sam_3d_body import SAM3DBodyEstimator  # type: ignore

            import torch
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self._model, self._model_cfg = load_sam_3d_body(cfg.ckpt_path, device=device, mhr_path=cfg.mhr_path)
            self._fov_estimator = self._build_fov(device, cfg.fov_path)
            self._estimator = SAM3DBodyEstimator(
                sam_3d_body_model=self._model,
                model_cfg=self._model_cfg,
                human_detector=None,
                human_segmentor=None,
                fov_estimator=self._fov_estimator,
            )
            self._faces = np.array(self._model_cfg.smpl.faces) if hasattr(self._model_cfg, "smpl") else None
            self.mode = "real"
            logger.info("SAM-3D-Body loaded (real mode)")
        except Exception as e:
            logger.warning(f"SAM-3D-Body unavailable: {e}; using stub mesh")
            self.mode = "stub"
            self._faces = self._build_smpl_faces()

    def _build_fov(self, device, fov_path: str):
        from models.sam_3d_body.tools.build_fov_estimator import FOVEstimator  # type: ignore
        return FOVEstimator(name="moge2", device=device, path=fov_path)

    def _build_smpl_faces(self) -> np.ndarray:
        """stub 24-vertex 占位 mesh faces (单位立方体简化版)。"""
        # 简单定义：24 顶点立方体（每个角 3 个顶点以保 mesh 连续性）
        return np.array([
            [0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6],
            [8, 10, 9], [8, 11, 10], [12, 13, 14], [12, 14, 15],
            [16, 18, 17], [16, 19, 18], [20, 21, 22], [20, 22, 23],
        ], dtype=np.int64)

    # ============== 公共 API ==============

    def process(
        self,
        image_paths: list[str],
        mask_paths: list[str],
        fov_path: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """对一批图像+mask执行 3D 重建。

        Returns: 每帧一个 dict: {"vertices": (V,3), "faces": (F,3), "joints": (24,3), "id": int}
        """
        if self.mode == "real":
            return self._real_process(image_paths, mask_paths)
        return self._stub_process(image_paths, mask_paths)

    def _stub_process(
        self,
        image_paths: list[str],
        mask_paths: list[str],
    ) -> list[dict[str, Any]]:
        """stub: 为每帧生成一个人形占位 mesh。

        用 mask 中心作为人体位置，固定比例构造 24 关节坐标。
        """
        from PIL import Image
        results = []
        for img_p, mask_p in zip(image_paths, mask_paths):
            try:
                mask = np.array(Image.open(mask_p).convert("L"))
                ys, xs = np.where(mask > 0)
                if len(xs) == 0:
                    cx, cy, h = 0, 0, 0
                else:
                    cx, cy = float(xs.mean()), float(ys.mean())
                    h = float(ys.max() - ys.min())
            except Exception:
                cx, cy, h = 0, 0, 0

            # 用 SMPL 24 关节的相对位置（站立姿态，单位米）
            joints_local = np.array(self._smpl_standing_template(), dtype=np.float32)
            # 缩放到 mask 高度
            if h > 0:
                joints_local *= h / 1.7  # SMPL 1.7m 标准化
            joints_local[:, 0] += cx
            joints_local[:, 1] += cy
            joints_local[:, 2] = 0.0  # stub 无深度

            vertices = self._joints_to_placeholder_mesh(joints_local)
            results.append({
                "vertices": vertices.astype(np.float32),
                "faces": self._faces,
                "joints": joints_local,
                "id": 1,
            })
        return results

    def _smpl_standing_template(self) -> list[list[float]]:
        """SMPL 24-关节站立姿态（局部坐标，单位米，y-up, z-front）。"""
        return [
            [0, 0.0, 0.0],       # 0 pelvis
            [0.1, -0.1, 0.0],    # 1 left_hip
            [-0.1, -0.1, 0.0],   # 2 right_hip
            [0, 0.2, 0.0],       # 3 spine1
            [0.1, -0.5, 0.0],    # 4 left_knee
            [-0.1, -0.5, 0.0],   # 5 right_knee
            [0, 0.4, 0.0],       # 6 spine2
            [0.1, -0.85, 0.0],   # 7 left_ankle
            [-0.1, -0.85, 0.0],  # 8 right_ankle
            [0, 0.55, 0.0],      # 9 spine3
            [0.1, -0.9, 0.1],    # 10 left_foot
            [-0.1, -0.9, 0.1],   # 11 right_foot
            [0, 0.7, 0.0],       # 12 neck
            [0.1, 0.65, 0.0],    # 13 left_collar
            [-0.1, 0.65, 0.0],   # 14 right_collar
            [0, 0.85, 0.0],      # 15 head
            [0.25, 0.65, 0.0],   # 16 left_shoulder
            [-0.25, 0.65, 0.0],  # 17 right_shoulder
            [0.3, 0.35, 0.0],    # 18 left_elbow
            [-0.3, 0.35, 0.0],   # 19 right_elbow
            [0.32, 0.05, 0.0],   # 20 left_wrist
            [-0.32, 0.05, 0.0],  # 21 right_wrist
            [0.33, -0.05, 0.0],  # 22 left_hand
            [-0.33, -0.05, 0.0], # 23 right_hand
        ]

    def _joints_to_placeholder_mesh(self, joints: np.ndarray) -> np.ndarray:
        """从 24 关节构造占位 mesh：每个关节周围 1 顶点。"""
        return joints.copy()

    def _real_process(
        self,
        image_paths: list[str],
        mask_paths: list[str],
    ) -> list[dict[str, Any]]:
        """真实模式：调用 SAM-3D-Body estimator。"""
        # 与 app.py 中 on_4d_generation 内部 process_image_with_mask 流程一致
        from models.sam_3d_body.notebook.utils import process_image_with_mask  # type: ignore

        outputs, id_batch, _ = process_image_with_mask(
            self._estimator, image_paths, mask_paths,
            idx_path={}, idx_dict={}, mhr_shape_scale_dict={}, occ_dict={},
            cam_int=None, iou_dict={},
        )
        results = []
        for out, id_cur in zip(outputs, id_batch):
            vertices = out.get("vertices", np.zeros((0, 3)))
            faces = self._faces
            joints = out.get("joints", np.zeros((24, 3)))
            results.append({
                "vertices": np.asarray(vertices, dtype=np.float32),
                "faces": faces,
                "joints": np.asarray(joints, dtype=np.float32),
                "id": int(id_cur) if id_cur is not None else 1,
            })
        return results

    @property
    def faces(self) -> Optional[np.ndarray]:
        return self._faces
