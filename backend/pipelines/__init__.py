"""backend.pipelines - 算法 Pipeline（含重模型降级）"""
from .diffusion_vas_pipeline import DiffusionVASPipeline
from .embedding_pipeline import EmbeddingPipeline
from .fine_cut_engine import FineCutEngine
from .fourd_pipeline import FourDPipeline, FourDResult
from .rough_cut_engine import CandidateClip, RoughCutEngine
from .sam3_pipeline import SAM3Pipeline
from .sam3d_body_pipeline import SAM3DBodyPipeline
from .vlm_pipeline import VLMPipeline

__all__ = [
    "CandidateClip",
    "DiffusionVASPipeline",
    "EmbeddingPipeline",
    "FineCutEngine",
    "FourDPipeline",
    "FourDResult",
    "RoughCutEngine",
    "SAM3DBodyPipeline",
    "SAM3Pipeline",
    "VLMPipeline",
]
