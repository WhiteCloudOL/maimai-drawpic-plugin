<div align="center">

<img src="assets/icon.png" alt="麦麦绘图插件图标" width="128" height="128">

# 🎨 麦麦绘图

![Plugin Version](https://img.shields.io/badge/Plugin-1.11.1-informational.svg)
![MaiBot](https://img.shields.io/badge/MaiBot-1.x-blue.svg)
![License](https://img.shields.io/badge/License-AGPL--3.0-green.svg)

为 MaiBot 提供图片生成、图片编辑与多模型管理能力。

[问题反馈](https://github.com/WhiteCloudOL/maimai-drawpic-plugin/issues) · [插件仓库](https://github.com/WhiteCloudOL/maimai-drawpic-plugin)

</div>

## 功能

- 支持文生图与图生图。
- 支持 OpenAI、Google Gemini、智谱、阿里百炼、火山引擎、硅基流动、NovelAI 和 ComfyUI。
- 支持全局首选模型、会话首选模型和生图备选模型。
- 支持多个 OpenAI 兼容接口实例和独立模型映射。
- 支持提示词审核与生成图片审核。
- 支持群聊、私聊独立额度和管理员权限。
- 支持 HTTP/HTTPS 代理与系统代理。
- 支持后台任务和状态查询。
- 支持全平台正向/反向提示词风格模板，以及文生图、图生图自动识别。
- 支持 NovelAI Anime、Furry、Background 会话级 mode、会话画师标签和 NAI 专属指令。
- 绘图失败会由插件直接发送状态，可选附带脱敏后的简要原因，不经过 LLM。

## Issue 反馈

遇到问题或希望增加功能时，请通过 [Issue 表单](https://github.com/WhiteCloudOL/maimai-drawpic-plugin/issues/new/choose) 提交：

- 错误报告：请先更新到最新版本，并提供插件与 MaiBot 版本、运行环境、图片平台、模型、相关参数、复现步骤以及日志或截图。
- 功能请求：请说明使用场景、期望效果和当前替代方式。
- 平台接入请求：请提供平台官网、API 文档、模型信息、鉴权方式和常用参数。
- 文档与使用反馈：请注明相关章节、配置项或命令。

提交日志、截图和配置前，请隐藏 API Key、Token、Cookie 等敏感信息。

另外也可以加入交流QQ群：637174573，建议优先通过issue反馈

## 图片平台

| 平台 | 文生图 | 图生图 | 说明 |
| --- | --- | --- | --- |
| OpenAI 及兼容接口 | ✅ | ✅ | 支持 Images API、Chat Completions 和多实例模型映射 |
| Google Gemini / Imagen | ✅ | ✅ | 支持 Gemini 图片模型与 Imagen 图片模型 |
| 智谱 | ✅ | ❌ | 适合中文提示词的图片生成 |
| 阿里百炼 | ✅ | ✅ | 支持通义万相及 Qwen Image 系列 |
| 火山引擎 | ✅ | ✅ | 支持统一模型以及文生图、图生图模型分组 |
| 硅基流动 | ✅ | ✅ | 支持平台开放的图片模型 |
| NovelAI / NovelAPI | ✅ | ✅ | 支持 V3、V4、V4.5、V5 与兼容网关 |
| ComfyUI | ✅ | ✅ | 使用本地 API 工作流 |

## 安装

### 插件市场

在 MaiBot WebUI 的插件市场中搜索“麦麦绘图”并安装。

### maibot CLI

```bash
maibot plugin install WhiteCloudOL/maimai-drawpic-plugin
```

### 手动安装

```bash
cd plugins
git clone https://github.com/WhiteCloudOL/maimai-drawpic-plugin.git maimai-drawpic
```

安装完成后重启 MaiBot，在插件配置页面填写需要启用的平台密钥与模型。

## 快速配置

以下示例展示常用配置组合，密钥和模型名请替换为实际值。

```toml
[general]
default_model = "doubao-seedream-4-0"
fallback_model = "gpt-image-2"
request_timeout_seconds = 150
admin_user_ids = ["你的管理员用户ID"]
failure_reason_enabled = true

[style]
default_style = "水彩"

[[style.presets]]
enabled = true
name = "水彩"
positive_prompt_template = "watercolor (medium), soft colors, {prompt}"
negative_prompt_template = "oil painting, 3d, {negative_prompt}"

[volcengine]
enabled = true
api_key = "your-volcengine-api-key"
unified_models = ["doubao-seedream-4-0"]
t2i_models = ["doubao-seedream-3-0-t2i"]
i2i_models = ["doubao-seedream-3-0-i2i"]
default_size = "2048*2048"

[openai]
enabled = true
base_url = "https://api.openai.com"
api_key = "your-openai-api-key"
models = ["gpt-image-2"]

[[openai.instances]]
enabled = true
name = "备用接口"
base_url = "https://api.example.com"
api_key = "your-relay-api-key"
models = "relay-image=gpt-image-2"
```

### 通用配置

| 配置项 | 说明 |
| --- | --- |
| `default_model` | 默认首选图片模型 |
| `fallback_model` | 首选模型调用失败时使用的备选模型，留空表示关闭 |
| `request_timeout_seconds` | 单次图片请求超时时间 |
| `command_reply_mode` | 命令回复形式，可选“图片”或“文本” |
| `failure_reason_enabled` | 失败通知是否附带脱敏、截断后的简要原因；失败状态始终直接发送 |
| `permission_enabled` | 模型、OpenAI 兼容模式、NAI mode、NAI 画师标签和额度管理命令的权限开关 |
| `admin_user_ids` | 插件管理员用户 ID 列表 |
| `image_edit_unsupported_models` | 仅支持文生图的模型名单 |
| `prompt_review_enabled` | 提示词审核开关 |
| `image_review_enabled` | 生成图片审核开关 |

### 全平台风格模板

`style` 是独立于图片平台的提示词模板配置，放在 `general` 后面。它适用于 OpenAI、Google、智谱、阿里百炼、火山引擎、硅基流动、NovelAI 和 ComfyUI，不会改变当前会话模型，也不会改变 NovelAI mode。

```toml
[style]
default_style = "赛博朋克"

[[style.presets]]
enabled = true
name = "赛博朋克"
positive_prompt_template = "cyberpunk, neon lights, cinematic lighting, {prompt}"
negative_prompt_template = "flat lighting, low contrast, {negative_prompt}"

[[style.presets]]
enabled = true
name = "水彩"
positive_prompt_template = "watercolor (medium), textured paper, {prompt}"
negative_prompt_template = "3d render, oil painting, {negative_prompt}"
```

- 正向模板中的 `{prompt}` 会替换为用户正向提示词；未写占位符时，用户提示词自动追加在模板后。
- 反向模板中的 `{negative_prompt}` 会替换为用户反向提示词；未写占位符时，用户反向提示词自动追加。
- NovelAI、阿里百炼、Imagen、硅基流动以及正反向节点模式的 ComfyUI 会使用独立反向字段。
- 不支持独立反向提示词的平台会把反向内容以 `Negative prompt:` 合并到单个提示词中。
- `draw_styles` 工具会把配置热重载后的风格名提供给模型；模型应先查询列表，再调用 `styled_draw`。

### 平台配置

| 配置节 | 常用配置 |
| --- | --- |
| `openai` | `base_url`、`api_key`、`models`、`default_size`、`default_openai_compatibility_mode` |
| `openai.instances` | `name`、`base_url`、`api_key`、`models` |
| `google` | `base_url`、`api_key`、`models`、`aspect_ratio` |
| `zhipu` | `api_key`、`models`、`size` |
| `aliyun` | `api_key`、`models`、`default_size` |
| `volcengine` | `api_key`、`unified_models`、`t2i_models`、`i2i_models`、`default_size` |
| `siliconflow` | `api_key`、`models`、`image_size` |
| `novelai` | `base_url`、`api_key`、`models`、`custom_models`、`default_mode`、`default_artist_tags`、`positive_prompt`、`negative_prompt`、`width`、`height` |
| `comfyui` | `base_url`、工作流路径和节点 ID |

NovelAI 官方模型可直接填写以下模型 ID：

- `nai-diffusion-5-full`
- `nai-diffusion-5-curated`
- `nai-diffusion-4-5-full`
- `nai-diffusion-4-5-curated`
- `nai-diffusion-4-full`
- `nai-diffusion-4-curated-preview`
- `nai-diffusion-3`
- `nai-diffusion-furry-3`

V3、V4、V4.5 和 V5 均支持文生图和图生图。插件会按模型自动使用对应提示词格式、质量标签和采样设置；SMEA 仅用于 V3 文生图。使用 NovelAPI 兼容网关时，请以网关提供的模型 ID 和参数说明为准。

NovelAI 配置示例：

```toml
[novelai]
default_mode = "anime" # anime / furry / background
default_artist_tags = "artist:example_name"
positive_prompt = ""
negative_prompt = "lowres, bad anatomy, bad hands, worst quality, watermark"
img2img_strength = 0.6
img2img_noise = 0.1
```

- V4、V4.5、V5 的 Furry mode 会按官方规则把 `fur dataset` 放在提示词最前方。
- V3 的 Furry mode 会在 `nai-diffusion-3` 与 `nai-diffusion-furry-3` 间切换，因此两个模型都应启用。
- Background mode 会添加 `background dataset`，仅适用于 V4.5、V5 及声明兼容的自定义模型。
- `default_artist_tags` 是 NAI 默认画师标签；会话可以用 `/绘图 nai 画师 <标签>` 覆盖，标签会放在数据集 mode 标签之后、普通正向提示词之前。
- 画师标签按原始文本传给 NovelAI，多个标签使用英文逗号分隔；重置为插件默认值可使用 `/绘图 nai 画师 跟随`。
- `positive_prompt` 是 NAI 平台默认正向词，会与用户正向提示词合并；`negative_prompt` 是独立的默认 UC，会继续合并风格反向模板和用户 `--反向` 内容。
- 图生图 `strength` 越高允许模型改动原图越多，越低则越接近原图；`noise` 可增加细节，但过高可能产生伪影。

额外参数使用 `key=value` 格式，每行填写一项。值支持布尔值、数字和 JSON。

### OpenAI 兼容模式

可选值：

- `auto`：根据模型选择接口格式。
- `images_api`：使用图片生成与编辑接口。
- `chat_completions`：使用多模态聊天接口。
- `novelai_images_api`：使用 NovelAI 风格图片响应。

多个兼容接口包含同名模型时，可在 `models` 中使用 `显示名=上游模型名`，例如：

```toml
models = "relay-gpt-image=gpt-image-2, relay-gemini=gemini-3.1-flash-image-preview"
```

## ComfyUI

ComfyUI 需要 API 格式工作流。推荐目录：

```text
plugins/maimai-drawpic/data/workflows/
├── t2i.json
└── i2i.json
```

基础配置：

```toml
[comfyui]
enabled = true
base_url = "http://127.0.0.1:8188"
t2i_workflow_path = "data/workflows/t2i.json"
i2i_workflow_path = "data/workflows/i2i.json"
seed = -1
```

请在 ComfyUI 中选择“导出（API 格式）”。普通画布工作流包含 `nodes`、`links` 等字段，不能作为 API 工作流提交。

### 提示词节点

单提示词工作流：

```toml
t2i_prompt_mode = "single_prompt"
t2i_prompt_node_id = "6"
prompt_input_name = "text"
```

正向、反向提示词工作流：

```toml
t2i_prompt_mode = "positive_negative"
t2i_positive_prompt_node_id = "6"
t2i_negative_prompt_node_id = "7"
t2i_negative_prompt = "low quality, blurry"
```

图生图还需填写图片节点：

```toml
i2i_image_node_id = "10"
image_input_name = "image"
```

工作流包含多个种子输入时，请填写对应任务的种子节点：

```toml
t2i_seed_node_id = "3"
i2i_seed_node_id = "3"
```

## 代理

```toml
[proxy]
enabled = true
use_system_proxy = false
scheme = "http"
host = "127.0.0.1"
port = 7890
username = ""
password = ""
bypass_china_providers = true
```

`use_system_proxy = true` 时读取系统代理环境变量。`bypass_china_providers` 可让阿里百炼、火山引擎和硅基流动使用直连网络。

## 权限与额度

群聊和私聊可分别配置额度：

```toml
[general]
permission_enabled = true
admin_user_ids = ["12345678"]

group_quota_enabled = true
group_quota_period = "daily"
group_default_quota = 5

private_quota_enabled = true
private_quota_period = "daily"
private_default_quota = 5
```

额度周期支持：

- `daily`：每日。
- `weekly`：每周。
- `monthly`：每月。
- `once`：一次性额度。

任务受理时会预留一次额度。任务失败、超时、审核拒绝或取消时，预留额度会自动返还。管理员不受额度限制。

OneBot v11 可填写数字 QQ 号和群号；QQ 官方适配器可填写用户 OpenID 与群 OpenID。

## 命令

| 命令 | 说明 |
| --- | --- |
| `/绘图` | 查看帮助、当前模型、兼容模式与额度 |
| `/绘图 状态` | 查看当前会话最近的绘图任务 |
| `/绘图 模型` | 查看可用模型 |
| `/绘图 模型 <模型名>` | 设置当前会话首选模型 |
| `/绘图 兼容模式` | 查看 OpenAI 兼容模式 |
| `/绘图 兼容模式 <模式>` | 设置当前会话兼容模式 |
| `/绘图 文生图 <提示词>` | 创建图片 |
| `/绘图 图生图 <提示词>` | 编辑消息中携带或引用的图片 |
| `/绘图 风格` | 查看已配置的全平台风格模板 |
| `/绘图 风格 <风格名称> <正向提示词> [--反向 <反向提示词>]` | 套用风格模板；附带/引用图片时自动图生图 |
| `/绘图 nai` | 查看 NAI 当前模型、mode、参数和用法 |
| `/绘图 nai 模式 <anime/furry/background/跟随>` | 设置会话级 NAI mode |
| `/绘图 nai 画师 <画师标签/跟随>` | 设置会话级 NAI 画师标签，支持逗号分隔多个标签 |
| `/绘图 nai 模型 <NAI模型名>` | 设置当前会话 NAI 模型 |
| `/绘图 nai 参数` | 查看 NAI 采样与图生图参数 |
| `/绘图 nai 文生图 <正向词> [--反向 <反向词>]` | 强制使用 NAI 文生图 |
| `/绘图 nai 图生图 <正向词> [--反向 <反向词>]` | 强制使用 NAI 编辑附带或引用图片 |
| `/绘图 nai furry <提示词>` | 仅本次使用指定 mode；`anime`、`background` 同理 |
| `/绘图 设置 群聊/用户 <ID> <次数>` | 设置目标额度 |
| `/绘图 增加 群聊/用户 <ID> <次数>` | 增加目标额度 |
| `/绘图 减少 群聊/用户 <ID> <次数>` | 减少目标额度 |

英文命令入口为 `/drawpic`，常用子命令支持 `status`、`model`、`compatible-mode`、`draw`、`edit` 和 `times`。

## LLM 工具

| 工具 | 用途 |
| --- | --- |
| `draw` | 根据文本提示创建图片 |
| `edit_image` | 编辑当前聊天中的真实图片 |
| `draw_styles` | 返回配置热重载后的可用全平台风格名称；风格化绘图前先调用 |
| `styled_draw` | 使用风格模板绘图；有真实源图时图生图，否则文生图；不填风格时保持普通绘图行为 |
| `draw_status` | 查询后台绘图任务状态 |

图片编辑仅查询当前聊天流中的消息。单条消息最多收集 8 张源图，单张图片大小上限为 25 MiB。

## 数据文件

运行数据位于插件目录的 `data/`：

```text
data/
├── session_preferences.json
├── draw_tasks.json
├── user_quotas.json
└── workflows/
```

- 会话偏好记录首选模型、OpenAI 兼容模式、NovelAI mode 和 NAI 画师标签。
- 任务记录保留最近 500 条状态，不保存用户提示词。
- 额度账本记录当前周期的使用量和管理员调整值。
- 入站源图缓存在内存中保存 30 分钟。

升级或备份插件时，请保留 `config.toml` 和 `data/`。

## 常见问题

### 当前未配置任何可用图片模型

检查目标平台的 `enabled`、`models` 和 API Key，并确认 `general.default_model` 存在于某个平台模型列表中。

### 找不到可编辑图片

发送图片后使用 `/绘图 图生图 <提示词>`，或回复包含图片的消息。图片必须位于当前聊天中。

### ComfyUI 工作流无法加载

确认文件为 API 格式 JSON，路径相对于插件目录填写，并核对提示词、图片和种子节点 ID。

### 图片任务超时

适当增加 `request_timeout_seconds`，并检查图片平台、代理或 ComfyUI 服务状态。

### 命令提示权限不足

将当前用户 ID 加入 `general.admin_user_ids`，或关闭 `permission_enabled`。

## License

[GNU Affero General Public License v3.0](LICENSE)
