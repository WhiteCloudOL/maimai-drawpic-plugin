<div align="center">

# 🎨 麦麦绘图

让 MaiBot 拥有强大的图片创建与编辑能力，支持 OpenAI 和 Google 平台的图片生成模型。

![Python Version](https://img.shields.io/badge/Python-3.10+-blue.svg)
![MaiBot 1.0+](https://img.shields.io/badge/MaiBot-1.0.0+-success.svg)
![License](https://img.shields.io/badge/License-AGPL%203.0-lightgrey.svg)

</div>

## 🌟 功能特性

- 🖼️ **文生图与图生图**：支持直接根据提示词生成图片，或基于历史消息的图片进行编辑。
- 🔄 **多平台支持**：内置支持 OpenAI 标准格式、OpenAI Chat Completion兼容以及 Google Gemini 的图片生成 API。
- 🧠 **会话隔离**：允许不同群聊/私聊使用独立的模型偏好。
- ⚡ **后台任务执行**：绘图过程不阻塞主聊天流，图片生成完成后自动下发。
- 🤖 **工具调用支持**：除命令外，大语言模型也可通过 Tool Calling 自动调用绘图和修图能力。

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
enabled = true
config_version = "2.2.0"

[general]
# 默认使用的模型名称
default_model = "gpt-image-2"
# OpenAI 兼容模式: 可选 "chat_completions" 或 "images_api"
default_openai_compatibility_mode = "chat_completions"
# 请求超时时间 (秒)
request_timeout_seconds = 280

[openai]
# 你的 OpenAI 格式中转或官方 API 地址
base_url = "https://api.openai.com/v1"
# OpenAI 接口所支持的模型列表
models = [
    "gpt-image-2",
    "dall-e-3"
]
# 你的 API Key
api_key = "your-openai-api-key"

[google]
# Google 接口地址 (留空使用默认官方地址)
base_url = "https://generativelanguage.googleapis.com"
# Google Gemini 图片生成模型
models = [
    "gemini-3.1-flash-image-preview",
    "gemini-3-pro-image-preview"
]
api_key = "your-google-api-key"
```

## 💬 命令使用说明

用户可以通过 `/绘图` 命令来快速生成图片或调整当前会话的偏好设置：

| 命令 | 说明 |
| :--- | :--- |
| `/绘图 <提示词>` | 开始根据提示词生成图片并在后台处理 |
| `/绘图 帮助` | 查看详细的绘图帮助信息 |
| `/绘图 状态` | 查看当前会话正在使用的模型与兼容模式 |
| `/绘图 模型 <模型名>` | 将当前会话切换到指定的绘图模型 (例如 `/绘图 模型 dall-e-3`) |
| `/绘图 兼容模式 <模式>` | 切换 OpenAI 格式的调用模式 (`images_api` 或 `chat_completions`) |

**💡 提示：** 麦麦具备工具调用能力，当麦麦判定你需要生成或者修改图片时，会自动在后台使用工具，无需每次手动输入命令！

## 📜 许可证

本项目遵循 [AGPL-3.0 许可证](LICENSE) 开源。
