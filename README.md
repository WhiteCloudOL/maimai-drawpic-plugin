<div align="center">

# 🎨 麦麦绘图 (MaiBot Drawpic Plugin)

![Python Version](https://img.shields.io/badge/Python-3.10+-blue.svg)
![MaiBot Version](https://img.shields.io/badge/MaiBot-1.0.0+-success.svg)
![SDK Version](https://img.shields.io/badge/maibot--sdk-2.x-blueviolet.svg)
![Plugin Version](https://img.shields.io/badge/Plugin-1.8.0-informational.svg)
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
* **🎀 会话级个性偏好**：群聊与私聊独立记忆模型与兼容模式设置，支持热更新，重启服务数据不丢失。
* **🤖 深度 LLM 赋能**：对外暴露 `draw`、`edit_image` 和 `draw_status` 工具，赋予大模型自主判断场景并调用绘图工具的能力，全程静默异步执行。
* **🛡️ 策略与安全管控**：内置服务商级英文提示词重写引擎，可选开启提示词审核、图片风控、用户额度管理及管理员权限校验，保障运营安全。

## 📦 安装指南

### 🔹 方式一：插件市场安装（推荐）
插件市场搜索：**麦麦绘图**，即可安装完成

### 🔹 方式二：maibot CLI 安装
非官方安装方式 支持Windows/MacOS/Linux多平台：https://github.com/WhiteCloudOL/MaiBot-Manager-TUI

maibot plugin install WhiteCloudOL/maimai-drawpic-plugin

### 🔹 方式三：手动安装

使用git下载插件文件至插件文件夹：
```bash
cd plugins # 进入插件文件夹
git clone https://github.com/WhiteCloudOL/maimai-drawpic-plugin
```

## ⚙️ 核心配置

首次加载生成的默认配置已能满足基础运行。日常使用通常只需配置 **全局默认模型**、**平台 API Key** 以及 **可用模型列表**。

**最小化配置示例：**

```toml
[general]
default_model = "doubao-seedream-3-0-t2i"
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
| **`general`** | `default_model` | 默认模型名，插件会自动在各平台模型列表中匹配归属。 |
| **`general`** | `quota_enabled` | 开启额度管理。配合 `quota_period` (周期) 与 `default_quota` (次数) 使用。 |
| **`general`** | `image_edit_unsupported_models` | 仅支持文生图的模型黑名单，命中后直接拦截图生图请求。 |
| **`general`** | `prompt_review_enabled` / `image_review_enabled` | 启用文本/图片审核，配合 `replyer` 和 `vlm` 任务模型保障内容安全。 |
| **`openai`** | `default_openai_compatibility_mode` | 兼容模式 (`auto` / `images_api` / `chat_completions` / `novelai_images_api`)。 |
| **`openai.instances`** | `name` / `base_url` / `api_key` / `models` | 额外 OpenAI 兼容实例；`models` 支持 `显示名=上游模型名`，适合多个中转站使用同名模型。 |
| **通用平台** | `api_key` / `models` | 对应服务商的鉴权密钥与允许使用的模型名列表。 |
| **通用平台** | `base_url` | 适用于 OpenAI、Google、NovelAI 的网关地址（其余平台使用内置官方地址）。 |
| **通用平台** | `rewrite_prompt_to_english` | 开启后，调用接口前将使用 MaiBot 的 `replyer` 模型自动翻译并规范化提示词标点。 |

### API Key 获取入口

| 平台 | 获取入口 |
| --- | --- |
| 火山引擎 / 方舟 | [API Key 管理](https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey) |
| 阿里百炼 | [获取 API Key 文档](https://help.aliyun.com/zh/model-studio/get-api-key) |
| 硅基流动 | [API 密钥页面](https://cloud.siliconflow.cn/account/ak) |

## 🔐 权限与额度管控

插件内置了完善的用户权限与生图次数管理机制，适合公开群聊或多用户环境下的资源调配：

* **权限管理 (`permission_enabled`)**
默认开启。生效后，所有核心配置的更改（如：切换会话模型、更改 OpenAI 兼容模式、调整他人额度等）仅限 `general.admin_user_ids` 列表中的管理员执行。
* **额度消耗 (`quota_enabled`)**
默认开启。普通用户通过指令（`/绘图 文生图`、`/绘图 图生图`）或触发 LLM 工具调用成功发起绘图时，均会消耗 1 次当前周期额度。
> 💡 **特权机制**：管理员账户不受任何绘图次数限制。


* **周期设定 (`quota_period`)**
支持四种额度刷新周期：`daily`（每日）、`weekly`（每周）、`monthly`（每月）或 `once`（一次性额度，不自动刷新）。

## 💾 会话偏好与数据持久化

插件为每个独立的聊天会话（私聊/群聊）提供状态记忆功能，保证多端多群互不干扰：

* **配置独立记忆**
会话级手动指定的模型与兼容模式会自动保存至 `data/session_preferences.json`，即使 MaiBot 重启，用户的专属设置依然生效。
* **智能跟随与回退**
* **默认状态**：新会话默认不锁定模型，始终跟随全局配置的 `default_model`。
* **主动锁定**：只有用户明确执行过 `/绘图 模型 <模型名>` 后，当前会话才会固定使用该模型。
* **自动清理**：当某个模型从 `config.toml` 中被移除时，插件会在加载时自动清空相关会话的失效偏好，使其平滑回退至全局默认模型。

## ⌨️ 指令交互

你可以使用 `/绘图` 唤出菜单，或直接使用以下快捷指令管理任务与偏好：

| 指令 | 作用描述 |
| --- | --- |
| `/绘图 模型 <模型名>` | 切换当前会话的指定绘图模型（开启权限时仅管理员可用）。 |
| `/绘图 状态` | 概览当前会话的模型设定、后台任务进度与剩余额度。 |
| `/绘图 兼容模式 <模式或跟随>` | 设定或清空当前会话的 OpenAI 兼容策略。 |
| `/绘图 文生图 <prompt>` | 强制纯文本生图。若消息附带图片将拦截并提示切换模式。 |
| `/绘图 图生图 <prompt>` | 强制基于参考图编辑，支持多图解析（优先读取附带图，其次读取引用图）。 |
| `/绘图 设置 <ID> <次数>` | 管理员快捷调整指定用户的周期额度。 |

## 🔧 LLM 工具集

插件向 MaiBot 暴露以下 Native Tools，由大语言模型根据对话上下文自然调用，无需人工干预指令：

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

## 📝 近期更新 (v1.8.0)

* **平台适配**：新增火山引擎 / 方舟即梦 AI、豆包生图接入，并内置智谱、阿里百炼、硅基流动官方接口地址。
* **配置优化**：WebUI 支持额外 OpenAI 兼容实例列表，可为多个中转站分别配置 `BaseURL`、`API Key` 和模型映射。
* **审核整理**：提示词审核与生成图片审核已移动到 `general` 通用配置，旧配置会自动迁移。
* **文档补充**：新增火山引擎、阿里百炼、硅基流动 API Key 获取入口。
