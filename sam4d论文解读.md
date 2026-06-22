**SAM 3 (Segment Anything Model 3)** 是 Meta 在 2024~2025 年间推出的新一代重量级**计算机视觉基础模型**。

简单来说，它的核心功能就是“抠图”与“物体追踪”**。但它比传统抠图软件强大无数倍：它不仅能识别照片里的东西，还能识别视频里的动态物体，并且**听得懂人话。

为了让你通俗易懂地理解，我们可以把 SAM 3 的核心本领拆解为以下几个方面：

---

## 1. 核心大招：听得懂人话的“提示词抠图” (PCS)

以前的初代 SAM 主要是靠你用鼠标“点一下”或者“画个框”来告诉它抠哪里。

而 **SAM 3 引入了“提示词概念分割”（Promptable Concept Segmentation）**。这意味着它具备了极强的开放词汇（Open-Vocabulary）理解能力。

* **听懂人话：** 你直接给它一张厨房的照片，对它说“把把手（handle）抠出来”，它就能把画面里平底锅、高压锅、橱柜上所有的把手都找出来。
* **正反向修正：** 如果它把烤箱的把手也抠出来了，但你不需要，你可以给它一个“反向框（Negative Box）”，告诉它：“把手，但排除这个区域。”它就会聪明地把烤箱把手去掉。

> **为什么厉害？**
> 官方测试了一个包含 **270,000 个独特概念**的超大视觉数据集（SA-CO benchmark），SAM 3 在这上面的表现已经达到了人类水平的 **75%-80%**。这意味着世界上绝大多数奇奇怪怪的物体，你只要说得出名字，它基本都能认得出、抠得准。

---

## 2. 视频追踪：从“静态”进化到“动态”

SAM 3 不仅能处理单张图片，还是个**视频追踪大师**。

* **一句话全片追踪：** 在一个视频里，你只要在第一帧输入提示词“人（person）”，它就能在接下来的几十甚至上百帧视频里，死死把这个人用面具（Mask）包裹住，无论他怎么走动、甚至被电线杆挡住一下再出来，都能精准追踪。
* **实时流式处理（Streaming）：** 它支持“来一帧处理一帧”的流式模式，这意味着它可以被应用到实时监控、路况自动驾驶、AR/VR 的实时画面渲染中。

---

## 3. 双重人格：你是要“概念”还是要“特定某一个”？

SAM 3 内部其实整合了两种非常实用的工作模式：

| 模式名称 | 它的通俗理解 | 举个例子 |
| --- | --- | --- |
| **PCS 模式**<br>

<br>(Concept) | **指名道姓认门类**：找出画面里所有符合这个名字的东西（不管有几个）。 | 输入“猫”，把画面里所有的猫（大猫、小猫、白猫）全部抠出来。 |
| **PVS 模式**<br>

<br>(Tracker) | **传统互动精准定位**：通过点选或画框，只追踪、抠出“这特定一个”物体。 | 画面里有五辆卡车，你在其中一辆上点了一下，它就只抠这一辆，别的卡车它不管。 |

---

## 4. 为什么它是开发者的“神兵利器”？

对于技术人员或动手的开发者来说，SAM 3 非常亲民：

* **多功能合一：** 它在抠出物体边缘（Instance Mask）的同时，还能顺便输出**语义分割（Semantic Segmentation）**，也就是把画面变成一张纯粹的“分类地图”。
* **无缝平替：** 它的 API（代码接口）设计完全继承了前代（SAM 2），如果你以前的代码是用 SAM 2 写的，现在可以像换个螺丝钉一样，直接把模型换成 SAM 3，性能立刻获得提升。
* **模型轻量：** 它的基础参数量大约在 **0.9B (9亿参数)** 左右，在 AI 界属于非常精悍小巧的体量，普通的消费级显卡（甚至部分移动端设备）就能跑得动。

---

## 总结

如果说初代 SAM 让计算机拥有了“看清物体边界”的眼睛，那么 **SAM 3 就是给这双眼睛加上了大语言模型的“大脑”**。它不再只是盲目地根据颜色和边界去抠图，而是真正理解了什么是“猫的耳朵”、什么是“烤箱的按钮”，成为了一个**既听得懂人话、又看得懂视频**的视觉全能王。



为你编写两个最基础的 Python 代码示例，分别展示 **SAM 3** 如何通过文本提示词（Text Prompt）**和**鼠标点击（Point Click）来对图片进行抠图。

这里我们以官方在 Hugging Face 上集成的 `transformers` 库代码为例，这是目前最标准、最通俗的调用方式。

---

### Demo 1：基于“文本提示词”（Text Prompt）的抠图

在这个模式下，你只需要给它一张图片，然后输入你想抠出来的物体名字（比如“猫的耳朵”），模型就会把所有符合的物体都找出来。

```python
import torch
from PIL import Image
import requests
from transformers import Sam3Processor, Sam3Model

# 1. 检查并设置运行设备（有显卡用显卡，没显卡用CPU）
device = "cuda" if torch.cuda.is_available() else "cpu"

# 2. 加载 SAM 3 的模型和处理器
model = Sam3Model.from_pretrained("facebook/sam3").to(device)
processor = Sam3Processor.from_pretrained("facebook/sam3")

# 3. 准备一张你的图片（这里用网络图片举例）
image_url = "http://images.cocodataset.org/val2017/000000077595.jpg"
image = Image.open(requests.get(image_url, stream=True).raw).convert("RGB")

# 4. 【核心步骤】告诉模型：我要抠图，提示词是 "ear"（耳朵）
inputs = processor(images=image, text="ear", return_tensors="pt").to(device)

# 5. 让模型进行推理计算
with torch.no_grad():
    outputs = model(**inputs)

# 6. 后处理：把模型输出的原始数据，转换成和原图一样大小的“遮罩（Mask）”
results = processor.post_process_instance_segmentation(
    outputs,
    threshold=0.5,
    mask_threshold=0.5,
    target_sizes=inputs.get("original_sizes").tolist()
)[0]

# 7. 打印结果：看看它找到了几个符合“耳朵”的物体
print(f"一共找到了 {len(results['masks'])} 个目标物体")
# results["masks"] 里面就包含了所有抠出来的图片图层（布尔矩阵）

```

---

### Demo 2：基于“互动点击”（Point Click）的抠图

如果你不需要它去理解名字，只是想在图片的某个像素坐标上“点一下”，让它把那一块的物体抠出来。这在 SAM 3 中由 `Sam3Tracker` 组件来完成。

```python
import torch
from PIL import Image
import requests
from transformers import Sam3TrackerProcessor, Sam3TrackerModel

device = "cuda" if torch.cuda.is_available() else "cpu"

# 1. 加载用于点击/追踪的 Tracker 模型和处理器
model = Sam3TrackerModel.from_pretrained("facebook/sam3").to(device)
processor = Sam3TrackerProcessor.from_pretrained("facebook/sam3")

# 2. 准备图片
image_url = "https://huggingface.co/datasets/hf-internal-testing/sam2-fixtures/resolve/main/truck.jpg"
raw_image = Image.open(requests.get(image_url, stream=True).raw).convert("RGB")

# 3. 【核心步骤】模拟鼠标点击
# 假设你在图片的横坐标 500，纵坐标 350 的位置点了一下
input_points = [[[[500, 350]]]] 
# 1 代表“正向点击”（我要抠这里），0 代表“反向点击”（不要这里）
input_labels = [[[1]]]           

# 4. 把图片和点击的坐标一起打包传给处理器
inputs = processor(
    images=raw_image, 
    input_points=input_points, 
    input_labels=input_labels, 
    return_tensors="pt"
).to(device)

# 5. 让模型进行推理
with torch.no_grad():
    outputs = model(**inputs)

# 6. 后处理：获取最终的抠图遮罩
masks = processor.post_process_masks(outputs.pred_masks.cpu(), inputs["original_sizes"])[0]

# 7. 打印结果（通常模型会针对你的点击返回几个不同精细度的候选遮罩，比如全身、半身等）
print(f"成功生成了 {masks.shape[1]} 个候选的抠图遮罩")

```

### 💡 核心区别小结：

* **Demo 1 (基于提示词)**：用的是 `Sam3Model`。你给它**词语**，它在全图搜寻**所有**符合概念的物体。
* **Demo 2 (基于点击)**：用的是 `Sam3TrackerModel`。你给它**坐标**，它只死磕**那一个**被你点中的特定物体。