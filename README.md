<div align="center">

# 🎨 麦麦绘图 (MaiBot Drawpic Plugin)

![Python Version](https://img.shields.io/badge/Python-3.10+-blue.svg)
![MaiBot Version](https://img.shields.io/badge/MaiBot-1.0.10+-success.svg)
![SDK Version](https://img.shields.io/badge/maibot--sdk-2.x-blueviolet.svg)
![Plugin Version](https://img.shields.io/badge/Plugin-1.9.1-informational.svg)
![License](https://img.shields.io/badge/License-AGPL%203.0-lightgrey.svg)

为 MaiBot 提供优雅、强大的图像生成与编辑能力。集成主流 AI 绘画平台，支持多模态场景下的对话式生图与工具调用。


</div>

> 💌 遇到问题？有新想法？<br>
> 如果你在使用中遇到问题、想到新功能、或希望优化代码，欢迎在仓库发起 Issue 或 Pull Request！<br>
> ☁️ 另外欢迎加入QQ群交流：637174573

## ✨ 功能特性

* **🎨 双模式绘图**：支持纯文本驱动的“文生图”与基于参考图的“图生图”。智能识别消息或引用中的图片，支持多图并行处理，且在源数据缺失或不兼容时提供精准提示，拒绝无效的强制降级。
* **🌐 多平台矩阵**：内置适配 OpenAI、Google Gemini、智谱、阿里百炼、火山引擎、硅基流动及 NovelAI 等主流服务商，轻松应对不同场景需求。
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
default_size = "1024x1024"

[openai]
base_url = "https://api.openai.com"
api_key = "your-openai-api-key"
models = ["gpt-image-2"]

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
| **`openai`** | `default_openai_compatibility_mode` | 兼容模式 (`auto` / `images_api` / `chat_completions` / `novelai_images_api`)。 |
| **`openai.instances`** | `name` / `base_url` / `api_key` / `models` | 额外 OpenAI 兼容实例；`models` 支持 `显示名=上游模型名`，适合多个中转站使用同名模型。WebUI 内为单行输入，多个模型用 `,` 或 `，` 分隔。 |
| **通用平台** | `api_key` / `models` | 对应服务商的鉴权密钥与允许使用的模型名列表。 |
| **通用平台** | `base_url` | 适用于 OpenAI、Google、NovelAI 的网关地址（其余平台使用内置官方地址）。 |
| **通用平台** | `rewrite_prompt_to_english` | 开启后，调用接口前将使用 MaiBot 的 `replyer` 模型自动翻译并规范化提示词标点。 |

## 🔐 权限与额度管控

插件内置了完善的用户权限与生图次数管理机制，适合公开群聊或多用户环境下的资源调配：

* **权限管理 (`permission_enabled`)**
默认开启。生效后，所有核心配置的更改（如：设置会话首选模型、更改 OpenAI 兼容模式、调整他人额度等）仅限 `general.admin_user_ids` 列表中的管理员执行。

* **额度消耗（群聊与私聊分离）**
额度按聊天归属扣除：群聊消耗该群剩余次数（键 `qq:group:群号`），私聊消耗该用户剩余次数（键 `qq:user:QQ号`）。群聊与私聊各自独立配置开关、重置周期与默认次数。
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
| `/绘图 设置/增加/减少 群聊/用户 群号/QQ号 数量` | 管理员调整群聊或用户的周期额度。例如 `/绘图 设置 用户 12345678 10`。 |

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

### v1.9.1

* **NovelAI 官方接口修复**：图像生成请求按官方规范以 HTTP `201` 判定成功，避免已生成的图片被误判为失败。
* **NovelAI 响应格式对齐**：请求 `Accept` 固定为官方声明的 `application/zip`，由插件解析生成的图片包。

### v1.9.0

* **额度按聊天归属扣除**：群聊额度按群号（`qq:group:群号`）扣除，私聊额度按用户 QQ（`qq:user:QQ号`）扣除，不再混合识别，与管理员命令参数一致。
* **群聊/私聊额度配置分离**：`quota_enabled` / `quota_period` / `default_quota` 拆分为 `group_*` 与 `private_*` 各三字段，可分别设置开关、重置周期与默认次数；旧配置自动迁移。
* **额度失败不扣除**：绘图额度改为任务成功后扣除，任务失败、超时、审核拒绝或提交异常时均不消耗次数，不再需要预扣回退。
* **管理员命令格式更新**：`/绘图 设置/增加/减少 群聊/用户 群号/QQ号 数量`，例如 `/绘图 设置 用户 12345678 10`。
* **群聊用户级额度限制说明**：因 MaiBot 工具参数更新，群聊工具调用链路无法稳定获取发起用户的 `user_id`，群聊额度只能按群组整体扣除，已在 README 中补充说明。

### v1.8.9

* **工具用户识别修复**：LLM 工具不再暴露或必填 `user_id`，插件优先使用 MaiBot 主程序注入的工具执行上下文和通用 `message_info.user_info.user_id` 解析真实发起用户，旧版 LLM 参数仅作为兼容兜底。
* **额度扣除修复**：绘图任务改为预扣额度并在任务失败、审核拒绝、后台取消或提交异常时自动回退；额度未启用时不再强制要求 `user_id`。
* **额度日志增强**：额度预扣、跳过、失败、回退均记录归属用户、聊天流、群号、周期和失败原因，便于排查多扣或失败未返还问题。
