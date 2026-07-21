<div align="center">

# 🎨 麦麦绘图 (MaiBot Drawpic Plugin)

![Python Version](https://img.shields.io/badge/Python-3.10+-blue.svg)
![MaiBot Version](https://img.shields.io/badge/MaiBot-1.0.10+-success.svg)
![SDK Version](https://img.shields.io/badge/maibot--sdk-2.x-blueviolet.svg)
![Plugin Version](https://img.shields.io/badge/Plugin-1.10.3-informational.svg)
![License](https://img.shields.io/badge/License-AGPL%203.0-lightgrey.svg)

为 MaiBot 提供优雅、强大的图像生成与编辑能力。集成主流 AI 绘画平台，支持多模态场景下的对话式生图与工具调用。


</div>

> 💌 遇到问题？有新想法？<br>
> 如果你在使用中遇到问题、想到新功能、或希望优化代码，欢迎在仓库发起 Issue 或 Pull Request！<br>
> ☁️ 另外欢迎加入QQ群交流：637174573

## ✨ 功能特性

* **🎨 双模式绘图**：支持纯文本驱动的“文生图”与基于参考图的“图生图”。智能识别消息或引用中的图片，支持多图并行处理，且在源数据缺失或不兼容时提供精准提示，拒绝无效的强制降级。
* **🌐 多平台矩阵**：内置适配 OpenAI、Google Gemini、智谱、阿里百炼、火山引擎、硅基流动、NovelAI 及本地 ComfyUI 工作流，轻松应对不同场景需求。
* **📐 智能尺寸自适应**：图生图模式下自动计算并适配源图比例，完美兼容官方标准与第三方中转接口的分辨率约束。
* **🎀 会话级个性偏好**：群聊与私聊独立记忆首选模型与兼容模式设置，支持全局生图备选模型，重启服务数据不丢失。
* **🤖 深度 LLM 赋能**：对外暴露 `draw`、`edit_image` 和 `draw_status` 工具，赋予大模型自主判断场景并调用绘图工具的能力，全程静默异步执行。
* **🛡️ 策略与安全管控**：内置服务商级英文提示词重写引擎，可选开启提示词审核、图片风控、用户额度管理及管理员权限校验，保障运营安全。

## 🌐 支持平台

| 平台 | 说明 | 文生图 | 图生图 | API Key 获取 / 官网 |
| --- | --- | :---: | :---: | --- |
| **OpenAI** 及兼容中转 | 官方 `gpt-image` 系列及任意 OpenAI 兼容接口（NewAPI、中转站等），支持多实例分别配置 BaseURL 与模型映射。 | ✅ | ✅ | [OpenAI开放平台](https://platform.openai.com/) |
| **Google Gemini** | Gemini `image-preview` / `flash-image` 系列图片模型，支持官方接口与兼容网关。 | ✅ | ✅ | [Google AI Studio](https://aistudio.google.com/apikey) |
| **智谱** | 智谱 GLM 图像生成接口，中文提示词友好。 | ✅ | ❌ | [智谱开放平台](https://open.bigmodel.cn/) |
| **阿里百炼** | 通义万相 `qwen-image` 系列，支持自由分辨率与图像编辑。 | ✅ | ✅ | [阿里云API-KEY管理](https://help.aliyun.com/zh/model-studio/get-api-key) |
| **火山引擎** | 豆包生图、即梦 AI 系列模型，内置官方接口地址。 | ✅ | ✅ | [火山引擎API-KEY管理](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey) |
| **硅基流动** | Kolors、Stable Diffusion 3.5 等开源模型，按量计费。 | ✅ | ✅ | [硅基流动API-KEY管理](https://cloud.siliconflow.cn/account/ak) |
| **NovelAI / NovelAPI** | NovelAI 官方接口或兼容 NovelAPI 网关，支持 `nai-diffusion` 全系列模型。 | ✅ | ✅ | [NovelAI官网](https://novelai.net/) |
| **ComfyUI** | 调用自建或局域网 ComfyUI 的 API 工作流；统一模型 `comfyui` 会按任务自动选择文生图或图生图工作流。 | ✅ | ✅ | [ComfyUI](https://github.com/Comfy-Org/ComfyUI) |

> 💡 标记为 ❌ 表示该平台不支持某一项功能，插件会在用户尝试图生图时提前拦截并提示切换模型。

## 📦 安装指南

### 🔹 方式一：插件市场安装（推荐）
插件市场搜索：`麦麦绘图`，即可安装完成

### 🔹 方式二：maibot CLI 安装
**非官方安装方式** 支持Windows/MacOS/Linux多平台：https://github.com/WhiteCloudOL/MaiBot-Manager-TUI  

```bash
maibot plugin install WhiteCloudOL/maimai-drawpic-plugin
```

### 🔹 方式三：手动安装

使用git下载插件文件至插件文件夹：

```bash
cd plugins # 进入插件文件夹
git clone https://github.com/WhiteCloudOL/maimai-drawpic-plugin
```

## ⚙️ 核心配置

首次加载生成的默认配置已能满足基础运行。日常使用通常只需配置 **全局默认首选模型**、**生图备选模型**、**平台 API Key** 以及 **可用模型列表**。

**最小化配置示例：**

```toml
[general]
default_model = "doubao-seedream-3-0-t2i"
fallback_model = "gpt-image-2"
request_timeout_seconds = 150
admin_user_ids = ["你的管理员用户ID"]

[volcengine]
api_key = "your-volcengine-api-key"
models = ["doubao-seedream-3-0-t2i", "doubao-seedream-3-0-i2i"]
default_size = "2048*2048"

[proxy]
enabled = true
use_system_proxy = false
scheme = "http"
host = "127.0.0.1"
port = 7890
bypass_china_providers = true

[openai]
base_url = "https://api.openai.com"
api_key = "your-openai-api-key"
models = ["gpt-image-2"]

[comfyui]
enabled = true
base_url = "http://127.0.0.1:8188"
t2i_workflow_path = "data/workflows/t2i.json"
i2i_workflow_path = "data/workflows/i2i.json"
seed = -1

[[openai.instances]]
enabled = true
name = "备用中转"
base_url = "https://api.example.com"
api_key = "your-relay-api-key"
models = "relay-gpt-image=gpt-image-2"

```

### 配置项参考速查

| 模块 | 核心字段 | 作用说明 |
| --- | --- | --- |
| **`general`** | `default_model` | 默认首选模型名，插件会自动在各平台模型列表中匹配归属。 |
| **`general`** | `fallback_model` | 生图备选模型名。首选模型调用失败或未返回图片时，后台任务会自动尝试该模型；留空表示不启用。 |
| **`general`** | `group_quota_enabled` / `private_quota_enabled` | 分别为群聊、私聊开启额度管理。配合对应周期与默认次数使用。 |
| **`general`** | `image_edit_unsupported_models` | 仅支持文生图的模型黑名单，命中后直接拦截图生图请求。 |
| **`general`** | `prompt_review_enabled` / `image_review_enabled` | 启用文本/图片审核，配合 `replyer` 和 `vlm` 任务模型保障内容安全。 |
| **`proxy`** | `enabled` / `use_system_proxy` | 图片提供商全局代理开关；系统代理读取 `HTTP_PROXY`、`HTTPS_PROXY` 与 `NO_PROXY`。 |
| **`proxy`** | `scheme` / `host` / `port` / `username` / `password` | 手动 HTTP/HTTPS 代理地址与可选认证信息；关闭系统代理后生效。 |
| **`proxy`** | `bypass_china_providers` | 开启后阿里百炼、火山引擎、硅基流动直连，不使用插件全局代理。 |
| **`novelai`** | `models` / `custom_models` | `models` 为官方模型多选；`custom_models` 可填写 NovelAPI 或兼容网关扩展模型，并自动合并去重。 |
| **`volcengine`** | `unified_models` / `t2i_models` / `i2i_models` | `unified_models` 填写同时支持两种任务的模型；另两个列表分别保留仅文生图、仅图生图模型。统一模型可直接用于两类任务。 |
| **`comfyui`** | `base_url` | ComfyUI 服务地址。启用后绘图模型列表固定提供 `comfyui`，选中后按任务类型自动路由到对应工作流。 |
| **`comfyui`** | `t2i_workflow_path` / `i2i_workflow_path` | 文生图、图生图 API 工作流路径；相对路径相对于插件目录，默认在 `data/workflows/`，也支持 Windows、Linux 和 macOS 的绝对路径。 |
| **`comfyui`** | `*_prompt_mode` / `*_prompt_node_id` / `*_positive_prompt_node_id` / `*_negative_prompt_node_id` | 配置工作流是单提示词，还是正向/反向提示词结构，并指定相应 API 工作流节点 ID。 |
| **`comfyui`** | `seed` / `*_seed_node_id` | `seed=-1` 时每次生成随机种子；非负整数固定种子。种子节点 ID 留空时自动识别唯一的 `seed` 输入节点。 |
| **`openai`** | `default_openai_compatibility_mode` | 兼容模式 (`auto` / `images_api` / `chat_completions` / `novelai_images_api`)。 |
| **`openai.instances`** | `name` / `base_url` / `api_key` / `models` | 额外 OpenAI 兼容实例；`models` 支持 `显示名=上游模型名`，适合多个中转站使用同名模型。WebUI 内为单行输入，多个模型用 `,` 或 `，` 分隔。 |
| **通用平台** | `api_key` / `models` | 对应服务商的鉴权密钥与允许使用的模型名列表。 |
| **通用平台** | `base_url` | 适用于 OpenAI、Google、NovelAI 的网关地址（其余平台使用内置官方地址）。 |
| **通用平台** | `rewrite_prompt_to_english` | 开启后，调用接口前将使用 MaiBot 的 `replyer` 模型自动翻译并规范化提示词标点。 |

## 🧩 ComfyUI 本地工作流

ComfyUI 不需要 API Key。启用 `comfyui.enabled` 后，在 `/绘图 模型 comfyui` 中选择统一模型 `comfyui` 即可：`/绘图 文生图` 自动使用 `t2i_workflow_path`，`/绘图 图生图` 或 `edit_image` 自动使用 `i2i_workflow_path`。无需为两类任务分别选择模型。

### 1. 导出正确的工作流文件

插件仅接受 **ComfyUI API 格式** JSON。请在 ComfyUI 中完成并验证工作流后，使用菜单的“导出（API 格式）”保存：

* 将文生图工作流保存为 `plugins/maimai-drawpic/data/workflows/t2i.json`。
* 将图生图工作流保存为 `plugins/maimai-drawpic/data/workflows/i2i.json`。

插件启动时会自动创建 `data/workflows/README.txt`，其中说明默认文件名、API 工作流导出要求与配置文档位置；该文件只会在首次缺失时生成，不会覆盖你的修改。

普通“保存”得到的画布工作流 JSON 通常包含 `nodes`、`links`、`last_node_id` 等字段，不能直接提交到 `/prompt` 接口。插件会拒绝该格式并在日志和任务错误中明确提示重新导出 API 格式。

工作流路径支持：

```toml
# 相对插件目录，跨平台推荐
t2i_workflow_path = "data/workflows/t2i.json"

# Windows 绝对路径
i2i_workflow_path = "C:/ComfyUI/workflows/i2i_api.json"

# Linux / macOS 绝对路径
# i2i_workflow_path = "/opt/comfyui/workflows/i2i_api.json"
```

### 2. 配置提示词节点

插件会在提交前把用户提示词写入 API 工作流的节点 `inputs`。节点 ID 是 API JSON 顶层的键，例如 `"3"`；标准 `CLIPTextEncode` 的输入字段通常是 `text`，对应 `prompt_input_name = "text"`。

正反提示词工作流示例：

```toml
[comfyui]
t2i_prompt_mode = "positive_negative"
t2i_positive_prompt_node_id = "3"
t2i_negative_prompt_node_id = "4"
t2i_negative_prompt = "low quality, blurry, watermark"

i2i_prompt_mode = "positive_negative"
i2i_positive_prompt_node_id = "12"
i2i_negative_prompt_node_id = "13"
i2i_negative_prompt = "low quality, blurry"
```

单提示词工作流示例（例如工作流只有一个接收完整提示词的自定义节点）：

```toml
[comfyui]
t2i_prompt_mode = "single_prompt"
t2i_prompt_node_id = "3"
i2i_prompt_mode = "single_prompt"
i2i_prompt_node_id = "12"
prompt_input_name = "text"
```

`positive_negative` 模式会用用户提示词覆盖正向节点，用 `*_negative_prompt` 覆盖反向节点；`single_prompt` 模式仅写入 `*_prompt_node_id`，不会改动其他提示词节点。不同任务可独立选择模式。

### 3. 配置图生图源图片节点

图生图工作流应包含 `LoadImage` 或兼容节点。插件会将聊天中的第一张源图上传到 ComfyUI，再把上传后的文件名写入该节点；标准 `LoadImage` 配置如下：

```toml
[comfyui]
i2i_image_node_id = "5"
image_input_name = "image"
```

当前工作流注入一张源图；如果用户消息携带多张图，插件会记录警告并使用第一张。工作流中必须保留图片输出节点（例如 `SaveImage` 或 `PreviewImage`），否则 ComfyUI 历史记录没有可下载图片。

### 4. 随机种子与固定种子

默认 `seed = -1`，插件会在每次文生图或图生图任务中生成新的 64 位随机种子；填写非负整数即可固定种子，方便复现结果。标准 `KSampler` 的输入字段为 `seed`，插件会自动识别工作流中唯一的种子节点。

```toml
[comfyui]
# 每次随机，默认值
seed = -1

# 固定种子示例
# seed = 123456789

# 工作流存在多个 seed 节点时，分别指定 API 工作流节点 ID
t2i_seed_node_id = "1"
i2i_seed_node_id = "1"
seed_input_name = "seed"
```

如果工作流没有标准 `seed` 输入，或存在多个种子节点但未指定对应 ID，强制 `/绘图 文生图`、`/绘图 图生图` 会直接在聊天中返回简短的配置错误，不会创建后台任务；LLM 工具调用不会主动发送该错误消息。

### 5. 地址、超时与排错

默认地址是 `http://127.0.0.1:8188`。远程或局域网 ComfyUI 可改为完整 HTTP 地址，例如 `http://192.168.1.14:8188`；请保证 MaiBot 机器可以访问该地址，并按需通过插件的全局代理设置访问远程实例。

`comfyui.poll_interval_seconds` 控制查询任务状态的间隔（默认 1 秒），总时限沿用 `general.request_timeout_seconds`。调用日志会记录工作流加载路径、ComfyUI `prompt_id`、上传文件名、执行耗时和接口错误，便于定位路径、节点 ID 或工作流执行问题。

## 🔐 权限与额度管控

插件内置了完善的用户权限与生图次数管理机制，适合公开群聊或多用户环境下的资源调配：

* **权限管理 (`permission_enabled`)**
默认开启。生效后，所有核心配置的更改（如：设置会话首选模型、更改 OpenAI 兼容模式、调整他人额度等）仅限 `general.admin_user_ids` 列表中的管理员执行。

* **额度消耗（群聊与私聊分离）**
额度按聊天归属扣除：群聊消耗该群剩余次数，私聊消耗该用户剩余次数。OneBot v11 使用数字 QQ 号和群号；QQ 官方适配器使用 `user_openid` / `member_openid` 与 `group_openid`，插件会自动兼容两种身份格式。群聊与私聊各自独立配置开关、重置周期与默认次数。
  * `group_quota_enabled` / `group_quota_period` / `group_default_quota`：群聊额度开关、周期与默认次数。
  * `private_quota_enabled` / `private_quota_period` / `private_default_quota`：私聊额度开关、周期与默认次数。

> ⚠️ **群聊用户级额度限制说明**
> 由于 MaiBot 工具参数更新的缘故，当前插件工具调用链路无法稳定获取群聊中发起用户的 `user_id`，因此群聊额度只能按群组整体扣除，无法做到群聊内按用户分别限制。如需按用户限制，请让该用户在私聊中使用绘图。

* **失败不扣除**
绘图任务仅在成功完成（图片已发送）后才扣除额度。任务失败、超时、审核拒绝或提交异常时均不消耗次数。

> 💡 **特权机制**：管理员账户不受任何绘图次数限制。

* **周期设定**
支持四种额度刷新周期：`daily`（每日）、`weekly`（每周）、`monthly`（每月）或 `once`（一次性额度，不自动刷新）。群聊与私聊可分别配置。

## 💾 会话偏好与数据持久化

插件为每个独立的聊天会话（私聊/群聊）提供状态记忆功能，保证多端多群互不干扰：

* **配置独立记忆**
会话级手动指定的首选模型与兼容模式会自动保存至 `data/session_preferences.json`，即使 MaiBot 重启，用户的专属设置依然生效。
* **智能跟随与回退**
* **默认状态**：新会话默认不锁定模型，始终跟随全局配置的 `default_model`。
* **主动锁定**：只有用户明确执行过 `/绘图 模型 <模型名>` 后，当前会话才会固定使用该模型作为首选模型。
* **生图备选**：当首选模型调用失败、超时或未返回图片时，后台任务会自动尝试 `fallback_model`；成功后任务状态和日志会记录实际使用的备选模型。
* **自动清理**：当某个模型从 `config.toml` 中被移除时，插件会在加载时自动清空相关会话的失效偏好，使其平滑回退至全局默认首选模型。

## ⌨️ 指令交互

你可以使用 `/绘图` 唤出菜单，或直接使用以下快捷指令管理任务与偏好：

| 指令 | 作用描述 |
| --- | --- |
| `/绘图 模型 <模型名>` | 设置当前会话的首选绘图模型（开启权限时仅管理员可用）。 |
| `/绘图 状态` | 概览当前会话的首选模型、备选模型、后台任务进度与剩余额度。 |
| `/绘图 兼容模式 <模式或跟随>` | 设定或清空当前会话的 OpenAI 兼容策略。 |
| `/绘图 文生图 <prompt>` | 强制纯文本生图。若消息附带图片将拦截并提示切换模式。 |
| `/绘图 图生图 <prompt>` | 强制基于参考图编辑，支持多图解析（优先读取附带图，其次读取引用图）。 |
| `/绘图 设置/增加/减少 群聊/用户 群ID/用户ID 数量` | 管理员调整群聊或用户的周期额度；支持 OneBot 数字 ID 与 QQ 官方 OpenID。例如 `/绘图 设置 用户 12345678 10`。 |

## 🔧 LLM 工具集

插件向 MaiBot 暴露以下 Native Tools，由大语言模型根据对话上下文自然调用，无需人工干预指令：

工具调用所需的 `stream_id`、`group_id`、`user_id` 优先由 MaiBot 主程序运行时上下文注入，LLM 不需要也不应该自行填写用户 ID。

> ⚠️ 因 MaiBot 工具参数更新，群聊场景下工具调用链路无法稳定获取发起用户的 `user_id`，因此群聊额度只能按群组整体扣除，无法实现群聊内按用户分别限制。

| 工具名称 | 核心能力 |
| --- | --- |
| `draw` | 接收提示词发起文生图任务，完成后将图像异步回调至当前聊天流。 |
| `edit_image` | 自动提取聊天中的最新真实图片或引用图片，执行图像重绘或编辑操作。 |
| `draw_status` | 追踪指定 `task_id` 或当前会话的最新绘图任务执行状态。 |

## 📂 工程结构

```text
plugins/maimai-drawpic-plugin/
├── plugin.py               # 插件入口，注册命令与原生工具
├── config.toml             # 运行配置 (首次启动生成)
├── data/                   # 本地持久化数据目录
│   ├── session_preferences.json # 会话偏好缓存
│   ├── draw_tasks.json     # 任务状态队列
│   └── user_quotas.json    # 额度消耗账本
├── core/                   # 核心调度逻辑 (调度器、审核、工具类)
└── providers/              # 各大模型服务商 API 适配层

```

## 近期更新

### v1.10.3

**用户侧**

* **QQ 官方适配器兼容**：支持使用 `member_openid`、`user_openid` 与 `group_openid` 解析绘图上下文、回传图片和记录额度。
* **关闭额度不再误报警告**：对应聊天场景关闭额度后，不再执行与额度有关的无效 QQ 用户身份警告。

**开发侧**

* **QQ 身份统一校验**：运行时身份同时支持 OneBot 数字 ID 与 QQ 官方 32 位 OpenID，仍拒绝昵称等不稳定值进入额度账本。

### v1.10.1

**用户侧**

* **ComfyUI 种子控制**：新增随机/固定种子配置，默认每次任务使用新的随机种子；标准工作流会自动识别唯一的种子节点。
* **强制绘图命令即时校验**：`/绘图 文生图`、`/绘图 图生图` 在 ComfyUI 工作流、提示词节点、种子节点或图生图源图节点配置有误时，直接在聊天中返回问题，不再创建后台任务。
* **工作流目录自动初始化**：插件启动时自动创建 `data/workflows` 及其 `README.txt` 说明文件，不覆盖已有说明或工作流。

**开发侧**

* **ComfyUI 命令预检**：仅对聊天强制绘图命令执行工作流静态预检；LLM 工具调用保持原有异步返回与消息行为。

### v1.10.0

**用户侧**

* **ComfyUI 本地工作流支持**：新增 ComfyUI 提供商，启用后可在 `/绘图 模型 comfyui` 选择统一模型；插件会按任务自动使用文生图或图生图工作流。
* **ComfyUI 工作流配置**：支持分别配置 T2I/I2I API 工作流、相对或 Windows/Linux/macOS 绝对路径、单提示词或正反提示词节点，以及图生图源图节点。
* **火山引擎统一模型列表**：新增 `unified_models`，同时支持文生图和图生图的模型只需配置一次；原 `t2i_models`、`i2i_models` 保留用于单能力模型。

**开发侧**

* **ComfyUI 任务可观测性**：补充工作流加载、任务提交、图片上传、执行耗时、接口失败与工作流格式错误日志；普通画布 JSON 会明确提示导出 API 格式。

### v1.9.2

* **NovelAI V3/V4/V4.5 兼容**：V3 保持 `uc` 反向提示词结构；V4 与 V4.5 自动使用 `params_version=3`、`negative_prompt`、`v4_prompt` 和 `v4_negative_prompt`，并使用独立的 V4/V4.5 `karras` 噪声调度配置。正向与反向提示词仍复用原有配置。
* **NovelAI 官方模型多选与自定义扩展**：官方模型使用 SDK 多选框，提供当前的 V4.5 Full/Curated、V4 Full/Curated Preview、Anime V3 和 Furry V3；NovelAPI 或兼容网关的扩展模型可在独立自定义列表中填写。
* **图片请求全局代理**：可使用系统代理或手动配置 HTTP/HTTPS 代理，支持认证；可单独让阿里百炼、火山引擎和硅基流动绕过代理直连。

### v1.9.1

* **NovelAI 官方接口修复**：图像生成请求按官方规范接受 HTTP `201`，同时兼容 NovelAPI 网关常见的 HTTP `200`。
* **NovelAI 响应格式对齐**：优先请求官方 `application/zip`，并兼容 JSON 和直接图片响应。

### v1.9.0

* **额度按聊天归属扣除**：群聊额度按群号（`qq:group:群号`）扣除，私聊额度按用户 QQ（`qq:user:QQ号`）扣除，不再混合识别，与管理员命令参数一致。
* **群聊/私聊额度配置分离**：`quota_enabled` / `quota_period` / `default_quota` 拆分为 `group_*` 与 `private_*` 各三字段，可分别设置开关、重置周期与默认次数；旧配置自动迁移。
* **额度失败不扣除**：绘图额度改为任务成功后扣除，任务失败、超时、审核拒绝或提交异常时均不消耗次数，不再需要预扣回退。
* **管理员命令格式更新**：`/绘图 设置/增加/减少 群聊/用户 群号/QQ号 数量`，例如 `/绘图 设置 用户 12345678 10`。
* **群聊用户级额度限制说明**：因 MaiBot 工具参数更新，群聊工具调用链路无法稳定获取发起用户的 `user_id`，群聊额度只能按群组整体扣除，已在 README 中补充说明。
