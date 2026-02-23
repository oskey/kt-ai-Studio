# ✨ KT-AI-Studio

<p align="center">
  <img src="docs/images/banner.png" alt="KT-AI-Studio Banner" width="100%" />
</p>

<p align="center">
  <strong>
    LLM 驱动的 ComfyUI 自动化漫剧 / 图像 / 视频生成工作室
  </strong>
</p>

<p align="center">
  <em>
    人物一致性 · 场景一致性 · 风格一致性 · 无需训练 LoRA
  </em>
</p>

<p align="center">
  <img src="https://img.shields.io/github/stars/oskey/kt-ai-Studio?style=flat-square" />
  <img src="https://img.shields.io/github/license/oskey/kt-ai-Studio?style=flat-square" />
  <img src="https://img.shields.io/badge/ComfyUI-API-blue?style=flat-square" />
  <img src="https://img.shields.io/badge/LLM-Qwen%20%7C%20Wan2.2-purple?style=flat-square" />
</p>

---

## 📌 项目简介

**KT-AI-Studio** 是一套基于 **ComfyUI + 大语言模型（LLM）** 的自动化生成工具，  
用于批量生成 **漫画、漫剧分镜、图像或视频内容**。

你可以把它理解为：

> **一个由 LLM 负责任务规划与提示词生成，  
> 由 ComfyUI 负责高质量本地生成的自动化工作室。**

项目的目标不是「一键出神作」，  
而是 **自动化重复劳动，让创作者把精力集中在创意本身**。

---

## 🧠 整体架构 & 工作流程

<p align="center">
  <img src="docs/images/architecture.png" alt="KT-AI-Studio Architecture" width="100%" />
</p>

## ✨ 界面演示

<div align="center">
  <table>
    <tr>
      <td align="center"><img src="docs/images/1.png" alt="首页" width="400"/> <br/> 首页 Dashboard</td>
      <td align="center"><img src="docs/images/2.png" alt="项目列表" width="400"/> <br/> 项目列表</td>
    </tr>
    <tr>
      <td align="center"><img src="docs/images/3.png" alt="项目详情" width="400"/> <br/> 项目详情 & 一键生成</td>
      <td align="center"><img src="docs/images/4.png" alt="人物管理" width="400"/> <br/> 人物管理 & 生成</td>
    </tr>
    <tr>
      <td align="center"><img src="docs/images/5.png" alt="场景管理" width="400"/> <br/> 场景管理 & 生成</td>
      <td align="center"><img src="docs/images/6.png" alt="视频生成" width="400"/> <br/> 视频生成</td>
    </tr>
    <tr>
      <td align="center"><img src="docs/images/7.png" alt="系统日志" width="400"/> <br/> 系统日志监控</td>
      <td align="center"><img src="docs/images/8.png" alt="系统设置" width="400"/> <br/> 系统设置</td>
    </tr>
  </table>
</div>

**核心流程：**

1. 使用内置的结构化 Prompt 模板
2. 向 LLM 请求人物与场景信息
3. 生成人物 / 场景基础素材
4. 再次向 LLM 请求适配 ComfyUI 的最终提示词
5. 通过 ComfyUI API 自动执行工作流
6. 输出图像或视频结果

👉 **全流程自动化，无需人工反复干预**

---

## 🚀 核心特点

### ✅ 支持本地运行，但推荐 LLM 走 API

项目支持 **完全本地运行**，  
但不推荐将 **LLM 与 ComfyUI 同时运行在同一张显卡上**：

- 本地 LLM 会占用大量显存
- 极易导致 ComfyUI 在生成阶段显存溢出

**推荐实践方式：**

| 模块 | 推荐方式 |
|----|----|
| LLM 推理 | API（ChatGPT / DeepSeek 等） |
| 图像 / 视频生成 | 本地 ComfyUI |
| 显存压力 | 可控 |
| 稳定性 | 高 |

---

### 🎭 无需训练 LoRA，也能实现一致性

在不训练 LoRA 的前提下，实现：

- 人物一致性  
- 场景一致性  
- 风格一致性  
- 提示词自动扩写与结构化约束  

---

### 🧩 对 ComfyUI 高度友好

项目 **不绑定任何固定模型或工作流**。

你可以自由使用：

- 自己的模型  
- 自己的 LoRA  
- 自己的 ComfyUI Workflow  

**只需保证以下节点 ID 与项目模板一致即可：**

- 正向提示词（Positive Prompt）
- 负向提示词（Negative Prompt）
- Seed
- Width / Height
- Length（视频时长）

无需修改代码，即可直接接入使用。

---

## �️ 快速上手

### 1. 环境准备与代码克隆
请将 ComfyUI 与本项目分别克隆到两个独立的目录中，避免文件混淆。

```bash
# 克隆 ComfyUI (如果您还没有)
git clone https://github.com/Comfy-Org/ComfyUI.git

# 克隆 KT-AI-Studio
git clone https://github.com/oskey/kt-ai-Studio.git
```

### 2. ComfyUI 初始化与启动
如果您是全新安装 ComfyUI，可以使用本项目提供的辅助脚本进行快速配置：

1.  复制 `docs/comfyui_sh/` 目录下的脚本到您的 `ComfyUI` 根目录。
2.  运行 install_flash_attention_uv.ps1 脚本进行依赖安装及环境初始化。

> **提示**：确保您的 Python 环境版本 >= 3.10。

### 3. 开启 ComfyUI API
本项目依赖 ComfyUI 的 API 接口进行通信。
您可以使用 `docs/comfyui_sh/Start-ComfyUI.ps1` 脚本来启动 ComfyUI。

### 4. 下载模型
请根据您的工作流需求，下载对应的 Checkpoint / LoRA / VAE 模型，并放置在 `ComfyUI/models/` 对应的子目录中。
具体模型列表请参考下方的 [📦 使用到的模型说明](#-使用到的模型说明非常重要)。

### 5. 安装本项目依赖
进入 `KT-AI-Studio` 目录，安装 Python 依赖：

```bash
cd kt-ai-Studio
pip install -r requirements.txt
```

### 6. 启动 KT-AI-Studio
在 `KT-AI-Studio` 根目录下运行以下命令启动服务：

```bash
# Windows / Linux / macOS
cd kt_ai_studio
python -m app.main
```

启动成功后，请使用浏览器访问：[http://127.0.0.1:8000](http://127.0.0.1:8000)

### 7. 系统配置
首次进入系统后，请前往 **系统设置 (System Settings)** 页面：

1.  **LLM 引擎配置**：
    *   本项目默认支持 OpenAI 格式接口。
    *   您可以配置 **本地 LLM** (如 Ollama / LM Studio) 或 **远程 LLM** (如 DeepSeek / ChatGPT)。
    *   *注意：开发测试环境使用的是 OpenAI 接口。*
2.  **ComfyUI 地址配置**：
    *   确保填写的 ComfyUI 地址 (如 `http://127.0.0.1:8188`) 正确且可访问。

---

## 📦 使用到的模型说明（非常重要）

### 🟣 Qwen 系列模型

```text
qwen_image_edit_2509_fp8_e4m3fn.safetensors
Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors
Qwen-Edit-2509-Multiple-angles.safetensors
qwen_2.5_vl_7b_fp8_scaled.safetensors
qwen_image_vae.safetensors
```

### 🔵 Wan 2.2 系列模型

```text
umt5_xxl_fp8_e4m3fn_scaled.safetensors
wan_2.1_vae.safetensors
wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors
wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors
wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors
wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors
```