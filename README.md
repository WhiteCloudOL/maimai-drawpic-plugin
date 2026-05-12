<div align="center">

# 🎨 麦麦绘图

让 MaiBot 拥有强大的图片创建与编辑能力，支持 OpenAI 和 Google 平台的图片生成模型。

![Python Version](https://img.shields.io/badge/Python-3.10+-blue.svg)
![MaiBot 1.0+](https://img.shields.io/badge/MaiBot-1.0.0+-success.svg)
![License](https://img.shields.io/badge/License-AGPL%203.0-lightgrey.svg)

</div>

## 🌟 功能特性

- 🖼️ **文生图与图生图**：支持直接根据提示词生成图片，或基于历史消息的图片进行编辑。
- 🔄 **多平台支持**：内置支持 OpenAI 标准 `images` API、OpenAI Chat Completion 兼容、NovelAI 兼容接口，以及 Google Gemini 的图片生成 API。
- 🧠 **会话隔离**：不同群聊 / 私聊可以使用独立的模型与兼容模式偏好，并在重启后持久化。
- ⚡ **后台任务执行**：绘图过程不阻塞主聊天流，图片生成完成后自动下发。
- 🤖 **工具调用支持**：除命令外，大语言模型也可通过 Tool Calling 自动调用 `draw` 与 `edit_image` 能力。

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

3. 重启 MaiBot 即可生效。

## ⚙️ 基础配置

插件首次加载时会使用默认配置文件 `config.toml`。你可以根据需要修改里面的参数来配置你的 API 信息：

```toml
[plugin]
# 是否启用插件
enabled = true
# 配置版本（请勿随意修改）
config_version = "2.2.0"

[general]
# 默认使用的模型名称，插件会自动在 OpenAI 与 Google 的模型列表中查找
default_model = "gpt-image-2"
# 默认 OpenAI 兼容模式：auto / images_api / chat_completions / novelai_images_api
# 通常建议保持 auto，由插件自动选择合适的接口
default_openai_compatibility_mode = "auto"
# 单次图片请求的超时时间（秒），建议 120 ~ 300
request_timeout_seconds = 150

[openai]
# OpenAI 或 OpenAI 兼容服务的基础 URL（填根地址，不要带 /v1）
base_url = "https://api.openai.com"
# 你的 API 密钥
api_key = "your-openai-api-key"
# 走 OpenAI 兼容接口的图片模型列表
models = [
    "gpt-image-2",
    "dall-e-3",
]

[google]
# Google Gemini 或兼容网关的基础 URL
base_url = "https://generativelanguage.googleapis.com"
# 你的 API 密钥
api_key = "your-google-api-key"
# 走 Google Gemini 接口的图片模型列表
models = [
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview",
]
```

### 🔌 OpenAI 兼容模式说明

`default_openai_compatibility_mode` 以及 `/绘图 兼容模式 <模式>` 支持下列取值：

| 模式 | 说明 |
| :--- | :--- |
| `auto` | 由插件根据模型与上游接口能力自动选择，推荐默认使用 |
| `images_api` | 使用 OpenAI 标准的 `/v1/images/generations` 与 `/v1/images/edits` 接口 |
| `chat_completions` | 使用 OpenAI 的 Chat Completion 接口返回图片（部分中转/自部署网关会这样实现） |
| `novelai_images_api` | 适配 NovelAI 风格的图片生成接口 |

> 📝 **提示：** 当使用 Google 模型时，`openai_compatibility_mode` 不会生效；插件会自动走 Google Gemini 的图片生成 API。

### 💾 会话偏好持久化

插件会把每个会话选择的模型与兼容模式保存到插件目录下的 `session_preferences.json`，即使重启 MaiBot 也会保留原有设置。

## 💬 命令使用说明

用户可以通过 `/绘图` 命令来快速生成图片或调整当前会话的偏好设置：

| 命令 | 说明 |
| :--- | :--- |
| `/绘图 <提示词>` | 根据提示词在后台生成图片，生成完成后自动发送 |
| `/绘图 帮助` | 查看详细的绘图帮助信息以及当前可用模型 |
| `/绘图 状态` | 查看当前会话正在使用的模型、提供商与兼容模式 |
| `/绘图 模型 <模型名>` | 将当前会话切换到指定的绘图模型（例如 `/绘图 模型 dall-e-3`） |
| `/绘图 兼容模式 <模式>` | 切换 OpenAI 兼容调用模式，可选 `auto` / `images_api` / `chat_completions` / `novelai_images_api` |

**💡 提示：** 麦麦具备工具调用能力，当麦麦判定你需要生成或者修改图片时，会自动在后台使用 `draw` 或 `edit_image` 工具，无需每次手动输入命令！

## 🛠️ 工具调用能力

插件向大语言模型暴露了以下两个工具：

- `draw`：根据提示词生成新图片。
- `edit_image`：编辑当前聊天中的最近一张图片，或编辑指定消息中的图片。

两个工具都会将结果以异步后台任务的形式回传到当前聊天流。

## 📜 许可证

本项目遵循 [AGPL-3.0 许可证](LICENSE) 开源。
