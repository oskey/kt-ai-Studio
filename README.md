# KT AI Studio - 项目文档

## 1. 项目概述 (Overview)

**KT AI Studio** 是一个专为 AI 辅助影视创作设计的 Web 应用程序。它旨在通过整合 LLM (大语言模型) 和 ComfyUI (Stable Diffusion 工作流)，实现从“自然语言描述”到“高质量分镜/角色资产”的自动化工作流。

**核心目标：**
*   **一致性 (Consistency):** 确保角色在不同镜头中的形象一致，场景风格在整个项目中统一。
*   **自动化 (Automation):** 自动生成提示词、反向提示词，并自动调度 ComfyUI 进行图像生成。
*   **资产管理 (Asset Management):** 集中管理项目、角色、场景及生成的图片资产。

---

## 2. 功能特性 (Features)

### 2.1 项目管理 (Project Management)
*   **创建与编辑:** 用户可以创建多个独立的项目，每个项目拥有独立的资产库。
*   **画风锁定 (Style Locking):**
    *   创建项目时必须选择一个 **Style Preset (画风预设)**。
    *   一旦选定，该项目下的所有角色和场景生成任务都会强制注入该画风的正向/反向提示词，以及 LLM 风格守卫 (Style Guard)，确保全项目视觉风格统一。
*   **项目代号:** 每个项目有一个唯一的代号 (Project Code)，用于生成文件系统的目录结构。

### 2.2 角色管理 (Character Management)
*   **角色创建:** 输入姓名、性别、外貌备注。
*   **AI 提示词生成 (GEN_PROMPT):**
    *   系统调用 LLM (DeepSeek/OpenAI)，根据角色备注和项目画风，自动扩写出结构化的 `prompt_pos` (人物外观、体型、服装、画质) 和 `prompt_neg`。
    *   **清洗逻辑:** 自动去除 LLM 输出中的“适合合成”、“图生视频”等无关废话，确保提示词纯净。
*   **角色基图生成 (GEN_BASE):**
    *   调用 ComfyUI (`wf_base_character.json`) 生成角色的全身立绘基图。
    *   支持进度实时回显。
*   **多视角生成 (GEN_8VIEWS):**
    *   基于角色基图，调用 ComfyUI (`wf_8views.json`) 生成 8 个标准视角 (正/背/侧/俯/仰等)。
    *   **增量更新:** 每生成一张图，前端即时刷新显示，无需等待全部完成。
*   **图片预览:** 支持缩略图点击放大预览。

### 2.3 场景管理 (Scene Management)
*   **场景创建:** 支持分集分镜 (Episode/Shot) 管理，支持绑定多个关联角色。
*   **AI 场景提示词生成 (GEN_SCENE_PROMPT):**
    *   类似于角色，LLM 会根据基础描述扩写场景结构、光影、材质。
    *   **强制约束:** 自动注入“无人物、无文字、纯背景”等负面约束，防止场景图中出现乱入的角色。
*   **场景基图生成 (GEN_SCENE_BASE):**
    *   调用 ComfyUI 生成纯净的场景底图，可作为后续合成的背景。
*   **多选交互:** 采用现代化的 iOS/App 风格多选组件 (Unified MultiSelect)，支持搜索、标签显示、性别图标区分。

### 2.4 任务系统 (Task System)
*   **异步队列:** 所有耗时操作 (LLM 请求、ComfyUI 生成) 均封装为异步任务。
*   **任务类型:**
    *   `GEN_PROMPT`: 生成角色提示词
    *   `GEN_BASE`: 生成角色基图
    *   `GEN_8VIEWS`: 生成角色多视角
    *   `GEN_SCENE_PROMPT`: 生成场景提示词
    *   `GEN_SCENE_BASE`: 生成场景基图
*   **状态追踪:** 实时追踪任务状态 (queued, running, done, failed)、进度 (0-100%)、耗时及错误日志。
*   **中断控制:** 支持手动中断正在运行的 ComfyUI 任务。

### 2.5 画风预设 (Style Presets)
*   **管理:** 支持增删改查画风预设。
*   **参数:** 包含 Style Positive (正向词)、Style Negative (反向词)、Engine Hint (模型提示)、LLM Style Guard (给 LLM 的自然语言约束)。

---

## 3. 技术架构 (Technical Architecture)

### 3.1 后端 (Backend)
*   **框架:** **FastAPI** (Python 3.10+) - 高性能异步 Web 框架。
*   **数据库:** **SQLite** (通过 **SQLAlchemy** ORM) - 轻量级关系型数据库，易于部署。
*   **任务队列:** 自研 `TaskManager` (基于 `threading` 和数据库轮询) - 简单可靠的后台任务调度，无需额外的 Redis/Celery 依赖。
*   **通信:**
    *   **HTTP:** 前后端数据交互。
    *   **WebSocket:** 与 ComfyUI 实时通信，获取生成进度和节点执行状态。
*   **LLM 集成:** 支持 OpenAI 接口格式 (兼容 DeepSeek, ChatGPT 等)。

### 3.2 前端 (Frontend)
*   **模板引擎:** **Jinja2** (服务端渲染)。
*   **UI 框架:** **Bootstrap 5** - 响应式布局，现代化组件。
*   **交互:** 原生 JavaScript (Vanilla JS) + AJAX 轮询 (用于任务状态更新)。
*   **风格:** 定制化的 CSS，追求类似 iOS/Mobile App 的现代化视觉体验 (圆角、阴影、标签式输入)。

### 3.3 图像生成 (Image Generation)
*   **引擎:** **ComfyUI** (外部服务)。
*   **工作流:** JSON 格式的 ComfyUI Workflow (`workflows/` 目录下)。
*   **文件交互:**
    *   上传: 将基图上传至 ComfyUI。
    *   下载: 生成完成后，自动将图片下载到本地 `output/` 目录，并按项目结构归档。

---

## 4. 数据库结构 (Database Schema)

### 4.1 `kt_ai_project` (项目表)
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | Integer | 主键 |
| `name` | String | 项目名称 |
| `project_code` | String | 项目代号 (唯一，用于文件路径) |
| `style_id` | Integer | 外键 -> `kt_ai_style_preset` (画风锁定) |
| `mark` | Text | 备注 |
| `created_at` | DateTime | 创建时间 |

### 4.2 `kt_ai_player` (角色表)
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | Integer | 主键 |
| `project_id` | Integer | 外键 -> `kt_ai_project` |
| `player_name` | String | 角色姓名 |
| `player_sex` | String | 性别 (male/female/other) |
| `player_mark` | Text | 外貌备注 (用户输入) |
| `player_desc` | Text | LLM 生成的纯净描述 |
| `prompt_pos` | Text | 正向提示词 (结构化) |
| `prompt_neg` | Text | 反向提示词 |
| `base_image_path` | Text | 基图路径 (相对路径) |
| `views_json` | Text | 多视角图片路径 (JSON) |
| `status` | String | 状态 (draft/ready/done) |

### 4.3 `kt_ai_scene` (场景表)
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | Integer | 主键 |
| `project_id` | Integer | 外键 -> `kt_ai_project` |
| `name` | String | 场景名称 |
| `episode` | Integer | 集数 |
| `shot` | Integer | 镜号 |
| `base_desc` | Text | 基础描述 (用户输入) |
| `scene_desc` | Text | LLM 生成的场景指纹 |
| `prompt_pos` | Text | 正向提示词 |
| `prompt_neg` | Text | 反向提示词 |
| `base_image_path` | Text | 场景基图路径 |
| `status` | String | 状态 |

### 4.4 `kt_ai_task` (任务表)
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | Integer | 主键 |
| `task_type` | String | 任务类型 (GEN_PROMPT, GEN_BASE...) |
| `status` | String | 状态 (queued, running, done, failed) |
| `progress` | Integer | 进度 (0-100) |
| `payload_json` | Text | 任务参数 (JSON) |
| `result_json` | Text | 执行结果 (JSON) |
| `error` | Text | 错误信息 |
| `duration` | Integer | 耗时 (秒) |

### 4.5 `kt_ai_style_preset` (画风预设表)
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `style_id` | Integer | 主键 |
| `name` | String | 画风名称 |
| `style_pos` | Text | 全局正向提示词 |
| `style_neg` | Text | 全局反向提示词 |
| `llm_style_guard` | Text | LLM 风格守卫指令 |

### 4.6 `kt_ai_llm_profile` (LLM 配置表)
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `id` | Integer | 主键 |
| `provider` | String | 服务商 (deepseek/openai) |
| `base_url` | String | API 地址 |
| `api_key` | String | 密钥 |
| `model` | String | 模型名称 |

---

## 5. 关键实现逻辑 (Implementation Details)

### 5.1 提示词清洗与结构化
在 `app/services/llm/openai_provider.py` 中：
*   **Tag 解析:** 使用正则表达式解析 LLM 返回的 `【人物外观】`、`【服装】` 等标签，强制重组为标准顺序。
*   **强制约束注入:** 在 LLM 生成内容之外，代码强制追加 `<style_name>`、`style_pos` 以及核心负面词 (如 "nsfw", "text", "watermark")，确保底线不被突破。
*   **清洗:** `clean_player_desc` 函数会移除 "Name is...", "用途是..." 等冗余文本。

### 5.2 ComfyUI 交互
在 `app/services/comfyui/runner.py` 和 `client.py` 中：
*   **Workflow 加载:** 读取本地 JSON 工作流模板。
*   **动态替换:** 运行时根据 Task 参数，动态替换工作流中的 Seed、Prompt、Image Path 等节点输入 (`set_input` 方法)。
*   **WebSocket 监听:** 连接 ComfyUI 的 WS 接口，监听 `progress` (进度条) 和 `executing` (当前节点) 事件，实时更新数据库中的 Task 状态。
*   **增量下载:** 对于多视角生成，每当一个 `SaveImage` 节点完成，立即通过 API 下载该图片并在前端展示，无需等待整个流结束。

### 5.3 路径管理
*   所有生成文件存储在 `output/` 目录下。
*   结构: `output/{project_code}/{players|scenes}/{id}_{name}/{base|views}/filename.png`
*   数据库存储相对路径 (如 `output/cyber_2077/...`)。
*   前端通过 `to_web_path` 辅助函数将相对路径转换为浏览器可访问的 URL (`/output/...`)。

---

## 6. 部署与运行 (Deployment)

1.  **环境准备:** Python 3.10+, ComfyUI (开启 API 模式)。
2.  **配置:** 复制 `.env.example` 为 `.env`，配置 DB 路径、ComfyUI 地址、OpenAI Key。
3.  **启动:**
    ```bash
    python -m uvicorn app.main:app --reload
    ```
4.  **访问:** 打开浏览器访问 `http://127.0.0.1:8000`。
