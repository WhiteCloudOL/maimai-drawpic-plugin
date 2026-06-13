<div align="center">

# 麦麦绘图

为 MaiBot 提供图片生成与图片编辑能力。插件支持 OpenAI 兼容接口、Google Gemini、智谱、阿里百炼、硅基流动和 NovelAI / NovelAPI 图片模型，并可通过命令或 LLM 工具调用使用。

![Python Version](https://img.shields.io/badge/Python-3.10+-blue.svg)
![MaiBot Version](https://img.shields.io/badge/MaiBot-1.0.0+-success.svg)
![SDK Version](https://img.shields.io/badge/maibot--sdk-2.x-blueviolet.svg)
![Plugin Version](https://img.shields.io/badge/Plugin-1.6.3-informational.svg)
![License](https://img.shields.io/badge/License-AGPL%203.0-lightgrey.svg)

</div>

## 功能特性

- **文生图与图生图**：根据提示词生成图片，也可以基于聊天中的真实图片继续编辑；回复/引用图片时会自动提取被引用的真实图片，编辑时会校验源图数据，避免把图片描述误当作源图。
- **多平台模型**：支持 OpenAI Images API、OpenAI Chat Completion 兼容、Google Gemini、智谱、阿里百炼、硅基流动和 NovelAI / NovelAPI。
- **平台参数配置**：各平台支持分辨率、生成数量、输出格式、随机种子、反向提示词、采样步数、引导强度和额外参数等常用配置，兼容不同上游能力差异。
- **会话偏好**：群聊和私聊可分别保存模型与 OpenAI 兼容模式；新会话默认跟随全局默认模型。
- **后台任务**：绘图不阻塞聊天流程，生成完成后自动发送图片，可通过状态命令或工具查询任务。
- **LLM 工具调用**：向 MaiBot 暴露 `draw`、`edit_image`、`draw_status`，由 LLM 在合适场景自主调用。
- **英文提示词改写**：可按服务商启用，调用 MaiBot 的 `replyer` 模型把非英文提示词改写为适合生图模型的英文提示词。
- **审核与额度**：可选启用提示词审核、图片审核、管理员权限和用户绘图次数管理。
- **配置热更新**：订阅 `bot` / `model` 配置重载事件，主体配置更新后插件会刷新内部服务。

欢迎通过 Issue 或 Pull Request 反馈问题、改进文档或提交功能建议。交流群：637174573。
 
## 安装

在 MaiBot 的 `plugins` 目录中克隆本仓库：

```bash
cd plugins
git clone https://github.com/WhiteCloudOL/maimai-drawpic-plugin
```

在 MaiBot 主项目环境中安装依赖：

```bash
pip install -r plugins/maimai-drawpic-plugin/requirements.txt
```

使用 `uv` 时可执行：

```bash
uv pip install -r plugins/maimai-drawpic-plugin/requirements.txt
```

重启 MaiBot 后插件生效。首次加载会在插件目录生成本地 `config.toml`。

运行依赖：`aiohttp`、`pillow`、`google-genai`。其中 `google-genai` 仅在使用 Google Gemini 图片接口时需要。

## 配置

插件首次加载时会生成默认配置。常用配置示例如下：

```toml
[plugin]
# 是否启用插件
enabled = true
# 配置版本（请勿随意修改，由插件用于升级迁移）
config_version = "2.12.0"

[general]
# 默认使用的模型名称，插件会自动在各平台模型列表中查找
default_model = "gpt-image-2"
# 单次图片请求的超时时间（秒），建议 120 ~ 300；插件会将其限制在 5 ~ 600 之间
request_timeout_seconds = 150
# 聊天命令返回形式：图片 / 文本
command_reply_mode = "图片"
# 是否启用权限管理；开启后，模型切换、兼容模式切换和用户次数调整仅允许插件管理员执行
permission_enabled = true
# 插件管理员用户 ID 列表，通常填写 QQ 号
admin_user_ids = []
# 是否启用用户绘图次数管理；管理员不受限制
quota_enabled = true
# 次数周期：daily / weekly / monthly / once
quota_period = "daily"
# 普通用户在当前周期内默认可用绘图次数
default_quota = 5

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
# 默认 OpenAI 兼容模式：auto / images_api / chat_completions / novelai_images_api
# 通常建议保持 auto，由插件自动选择合适的接口
default_openai_compatibility_mode = "auto"
# OpenAI Images API 默认分辨率；兼容平台可按自身要求填写
default_size = "1024x1024"
# 按模型覆盖分辨率。每项格式为 模型名=宽x高
model_size_overrides = []
# OpenAI Images API 可选质量参数；留空则不传，兼容性最好
quality = ""
# 可选响应格式：b64_json / url；留空时非 gpt-image 模型默认使用 b64_json
response_format = ""
# 可选输出格式：png / jpeg / webp；留空则不传
output_format = ""
# 可选背景：transparent / opaque / auto；留空则不传
background = ""
# 可选审核强度：auto / low；留空则不传
moderation = ""
# 单次请求图片数量上限
max_images = 1
# 额外 JSON 参数。每项格式为 key=value，值支持 true/false、数字或 JSON
extra_parameters = []
# 是否在调用 OpenAI 提供商前使用 MaiBot replyer 模型改写为英文提示词
# 使用 NovelAI/StableDiffusion 兼容模型时必须开启，否则可能生图失败
rewrite_prompt_to_english = false

[google]
# Google Gemini 或兼容网关的基础 URL
base_url = "https://generativelanguage.googleapis.com"
# 你的 API 密钥
api_key = "your-google-api-key"
# 走 Google Gemini 接口的图片模型列表（可按需增删）
models = [
    "gemini-3.1-flash-image-preview",
]
# Google generate_images/edit_image 图片数量；Gemini generateContent 图片模型通常只返回 1 张
number_of_images = 1
# Google 图片宽高比；常见值 1:1、3:4、4:3、9:16、16:9
aspect_ratio = "1:1"
# 输出图片 MIME 类型
output_mime_type = "image/png"
# 人物生成策略，按模型支持填写；留空则不传
person_generation = ""
# 反向提示词；Imagen/edit_image 路径支持，Gemini generateContent 可能忽略
negative_prompt = ""
# 随机种子，负数表示不传
seed = -1
# 引导强度，大于 0 时传入
guidance_scale = 0.0
# 是否添加 Google 水印；仅 SDK/模型支持时生效
add_watermark = false
# Google 图片配置额外参数，只会传入当前 SDK 支持的字段
extra_parameters = []
# 是否在调用 Google 提供商前使用 MaiBot replyer 模型改写为英文提示词
rewrite_prompt_to_english = false

[zhipu]
# 智谱基础 URL（填根地址，不要带具体接口路径）
base_url = "https://open.bigmodel.cn"
# 你的 API 密钥
api_key = "your-zhipu-api-key"
# 走智谱图像生成接口的模型列表（当前仅支持文生图）
models = [
    "glm-image",
]
# 图片分辨率
size = "1280x1280"
# 响应格式：url / b64_json；留空则不传
response_format = "url"
# 终端用户标识，留空则不传
user = ""
# 智谱图片接口额外参数
extra_parameters = []
# 是否在调用智谱提供商前使用 MaiBot replyer 模型改写为英文提示词
rewrite_prompt_to_english = false

[aliyun]
# 阿里百炼基础 URL（填根地址，不要带具体接口路径）
base_url = "https://dashscope.aliyuncs.com"
# 你的 API 密钥
api_key = "your-aliyun-api-key"
# 走阿里百炼图片接口的模型列表（支持文生图与图像编辑）
models = [
    "qwen-image-2.0",
    "qwen-image-2.0-pro",
    "qwen-image-max",
    "qwen-image-plus",
    "qwen-image-edit-max",
    "qwen-image-edit-plus",
]
# 未在 model_size_overrides 中配置的阿里百炼模型会使用该分辨率
default_size = "2048*2048"
# 按模型覆盖分辨率。每项格式为 模型名=宽*高
model_size_overrides = [
    "qwen-image-2.0=2048*2048",
    "qwen-image-2.0-pro=2048*2048",
    "qwen-image-max=1328*1328",
    "qwen-image-plus=1328*1328",
    "qwen-image-edit-max=1024*1024",
    "qwen-image-edit-plus=1024*1024",
]
# 反向提示词，留空则不传 negative_prompt
negative_prompt = "低分辨率，低画质，肢体畸形，手指畸形，文字模糊，构图混乱，过度光滑，画面具有 AI 感。"
# 是否开启百炼提示词智能改写
prompt_extend = true
# 是否添加百炼水印
watermark = false
# 单次请求图片数量上限
max_images = 1
# 阿里百炼 parameters 额外参数
extra_parameters = []
# 是否在调用阿里百炼提供商前使用 MaiBot replyer 模型改写为英文提示词
rewrite_prompt_to_english = false

[siliconflow]
# 硅基流动基础 URL，官方默认 https://api.siliconflow.cn
base_url = "https://api.siliconflow.cn"
# 你的硅基流动 API 密钥
api_key = "your-siliconflow-api-key"
# 走硅基流动图片接口的模型列表
models = [
    "Kwai-Kolors/Kolors",
    "stabilityai/stable-diffusion-3-5-large",
]
# 图片尺寸，写入 image_size
image_size = "1024x1024"
# 按模型覆盖图片尺寸。每项格式为 模型名=宽x高
model_size_overrides = []
# 单次生成数量，写入 batch_size
batch_size = 1
# 随机种子，负数表示不传
seed = -1
# 采样步数，0 或负数表示不传
num_inference_steps = 20
# 提示词引导强度，0 或负数表示不传
guidance_scale = 7.5
# 反向提示词，留空则不传
negative_prompt = ""
# 输出格式：png / jpeg / webp
output_format = "png"
# 硅基流动图片接口额外参数
extra_parameters = []
# Stable Diffusion 类模型建议开启英文提示词改写
rewrite_prompt_to_english = false

[novelai]
# NovelAI 官方图片接口基础 URL；NovelAPI/中转平台按文档填写根地址
base_url = "https://image.novelai.net"
# NovelAI Bearer Token 或 NovelAPI 平台密钥
api_key = "your-novelai-api-key"
# NovelAI / NovelAPI 模型列表
models = [
    "nai-diffusion-4-full",
    "nai-diffusion-4-curated-preview",
    "nai-diffusion-3",
]
# 默认图片尺寸
width = 832
height = 1216
# 按模型覆盖尺寸。每项格式为 模型名=宽x高
model_size_overrides = []
# 采样器、采样步数与 Prompt Guidance
sampler = "k_euler_ancestral"
steps = 28
scale = 5.0
# 随机种子，负数表示每次随机
seed = -1
# 反向提示词，写入 uc
negative_prompt = "lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry"
# NovelAI 常见参数
uc_preset = 0
quality_toggle = true
sm = false
sm_dyn = false
noise_schedule = "native"
# 图生图参数
img2img_strength = 0.6
img2img_noise = 0.1
# 单次请求图片数量上限，写入 n_samples
max_images = 1
# NovelAI parameters 额外参数
extra_parameters = []
# NovelAI 标签体系建议开启英文提示词改写
rewrite_prompt_to_english = true

```

### 配置项说明

| 配置段 | 字段 | 含义 |
| :--- | :--- | :--- |
| `[plugin]` | `enabled` | 是否启用插件 |
| `[plugin]` | `config_version` | 配置版本号，用于插件自身的配置迁移，请勿随意修改 |
| `[general]` | `default_model` | 默认模型名，插件会在全部平台模型列表中查找归属 |
| `[general]` | `request_timeout_seconds` | 单次图片请求超时时间（秒），取值会被夹紧到 `[5, 600]` 区间 |
| `[general]` | `command_reply_mode` | 聊天命令返回形式，可选 `图片` / `文本`，默认 `图片` |
| `[general]` | `permission_enabled` / `admin_user_ids` | 权限管理开关与插件管理员用户 ID 列表 |
| `[general]` | `quota_enabled` / `quota_period` / `default_quota` | 用户绘图次数管理开关、周期与默认可用次数 |
| `[aliyun]` | `base_url` / `api_key` / `models` | 阿里百炼图片接口的基础 URL、密钥与模型列表（支持文生图与图像编辑） |
| `[aliyun]` | `default_size` / `model_size_overrides` | 阿里百炼默认分辨率和按模型覆盖分辨率，覆盖项格式为 `模型名=宽*高` |
| `[aliyun]` | `negative_prompt` / `prompt_extend` / `watermark` | 阿里百炼反向提示词、提示词智能改写和水印开关 |
| `[aliyun]` | `max_images` / `extra_parameters` | 阿里百炼单次图片数量上限与 `parameters` 额外参数 |
| `[aliyun]` | `rewrite_prompt_to_english` | 调用阿里百炼前是否先使用 MaiBot `replyer` 模型改写为英文提示词 |
| `[openai]` | `base_url` / `api_key` / `models` | OpenAI 或 OpenAI 兼容服务的基础 URL、密钥与模型列表 |
| `[openai]` | `default_openai_compatibility_mode` | 默认 OpenAI 兼容模式，支持 `auto` / `images_api` / `chat_completions` / `novelai_images_api` |
| `[openai]` | `default_size` / `model_size_overrides` | OpenAI Images API 默认分辨率和按模型覆盖分辨率 |
| `[openai]` | `quality` / `response_format` / `output_format` / `background` / `moderation` | OpenAI Images API 常用可选参数，留空则不传 |
| `[openai]` | `max_images` / `extra_parameters` | OpenAI 单次图片数量上限与兼容接口额外 JSON 参数 |
| `[openai]` | `rewrite_prompt_to_english` | 调用 OpenAI 提供商前是否先使用 MaiBot `replyer` 模型改写为英文提示词 |
| `[google]` | `base_url` / `api_key` / `models` | Google Gemini 或兼容网关的基础 URL、密钥与模型列表 |
| `[google]` | `number_of_images` / `aspect_ratio` / `output_mime_type` | Google 图片数量、宽高比和输出 MIME 类型 |
| `[google]` | `person_generation` / `negative_prompt` / `seed` / `guidance_scale` / `add_watermark` | Google 图片接口常用可选参数，仅在 SDK 与模型支持时生效 |
| `[google]` | `extra_parameters` | Google 图片配置额外参数，插件会过滤当前 SDK 不支持的字段 |
| `[google]` | `rewrite_prompt_to_english` | 调用 Google 提供商前是否先使用 MaiBot `replyer` 模型改写为英文提示词 |
| `[zhipu]` | `base_url` / `api_key` / `models` | 智谱图像生成接口的基础 URL、密钥与模型列表（当前仅支持文生图） |
| `[zhipu]` | `size` / `response_format` / `user` / `extra_parameters` | 智谱分辨率、响应格式、终端用户标识和额外参数 |
| `[zhipu]` | `rewrite_prompt_to_english` | 调用智谱前是否先使用 MaiBot `replyer` 模型改写为英文提示词 |
| `[siliconflow]` | `base_url` / `api_key` / `models` | 硅基流动图片接口基础 URL、密钥与模型列表 |
| `[siliconflow]` | `image_size` / `model_size_overrides` / `batch_size` / `output_format` | 硅基流动图片尺寸、按模型覆盖尺寸、生成数量和输出格式 |
| `[siliconflow]` | `seed` / `num_inference_steps` / `guidance_scale` / `negative_prompt` / `extra_parameters` | 硅基流动随机种子、采样步数、引导强度、反向提示词和额外参数 |
| `[siliconflow]` | `rewrite_prompt_to_english` | 调用硅基流动前是否先使用 MaiBot `replyer` 模型改写为英文提示词 |
| `[novelai]` | `base_url` / `api_key` / `models` | NovelAI 官方图片接口或 NovelAPI 网关的基础 URL、密钥与模型列表 |
| `[novelai]` | `width` / `height` / `model_size_overrides` | NovelAI 默认尺寸和按模型覆盖尺寸 |
| `[novelai]` | `sampler` / `steps` / `scale` / `seed` / `negative_prompt` / `uc_preset` | NovelAI 采样器、步数、Prompt Guidance、随机种子、反向提示词和 UC 预设 |
| `[novelai]` | `quality_toggle` / `sm` / `sm_dyn` / `noise_schedule` | NovelAI 常用画质与噪声调度参数 |
| `[novelai]` | `img2img_strength` / `img2img_noise` / `max_images` / `extra_parameters` | NovelAI 图生图强度、噪声、图片数量上限和额外参数 |
| `[novelai]` | `rewrite_prompt_to_english` | 调用 NovelAI / NovelAPI 前是否先使用 MaiBot `replyer` 模型改写为英文提示词 |
| `[prompt_review]` | `enabled` / `review_prompt` | 是否启用提示词审核以及审核提示模板（支持 `{user_prompt}` 占位符） |
| `[image_review]` | `enabled` / `review_prompt` | 是否启用生成图片审核以及审核提示模板（支持 `{user_prompt}` 占位符） |

> 💡 **模型归属：** 模型走哪个平台，取决于它出现在哪一侧的 `models` 列表里。同名模型不要同时出现在多侧。

> 💡 **额外参数：** 各平台的 `extra_parameters` 使用 `key=value` 列表。值会尽量解析为 `true` / `false`、整数、小数或 JSON，例如 `enhance_prompt=true`、`seed=12345`、`labels={"source":"maibot"}`。

### 审核配置

- `prompt_review.enabled`：开启后，`draw` / `edit_image` / `/绘图` 的提示词会先交给 MaiBot 的 `replyer` 模型审核。
- `image_review.enabled`：开启后，图片生成完成后会逐张交给 MaiBot 的 `vlm` 模型审核，只有通过的图片才会发送。
- `review_prompt`：审核提示模板，支持使用 `{user_prompt}` 注入本次绘图提示词。

启用审核前，请确认 MaiBot 主体已经在 `model_config.toml` 中配置好可用的 `replyer` 与 `vlm` 任务模型。

### OpenAI 兼容模式

`openai.default_openai_compatibility_mode` 以及 `/绘图 兼容模式 <模式>` 支持下列取值：

| 模式 | 说明 |
| :--- | :--- |
| `auto` | 由插件根据模型与上游接口能力自动选择，推荐默认使用 |
| `images_api` | 使用 OpenAI 标准的 `/v1/images/generations` 与 `/v1/images/edits` 接口 |
| `chat_completions` | 使用 OpenAI 的 Chat Completion 接口返回图片（部分中转/自部署网关会这样实现） |
| `novelai_images_api` | 旧版 NovelAI 风格 OpenAI 兼容接口，仅用于仍按 OpenAI provider 配置的中转 |

OpenAI provider 面向 OpenAI 官方 Images API、NewAPI 等 OpenAI 兼容中转，以及部分用 Chat Completion 返回图片的网关。NovelAI 官方图片接口或兼容 NovelAI payload 的 NovelAPI 网关，建议使用独立的 `[novelai]` 配置段，不再依赖 OpenAI 兼容模式。

使用阿里百炼、Google、智谱、硅基流动或 NovelAI 模型时，`openai_compatibility_mode` 不生效，插件会走对应平台的图片接口。智谱模型当前仅支持文生图，不能用于 `edit_image` 图生图编辑。

### 平台适配说明

- **硅基流动**：调用 `/v1/images/generations`，支持文生图和带 `image` 的图生图请求；响应兼容官方 `images` 数组和 OpenAI 风格 `data` 数组。
- **NovelAI / NovelAPI**：调用 `/ai/generate-image`，支持官方 zip 图片响应、直接图片响应，以及常见 NovelAPI JSON 响应。图生图会传入 `image`、`strength` 和 `noise`。
- **OpenAI 兼容平台**：默认 `auto` 会按模型特征尝试 Images API 或 Chat Completions；`extra_parameters` 可用于 NewAPI 等中转自定义字段。
- **Google**：Imagen 生成/编辑路径传入 SDK 支持的配置字段；Gemini generateContent 图片模型使用 `image_config` 传入可用图像参数。

### 英文提示词改写

各服务商都提供独立的 `rewrite_prompt_to_english` 开关。开启后，插件会在调用图片接口前使用 MaiBot 当前配置的 `replyer` 模型，将中文、日文等非英文内容改写为英文单词，并把中文/全角标点整理为 NovelAI、Stable Diffusion 更容易识别的英文半角标点。

该改写提示词由插件内置，不提供额外模板配置。使用 NovelAI 或 Stable Diffusion 兼容模型时必须开启，否则非英文提示词可能导致生图失败或效果异常。

### 会话偏好

插件会把每个会话手动选择的模型与兼容模式保存到插件目录下的 `data/session_preferences.json`，即使重启 MaiBot 也会保留原有设置。新会话默认不锁定模型，会跟随当前默认模型；只有执行过 `/绘图 模型 模型名` 后，才会固定该会话的模型。当模型列表在配置里被移除时，已失效的模型偏好会在加载时清空并重新跟随默认模型。

旧版本生成在插件根目录下的 `session_preferences.json` 与 `draw_tasks.json` 会在插件启动时自动迁移到 `data/` 目录；如果 `data/` 中已经存在同名文件，则不会覆盖已有数据。

### 配置热更新

插件订阅了 MaiBot 的 `bot` 与 `model` 配置重载事件。修改主体配置（例如切换 `replyer` / `vlm` 模型）后，插件会自动刷新内部服务，并保持现有的会话偏好不丢失。

### 权限与用户次数

- `general.permission_enabled` 默认开启。开启后，切换会话模型、切换 OpenAI 兼容模式、调整用户次数都需要用户 ID 出现在 `general.admin_user_ids` 中。
- `general.quota_enabled` 默认开启。普通用户使用 `/绘图 绘制 <prompt>` 或 LLM 工具调用发起绘图时，会消耗一次当前周期额度。
- `general.quota_period` 支持 `daily`、`weekly`、`monthly`、`once`，分别表示每日、每周、每月、一次性额度。
- 管理员不受绘图次数限制。

## 命令

使用 `/绘图` 管理当前会话的绘图模型、兼容模式、额度和绘图任务：

| 命令 | 说明 |
| :--- | :--- |
| `/绘图` | 查看各个子命令用法，不展示模型列表 |
| `/绘图 模型` | 查看当前使用模型与各提供商可用模型 |
| `/绘图 模型 <模型名>` | 将当前会话切换到指定绘图模型，启用权限管理时仅管理员可用 |
| `/绘图 状态` | 查看当前会话绘图模型、兼容模式、当前绘图任务与用户剩余次数 |
| `/绘图 兼容模式` | 查看 OpenAI 兼容模式说明 |
| `/绘图 兼容模式 <模式>` | 设置 OpenAI 兼容模式，仅对 OpenAI 提供商生效，启用权限管理时仅管理员可用 |
| `/绘图 绘制 <prompt>` | 强制发起文生图，`prompt` 可包含空格 |
| `/绘图 添加/减少/设置 用户ID 次数` | 管理员调整用户当前周期剩余次数 |

> 旧版 `/绘图 <提示词>` 直接绘图入口已移除；请使用 `/绘图 绘制 <prompt>`。

命令回复默认使用简约粉色图片模板，也可以通过 `general.command_reply_mode = "文本"` 改为纯文本。除命令外，MaiBot LLM 也可以在合适场景通过工具调用自动发起绘图或图片编辑。

工具调用启动后台任务后，插件只把任务提交信息写入日志，聊天中的开始提示由 MaiBot 的 LLM 根据上下文自行组织；图片生成或编辑完成后仍会自动发送到当前聊天流。

## LLM 工具

插件向大语言模型暴露以下工具：

| 工具名 | 作用 |
| :--- | :--- |
| `draw` | 根据提示词生成新图片，结果以异步后台任务形式回传到当前聊天流 |
| `edit_image` | 编辑当前聊天中的最近一张真实图片；如果用户回复/引用图片，会优先提取被引用消息中的真实图片，也可编辑指定 `source_message_id` / `source_image_base64` 对应的图片；`source_image_base64` 必须是真实图片 Base64 或 `data:image/...;base64`，不能传图片描述文本（智谱模型暂不支持，其他平台取决于上游模型能力） |
| `draw_status` | 查询当前会话最近一个绘图后台任务，或按 `task_id` 查询指定任务的状态 |

共通可选参数：

- `model`：本次调用使用的模型名。不填则优先使用当前会话锁定模型；会话未锁定时跟随插件默认模型。
- `user_id` / `group_id` / `platform`：用于在回传图片时定位真实聊天流，默认 `platform = qq`。

工具调用同样受用户次数管理影响。次数不足时，工具会把无法继续绘图的原因返回给 MaiBot LLM，由 LLM 根据上下文自然回复用户；插件不会额外发送机械式文本或图片。

## 目录结构

```
plugins/maimai-drawpic-plugin/
├── _manifest.json          # 插件元数据（MaiBot 1.0+，maibot-sdk 2.x）
├── plugin.py               # 插件入口，定义命令与工具
├── requirements.txt        # 依赖：aiohttp、pillow、google-genai
├── config.toml             # 首次加载自动生成的运行配置（本地生成）
├── assets/
│   └── font.ttf            # 命令图片回复默认字体
├── data/                   # 插件运行时数据（本地生成）
│   ├── session_preferences.json # 会话级模型/兼容模式偏好
│   ├── draw_tasks.json     # 后台任务状态缓存
│   └── user_quotas.json    # 用户绘图次数状态
├── core/
│   ├── config.py           # 配置模型定义
│   ├── draw_service.py     # 文生图 / 图生图后台任务调度
│   ├── image_reply.py      # 命令图片回复渲染
│   ├── message_utils.py    # 查找源图片等聊天消息工具
│   ├── moderation.py       # 提示词与图片审核服务
│   ├── provider_options.py # Provider 通用配置解析工具
│   ├── provider_router.py  # 模型归属判断与 Provider 创建
│   ├── session_preferences.py # 会话偏好加载与持久化
│   ├── stream_service.py   # 聊天流相关辅助
│   ├── task_store.py       # 后台任务登记与查询
│   ├── texts.py            # 命令帮助 / 状态文本
│   └── usage_store.py      # 用户绘图次数持久化
└── providers/
    ├── aliyun_platform.py  # 阿里百炼图片接口调用
    ├── novelai_platform.py # NovelAI / NovelAPI 图片接口调用
    ├── openai_platform.py  # OpenAI 兼容图片接口调用
    ├── google_platform.py  # Google Gemini 图片接口调用
    ├── siliconflow_platform.py # 硅基流动图片接口调用
    └── zhipu_platform.py   # 智谱图片生成接口调用
```

## 许可证

本项目遵循 [AGPL-3.0 许可证](LICENSE) 开源。
