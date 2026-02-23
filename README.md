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
  <img src="https://img.shields.io/github/stars/yourname/kt_ai_studio?style=flat-square" />
  <img src="https://img.shields.io/github/license/yourname/kt_ai_studio?style=flat-square" />
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

项目的核心目标不是「一键出神作」，  
而是 **自动化重复劳动，让创作者把精力集中在创意本身**。

---

## 🧠 整体架构 & 工作流程

<p align="center">
  <img src="docs/images/architecture.png" alt="KT-AI-Studio Architecture" width="100%" />
</p>

**核心流程：**

1. 使用内置结构化 Prompt 模板
2. 向 LLM 请求：
   - 人物设定
   - 场景设定
3. 生成人物 / 场景基础素材
4. 再次向 LLM 请求：
   - 适配 ComfyUI 的最终正向 / 负向提示词
5. 通过 ComfyUI API 自动执行工作流
6. 输出图像或视频结果

👉 **全流程自动化，无需人工反复干预**

---

## 🚀 核心特点

### ✅ 支持本地运行，但推荐 LLM 走 API

项目支持 **完全本地运行**，  
但不推荐将 **LLM 与 ComfyUI 同时运行在同一张显卡上**：

- 本地 LLM 会占用大量显存
- 极易导致 ComfyUI 生成阶段显存溢出

**推荐的稳定实践方式：**

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
- 提示词自动扩写与约束

---

### 🧩 对 ComfyUI 高度友好

项目 **不绑定任何固定模型或工作流**。

你可以自由使用：
- 自己的模型
- 自己的 LoRA
- 自己的 ComfyUI Workflow

**只需保证以下节点 ID 与模板一致即可：**

- 正向提示词（Positive Prompt）
- 负向提示词（Negative Prompt）
- Seed
- Width / Height
- Length（视频时长）

无需修改代码，即可直接接入。

---

## 📦 使用到的模型说明（重要）

### 🟣 Qwen 系列模型

主要用于：
- 图像编辑
- 多视角生成
- 多模态理解
- 提示词生成与解析

**所需模型文件：**

```text
qwen_image_edit_2509_fp8_e4m3fn.safetensors
Qwen-Image-Edit-2509-Lightning-4steps-V1.0-bf16.safetensors
Qwen-Edit-2509-Multiple-angles.safetensors
qwen_2.5_vl_7b_fp8_scaled.safetensors
qwen_image_vae.safetensors