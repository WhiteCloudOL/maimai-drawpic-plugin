# 插件联动 API 接入指南

本页面向同一 MaiBot 实例内的插件开发者，说明有哪些公开 API、各自的用途、参数、返回值和调用方法。仅使用绘图工作台的用户请看[使用指南](usage.md)；管理员配置见[配置说明](configuration.md)。

插件 ID 为 `maimai-drawpic-plugin`。所有接口均通过 Host 转发的 `ctx.api.call` 调用，没有额外 HTTP 监听、令牌或跨实例服务。

本次主线新增自我参考、两类绘图预设及素材来源选项。**原 2.2.1 release 不包含这些新增契约**；接入新功能时须使用包含 `drawpic_references_v2` 和 `reference_options_json` 的主线版本。运行环境最低为 **MaiBot 1.3.19、插件 SDK 2.20.0、Python 3.12**，具体上限见 [_manifest.json](../_manifest.json)。[MaiBot 1.3.19 的依赖声明](https://github.com/Mai-with-u/MaiBot/blob/v1.3.19/pyproject.toml)首次将 SDK 最低依赖提升至 2.20.0。

目录：[接口目录](#接口目录) · [接入准备](#接入准备) · [最小调用](#最小调用) · [任务提交](#drawpic_submit_v2提交任务) · [参考与素材](#参考与素材选项) · [查询恢复](#任务查询与恢复) · [图片读取](#drawpic_image_v2读取图片) · [取消与列表](#任务取消与列表) · [模型目录](#drawpic_models模型目录) · [会话偏好](#会话偏好读写) · [绘图预设](#drawpic_presets_v2绘图预设管理) · [参考目录](#drawpic_references_v2只读参考目录) · [客户端](#drawingclient方法与结果) · [完整示例](#完整接入示例) · [错误处理](#错误与恢复规则) · [v1 兼容](#v1-兼容接口) · [权限与资源](#权限与资源边界)。

## 接口目录

调用时建议始终填写完整名称 `maimai-drawpic-plugin.<API 名>` 和明确版本。v2 接口名带 `_v2`，版本为字符串 `"2"`；v1 使用原名称和 `"1"`，避免 Host 对未指定版本的旧调用产生歧义。

| API 名 | 版本 | 作用 | DrawingClient 方法 |
| --- | --- | --- | --- |
| `drawpic_submit_v2` | 2 | 受理文生图/图生图，立即返回持久任务句柄 | `submit`；`generate` 内部也调用它 |
| `drawpic_task_v2` | 2 | 查询单个任务、错误、结果引用和投递状态 | `task`、`wait` |
| `drawpic_request_v2` | 2 | 回执丢失后按原 request_id 只读找回任务 | `request`、`recover` |
| `drawpic_image_v2` | 2 | 读取原图分块、预览或缩略图 | `read_image`、`save_image` |
| `drawpic_cancel_v2` | 2 | 请求取消当前实例的本地后台等待 | `cancel` |
| `drawpic_tasks_v2` | 2 | 分页列出任务，支持状态和文字筛选 | `tasks` |
| `drawpic_preferences_v2` | 2 | 读取真实聊天流的会话绘图覆盖值 | `preferences` |
| `drawpic_preferences_set_v2` | 2 | 部分更新会话模型、兼容模式和 NAI 偏好 | `set_preferences` |
| `drawpic_presets_v2` | 2 | 列出、读取、保存、重命名或删除两类预设 | `presets`、`preset`、`save_preset`、`delete_preset` |
| `drawpic_references_v2` | 2 | 读取自我图库元数据和功能可用状态 | `references` |
| `drawpic_models` | 1 | 列出完整模型名、文生图/图生图能力及输入限制 | `models` |
| `drawpic_submit` | 1 | 历史提交协议，返回 task_id/reused | 直接 SDK 调用 |
| `drawpic_task` | 1 | 历史任务查询协议 | 直接 SDK 调用 |
| `drawpic_tasks` | 1 | 历史分页任务目录 | 直接 SDK 调用 |
| `drawpic_image` | 1 | 历史图片读取协议，默认读取 preview | 直接 SDK 调用 |
| `drawpic_cancel` | 1 | 历史取消协议 | 直接 SDK 调用 |
| `drawpic_presets` | 1 | 历史文字风格管理，不开放图生图类型预设 | 直接 SDK 调用 |

`workspace_*` 是工作台绑定的私有 API，不属于第三方插件接入契约。平台密钥、通用配置写入、图库上传/删除/设默认和运行日志查询不公开。没有 `compose_image`、独立素材搜索 RPC 或长等待的 `drawpic_generate` RPC。

## 接入准备

调用插件在自己的 manifest 中声明：

```json
{"capabilities": ["api.call"]}
```

需要发现接口时再加入 `api.get`、`api.list`。例如读取 `maimai-drawpic-plugin.drawpic_references_v2` 的元信息，可以判断目标主线是否提供新参考目录；不存在时明确提示升级，不剥掉参考选项重试，也不降级成另一种绘图。

独立 DrawingClient 单独采用 [MIT 协议](../clients/maimai_drawing_client/LICENSE)。推荐整体复制 [clients/maimai_drawing_client](../clients/maimai_drawing_client) 到调用插件的 `vendor/`，保留许可证和版权声明；绘图插件主体采用 AGPL-3.0。

```python
from .vendor.maimai_drawing_client import DrawingClient, DrawingError

client = DrawingClient(self.ctx.api)
```

客户端仅依赖 Python 标准库，不导入绘图插件内部模块。调用前，由调用插件持久保存 **request_id、完整原始参数、当前用户/会话授权关联**；收到响应后补存 task_id。客户端自动生成随机 request_id 只是便利，不代替调用方持久化。

## 最小调用

普通后台协程可以先提交，再等待已有任务：

```python
async def submit_once(ctx, prompt, saved_request_id):
    client = DrawingClient(ctx.api)
    handle = await client.submit(prompt, request_id=saved_request_id)
    # 立即保存 handle.task_id / handle.request_id。
    if handle.status == "submission_unknown":
        return handle
    return await client.wait(handle, wait_seconds=120)
```

LLM Tool 应优先使用 `submit` 并快速返回句柄；后续另查状态。不要把长等待塞进快到期的工具，也不要因为工具超时而换键重新绘图。后台协程需要由调用插件生命周期管理引用、异常和卸载取消。

直接 SDK 调用时，**SDK 2.20.0 与 2.22.1 均已解开 Host 的 `success/result` 包装**。`ctx.api.call` 直接返回下文的业务对象，不能再取一次 `response["result"]`：

```python
async def call_v2(ctx, operation, **args):
    return await ctx.api.call(
        f"maimai-drawpic-plugin.drawpic_{operation}_v2",
        version="2", **args,
    )
```

SDK/传输异常与业务错误分别处理。一次调用正常返回，不表示绘图成功；继续检查 `accepted/status/error`、`results_readable` 和 `delivery`。

## drawpic_submit_v2：提交任务

用途：校验请求并持久化任务与幂等映射，随后在原任务中完成必要素材准备、审核、提供商调用、缓存与可选投递。接口不等待图片生成。

| 参数 | 类型/默认值 | 说明 |
| --- | --- | --- |
| `prompt` | 必填字符串 | 1～16000 字符，当前绘图/编辑描述 |
| `model` | 字符串，`""` | 已启用的完整 `平台名称/模型名称`，最多 200 字符；省略用工作台默认模型 |
| `negative_prompt` | 字符串，`""` | 最多 16000 字符；按目标实例反向词开关、默认词和模板规则处理 |
| `style` | 字符串，`""` | 预设名，最多 80 字符；空/default 用当前模式的自动匹配与默认项；`none` 跳过预设 |
| `task_type` | `draw` / `edit_image`，默认 `draw` | 文生图严格不加图片；使用自我图、预设图、素材图时明确传 `edit_image` |
| `stream_id` | 字符串，`""` | 最多 200 字符；非空要求当前实例真实已有且有权访问的聊天流，并将结果发送到该流 |
| `source_images` | 字符串列表 / `null` | 真实图片 Base64 或 data URI；最多 8 张，不接受本机文件路径 |
| `request_id` | 字符串，`""` | 建议调用方必填；8～80 位字母、数字、下划线或横线；相同键保护一次请求不重复生成 |
| `openai_compatibility_mode` | 字符串，`""` | 本次 OpenAI 兼容格式覆盖；只对对应平台生效 |
| `novelai_mode` | 字符串，`""` | 本次 NovelAI 模式覆盖；可用枚举见当前实例模式配置 |
| `novelai_artist_tags` | 字符串 / `null` | `null` 不显式覆盖；空字符串表示本次显式清除画师标签覆盖 |
| `reference_options_json` | JSON 字符串，`""` | 下节的单次参考选项，最多 60 KiB；客户端用 `reference_options={...}` 自动序列化 |

`model` 省略时不自动切换为会话模型。需要会话覆盖时先调用偏好读取接口，再显式传入所需值。API 不推断 QQ 号、OpenID 或自行生成会话 hash。

单张 RPC Base64 编码最长 8 MiB 字符；解码后仍受单图 20 MiB、总计 40 MiB、真实图片和像素限制。客户端传入 `bytes` 只是在线程中编码，不会绕过服务端限制。与图库、预设、搜索素材合并后也须通过总图数、体积、所选模型能力及已有硬限制。

受理响应包含完整任务快照，另有：

```json
{
  "accepted": true,
  "task_id": "abcdef123456",
  "request_id": "saved-request-001",
  "reused": false,
  "status": "pending",
  "error": null
}
```

示例只列关键字段，其余见单任务快照。`reused=true` 表示找回原任务，不再识别、搜索或生成。受理前拒绝为 `accepted=false/task_id=null/status="not_accepted"`，并带结构化 `error`。受理后素材缺失、识别不明确或准备失败，通过原 task_id 查询终态，不再返回第二个任务。

没有可信回执时，调用方不能推断“未受理”。使用原 request_id 只读恢复。

## 参考与素材选项

这些是普通生成前处理，没有插件内 Agent、工具循环或通用创作规划。

| `reference_options` 字段 | 默认值 | 用法与限制 |
| --- | --- | --- |
| `self_reference` | `off` | `off` 不使用自身图库；`auto` 识别原始请求；`required` 明确描绘机器人自身 |
| `user_request` | `""` | 用户原始请求，最多 16000 字符；`auto` 或任一素材来源启用时必填，不能用改写后的第一人称 prompt 替代 |
| `self_reference_ids` | `[]` | 最多 8 个已存在自我图片 ID；优先于 tag；多选只能使用工作台已确认的组合 |
| `self_reference_tags` | `[]` | 最多 32 个、每个 1～80 字符；未指定 ID 时按规范化 tag/原始请求匹配，未命中用指定默认图 |
| `material_sources` | `[]` | `chat`、`web` 的子集，不得重复；本次限制不能打开全局关闭的来源 |

旧 API 调用及未传选项的新 v2 调用不会因管理员打开全局设置而突然读取聊天或联网。聊天工具和工作台按各自显式选择接入这些能力，外部 API 必须主动选择。

### 自我参考

管理员先在“预设参考 → 自我参考”开启自我参考、上传 tag 图片并设置默认图。首张自我图片成为默认图；后续上传不自动更换默认项。图库存在并不代表功能已开启。名称/别称与可选识别关键词用于 auto 的语义判断，不按关键词命中直接选人物。

聊天工具优先由宿主 LLM 明确给出 self_reference；空值、错拼或非法类型会在工具入口归一为 auto，再依据真实原话判断。此修正仅适用于聊天工具，公开 v1/v2 API 继续严格校验参数；没有原话不能拿改写 prompt 代替。

- `required` 在全局关闭时明确拒绝；`auto` 在关闭时跳过识别，不注入图片。
- 全局关闭时不能指定自我 ID/tag；`off` 也不能附带自身选图条件。
- `auto` 返回自身、其他、不明确三种分类。“你的自拍”可以指向机器人；“我的照片/给我自拍”不能仅凭“自拍”就指向机器人。
- 不明确时返回 `SELF_SUBJECT_UNCERTAIN`，不能把默认图当作身份判断的替代。
- 图库只绑定机器人；同框的其他人物仍需要独立素材，不用同名网图替代机器人或用户本人。
- 默认图只处理正常 tag 未命中；索引损坏、图片丢失、识别失败分别报错。

```python
async def draw_bot(ctx, saved_request_id):
    return await DrawingClient(ctx.api).submit(
        "麦麦穿冬装在海边",
        task_type="edit_image",
        request_id=saved_request_id,
        reference_options={
            "self_reference": "required",
            "self_reference_tags": ["冬装"],
        },
    )
```

### 聊天与网络素材

管理员分别开启“允许聊天记录取材”“允许网络素材搜索”。调用方再用 `material_sources` 限定本次可用来源。

| 来源选择 | 实际行为 |
| --- | --- |
| `[]` | 不自动搜索，只用显式图片和本次允许的配置资产 |
| `["chat"]` | 仅明确接续前图时读取当前聊天；普通新任务不触发 |
| `["web"]` | 仅为具体角色、特定物件或明确参考图请求调用 MaiBot 搜索服务 |
| `["chat", "web"]` | 分别按接续前图和具体实体条件触发，已有合适参考时不重复搜索 |

选择 `chat` 必须提供真实可访问的 stream_id；即使没有黑白名单，也不能省略会话校验。**该参数同时沿用结果投递契约**，因此调用前必须确认允许读取该聊天并发送结果。仅填写 stream_id 不等于允许历史搜索。

检查围绕“目标实体 + 图片用途”进行。已有一张机器人图片，不代表同框角色或特定服装已有可靠参考。原创人物、通用海边等通常无需搜索；角色、服装版本或具体物件则需要核对。搜索结果先经过真实图片与尺寸校验，再进行视觉匹配；网页标题和图片描述不作为图片输入。

来源关闭时零调用；显式请求关闭来源时报错。聊天读取、搜索服务配置/鉴权、网页读取和素材下载错误不会被当作空结果静默换来源。搜索结果不自动写入图库。

当前 SDK 搜索返回网页链接与正文，没有通用搜图候选字段。插件会有界提取正文中的图片链接；必要时按同一代理、地址及跳转规则读取网页图片标记。搜索服务必须由管理员在 MaiBot 配置并分配给联网搜索，插件不读取或复制其凭据。当前 SDK 的 `web.search` / `web.fetch` 只使用统一分配的服务，不支持服务商参数或服务目录查询；更换服务商需在 MaiBot 中调整分配。

取材识别由固定的一次语义分类给出 `chat_followup` 和具体实体需求；检索词必须包含原话中的实体，不对整句分词搜索。不确定或普通新任务不会读取历史。聊天候选优先使用 MaiBot 已识别描述，信息不足时才视图核对。接续前图失败会要求补图，不用网图代替前图。

管理员可在工作台设置 `material_model`，默认 `vlm`，建议快速多模态模型；调用方不能覆盖识别模型或扩大聊天范围。

指定识别模型使用 SDK 2.20.0 已提供的 `ctx.llm.generate(prompt, task_name="vlm", model_name="已配置模型名称")`。名称来自 MaiBot 模型配置的 `name`，不是服务商原始模型 ID；即使与 `planner`、`vlm` 等任务同名，也严格选取该具体模型。`get_available_models()` 仅返回任务名称，不能据此列出所有具体模型，因此工作台让管理员输入名称，由宿主在调用时验证。工作台保存格式见[手动配置](manual-configuration.md#参考与素材字段)。

触发关键词只在宿主的 planner 请求 Hook 中追加固定提醒，不启动另一套规划流程，不在消息接收 Hook 中检查或唤醒回复，也不会直接调用绘图工具。提醒位于本轮提示尾部，保留原系统提示词和历史消息前缀；关键词、用户原话和时间不会动态写入提醒，避免无谓破坏 LLM 缓存。

预算：最多 3 个素材需求；当前聊天读取最近 24 小时内最多 `chat_material_search_limit` 条消息（默认推荐 50，可设 1～200）/6 张候选，每个任务只读取一次、不同素材需求共享候选；每次网络查询最多 3 个网页、6 张候选；本次最多 12 张次视觉核对，整体准备最多 90 秒。达不到目标或预算耗尽时要求补图，不自动发起新的改词搜索或重画。

```python
async def draw_group(ctx, real_stream_id, saved_request_id):
    return await DrawingClient(ctx.api).submit(
        "麦麦与甘雨在海边合照",
        task_type="edit_image", stream_id=real_stream_id,
        request_id=saved_request_id,
        reference_options={
            "self_reference": "required",
            "user_request": "画你和甘雨在海边的合照",
            "material_sources": ["chat", "web"],
        },
    )
```

此例要求自我参考、两个来源及相应多图合用配置已经由管理员开启/确认。图生图预设可以保持关闭。

### 多图与模式

`source_images` 原本就支持列表，本次没有新增独立多图 RPC。新增自我/预设多图及其与其他图片合用的配置，需要管理员在工作台通过 dialog 核实具体服务商模型是否支持多图；API 不能用一个 `confirmed=true` 绕过确认。

生图前至少检查图生图能力，保留已知数量上限、输入方式与体积限制。确认不代表自动探测，也不能覆盖模型已知限制。提供商拒绝时不静默减图。

`task_type="draw"` 始终是纯文生图，不能因为参考选项或图生图预设而静默转换。`edit_image` 可以没有直接传入的 Base64，但生成前必须从显式配置或允许的素材来源得到真实图片，否则失败；不会降级成文生图。

## 任务查询与恢复

### drawpic_task_v2

参数只有 `task_id`：当前实例的 12 位小写十六进制任务 ID。它只读，不重新生成、不重新发送。

```python
async def query_task(ctx, task_id):
    return await DrawingClient(ctx.api).task(task_id)
```

任务快照的重要字段：

| 字段 | 说明 |
| --- | --- |
| `task_id` / `request_id` | 持久句柄与原请求键；失败恢复时继续保留 |
| `status` | `pending/running/completed/failed/rejected/unconfirmed/cancelled` |
| `task_type` / `model` / `provider` | 实际模式与已解析的完整模型/提供商 |
| `message` / `error` | 脱敏说明与结构化错误；成功无业务错误时 error 为 null |
| `retry_after_ms` | pending/running 时当前为 3000，其余为 0；用于合理轮询 |
| `generation_completed` | 已产生生成结果；不保证审核、缓存或投递成功 |
| `results_readable` | 当前能读取缓存图片，不是永久保存承诺 |
| `images` | 已通过审核并可读取的生成图片引用，包含 index、size、mime、expires_at 等；没有整张 Base64 |
| `delivery` | 是否要求投递、投递状态与已确认发送数 |
| `created_at` / `updated_at` | 任务创建与更新时刻 |

`delivery.status` 为 `not_requested/pending/sent/partial/failed/unconfirmed`。生成成功、结果可读、消息发送成功是三个不同事实：例如 `generation_completed=true` 但 `results_readable=false` 可能是缓存失败/过期；`completed` 也不能证明全部消息已发送。

### drawpic_request_v2

参数只有 `request_id`，格式与提交一致。只查询保留期内的持久映射，成功直接返回上面的任务快照，**没有额外 `accepted/record` 包装**。

```python
async def recover_receipt(ctx, saved_request_id):
    client = DrawingClient(ctx.api)
    snapshot = await client.request(saved_request_id)
    return await client.wait(snapshot["task_id"], request_id=saved_request_id, wait_seconds=120)
```

找不到时为 `REQUEST_NOT_FOUND`。可能仍在受理、查询了错误实例或记录已淘汰，不能据此认定从未受理。`recover` 内部只读找回并继续等待，不会重新提交提示词或图片。

## drawpic_image_v2：读取图片

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `task_id` | 必填 | 当前实例的任务句柄 |
| `index` | 0 | 图片索引，从 0 开始，使用任务 images 中的 index |
| `kind` | `original` | `original`、`preview` 或 `thumbnail` |
| `offset` | 0 | 原图的字节偏移，必须是非负整数；预览不需要分块偏移 |

原图每次最多读取 **192 KiB 原始字节**，返回：

```json
{"data":"...Base64...","offset":0,"next_offset":196608,"size":420000,"mime":"image/png","filename":"abcdef123456-1.png","done":false,"error":null}
```

使用 `next_offset` 继续读取，直到 done；必须校验总大小、偏移连续和终止标记，不能每次继续请求 offset=0。优先用客户端：

```python
async def obtain_image(ctx, task_id, output_path):
    client = DrawingClient(ctx.api)
    raw = await client.read_image(task_id, index=0)
    await client.save_image(task_id, output_path, index=0)
    return raw
```

`output_path` 是调用方自己有权写入的本地目录，客户端在线程内写入；服务器没有接收任意文件路径的接口。预览/缩略图返回 `data_url` 等图片元信息，MIME 以返回值为准，不能假定都是 JPEG。

尚未产生图片时为 `RESULT_NOT_READY`；过期/清理为 `RESULT_EXPIRED`。读取失败不等于生成失败，更不能据此重新生成。需要长期保存时，调用方及时复制到自己的授予目录。

## 任务取消与列表

### drawpic_cancel_v2

参数 `task_id` 必填。返回任务的实际快照，另有 `cancel_requested` 与 `upstream_cancelled`（当前为 null）。客户端：`await client.cancel(task_id)`。

只请求停止本地等待。上游可能已经受理并计费，不能承诺远端撤单；完成与取消竞争时保留实际终态。已完成任务不会为了取消而再次生成或投递。

### drawpic_tasks_v2

| 参数 | 默认值 | 限制 |
| --- | --- | --- |
| `page` | 1 | 整数 1～100，每页固定 12 条 |
| `status` | `""` | 空值或任一 v2 任务状态 |
| `search` | `""` | 最多 200 字符，按任务号、模型和消息文字筛选 |

返回 `items/total/page/page_size/error`，items 为任务快照，不夹带缩略图内容。示例：`await client.tasks(page=1, status="running")`。这是当前实例的可信插件管理目录；调用插件不能直接无条件开放给普通聊天用户。

## drawpic_models：模型目录

唯一仍由正式客户端使用的 v1 发现接口，版本为 `"1"`，没有参数。示例：`await client.models()`。

返回 `models/default_model/default_model_error`。每个模型包含完整 `name`、实例/提供商与真实模型信息，以及：

- `draw/draw_reason`：文生图能力与拒绝原因。
- `edit_image/edit_reason`：整体图生图能力。
- `api_edit_image/api_edit_reason`：是否接受公开 API/网页上传的本地图片输入；要求原图 URL 的模型可能不接受 Base64。
- `max_source_images`：主线已知数量上限与插件 8 张安全上限的交集；不能据此推断未经确认的多图支持。

目录仅供展示和事前检查；提交/生成前仍会重新检查实际模型能力。不增加自动多图试探或虚构的 `supports_multi_reference`。

## 会话偏好读写

### drawpic_preferences_v2

必填参数 `stream_id`，返回 `stream_id/preferences/error`。偏好字段始终是字符串，空值表示没有对应会话覆盖。

### drawpic_preferences_set_v2

必填 `stream_id` 与 `preference_json`（JSON 对象文本），只部分更新提供的字段：

| 字段 | 最大长度 | 含义 |
| --- | --- | --- |
| `model` | 200 | 已启用的完整模型名 |
| `openai_compatibility_mode` | 40 | OpenAI 兼容接口格式 |
| `novelai_mode` | 40 | NovelAI 模式 |
| `novelai_artist_tags` | 16000 | NAI 画师标签 |

未提供的字段保持原值，空字符串清除该字段覆盖。未知字段/非字符串值拒绝。只解析真实已存在会话，不创建会话，不把 stream_id 当 QQ/OpenID。自我参考、素材来源和图生图预设总开关不属于会话偏好写入范围。

```python
async def choose_session_model(ctx, real_stream_id, full_model_name):
    client = DrawingClient(ctx.api)
    await client.set_preferences(real_stream_id, model=full_model_name)
    return await client.preferences(real_stream_id)
```

写入不自动重试。回执未知时先读取核对；勿将这些管理能力无条件暴露给群成员。

## drawpic_presets_v2：绘图预设管理

参数为 `operation="list"`、`name=""`、`preset_json=""`。名称最多 80 字符，两类预设名称全局唯一。此接口不修改全局开关或默认项。

| operation | 参数 | 返回/作用 | 客户端 |
| --- | --- | --- | --- |
| `list` | 无需其他参数 | presets、default_style、image_edit_presets_enabled、default_image_edit_preset、error | `presets()` |
| `get` | name | preset/error | `preset(name)` |
| `save` | preset_json；更新/重命名时 name 为旧名 | 创建或更新，返回最新目录；省略新增字段保留已有值 | `save_preset(preset, name=旧名)` |
| `delete` | name | 删除并更新默认引用，返回目录 | `delete_preset(name)` |

预设字段：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `name` | 自定义风格 | 非空名称；建议调用方创建时总是明确提供 |
| `description` | `""` | 给用户与调用方看的语义说明 |
| `enabled` | true | 当前预设是否可用 |
| `positive_prompt_template` | `{prompt}` | 正向模板；保留用户本次描述；没有占位符时仍追加用户描述 |
| `negative_prompt_template` | `{negative_prompt}` | 反向模板，复用实例开关、默认词与去重逻辑 |
| `preset_type` | `text_to_image` | 文生图或 `image_to_image` 图生图类型 |
| `tags` | `[]` | 本次请求的固定匹配 tag |
| `apply_to_image_edit` | false | 仅文生图类型可勾选“同时应用到图生图” |
| `reference_bindings` | `[]` | 仅图生图类型可关联真实预设图片，最多 8 条用途绑定 |
| `multi_reference_confirmed` | false | 工作台 dialog 的已确认配置；公开 API 不能自行设置为 true 或变更多图绑定来绕过确认 |

每个绑定包含 `asset_id`、`role`、`subject_id`、`note`。role 为 `identity/clothing/scene/lighting/composition/base`；note 最多 500 字符。身份参考标明对应人物，服装参考不额外增加一个出镜人物。同图可承担不同用途，最终编号一致并按真实内容去重。

管理规则：

1. 文生图预设不绑定图片；图生图预设不可勾选跨模式标记。
2. 图生图预设总开关默认关闭，关闭时 v2 图生图不自动套用任何预设；显式要求套用则拒绝。总开关不影响图生图能力和独立自我参考。
3. 开启后，图生图使用图生图类型或已勾选兼容的文生图类型；一次只应用一条模板。
4. 显式选择优先；否则匹配当前模式允许的 tag，再使用模式默认项。图生图默认项未设置时，才考虑已勾选兼容的默认文生图预设。配置的默认项无效时明确报错。
5. 不会仅为套默认图生图预设而向纯文生图加入图片。图生图需要真实源图；显式图生图预设可以提供自己的关联图。
6. 关联图在工作台上传，API 只引用已经存在且用途属于预设的资产。自我图库 ID 不能伪装为预设资产来绕过自身开关。
7. 创建/改变多图配置返回 `MULTI_REFERENCE_CONFIRMATION_REQUIRED`，由管理员在工作台完成 dialog；写入回执未知先 get/list 核对，不自动重试写入。

```python
async def save_watercolor(ctx):
    client = DrawingClient(ctx.api)
    await client.save_preset({
        "name": "水彩海边", "preset_type": "text_to_image",
        "tags": ["海边"], "apply_to_image_edit": True,
        "positive_prompt_template": "watercolor, seaside, {prompt}",
        "negative_prompt_template": "blur, {negative_prompt}",
    })
    return await client.preset("水彩海边")
```

全局图生图开关仍需管理员在工作台打开。保存该标记不会偷偷启用总开关。

## drawpic_references_v2：只读参考目录

可选参数 `page=1`，范围 1～10，每页 12 条。用于展示可选自我图、tag、默认项和实际可用状态。

```json
{
  "page":1,"page_size":12,"total":1,
  "assets":[{"id":"0123456789abcdef0123456789abcdef","name":"冬装","tags":["冬装"],"default":true}],
  "self_reference_enabled":false,
  "allow_chat_material_search":false,
  "chat_material_search_limit":50,
  "material_model":"vlm",
  "allow_web_material_search":false,
  "multi_reference_confirmed":false,
  "error":null
}
```

`chat_material_search_limit` 是管理员配置的聊天消息搜索上限；调用方不能通过单次参考选项扩大它。在途任务采用提交时与执行时上限的较小值。

只返回元数据，不返回 Base64、文件路径、签名链接、候选图或搜索历史。`total` 是自我图库条数，不包括预设图片。图库上传、图片参考提示词、删除及默认项仍在工作台管理，不能通过此接口修改。图片参考提示词会随本次选中的图片自动应用。

```python
async def list_self_options(ctx):
    return await DrawingClient(ctx.api).references(page=1)
```

这些状态只供展示，不是授权凭证；提交和执行会重新检查开关。客户端不要缓存目录后假设永久可用。

## DrawingClient 方法与结果

初始化参数：`rpc_timeout=8` 秒（>0 且 ≤30）、`poll_interval=3` 秒（>0 且 ≤60）、`max_image_bytes=64 MiB`、`max_result_bytes=128 MiB`。客户端容量预算不改变服务端缓存或模型输出上限。

| 方法 | 用法/结果 |
| --- | --- |
| `submit(prompt, request_id=..., **request)` | 立即返回 TaskHandle；受理前明确拒绝抛 DrawingError，回执不可信返回 submission_unknown 句柄 |
| `generate(prompt, request_id=..., wait_seconds=120, read_images=True, **request)` | 提交一次，然后在有限预算内等待，返回 DrawingResult |
| `wait(handle_or_task_id, request_id=..., wait_seconds=120, read_images=True)` | 只等待已有任务；预算 >0 且 ≤3600 秒，不提交生成 |
| `task(task_id)` / `request(request_id)` | 一次只读查询，返回业务快照 |
| `recover(request_id, wait_seconds=120, read_images=True)` | 按原键只读找回，再等待同一任务 |
| `read_image(task_id, index=0)` | 分块校验后返回 bytes |
| `save_image(task_id, destination, index=0, overwrite=False)` | 读图并在线程中写入调用方指定文件 |
| `cancel(task_id)` / `tasks(page=1,status="",search="")` | 取消或管理任务 |
| `models()` / `references(page=1)` | 发现模型能力或只读自我参考目录 |
| `preferences(stream_id)` / `set_preferences(stream_id, **patch)` | 会话绘图覆盖值读写 |
| `presets()` / `preset(name)` / `save_preset(preset,name=...)` / `delete_preset(name)` | 预设目录与管理 |

`DrawingRequest` 支持提交表中的本次参数；`source_images` 可传 bytes 或现成 Base64。参考对象用 `reference_options`，不要把 RPC 专用的 `reference_options_json` 当客户端 kwargs 传入。

`TaskHandle` 重点读取 task_id、request_id、status、reused、error。`DrawingResult` 另有 images（下载成功的 GeneratedImage，字节在 `.data`）、image_references、generation_completed、results_readable、delivery 和 wait_expired。等待到期保留句柄，不自动取消。

生成结果太大时，客户端可以返回 `RESULT_TOO_LARGE` 且保留服务端图片引用；不要为降低本地下载尺寸而重新生成。可先用 `read_images=False` 等待，再分张保存或调整调用方自己的读取预算。

## 完整接入示例

以下 ctx 属于调用插件；输出目录和用户授权由调用方负责。首次调用前保存 request_id 与原始参数，回执后保存 task_id。

```python
import asyncio
import base64
from .vendor.maimai_drawing_client import DrawingClient, DrawingError
```

### 后台生成并保存

```python
async def background_draw(ctx, prompt, request_id, output):
    client = DrawingClient(ctx.api)
    try:
        result = await client.generate(
            prompt, request_id=request_id, wait_seconds=120
        )
    except DrawingError as exc:
        return {"code": exc.code, "request_id": exc.request_id}
    if result.wait_expired or result.status == "submission_unknown":
        return result  # 持久保存句柄，稍后恢复；不要取消或换新请求键。
    if result.error or not result.images:
        return result  # 拒绝、待确认、过期、读取失败分别保留在 status/error。
    await asyncio.to_thread(output.write_bytes, result.images[0].data)
    return result
```

### LLM 工具快速提交

```python
async def llm_submit(
    ctx, prompt, request_id, remaining_seconds,
    stream_id="", auto_send=False,
):
    if remaining_seconds <= 1:
        raise ValueError("工具剩余预算不足，请在后续调用提交")
    if auto_send and not stream_id:
        raise ValueError("自动发送需要已授权的真实聊天流")
    client = DrawingClient(ctx.api, rpc_timeout=min(8, remaining_seconds - 1))
    handle = await client.submit(
        prompt, request_id=request_id,
        stream_id=stream_id if auto_send else "",
    )
    return {"task_id": handle.task_id, "request_id": handle.request_id,
            "status": handle.status}
```

### 后续工具只读查询

```python
async def llm_query(ctx, task_id):
    # 调用前按自己保存的映射校验当前用户/会话是否有权访问此 task_id。
    return await DrawingClient(ctx.api).task(task_id)
```

### 显式图片编辑

```python
async def edit_picture(ctx, source, model, request_id):
    encoded = await asyncio.to_thread(
        lambda: base64.b64encode(source).decode("ascii")
    )
    return await DrawingClient(ctx.api).generate(
        "保留主体，把背景改成樱花树林",
        model=model, task_type="edit_image", source_images=[encoded],
        request_id=request_id, wait_seconds=120,
    )
```

### 回执丢失与等待到期后的恢复

```python
async def resume_drawing(ctx, saved, wait_seconds=120):
    client = DrawingClient(ctx.api)
    if saved.get("task_id"):
        return await client.wait(
            saved["task_id"], request_id=saved["request_id"],
            wait_seconds=wait_seconds,
        )
    # 2.1.1 起支持纯查询恢复，不需要再次发送提示词和图片。
    return await client.recover(saved["request_id"], wait_seconds=wait_seconds)
```


## 错误与恢复规则

v2 的可预期业务错误使用：

```json
{"code":"MATERIAL_SOURCE_DISABLED","message":"素材来源尚未开启：web","retry_query":false,"retry_submit":false}
```

不能从 message 字符串猜测是否重提。`retry_query` 允许继续读同一任务；`retry_submit` 仅说明该明确拒绝类型允许由调用方按其业务规则发起新的请求，**客户端不会自动重提**。传输未知、上游受理后断线、解析/下载失败或聊天发送未知不能触发第二次生成。

| 错误/状态 | 含义与处理 |
| --- | --- |
| `INVALID_REQUEST` | 类型、长度、预设名称/模式等参数不合法；修正输入 |
| `PERMISSION_DENIED` | 联动开关或会话名单拒绝；不绕过、不切换会话重发 |
| `CONCURRENCY_LIMIT` | 当前 4 个任务名额已用完；明确未受理时可由用户稍后重新发起 |
| `REQUEST_ID_CONFLICT` | 同一 request_id 对应不同显式参数；核对调用方保存的原始请求 |
| `REQUEST_NOT_FOUND` / `TASK_NOT_FOUND` | 未找到保留记录；不能据此判断从未受理 |
| `SELF_REFERENCE_DISABLED` / `SELF_REFERENCE_MISSING` | 自我参考未开启或缺图；由管理员配置或用户补图 |
| `SELF_SUBJECT_UNCERTAIN` | 自身指向不明确，先明确人物 |
| `MATERIAL_SOURCE_DISABLED` / `STREAM_UNAVAILABLE` | 来源未允许或真实会话不可用 |
| `REFERENCE_RECOGNITION_FAILED` | 分类/视觉识别失败或返回不合法，任务不继续猜测 |
| `MATERIAL_MISSING` | 没有满足特定主体/用途的真实参考，请补图 |
| `CHAT_MATERIAL_UNAVAILABLE` / `WEB_MATERIAL_UNAVAILABLE` | 来源服务、读取或下载出错；不会伪装成空结果 |
| `MATERIAL_BUDGET_EXCEEDED` / `MATERIAL_PREPARATION_TIMEOUT` | 识别预算或 90 秒准备时间用尽，请直接补充素材 |
| `MULTI_REFERENCE_CONFIRMATION_REQUIRED` | 由管理员在工作台 dialog 核实多图配置 |
| `REFERENCE_LIMIT_EXCEEDED` / `MATERIAL_LIMIT_EXCEEDED` | 图数或体积超限；减少输入 |
| `SOURCE_IMAGE_REQUIRED` / `TASK_MODE_CONFLICT` | 缺少真实图或新参考请求与显式模式冲突 |
| `MODERATION_REJECTED` | 提示词/图片审核拒绝，停止任务 |
| `UPSTREAM_UNCONFIRMED` / `RESTART_UNCONFIRMED` | 远端受理结果未知或重启中断；核对提供商/聊天记录，禁止自动重画 |
| `UPSTREAM_UNREACHABLE` / `UPSTREAM_REJECTED` | 明确连接不可达或提供商拒绝；读取具体 retry 字段 |
| `RESULT_NOT_READY` / `RESULT_EXPIRED` / `RESULT_UNAVAILABLE` | 暂无结果、已过期或未能缓存；查询/读取错误不证明应重画 |
| `SUBMISSION_UNKNOWN` | 客户端未取得可信受理回执，保留原键只读恢复 |
| `RESULT_TOO_LARGE` | 客户端读取预算不足，保留原任务与引用，不重新生成 |

未知运行异常仍由 SDK 报错并记录完整脱敏日志，不伪装为正常空状态。

## v1 兼容接口

v1 名称、参数、历史文字风格语义保留；不会自动注入自我图、预设图或进行素材搜索。历史文字风格仍可作用于 v1 图生图，这是与新 v2 图生图预设开关/跨模式勾选的兼容区别。

下面 helper 返回已经由 SDK 解包的原业务值。v1 不承诺 v2 的结构化错误与生成/缓存/投递分离字段：

```python
import asyncio
async def call_drawpic(plugin, name, **args):
    async with asyncio.timeout(8):
        return await plugin.ctx.api.call(
            f"maimai-drawpic-plugin.{name}", version="1", **args
        )
```


| v1 API | 参数 | 用法与差异 |
| --- | --- | --- |
| `drawpic_models` | 无 | 现行模型发现接口，能力字段见前文 |
| `drawpic_submit` | prompt；model/negative_prompt/style/task_type/stream_id/source_images/request_id 可选 | 返回 task_id/reused；没有 accepted。文生图不带源图，图生图要求显式真实源图；不支持单次参考选项 |
| `drawpic_task` | task_id | 返回旧任务详情；取消后的底层失败状态等不做 v2 状态映射 |
| `drawpic_tasks` | page=1,status="",search="" | 每页 12 条，旧目录包含 counts 和缩略图；状态仅 pending/running/completed/failed/rejected |
| `drawpic_image` | task_id,index=0,kind="preview",offset=0 | 默认 preview；original 分块规则相同，原图/预览没有 v2 error 契约保证 |
| `drawpic_cancel` | task_id | 保留旧取消响应，不具有 v2 upstream_cancelled 等保证 |
| `drawpic_presets` | operation/name/preset_json | 只投影历史文字风格字段；旧保存保留新增元数据，不允许读取、覆盖或删除图生图类型预设 |

v1 `style=""`/default 继续使用历史默认文字风格；`none` 跳过。升级调用方到 v2 时，必须按实际任务模式核对图生图预设开关与逐条兼容标记，而不是把旧参数原样解释为新图生图预设。

## 权限与资源边界

- 联动总开关位于“插件设置 → 运行设置”，默认开启。关闭后全部公开 API 拒绝；v2 返回 `PERMISSION_DENIED`，v1 沿用异常；工作台私有接口与聊天入口独立。已受理任务继续执行，不据此重提。
- 指定 stream_id 的提交与偏好操作依据宿主真实身份检查群聊/私聊名单。参考搜索的聊天来源额外要求真实会话；调用方参数不能覆盖该身份。调用插件仍负责自己的用户授权，接口不提供跨插件的用户鉴权系统。
- 没有 stream_id 时只生成并保留结果，不扣聊天额度、不自动发送；有 stream_id 时沿用会话权限和额度，调用方不要重复发送同一结果。
- 管理员可以单独开启成功投递生成图同步到 MaiSaka 历史。`delivery.status="sent"` 只确认消息投递，不确认视觉上下文已读取图片；同步失败不构成重发理由。
- 在调用生成前持久化任务/request_id。参数签名包含显式单次参考选项；未启用新参数的历史签名保留。相同键只找回原任务，不受后续 tag、配置或素材更新影响而另画一次。
- 在途任务使用读取到的资产版本；持久图库不进入生成图片缓存清理。重启中断标为待确认，不自动搜索并重放生成。图库总计最多 100 张、128 MiB；任务/request_id 最多保留 500 条。
- 生成缓存默认 300 MB，并受 30 天/500 任务清理；上传输入另有 24 小时/100 文件和容量限制。目录仍有任务记录不代表原图永久可读。
- 运行期参数、日志和错误会脱敏。公开目录不包含密钥、原始提示词/内部会话键或整张源图；不能通过修改 source_images 传服务器路径。
- `ctx.api.call(timeout_ms=...)` 不是 RPC 超时选项，它会作为业务参数传给目标接口。用客户端 rpc_timeout 或调用方 asyncio.timeout；等待预算不能突破外层 Tool/API 的截止时间。

[SDK API 指南](https://docs.mai-mai.org/plugin/api-components)介绍宿主组件机制。本页提供绘图插件的具体契约；复制客户端与服务端应同步升级，不自动降级，也不通过失败重试掩盖不兼容。
