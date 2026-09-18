# 阿里云百炼图像模型完整支持设计

## 背景与目标

当前插件的阿里云提供商只使用固定的公网 DashScope 主机和同步多模态生成接口，请求参数也按早期千问图片模型统一构造。该实现无法正确调用千问 3.0、Z-Image、可灵和 Vidu 的全部图像模型，尤其无法处理可灵、Vidu 强制要求的异步任务协议及其仅接受 URL 的参考图输入。

本次改造只修改 `maimai-drawpic-plugin`，不修改 MaiBot 主程序。目标是在保持现有绘图与图生图工具接口不变的前提下，为以下阿里云百炼图像模型族提供原生支持：

- 千问图像生成与编辑 3.0、2.0 和早期生成/编辑模型；
- Z-Image；
- 可灵图像生成；
- Vidu 图像生成、参考生图与编辑。

不包含万象、创意工具与图像翻译，也不扩展视频生成能力。

## 范围与模型清单

内置模型清单以阿里云官方文档在 2026-09-18 公布的图像模型为准。用户仍可通过配置增删模型。

### 千问

- `qwen-image-3.0-pro`
- `qwen-image-3.0`
- `qwen-image-2.0-pro`
- `qwen-image-2.0-pro-2026-06-22`
- `qwen-image-2.0-pro-2026-04-22`
- `qwen-image-2.0-pro-2026-03-03`
- `qwen-image-2.0`
- `qwen-image-2.0-2026-03-03`
- `qwen-image-max`
- `qwen-image-max-2025-12-30`
- `qwen-image-plus`
- `qwen-image-plus-2026-01-09`
- `qwen-image`
- `qwen-image-edit-max`
- `qwen-image-edit-max-2026-01-16`
- `qwen-image-edit-plus`
- `qwen-image-edit-plus-2025-12-15`
- `qwen-image-edit-plus-2025-10-30`
- `qwen-image-edit`

能力按官方定义建模：3.0 与 2.0 系列同时支持文生图和图生图；`max`、`plus` 与早期 `qwen-image` 只支持文生图；`edit-*` 和 `qwen-image-edit` 只支持图像编辑。

### Z-Image

- `z-image-turbo`

只支持文生图。

### 可灵

- `kling/kling-v3-image-generation`
- `kling/kling-v3-omni-image-generation`

两者支持文生图和参考图生图。普通 V3 只接受一张参考图；Omni 支持多图、单图模式和连续分镜组图。

### Vidu

- `vidu/vidu-image_reference2image`
- `vidu/vidu-image-pro_reference2image`
- `vidu/vidu-image-lite_reference2image`
- `vidu/viduq3-fast_reference2image`
- `vidu/viduq2-pro_reference2image`
- `vidu/viduq2-fast_reference2image`

均支持文生图、参考生图与图片编辑，最多接收 14 张参考图，单次固定输出 1 张图片。

## 总体架构

采用“模型能力注册表 + 共享 HTTP 传输层”的结构。

新增 `models/aliyun_models.py`，集中维护模型族识别、文生图/图生图能力、输入图片数量、同步/异步协议和每个模型族的参数构造。`providers/aliyun_platform.py` 只负责鉴权、URL 派生、同步请求、异步轮询、错误处理、结果解析和图片下载。

这样可避免为四个模型族复制网络代码，也不会继续把千问参数错误地发送给可灵或 Vidu。官方新增同前缀模型时可由族规则识别；配置中无法识别的旧自定义模型继续按原有同步多模态协议调用，以保持兼容性。

## 接口选择与数据流

### 同步模型

千问与 Z-Image 使用：

`POST {base_url}/services/aigc/multimodal-generation/generation`

`base_url` 统一采用包含 `/api/v1` 的形式。文生图直接提交文本；千问图生图把插件收到的图片字节编码为 Data URL。同步响应从 `output.choices[].message.content[].image` 提取下载地址。

### 异步模型

可灵与 Vidu 使用：

1. `POST {base_url}/services/aigc/image-generation/generation`，携带 `X-DashScope-Async: enable`；
2. 从响应读取 `output.task_id`；
3. 每隔配置的轮询间隔请求 `GET {base_url}/tasks/{task_id}`；
4. `SUCCEEDED` 时解析图片，`FAILED`、`CANCELED` 或 `UNKNOWN` 时立即抛出包含业务错误码与消息的异常；
5. 整体时限继续由插件现有 `general.request_timeout_seconds` 控制，不在提供商内另设相互冲突的总超时。

### 源图 URL 保留与可灵/Vidu 参考图

可灵和 Vidu 官方 HTTP 接口只接受公网 URL。平台适配器在下载图片的同时能够提供原始图片 URL，因此插件不能在提取 Base64 时丢弃该信息。

`core/message_utils.py` 新增结构化源图对象，同时保存经过校验的 Base64 与适配器 URL。URL 从图片消息段的标准及兼容字段中提取，包括顶层或 `data` 内的 `url`、`image_url`、`file_url` 和 `download_url`；只接受 `http://` 或 `https://` 地址。源图缓存也保存这两个值，使直接图片、引用图片和历史消息查找都能保留 URL。

插件向后台绘图服务同时传递图片字节与一一对应的 URL。其他提供商继续使用图片字节；阿里云提供商默认在千问图生图时使用 Base64，在可灵/Vidu 图生图时使用原始 URL。缺少 URL 时必须明确提示“当前适配器未提供原始图片 URL”，不上传临时文件，也不回退到官方不支持的 Data URL。

阿里云配置提供 `image_input_mode`：

- `auto`（默认）：按模型官方能力选择，千问使用 Base64，可灵/Vidu 使用 URL；
- `base64`：强制使用 Base64，仅允许官方支持 Base64 的模型；
- `url`：强制使用原始 URL，源消息没有 HTTP(S) URL 时明确失败。

显式配置不能绕过模型能力。对只接受 URL 的可灵/Vidu 选择 `base64` 时，在网络请求前返回配置错误。

为兼容当前工具中显式传入的 `source_image_base64`，该输入仍可用于千问图生图；选择可灵/Vidu 时会因没有适配器 URL 而提前拒绝。文生图不受 URL 可用性影响。

## 配置设计

沿用单个 `[aliyun]` 配置节，在现有字段基础上补齐模型族参数。WebUI 的字段标签与提示明确标注“必填”或“可选”。

### 必填配置

| 字段 | 含义 |
| --- | --- |
| `api_key` | 百炼 API Key；密码输入框，不提供真实默认值 |
| `base_url` | DashScope API 根地址，必须包含 `/api/v1`；默认公网地址，可填写工作空间专属地址 |
| `models` | 启用并参与路由的阿里云图片模型 ID 列表 |

### 通用可选配置

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `default_size` | `2048*2048` | 没有模型覆盖值时的尺寸；允许留空表示由模型自动决定 |
| `model_size_overrides` | 按内置模型设置 | 每个模型的尺寸覆盖 |
| `seed` | `0` | 传给支持 seed 的模型；Vidu 中 `0` 表示随机 |
| `watermark` | `false` | 仅传给官方支持水印参数的模型族 |
| `max_images` | `1` | 限制千问和可灵单图模式的输出数量；仍受模型上限约束 |
| `async_poll_interval_seconds` | `5.0` | 可灵/Vidu 异步任务轮询间隔 |
| `image_input_mode` | `auto` | `auto`、`base64` 或 `url`；默认按模型官方能力选择源图形式 |

### 千问可选配置

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `negative_prompt` | 现有中文负面提示词 | 反向提示词 |
| `prompt_extend` | `true` | 开启提示词智能改写 |
| `qwen_prompt_extend_mode` | `direct` | `direct` 或 `agent`；图生图强制拒绝 `agent` |
| `qwen_enable_thinking` | `true` | 在开启提示词改写时启用思考模式 |
| `qwen_extra_parameters` | 空 | 千问专用扩展参数 |

### Z-Image 可选配置

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `zimage_prompt_extend` | `false` | 智能改写会增加成本，因此默认关闭 |
| `zimage_extra_parameters` | 空 | Z-Image 专用扩展参数 |

### 可灵可选配置

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `kling_aspect_ratio` | `1:1` | `16:9`、`9:16` 或 `1:1` |
| `kling_resolution` | `1k` | 普通 V3 支持 `1k`/`2k`，Omni 额外支持 `4k` |
| `kling_result_type` | `single` | Omni 的 `single` 或 `series` |
| `kling_series_amount` | `4` | Omni 组图数量，范围 2～9 |
| `kling_extra_parameters` | 空 | 可灵专用扩展参数，如 `element_list` |

### Vidu 可选配置

| 字段 | 默认值 | 含义 |
| --- | --- | --- |
| `vidu_extra_parameters` | 空 | Vidu 专用扩展参数；尺寸、seed、水印使用通用字段 |

现有 `extra_parameters` 保留为兼容字段，但只用于无法识别的旧自定义模型；已识别模型族使用各自的扩展参数，避免参数串族。

## 参数与能力校验

能力判断采用“自动识别 + 人工覆盖”两层机制。阿里云内置模型先由注册表自动识别文生图/图生图能力；`general.image_edit_unsupported_models` 作为“仅支持文生图模型”人工名单，新增 `general.text_to_image_unsupported_models` 作为“仅支持图生图模型”人工名单。人工名单优先于自动识别，允许为自定义或未来模型补充能力；同一模型同时出现在两张名单时视为配置冲突并明确报错。

注册表和路由层在发起网络请求前完成以下校验：

- 模型是否支持当前文生图或图生图任务；
- 源图数量是否满足模型限制；
- 配置的图片输入形式是否被当前模型支持，以及 URL 模式下每张源图是否都有 HTTP(S) URL；
- `n` 是否落在模型允许范围；
- 千问 3.0 图生图不能使用 `prompt_extend_mode=agent`；
- 可灵分辨率、宽高比、单图/组图组合是否合法；
- Vidu 强制 `n=1`；
- Z-Image 固定 `n=1` 且拒绝图生图。

错误应完整暴露具体模型、任务和不合法参数，不做静默回退。路由层使用同一注册表提前报告不支持的任务，避免创建必然失败的后台任务。

当所选模型不支持当前任务时，中央任务入口必须在提示词审核、额度预留和后台任务创建之前拒绝：聊天指令向用户发送包含模型名和缺失能力的中文提示；工具调用返回 `success: false` 及可供 LLM 转述的失败原因。DrawService 在真正调用首选或备选模型前再次校验，防止配置热更新或备选切换绕过前置检查。

## 错误处理与日志

- 能力拒绝使用 warning 日志，记录模型、提供商、任务类型、源图数量和判断来源（自动、人工或冲突），不记录完整提示词；
- HTTP 非 2xx 响应记录状态码、耗时、去除查询参数后的 URL、脱敏业务错误与 `request_id`，不记录原始响应、Authorization、API Key、图片 Base64 或签名参数；
- 百炼业务响应中的 `code`/`message`/`request_id` 转换为带中文上下文的异常；
- 异步轮询日志只记录任务状态变化，包含模型、`task_id`、前后状态和已用时间，避免每 5 秒刷屏；
- 缺失 `task_id`、未知任务状态或成功响应没有图片均视为协议错误；
- 请求与下载沿用插件代理设置；国内提供商默认仍可绕过代理；
- API Key 不进入测试夹具、文档、日志或提交历史。

## 文件变更

- 新增 `models/aliyun_models.py`：模型注册表、能力与参数构造；
- 重构 `providers/aliyun_platform.py`：可配置 Base URL、同步/异步调用与轮询；
- 修改 `core/message_utils.py`：保留适配器图片 URL，并与 Base64/字节数据一一对应缓存和查找；
- 修改 `core/draw_service.py` 与 `plugin.py`：在现有后台任务链路中携带源图 URL；
- 修改 `core/config.py`：新增阿里云配置字段、仅支持图生图人工名单，并把配置版本从 `2.23.0` 提升到 `2.24.0`；
- 修改 `core/provider_router.py`：传递配置，结合自动注册表与两张人工名单判断任务能力；
- 修改 `tests/test_imports.py`：覆盖新模块导入；
- 新增 `tests/test_aliyun.py`：阿里云专用单元测试；
- 更新 `README.md`：模型、必填/可选参数、专属 Base URL 和适配器原始图片 URL 说明；
- 更新 `_manifest.json`：功能版本提升为 `1.12.0`。

不修改插件目录外的任何文件，不新增主程序依赖；继续使用现有 `aiohttp`。

## 测试策略

严格采用测试先行：先为模型识别、能力、参数和传输行为写失败测试，再写最小实现。

自动化测试覆盖：

- 所有内置模型 ID 的模型族与任务能力；
- 四个模型族的文生图请求体；
- 千问图生图 Data URL 与数量限制；
- 图片消息段 URL 提取、缓存、引用/历史查找以及与图片字节的顺序对应；
- 可灵/Vidu 图生图使用原始 HTTP(S) URL，缺失 URL 时在请求前明确失败；
- 异步任务的 PENDING、RUNNING、SUCCEEDED、FAILED、CANCELED、UNKNOWN；
- 同步与异步响应图片提取；
- Base URL 尾斜线规范化和所有派生 URL；
- 路由层配置传递与不支持任务提示；
- 自动能力判断、仅支持文生图/仅支持图生图人工覆盖，以及重复配置冲突；
- 指令提示、工具失败返回、额度预留前拒绝和后台二次校验；
- HTTP/业务错误的 `request_id`、异步状态变化日志和敏感 URL/Base64 脱敏；
- 现有全量测试不回归。

付费真实请求只在自动化测试全部通过后进行，且测试密钥仅存在于当前进程环境：最多调用一次千问 3.0 同步文生图和一次异步文生图，以覆盖两条真实协议。只有真实响应显示官方协议与文档不一致时，才追加一次针对性请求；不为每个模型逐一产生费用，也不进行付费图生图测试。

## 官方依据

- [千问图像生成与编辑 3.0 API](https://help.aliyun.com/zh/model-studio/qwen-image-generation-and-editing-api-reference)
- [Z-Image API](https://help.aliyun.com/zh/model-studio/z-image-api-reference)
- [可灵图像生成 API](https://help.aliyun.com/zh/model-studio/kling-image-generation-api-reference)
- [Vidu 图像生成 API](https://help.aliyun.com/zh/model-studio/vidu-image-generation-api-reference)
