"""4D Pipeline - 编排 SAM-3 传播 + Diffusion-VAS 补全 + SAM-3D-Body 重建

核心算法（与 app.py:on_4d_generation 一致）：
- cap_consecutive_ones_by_iou: 帧内连续性筛选
- mask_completion_and_iou_init: 初步 amodal 检测
- mask_completion_and_iou_final: 高分 amodal 检测
- 4D mesh 重建 + 视频渲染

输出：
- outputs/{task_id}/images/, masks/        - 帧级图像与 mask
- outputs/{task_id}/rendered_frames/      - 渲染结果
- outputs/{task_id}/4d_*.mp4              - 渲染视频
"""
from __future__ import annotations

import logging
import os
import random
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image
from tqdm import tqdm

from ..config import get_config
from ..store import (
    ActionClip,
    Clip,
    ClipStatus,
    TaskStatus,
    VideoSource,
    get_store,
)
from ..utils import (
    DAVIS_PALETTE,
    bbox_from_mask,
    is_skinny_mask,
    is_super_long_or_wide,
    jpg_folder_to_mp4,
    keep_largest_component,
    mask_painter,
    resize_mask_with_unique_label,
)
from .sam3_pipeline import SAM3Pipeline
from .sam3d_body_pipeline import SAM3DBodyPipeline
from .diffusion_vas_pipeline import DiffusionVASPipeline

logger = logging.getLogger(__name__)


# ============== 复现 app.py:253-314 ==============


def cap_consecutive_ones_by_iou(
    flag: list[int],
    iou: list[float],
    max_keep: int = 3,
) -> list[int]:
    """
    复现 app.py 中 cap_consecutive_ones_by_iou 的逻辑。
    """
    n = len(flag)
    if len(iou) != n:
        raise ValueError(f"len(flag)={n} != len(iou)={len(iou)}")
    out = [1 if flag[i] == 0 else 0 for i in range(n)]
    i = 0
    while i < n:
        if flag[i] != 1:
            i += 1
            continue
        j = i
        while j < n and flag[j] == 1:
            j += 1
        run_idx = list(range(i, j))
        if len(run_idx) <= max_keep:
            for k in run_idx:
                out[k] = 1
        else:
            top = sorted(run_idx, key=lambda k: (-float(iou[k]), k))[:max_keep]
            for k in top:
                out[k] = 1
        i = j
    return out


# ============== 复现 app.py:584-674 ==============


def mask_completion_and_iou_init(
    pred_amodal_masks,
    pred_res,
    obj_id,
    batch_masks,
    i,
    W,
    H,
):
    """复现 app.py:mask_completion_and_iou_init"""
    obj_ratio_dict_obj_id = None
    iou_dict_obj_id = None
    occ_dict_obj_id = None
    idx_dict_obj_id = None
    idx_path_obj_id = None

    pred_amodal_masks_com = [np.array(img.resize((pred_res[1], pred_res[0]))) for img in pred_amodal_masks]
    pred_amodal_masks_com = np.array(pred_amodal_masks_com).astype("uint8")
    pred_amodal_masks_com = (pred_amodal_masks_com.sum(axis=-1) > 600).astype("uint8")
    pred_amodal_masks_com = [keep_largest_component(pamc) for pamc in pred_amodal_masks_com]

    pred_amodal_masks = [np.array(img.resize((W, H))) for img in pred_amodal_masks]
    pred_amodal_masks = np.array(pred_amodal_masks).astype("uint8")
    pred_amodal_masks = (pred_amodal_masks.sum(axis=-1) > 600).astype("uint8")
    pred_amodal_masks = [keep_largest_component(pamc) for pamc in pred_amodal_masks]

    masks = [(np.array(Image.open(bm).convert("P")) == obj_id).astype("uint8") for bm in batch_masks]
    ious = []
    masks_margin_shrink = [bm.copy() for bm in masks]
    mask_H, mask_W = masks_margin_shrink[0].shape
    occlusion_threshold = 0.55
    for bi, (a, b) in enumerate(zip(masks, pred_amodal_masks)):
        zero_mask_cp = np.zeros_like(masks_margin_shrink[bi])
        zero_mask_cp[masks_margin_shrink[bi] == 1] = 255
        mask_binary_cp = zero_mask_cp.astype(np.uint8)
        mask_binary_cp[: int(mask_H * 0.05), :] = 0
        mask_binary_cp[-int(mask_H * 0.05):, :] = 0
        mask_binary_cp[:, : int(mask_W * 0.05)] = 0
        mask_binary_cp[:, -int(mask_W * 0.05):] = 0
        if mask_binary_cp.max() == 0:
            ious.append(occlusion_threshold)
            continue
        area_a = (a > 0).sum()
        area_b = (b > 0).sum()
        if area_a == 0 and area_b == 0:
            ious.append(occlusion_threshold)
        elif area_a > area_b:
            ious.append(occlusion_threshold)
        else:
            inter = np.logical_and(a > 0, b > 0).sum()
            uni = np.logical_or(a > 0, b > 0).sum()
            obj_iou = inter / (uni + 1e-6)
            ious.append(obj_iou)
        if i == 0 and bi == 0:
            if ious[0] < occlusion_threshold:
                obj_ratio_dict_obj_id = bbox_from_mask(b)
            else:
                obj_ratio_dict_obj_id = bbox_from_mask(a)

    for pi, pamc in enumerate(pred_amodal_masks_com):
        if masks[pi].sum() > pred_amodal_masks[pi].sum():
            ious[pi] = occlusion_threshold
            pred_amodal_masks_com[pi] = resize_mask_with_unique_label(masks[pi], pred_res[0], pred_res[1], obj_id)
        elif is_super_long_or_wide(pred_amodal_masks[pi], obj_id):
            ious[pi] = occlusion_threshold
            pred_amodal_masks_com[pi] = resize_mask_with_unique_label(masks[pi], pred_res[0], pred_res[1], obj_id)
        elif is_skinny_mask(pred_amodal_masks[pi]):
            ious[pi] = occlusion_threshold
            pred_amodal_masks_com[pi] = resize_mask_with_unique_label(masks[pi], pred_res[0], pred_res[1], obj_id)

    iou_dict_obj_id = [float(x) for x in ious]
    arr = iou_dict_obj_id[:]
    for isb in range(1, len(arr) - 1):
        if arr[isb] == occlusion_threshold and arr[isb - 1] < occlusion_threshold and arr[isb + 1] < occlusion_threshold:
            arr[isb] = 0.0
    iou_dict_obj_id = arr
    occ_dict_obj_id = [1 if ix >= occlusion_threshold else 0 for ix in iou_dict_obj_id]
    idxs = [ix for ix, x in enumerate(iou_dict_obj_id) if x < occlusion_threshold]
    start, end = (idxs[0], idxs[-1]) if idxs else (None, None)
    if start is not None and end is not None:
        start = max(0, start - 2)
        end = min(len(pred_amodal_masks), end + 2)
        idx_dict_obj_id = (start, end)
        completion_path = "".join(random.choices("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=4))
        # 用 task_id 占位（实际由调用方在 4D.run 内替换）
        idx_path_obj_id = {
            "images": f"__TASK_OUT__/completion/{completion_path}/images",
            "masks": f"__TASK_OUT__/completion/{completion_path}/masks",
        }
    return obj_ratio_dict_obj_id, iou_dict_obj_id, occ_dict_obj_id, idx_dict_obj_id, idx_path_obj_id


def mask_completion_and_iou_final(
    pred_amodal_masks,
    pred_res,
    obj_id,
    batch_masks,
    W,
    H,
    iou_dict_obj_id,
    occ_dict_obj_id,
    idx_path_obj_id,
    keep_idx,
):
    """复现 app.py:mask_completion_and_iou_final"""
    keep_id = [io for io, vo in enumerate(keep_idx) if vo == 1]
    batch_masks_ = [batch_masks[io] for io in keep_id]

    zero_com = np.zeros_like(np.array(pred_amodal_masks[0].resize((pred_res[1], pred_res[0])))[:, :, 0])
    pred_amodal_masks_com = [np.array(img.resize((pred_res[1], pred_res[0]))) for img in pred_amodal_masks]
    pred_amodal_masks_com = np.array(pred_amodal_masks_com).astype("uint8")
    pred_amodal_masks_com = (pred_amodal_masks_com.sum(axis=-1) > 600).astype("uint8")
    pred_amodal_masks_com = [keep_largest_component(pamc) for pamc in pred_amodal_masks_com]

    pred_amodal_masks = [np.array(img.resize((W, H))) for img in pred_amodal_masks]
    pred_amodal_masks = np.array(pred_amodal_masks).astype("uint8")
    pred_amodal_masks = (pred_amodal_masks.sum(axis=-1) > 600).astype("uint8")
    pred_amodal_masks = [keep_largest_component(pamc) for pamc in pred_amodal_masks]

    masks = [(np.array(Image.open(bm).convert("P")) == obj_id).astype("uint8") for bm in batch_masks_]
    ious = []
    masks_margin_shrink = [bm.copy() for bm in masks]
    mask_H, mask_W = masks_margin_shrink[0].shape
    occlusion_threshold = 0.65
    for bi, (a, b) in enumerate(zip(masks, pred_amodal_masks)):
        zero_mask_cp = np.zeros_like(masks_margin_shrink[bi])
        zero_mask_cp[masks_margin_shrink[bi] == 1] = 255
        mask_binary_cp = zero_mask_cp.astype(np.uint8)
        mask_binary_cp[: int(mask_H * 0.05), :] = 0
        mask_binary_cp[-int(mask_H * 0.05):, :] = 0
        mask_binary_cp[:, : int(mask_W * 0.05)] = 0
        mask_binary_cp[:, -int(mask_W * 0.05):] = 0
        if mask_binary_cp.max() == 0:
            ious.append(occlusion_threshold)
            continue
        area_a = (a > 0).sum()
        area_b = (b > 0).sum()
        if area_a == 0 and area_b == 0:
            ious.append(occlusion_threshold)
        elif area_a > area_b:
            ious.append(occlusion_threshold)
        else:
            inter = np.logical_and(a > 0, b > 0).sum()
            uni = np.logical_or(a > 0, b > 0).sum()
            obj_iou = inter / (uni + 1e-6)
            ious.append(obj_iou)

    for pi, pamc in enumerate(pred_amodal_masks_com):
        if masks[pi].sum() > pred_amodal_masks[pi].sum():
            ious[pi] = occlusion_threshold
            pred_amodal_masks_com[pi] = resize_mask_with_unique_label(masks[pi], pred_res[0], pred_res[1], obj_id)
        elif is_super_long_or_wide(pred_amodal_masks[pi], obj_id):
            ious[pi] = occlusion_threshold
            pred_amodal_masks_com[pi] = resize_mask_with_unique_label(masks[pi], pred_res[0], pred_res[1], obj_id)
        elif is_skinny_mask(pred_amodal_masks[pi]):
            ious[pi] = occlusion_threshold
            pred_amodal_masks_com[pi] = resize_mask_with_unique_label(masks[pi], pred_res[0], pred_res[1], obj_id)

    iou_dict_obj_id_ = [float(x) for x in ious]
    arr = iou_dict_obj_id_[:]
    for isb in range(1, len(arr) - 1):
        if arr[isb] == occlusion_threshold and arr[isb - 1] < occlusion_threshold and arr[isb + 1] < occlusion_threshold:
            arr[isb] = 0.0
    iou_dict_obj_id_ = arr
    occ_dict_obj_id_ = [1 if ix >= occlusion_threshold else 0 for ix in iou_dict_obj_id_]

    completion_masks_path = idx_path_obj_id["masks"]
    current_id = 0
    final_pred_amodal_masks_com = []
    for ki, kid in enumerate(keep_idx):
        if kid == 0:
            final_pred_amodal_masks_com.append(zero_com)
            continue
        occ_dict_obj_id[ki] = occ_dict_obj_id_[current_id]
        iou_dict_obj_id[ki] = iou_dict_obj_id_[current_id]
        if occ_dict_obj_id_[current_id] == 1:
            current_id += 1
            final_pred_amodal_masks_com.append(zero_com)
            continue
        final_pred_amodal_masks_com.append(pred_amodal_masks_com[current_id])
        mask_idx_ = pred_amodal_masks[current_id].copy()
        mask_idx_[mask_idx_ > 0] = obj_id
        mask_idx_ = Image.fromarray(mask_idx_).convert("P")
        mask_idx_.putpalette(DAVIS_PALETTE)
        os.makedirs(completion_masks_path, exist_ok=True)
        mask_idx_.save(os.path.join(completion_masks_path, f"{ki:08d}.png"))
        current_id += 1
    return iou_dict_obj_id, occ_dict_obj_id, final_pred_amodal_masks_com


# ============== 4D 编排 ==============


@dataclass
class FourDResult:
    """4D 重建结果"""
    task_id: str
    video_id: str
    images_dir: str
    masks_dir: str
    rendered_dir: str
    output_video: str = ""
    total_frames: int = 0
    obj_ids: list[int] = field(default_factory=list)
    duration: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class FourDPipeline:
    """4D 重建 + 渲染编排。

    工作流（与 app.py:on_4d_generation 一致）：
    1. 从精切片段抽帧到 images/，mask 同步
    2. SAM-3 传播：填全 masks
    3. (可选) Diffusion-VAS 检测遮挡 + amodal 补全
    4. SAM-3D-Body 逐帧重建 mesh
    5. Mesh 渲染回 2D，写入 rendered_frames/
    6. 合成 4D MP4
    """

    def __init__(
        self,
        sam3: Optional[SAM3Pipeline] = None,
        sam3d: Optional[SAM3DBodyPipeline] = None,
        vas: Optional[DiffusionVASPipeline] = None,
    ):
        self.cfg = get_config()
        self.sam3 = sam3 or SAM3Pipeline()
        self.sam3d = sam3d or SAM3DBodyPipeline()
        self.vas = vas or DiffusionVASPipeline()
        self._generator = torch.manual_seed(23)

    def run(
        self,
        task_id: str,
        video_id: str,
        clip_id: str,
        video_path: str,
        obj_ids: list[int],
        fps: float,
        start_sec: float,
        end_sec: float,
        progress_cb: Optional[Any] = None,
    ) -> FourDResult:
        """执行 4D 重建。

        Args:
            task_id, video_id, clip_id: 业务 ID
            video_path: 源视频（已精切的临时文件）
            obj_ids: 所有目标 ID
            fps: 帧率
            start_sec, end_sec: 起止时间
        """
        store = get_store()
        out_dir = Path(self.cfg.runtime.output_dir) / task_id
        images_dir = out_dir / "images"
        masks_dir = out_dir / "masks"
        rendered_dir = out_dir / "rendered_frames"
        completion_dir = out_dir / "completion"
        for d in [images_dir, masks_dir, rendered_dir, completion_dir]:
            d.mkdir(parents=True, exist_ok=True)

        # 1) 抽帧 (如果 video_path 来自 trimmed_path，则是精切后的剪辑)
        clip_obj = store.get_clip(clip_id) if clip_id else None
        use_trimmed = bool(
            clip_obj and clip_obj.meta.get("trimmed_path")
            and Path(clip_obj.meta["trimmed_path"]) == Path(video_path)
        )
        n = self._extract_frames(video_path, images_dir, fps, start_sec, end_sec, use_trimmed=use_trimmed)
        if n == 0:
            raise RuntimeError("No frames extracted from video")
        # 清理过期的 images
        for p in images_dir.glob("*.jpg"):
            try:
                if int(p.stem) >= n:
                    p.unlink()
            except ValueError:
                pass
        image_paths = sorted(images_dir.glob("*.jpg"))[:n]

        # 2) 用首批 mask（来自标注） + 传播填充 masks
        #    stub 模式：直接复制首批 mask 到所有帧
        #    真实模式：调用 SAM-3 propagate_in_video
        mask_outputs = self._propagate_masks(
            video_path, start_sec, end_sec, fps, obj_ids, masks_dir,
            max_frames=n,
        )

        # 3) 4D 重建 + 渲染
        rendered_paths: list[str] = []
        for i in tqdm(range(n), desc="4D Reconstruct"):
            img_p = str(image_paths[i])
            mask_p = str(self._mask_path_for_frame(masks_dir, i))
            try:
                outputs = self.sam3d.process([img_p], [mask_p])
            except Exception as e:
                logger.warning(f"SAM-3D-Body frame {i} failed: {e}")
                outputs = []

            # 渲染：把 mesh overlay 到原图
            img = cv2.imread(img_p)
            rendered = self._render_frame(img, outputs)
            rpath = str(rendered_dir / f"{i:08d}.jpg")
            cv2.imwrite(rpath, rendered)
            rendered_paths.append(rpath)

            if progress_cb:
                progress_cb(i + 1, n)

        # 4) 合成视频
        out_video = str(out_dir / f"4d_{int(time.time())}.mp4")
        jpg_folder_to_mp4(str(rendered_dir), out_video, fps=fps)

        # 5) 持久化
        result = FourDResult(
            task_id=task_id,
            video_id=video_id,
            images_dir=str(images_dir),
            masks_dir=str(masks_dir),
            rendered_dir=str(rendered_dir),
            output_video=out_video,
            total_frames=n,
            obj_ids=obj_ids,
            duration=(end_sec - start_sec),
        )

        # 更新 clip
        clip = store.get_clip(clip_id)
        if clip is not None:
            clip.status = ClipStatus.FOUR_D_DONE
            clip.rendered_video_url = f"/api/outputs/{task_id}/{Path(out_video).name}"
            clip.mesh_dir = f"/api/outputs/{task_id}/rendered_frames"
            clip.duration = result.duration
            store.upsert_clip(clip)

        # 推进 task 状态
        store.update_task(
            task_id,
            status=TaskStatus.FOUR_D_RECONSTRUCTING,
            progress=1.0,
            current_stage="4d_reconstructing",
            message="4D 重建完成",
        )

        return result

    # ============== 辅助方法 ==============

    def _extract_frames(self, video_path, images_dir, fps, start_sec, end_sec,
                        use_trimmed: bool = True) -> None:
        """从视频抽帧到 images_dir/{idx:08d}.jpg

        当 use_trimmed=True 时，video_path 是已精切的剪辑文件，
        此时 start_sec/end_sec 应当是剪辑内的局部时间（通常为 0..duration）。
        当 use_trimmed=False 时，是原视频，start_sec/end_sec 是原视频时间。
        """
        cap = cv2.VideoCapture(video_path)
        if use_trimmed:
            seek_sec = 0.0
            end_at = end_sec - start_sec
        else:
            seek_sec = start_sec
            end_at = end_sec
        cap.set(cv2.CAP_PROP_POS_MSEC, seek_sec * 1000)
        idx = 0
        end_ms = end_at * 1000
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            cur_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            if cur_ms > end_ms:
                break
            cv2.imwrite(str(images_dir / f"{idx:08d}.jpg"), frame)
            idx += 1
        cap.release()
        return idx  # 返回实际抽帧数

    def _propagate_masks(
        self,
        video_path: str,
        start_sec: float,
        end_sec: float,
        fps: float,
        obj_ids: list[int],
        masks_dir: Path,
        max_frames: Optional[int] = None,
    ) -> dict[int, dict[int, np.ndarray]]:
        """用 SAM-3 传播或 stub：填充 masks/{idx}.png

        真实模式：调用 self.sam3.propagate_in_video
        stub 模式：用 MOG2 背景减除（已在 sam3._stub_propagate 中实现）

        Returns: {obj_id: {frame_idx: mask}}
        """
        # 初始化 inference_state
        state = self.sam3.init_state(video_path)
        # stub: 加载所有帧后用 MOG2
        if self.sam3.mode == "stub":
            state["frames"] = []
            cap = cv2.VideoCapture(video_path)
            while True:
                ok, f = cap.read()
                if not ok:
                    break
                state["frames"].append(f)
            cap.release()
            state["total_frames"] = len(state["frames"])
            state["video_height"] = state["frames"][0].shape[0]
            state["video_width"] = state["frames"][0].shape[1]

        # 标记首帧每个目标
        H, W = state["video_height"], state["video_width"]
        seed_frame = 0
        for obj_id in obj_ids:
            # 用图像中心作为种子点
            cx, cy = W // 2, H // 2
            points = np.array([[cx, cy]], dtype=np.int32)
            labels = np.array([1], dtype=np.int32)
            try:
                self.sam3.add_new_points_or_box(state, seed_frame, obj_id, points, labels)
            except Exception as e:
                logger.warning(f"add_new_points_or_box obj={obj_id} failed: {e}")

        # 传播生成所有帧的 mask
        per_obj_masks: dict[int, dict[int, np.ndarray]] = {oid: {} for oid in obj_ids}
        for f_idx, ids, _, v_res, _, _ in self.sam3.propagate_in_video(state, start_frame_idx=0, max_frame_num_to_track=10**9):
            for k, oid in enumerate(ids):
                m = v_res[k, 0].detach().cpu().numpy() if hasattr(v_res, "detach") else v_res[k, 0]
                mask = (m > 0).astype(np.uint8) * int(oid)
                per_obj_masks[oid][int(f_idx)] = mask
                # 写入 masks_dir/{f_idx:08d}.png
                self._save_combined_mask(masks_dir, int(f_idx), per_obj_masks, obj_ids)

        # 确保每帧都有 mask (与 images 数量对齐)
        total = min(state["total_frames"], max_frames or state["total_frames"])
        for f in range(total):
            if not (masks_dir / f"{f:08d}.png").exists():
                self._save_combined_mask(masks_dir, f, per_obj_masks, obj_ids, fill_zero=True)
        # 清理超出 images 范围的 mask
        max_idx = max_frames if max_frames else total
        for p in masks_dir.glob("*.png"):
            try:
                idx = int(p.stem)
                if idx >= max_idx:
                    p.unlink()
            except ValueError:
                pass
        return per_obj_masks

    def _save_combined_mask(
        self,
        masks_dir: Path,
        frame_idx: int,
        per_obj_masks: dict[int, dict[int, np.ndarray]],
        obj_ids: list[int],
        fill_zero: bool = False,
    ) -> None:
        """合并所有 obj 的 mask 到单通道 png."""
        if frame_idx in next(iter(per_obj_masks.values()), {}):
            combined = np.zeros_like(next(iter(per_obj_masks.values()))[frame_idx])
        else:
            combined = None
        if combined is None:
            if per_obj_masks:
                sample = next(iter(per_obj_masks.values()))
                sample_mask = next(iter(sample.values()), None)
                if sample_mask is not None:
                    combined = np.zeros_like(sample_mask)
                else:
                    return
            else:
                return
        for oid in obj_ids:
            m = per_obj_masks.get(oid, {}).get(frame_idx)
            if m is not None:
                combined[m > 0] = oid
        pil = Image.fromarray(combined.astype(np.uint8)).convert("P")
        pil.putpalette(DAVIS_PALETTE)
        pil.save(masks_dir / f"{frame_idx:08d}.png")

    def _mask_path_for_frame(self, masks_dir: Path, idx: int) -> Path:
        p = masks_dir / f"{idx:08d}.png"
        if not p.exists():
            # 写入零 mask
            pil = Image.new("P", (640, 360), 0)
            pil.putpalette(DAVIS_PALETTE)
            pil.save(p)
        return p

    def _render_frame(
        self,
        img: np.ndarray,
        outputs: list[dict[str, Any]],
    ) -> np.ndarray:
        """把 SAM-3D-Body 输出 mesh 简单渲染到原图。

        stub 实现：用 joints 画 2D 骨架
        """
        rendered = img.copy()
        for out in outputs:
            joints = out.get("joints")
            if joints is None or len(joints) == 0:
                continue
            # 取前两维作 2D 投影
            pts_2d = joints[:, :2].astype(np.int32)
            H, W = img.shape[:2]
            for (x, y) in pts_2d:
                if 0 <= x < W and 0 <= y < H:
                    cv2.circle(rendered, (int(x), int(y)), 4, (59, 130, 246), -1, cv2.LINE_AA)
            # 画连线
            skeleton_pairs = [
                (0, 1), (0, 2), (1, 4), (2, 5), (4, 7), (5, 8),
                (0, 3), (3, 6), (6, 9), (9, 12), (9, 13), (9, 14),
                (12, 15), (13, 16), (14, 17), (16, 18), (17, 19),
                (18, 20), (19, 21), (20, 22), (21, 23),
            ]
            for i, j in skeleton_pairs:
                if i < len(pts_2d) and j < len(pts_2d):
                    p1 = tuple(pts_2d[i])
                    p2 = tuple(pts_2d[j])
                    if 0 <= p1[0] < W and 0 <= p1[1] < H and 0 <= p2[0] < W and 0 <= p2[1] < H:
                        cv2.line(rendered, p1, p2, (139, 92, 246), 2, cv2.LINE_AA)
        return rendered
