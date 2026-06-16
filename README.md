# 4D 动作知识库系统 (4D Action Knowledge Base System)

> 把单视频交互式算法 Demo 升级为端到端的"4D 动作知识库系统"——通过纯文本语义检索，为视频大模型提供高质量的 4D 渲染视频作为动作视觉参考。

---

## 🎯 项目概述

本项目实现 PRD 描述的完整系统：
- **上游接入**：本地视频 + GUID 批量拉取
- **处理流水线**：粗切自动化 → 精切人工校验 → Target 标注 → 4D 重建 → 渲染视频导出
- **下游语义化**：Qwen-VL 描述生成 → 人工标签 → Qwen3-Embedding → Weaviate 入库
- **应用层**：纯文本语义检索 + 大模型渲染视频引用

## 🏗️ 架构

```
video2action/
├── app.py                  # 原始 Gradio demo（保留为算法参考）
├── sam_body4d_studio.html  # 原始前端设计稿（保留为视觉参考）
├── prd.md                  # 产品需求文档
│
├── backend/                # FastAPI 后端（核心实现）
│   ├── main.py            # FastAPI 入口 + 静态资源挂载
│   ├── config.py          # YAML 配置加载
│   ├── pipeline_registry.py # Pipeline 单例管理（避免循环导入）
│   ├── api/               # 11 个模块的 REST 路由
│   ├── pipelines/         # 算法 Pipeline（含重模型降级）
│   ├── store/             # SQLite 业务状态 + Pydantic 数据模型
│   ├── vector/            # 向量库抽象 (Stub + Weaviate)
│   └── utils/             # 复现 app.py 引用的工具函数
│
├── frontend/              # 静态前端
│   ├── index.html         # 11 模块 SPA 入口
│   ├── css/               # 提取自原 HTML 的视觉样式
│   └── js/                # 模块化 JS（api / state / utils / 11 模块）
│
├── configs/
│   ├── body4d.yaml        # 模型与系统配置
│   └── vlm_prompts.json   # VLM 描述模板
│
├── data/                  # 运行时数据 (SQLite + 向量持久化)
├── outputs/               # 渲染视频 / 中间产物
└── tests/                 # 单元测试 + 端到端测试
```

---

## 🚀 快速开始

### 1. 安装依赖

```bash
cd /Users/yaolf/video2action
pip install -r backend/requirements.txt
```

必需依赖：fastapi, uvicorn, pydantic, pydantic-settings, opencv-python-headless, torch, numpy, Pillow, omegaconf, sentence-transformers, pyyaml, python-multipart, pytest, httpx

### 2. 启动后端

```bash
# 方式 A：直接 python
python backend/main.py

# 方式 B：uvicorn
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. 访问前端

打开浏览器访问 `http://localhost:8000/`

后端 API 文档（OpenAPI）：`http://localhost:8000/docs`

### 4. 跑测试

```bash
PYTHONPATH=. pytest tests/ -v
```

---

## 📊 API 端点总览

| 模块 | 端点 | 功能 |
|------|------|------|
| **Dashboard** | `GET /api/dashboard/metrics` | 总览指标 |
| | `GET /api/dashboard/recent` | 最近视频 |
| | `GET /api/dashboard/category-stats` | 资产分类 |
| **Tasks** | `GET /api/tasks` | 任务列表 |
| | `POST /api/tasks` | 创建任务 |
| | `POST /api/tasks/{id}/advance` | 推进状态 |
| **Import** | `POST /api/import/local` | 本地上传 |
| | `POST /api/import/guid` | GUID 批量 |
| | `GET /api/import/history` | 导入历史 |
| **Rough Cut** | `POST /api/rough-cut/run` | 自动化粗切 |
| | `GET /api/rough-cut/candidates/{video_id}` | 候选列表 |
| **Fine Cut** | `POST /api/fine-cut/trim` | FFmpeg 精切 |
| | `GET /api/fine-cut/clips` | 片段列表 |
| **Target** | `POST /api/target/click` | 点击标注 |
| | `POST /api/target/add` | 添加目标 |
| **4D** | `POST /api/4d/mask` | Mask 传播 |
| | `POST /api/4d/reconstruct` | 4D 重建 |
| **Tagging** | `POST /api/tagging/vlm` | VLM 描述 |
| | `POST /api/tagging/save` | 保存标签 |
| | `POST /api/tagging/index` | 入库向量库 |
| **Assets** | `GET /api/assets` | 资产库 |
| **Search** | `POST /api/search/text` | 纯文本检索 |
| | `POST /api/search/reference` | 大模型引用 |
| **Completed** | `GET /api/completed/{task_id}` | 完成指标 |

---

## 🧠 重模型降级策略

本地默认无 checkpoint，所有 Pipeline 自动降级：

| Pipeline | 真实模式 | 降级方案 |
|----------|---------|---------|
| **SAM-3** | `models.sam3.sam3.model_builder` | OpenCV MOG2 背景减除 + 形态学 |
| **SAM-3D-Body** | `models.sam_3d_body.sam_3d_body` | SMPL 24 关节占位 mesh |
| **Diffusion-VAS** | `models.diffusion_vas.demo` | cv2.inpaint + 形态学闭运算 |
| **Qwen-VL** | `transformers.Qwen2_5_VLForConditionalGeneration` | 关键词模板 (configs/vlm_prompts.json) |
| **Qwen3-Embedding** | `transformers.AutoModel` | sentence-transformers 多语种 MiniLM |

### 启用真实模式

1. 把 checkpoint 放到 `configs/body4d.yaml` 中指定的路径
2. 重启服务即可自动检测并加载真实模型（无需改代码）
3. 日志会显示 `mode=real` 或 `mode=stub`

### 切换向量库后端

```bash
# 默认 stub (in-memory + JSON 持久化)
python backend/main.py

# 切换到 Weaviate
export VECTOR_BACKEND=weaviate
export WEAVIATE_URL=http://localhost:8080
pip install weaviate-client  # 首次需要
python backend/main.py
```

---

## 🔍 核心算法（来自 app.py）

下列函数直接复用 `app.py` 中的实现：

| 函数 | 位置 | 作用 |
|------|------|------|
| `cap_consecutive_ones_by_iou` | `backend/pipelines/fourd_pipeline.py` | 帧内连续性筛选 |
| `mask_completion_and_iou_init` | 同上 | 初步 amodal 检测 |
| `mask_completion_and_iou_final` | 同上 | 高分 amodal 检测 |
| `on_mask_generation` 编排 | `backend/pipelines/fourd_pipeline.FourDPipeline.run` | SAM-3 传播 + 帧保存 |
| `on_4d_generation` 编排 | 同上 | 4D 重建 + 视频渲染 |
| `draw_point_marker / mask_painter / DAVIS_PALETTE` | `backend/utils/` | 可视化 |

---

## 🧪 测试覆盖

```bash
# 单元测试（Store / Vector / Utils / VLM / 核心算法）
pytest tests/test_pipelines.py -v

# 端到端：上传 → 粗切 → 精切 → 标注 → 4D → 标签 → 检索
pytest tests/test_api.py -v
```

E2E 测试使用程序生成的简单 MP4，跑通全链路，验证：
- 11 个 API 端点全部 200
- 流程状态正确推进
- 入库后检索能召回刚入库的资产

---

## 📁 数据流

```
1. 上传视频 → outputs/uploads/{uuid}.mp4
2. 抽帧 → outputs/{task_id}/images/00000000.jpg ...
3. SAM-3 传播 → outputs/{task_id}/masks/00000000.png ...
4. SAM-3D-Body 重建 → outputs/{task_id}/rendered_frames/00000000.jpg ...
5. 合成渲染视频 → outputs/{task_id}/4d_*.mp4
6. 静态服务挂载 /api/outputs/...
```

---

## 🛠️ 配置项

`configs/body4d.yaml` 关键字段：

```yaml
runtime:
  output_dir: "./outputs"
  data_dir: "./data"
  port: 8000

vector_db:
  backend: "stub"  # stub | weaviate
  weaviate_url: "http://localhost:8080"

completion:
  enable: false  # 主开关：是否启用 Diffusion-VAS 补全

vlm:
  fallback_enabled: true  # 模板降级
```

环境变量优先级高于 YAML：
- `VECTOR_BACKEND=stub|weaviate`
- `WEAVIATE_URL=...`
- `LOG_LEVEL=DEBUG|INFO|WARNING`

---

## 🎓 与 PRD 的映射

| PRD 模块 | 实现位置 |
|---------|---------|
| 3.1.1 GUID 批量视频拉取 | `backend/api/video_import.py` |
| 3.1.2 自动化粗切 | `backend/pipelines/rough_cut_engine.py` |
| 3.1.3 人工精切 | `backend/pipelines/fine_cut_engine.py` + `backend/api/fine_cut.py` |
| 3.2.1 视频打点标注 | `backend/api/target.py` |
| 3.2.2 Mask 传播与遮挡补全 | `backend/pipelines/fourd_pipeline.py` |
| 3.2.3 4D 人体重建与渲染视频 | `backend/pipelines/fourd_pipeline.py` |
| 3.3.1 基于关键词的 VLM 描述 | `backend/pipelines/vlm_pipeline.py` |
| 3.3.3 Weaviate 纯文本向量库入库 | `backend/vector/{stub,weaviate}_client.py` |
| 3.4.1 纯文本语义检索接口 | `backend/api/search.py` |
| 3.4.2 大模型引用接口 | `backend/api/search.py:reference_for_generation` |
| 4.1 任务状态机 | `backend/store/models.py:TaskStatus` |

---

## 📜 版本

- v 2.4.1 · 2024-05
- 基于 SAM-Body4D Studio 设计稿
- PRD: `prd.md`

---

## 📄 License

Internal project - All rights reserved.
