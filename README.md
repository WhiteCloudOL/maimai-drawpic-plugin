<div align="center">

# 🎨 麦麦绘图

让 MaiBot 拥有强大的图片创建与编辑能力，支持 OpenAI、Google、智谱和阿里百炼平台的图片生成模型。

![Python Version](https://img.shields.io/badge/Python-3.10+-blue.svg)
![MaiBot Version](https://img.shields.io/badge/MaiBot-1.0.0+-success.svg)
![SDK Version](https://img.shields.io/badge/maibot--sdk-2.x-blueviolet.svg)
![Plugin Version](https://img.shields.io/badge/Plugin-1.4.1-informational.svg)
![License](https://img.shields.io/badge/License-AGPL%203.0-lightgrey.svg)

</div>

## 🌟 功能特性

- 🖼️ **文生图与图生图**：支持直接根据提示词生成图片，或基于历史消息的图片进行编辑。
- 🔄 **多平台支持**：支持 OpenAI 标准 Images API、OpenAI Chat Completion 兼容、NovelAI 兼容接口、Google Gemini 图片生成 API、智谱图片生成 API，以及阿里百炼图片生成 / 编辑 API。
- 🧠 **会话隔离**：不同群聊 / 私聊可以使用独立的模型与兼容模式偏好，并在重启后持久化。
- ⚡ **后台任务执行**：绘图过程不阻塞主聊天流，图片生成完成后自动下发，并提供任务状态查询工具。
- 🤖 **工具调用支持**：除命令外，大语言模型也可通过 Tool Calling 自动调用 `draw`、`edit_image`、`draw_status` 能力。
- 🛡️ **双重审核能力**：可选启用提示词审核与生成结果图片审核，分别复用 MaiBot 当前配置的 `replyer` 与 `vlm` 模型。
- ♻️ **配置热更新**：订阅 `bot` / `model` 配置重载事件，调整主体配置后插件会自动刷新内部服务，无需重启。

> 💌 **遇到问题？有新想法？**  
> 如果你在使用中遇到问题、想到新功能、或希望优化文档与代码，欢迎在仓库发起 **Issue** 或 **Pull Request**，一起把插件做得更好。  
> ☁️另外欢迎加入我们的QQ群：637174573
 
## 📦 安装指南

请将插件安装到 MaiBot 的 `plugins` 目录下，步骤如下：

1. 进入 MaiBot 的插件目录：
   ```bash
   cd plugins
   ```
   *(注：完整路径通常为 `MaiBot/plugins`)*

2. 使用 Git 克隆本仓库：
   ```bash
   git clone https://github.com/WhiteCloudOL/maimai-drawpic-plugin
   ```

3. 安装插件依赖（在 MaiBot 主项目环境下执行）：
   ```bash
   pip install -r plugins/maimai-drawpic-plugin/requirements.txt
   ```
   若使用 `uv`，可执行 `uv pip install -r plugins/maimai-drawpic-plugin/requirements.txt`。

4. 重启 MaiBot 即可生效。首次加载会在插件目录下生成默认 `config.toml`。

> 📌 **运行依赖：** `aiohttp`、`pillow`、`google-genai`。`google-genai` 仅在使用 Google Gemini 图片接口时必须。

## ⚙️ 基础配置

插件首次加载时会使用默认配置文件 `config.toml`。你可以根据需要修改里面的参数来配置你的 API 信息：

```toml
[plugin]
# 是否启用插件
enabled = true
# 配置版本（请勿随意修改，由插件用于升级迁移）
config_version = "2.5.0"

[general]
# 默认使用的模型名称，插件会自动在阿里百炼、OpenAI、Google 与智谱的模型列表中查找
default_model = "gpt-image-2"
# 默认 OpenAI 兼容模式：auto / images_api / chat_completions / novelai_images_api
# 通常建议保持 auto，由插件自动选择合适的接口
default_openai_compatibility_mode = "auto"
# 单次图片请求的超时时间（秒），建议 120 ~ 300；插件会将其限制在 5 ~ 600 之间
request_timeout_seconds = 150

[prompt_review]
# 是否启用提示词审核（调用 MaiBot 当前配置的 replyer 模型）
enabled = false
# 审核提示词，支持 {user_prompt} 占位符
review_prompt = """
你是绘图提示词审核器。请判断下面的绘图提示词是否适合继续交给绘图模型生成。
你的回复必须严格使用以下格式，不要输出多余内容：
结论：PASS 或 REJECT
原因：一句简短中文说明

待审核提示词：
{user_prompt}
"""

[image_review]
# 是否启用生成图片审核（调用 MaiBot 当前配置的 vlm 模型）
enabled = false
# 审核提示词，支持 {user_prompt} 占位符
review_prompt = """
你是绘图结果审核器。请审核这张图片是否适合直接发送给普通聊天场景。
你的回复必须严格使用以下格式，不要输出多余内容：
结论：PASS 或 REJECT
原因：一句简短中文说明

本次生成提示词：
{user_prompt}
"""

[openai]
# OpenAI 或 OpenAI 兼容服务的基础 URL（填根地址，不要带 /v1）
base_url = "https://api.openai.com"
# 你的 API 密钥
api_key = "your-openai-api-key"
# 走 OpenAI 兼容接口的图片模型列表（可按需增删）
models = [
    "gpt-image-2",
]

[google]
# Google Gemini 或兼容网关的基础 URL
base_url = "https://generativelanguage.googleapis.com"
# 你的 API 密钥
api_key = "your-google-api-key"
# 走 Google Gemini 接口的图片模型列表（可按需增删）
models = [
    "gemini-3.1-flash-image-preview",
]

[zhipu]
# 智谱基础 URL（填根地址，不要带具体接口路径）
base_url = "https://open.bigmodel.cn"
# 你的 API 密钥
api_key = "your-zhipu-api-key"
# 走智谱图像生成接口的模型列表（当前仅支持文生图）
models = [
    "glm-image",
]

[aliyun]
# 阿里百炼基础 URL（填根地址，不要带具体接口路径）
base_url = "https://dashscope.aliyuncs.com"
# 你的 API 密钥
api_key = "your-aliyun-api-key"
# 走阿里百炼图片接口的模型列表（支持文生图与图像编辑）
models = [
    "qwen-image-2.0",
]
```

### 🔧 主要配置项说明

| 配置段 | 字段 | 含义 |
| :--- | :--- | :--- |
| `[plugin]` | `enabled` | 是否启用插件 |
| `[plugin]` | `config_version` | 配置版本号，用于插件自身的配置迁移，请勿随意修改 |
| `[general]` | `default_model` | 默认模型名，插件会在阿里百炼、OpenAI、Google 与智谱的模型列表中查找归属 |
| `[aliyun]` | `base_url` / `api_key` / `models` | 阿里百炼图片接口的基础 URL、密钥与模型列表（支持文生图与图像编辑） |
| `[general]` | `default_openai_compatibility_mode` | 默认 OpenAI 兼容模式，支持 `auto` / `images_api` / `chat_completions` / `novelai_images_api` |
| `[general]` | `request_timeout_seconds` | 单次图片请求超时时间（秒），取值会被夹紧到 `[5, 600]` 区间 |
| `[openai]` | `base_url` / `api_key` / `models` | OpenAI 或 OpenAI 兼容服务的基础 URL、密钥与模型列表 |
| `[google]` | `base_url` / `api_key` / `models` | Google Gemini 或兼容网关的基础 URL、密钥与模型列表 |
| `[zhipu]` | `base_url` / `api_key` / `models` | 智谱图像生成接口的基础 URL、密钥与模型列表（当前仅支持文生图） |
| `[prompt_review]` | `enabled` / `review_prompt` | 是否启用提示词审核以及审核提示模板（支持 `{user_prompt}` 占位符） |
| `[image_review]` | `enabled` / `review_prompt` | 是否启用生成图片审核以及审核提示模板（支持 `{user_prompt}` 占位符） |

> 💡 **模型归属：** 模型是否走阿里百炼、OpenAI、Google 或智谱接口，取决于它出现在哪一侧的 `models` 列表里。同名模型不要同时出现在多侧。

### 🛡️ 审核配置说明

- `prompt_review.enabled`：开启后，`draw` / `edit_image` / `/绘图` 的提示词会先交给 MaiBot 的 `replyer` 模型审核。
- `image_review.enabled`：开启后，图片生成完成后会逐张交给 MaiBot 的 `vlm` 模型审核，只有通过的图片才会发送。
- `review_prompt`：审核提示模板，支持使用 `{user_prompt}` 注入本次绘图提示词。

> ⚠️ **注意：** 启用审核前，请确认 MaiBot 主体已经在 `model_config.toml` 中配置好可用的 `replyer` 与 `vlm` 任务模型。

### 🔌 OpenAI 兼容模式说明

`default_openai_compatibility_mode` 以及 `/绘图 兼容模式 <模式>` 支持下列取值：

| 模式 | 说明 |
| :--- | :--- |
| `auto` | 由插件根据模型与上游接口能力自动选择，推荐默认使用 |
| `images_api` | 使用 OpenAI 标准的 `/v1/images/generations` 与 `/v1/images/edits` 接口 |
| `chat_completions` | 使用 OpenAI 的 Chat Completion 接口返回图片（部分中转/自部署网关会这样实现） |
| `novelai_images_api` | 适配 NovelAI 风格的图片生成接口 |

> 📝 **提示：** 当使用阿里百炼、Google 或智谱模型时，`openai_compatibility_mode` 不会生效；插件会自动走对应平台的图片生成 API。
>
> ⚠️ **限制：** 智谱模型当前只接入了文生图接口，不能用于 `edit_image` 图生图编辑。

### 💾 会话偏好持久化

插件会把每个会话手动选择的模型与兼容模式保存到插件目录下的 `data/session_preferences.json`，即使重启 MaiBot 也会保留原有设置。新会话默认不锁定模型，会跟随当前默认模型；只有执行过 `/绘图 模型 模型名` 后，才会固定该会话的模型。当模型列表在配置里被移除时，已失效的模型偏好会在加载时清空并重新跟随默认模型。

旧版本生成在插件根目录下的 `session_preferences.json` 与 `draw_tasks.json` 会在插件启动时自动迁移到 `data/` 目录；如果 `data/` 中已经存在同名文件，则不会覆盖已有数据。

### ♻️ 配置热更新

插件订阅了 MaiBot 的 `bot` 与 `model` 配置重载事件。修改主体配置（例如切换 `replyer` / `vlm` 模型）后，插件会自动刷新内部服务，并保持现有的会话偏好不丢失。

## 💬 命令使用说明

用户可以通过 `/绘图` 命令来快速生成图片或调整当前会话的偏好设置：

| 命令 | 说明 |
| :--- | :--- |
| `/绘图 <提示词>` | 根据提示词在后台生成图片，生成完成后自动发送 |
| `/绘图 帮助` | 查看详细的绘图帮助信息以及当前可用模型（无参数时等价于 `帮助`） |
| `/绘图 状态` | 查看当前会话正在使用的模型、提供商与兼容模式 |
| `/绘图 模型 <模型名>` | 将当前会话切换到指定的绘图模型（例如 `/绘图 模型 gpt-image-2`） |
| `/绘图 兼容模式 <模式>` | 切换 OpenAI 兼容调用模式，可选 `auto` / `images_api` / `chat_completions` / `novelai_images_api` |

**💡 提示：** 麦麦具备工具调用能力，当麦麦判定你需要生成或者修改图片时，会自动在后台使用 `draw` 或 `edit_image` 工具，无需每次手动输入命令。

工具调用启动后台任务后，插件只把任务提交信息写入日志，聊天中的开始提示由 MaiBot 的 LLM 根据上下文自行组织；图片生成或编辑完成后仍会自动发送到当前聊天流。

## 🛠️ 工具调用能力

插件向大语言模型暴露了以下三个工具：

| 工具名 | 作用 |
| :--- | :--- |
| `draw` | 根据提示词生成新图片，结果以异步后台任务形式回传到当前聊天流 |
| `edit_image` | 编辑当前聊天中的最近一张图片，或编辑指定 `source_message_id` / `source_image_base64` 对应的图片（智谱模型暂不支持，阿里百炼支持） |
| `draw_status` | 查询当前会话最近一个绘图后台任务，或按 `task_id` 查询指定任务的状态 |

共通可选参数：

- `model`：本次调用使用的模型名。不填则优先使用当前会话锁定模型；会话未锁定时跟随插件默认模型。
- `user_id` / `group_id` / `platform`：用于在回传图片时定位真实聊天流，默认 `platform = qq`。

## 📁 目录结构一览

```
plugins/maimai-drawpic-plugin/
├── _manifest.json          # 插件元数据（MaiBot 1.0+，maibot-sdk 2.x）
├── plugin.py               # 插件入口，定义命令与工具
├── requirements.txt        # 依赖：aiohttp、pillow、google-genai
├── config.toml             # 首次加载自动生成的运行配置（本地生成）
├── data/                   # 插件运行时数据（本地生成）
│   ├── session_preferences.json # 会话级模型/兼容模式偏好
│   └── draw_tasks.json     # 后台任务状态缓存
├── core/
│   ├── config.py           # 配置模型定义
│   ├── draw_service.py     # 文生图 / 图生图后台任务调度
│   ├── message_utils.py    # 查找源图片等聊天消息工具
│   ├── moderation.py       # 提示词与图片审核服务
│   ├── provider_router.py  # 模型归属判断与 Provider 创建
│   ├── session_preferences.py # 会话偏好加载与持久化
│   ├── stream_service.py   # 聊天流相关辅助
│   ├── task_store.py       # 后台任务登记与查询
│   └── texts.py            # 命令帮助 / 状态文本
└── providers/
    ├── aliyun_platform.py  # 阿里百炼图片接口调用
    ├── openai_platform.py  # OpenAI 兼容图片接口调用
    ├── google_platform.py  # Google Gemini 图片接口调用
    └── zhipu_platform.py   # 智谱图片生成接口调用
```

## 📜 许可证

本项目遵循 [AGPL-3.0 许可证](LICENSE) 开源。
