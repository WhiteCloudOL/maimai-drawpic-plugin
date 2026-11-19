# 插件联动 API 接入指南

本页面向同一 MaiBot 实例内的插件开发者，说明有哪些公开 API、各自的用途、参数、返回值和调用方法。仅使用绘图工作台的用户请看[使用指南](usage.md)；管理员配置见[配置说明](configuration.md)。

插件 ID 为 `maimai-drawpic-plugin`。所有接口均通过 Host 转发的 `ctx.api.call` 调用，没有额外 HTTP 监听、令牌或跨实例服务。

2.3.0 提供统一的 17 个公开接口，包含简易绘图、高级提交、自我参考设置、参考图库管理、两类绘图预设、素材来源、幂等任务恢复和会话偏好。接口及客户端需一起更新，不提供旧协议兼容入口。运行环境最低为 **MaiBot 1.3.19、插件 SDK 2.20.0、Python 3.12**，具体上限见 [_manifest.json](../_manifest.json)。[MaiBot 1.3.19 的依赖声明](https://github.com/Mai-with-u/MaiBot/blob/v1.3.19/pyproject.toml)首次将 SDK 最低依赖提升至 2.20.0。

目录：[接口目录](#接口目录) · [接入准备](#接入准备) · [最小调用](#最小调用) · [简易/高级调用](#简易调用与高级调用) · [高级提交](#drawpic_submit提交任务) · [参考素材](#参考与素材选项) · [查询恢复](#任务查询与恢复) · [图片读取](#drawpic_image读取图片) · [取消和列表](#任务取消与列表) · [模型目录](#drawpic_models模型目录) · [会话偏好](#会话偏好读写) · [绘图预设](#drawpic_presets绘图预设管理) · [参考目录](#drawpic_references参考目录) · [图库管理](#drawpic_reference_update参考图管理) · [自我设置](#drawpic_reference_settings自我参考及预设设置) · [客户端](#drawingclient方法与结果) · [完整示例](#完整接入示例) · [错误处理](#错误与恢复规则) · [权限和资源](#权限与资源边界)。

## 接口目录

调用时填写完整名称 `maimai-drawpic-plugin.<API 名>`，无需选择 API 版本。每个名称仅注册一个契约；SDK 元数据统一使用默认版本 `"1"`。所有接口均返回 `error` 字段，成功为 `null`，失败为结构化错误对象。

| API 名 | 作用 | DrawingClient 方法 |
| --- | --- | --- |
| `drawpic_draw` | 简易提交，按明确的源图、参考 ID 或预设自动选择绘图模式 | `draw` |
| `drawpic_submit` | 高级提交，显式控制模式、模型、预设、参考和本次参数 | `submit`；`generate` 内部也调用它 |
| `drawpic_task` | 查询单个任务、错误、结果引用和投递状态 | `task`、`wait` |
| `drawpic_request` | 回执丢失后按原 request_id 只读找回任务 | `request`、`recover` |
| `drawpic_image` | 读取原图分块、预览或缩略图 | `read_image`、`save_image` |
| `drawpic_cancel` | 请求取消当前实例的本地后台等待 | `cancel` |
| `drawpic_tasks` | 分页列出任务，支持状态和文字筛选 | `tasks` |
| `drawpic_preferences` | 读取真实聊天流的会话绘图覆盖值 | `preferences` |
| `drawpic_preferences_set` | 部分更新会话模型、兼容模式和 NAI 偏好 | `set_preferences` |
| `drawpic_presets` | 列出、读取、保存、重命名或删除两类预设 | `presets`、`preset`、`save_preset`、`delete_preset` |
| `drawpic_references` | 分页搜索自我及预设参考目录和功能状态 | `references` |
| `drawpic_reference` | 读取单张参考图元数据、提示词及版本 | `reference` |
| `drawpic_reference_update` | 上传、编辑、删除、设默认及排序参考图 | `save_reference`、`delete_reference`、`set_default_reference`、`move_reference` |
| `drawpic_reference_image` | 参考图预览或固定版本原图分块 | `reference_preview`、`read_reference_image`、`save_reference_image` |
| `drawpic_reference_settings` | 读取自我参考、触发关键词及默认预设设置 | `reference_settings` |
| `drawpic_reference_settings_set` | 按修订号部分更新上述设置 | `set_reference_settings` |
| `drawpic_models` | 列出完整模型名、文生图/图生图能力及输入限制 | `models` |

`workspace_*` 是工作台绑定的私有 API，不属于第三方插件接入契约。平台密钥、网络搜索密钥、通用运行配置和日志不公开；这里只开放绘图插件自己的自我参考及预设设置，不读写 MaiBot 全局人设。没有 `compose_image`、独立素材搜索 RPC 或长等待的 `drawpic_generate` RPC。

## 接入准备

调用插件在自己的 manifest 中声明：

```json
{"capabilities": ["api.call"]}
```

需要发现接口时再加入 `api.get`、`api.list`。例如读取 `maimai-drawpic-plugin.drawpic_references` 的元信息，可以判断目标主线是否提供新参考目录；不存在时明确提示升级，不剥掉参考选项重试，也不降级成另一种绘图。

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
import asyncio

async def call_drawing(ctx, endpoint, /, **args):
    async with asyncio.timeout(8):
        return await ctx.api.call(
            f"maimai-drawpic-plugin.drawpic_{endpoint}", **args,
        )
```

SDK/传输异常与业务错误分别处理。一次调用正常返回，不表示绘图成功；继续检查 `accepted/status/error`、`results_readable` 和 `delivery`。

## 简易调用与高级调用

| 需求 | 推荐调用 | 返回 |
| --- | --- | --- |
| 后台快速发起，参数越少越好 | `client.draw("画一只猫", request_id=...)` | TaskHandle，用 wait 或 task 跟进 |
| 一次 await 等待并获取图片 | `client.generate("画一只猫", request_id=..., wait_seconds=...)` | DrawingResult，内部走高级提交及短轮询 |
| 精确指定模式、多图、反向词、来源或 NAI 参数 | `client.submit(..., **request)` 后 wait | 持久任务句柄，等待预算由调用方控制 |

两种提交入口使用同一个后台执行和去重记录。提交前持久化 request_id；回执不确定时按原键查询，不能因为切换入口就换键重新画。

## drawpic_draw：简易绘图

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `prompt` | 必填 | 画面描述，1～16000 字符 |
| `model` | `""` | 完整平台/模型名称；留空使用插件默认模型 |
| `style` | `""` | 预设名称；none 跳过预设 |
| `source_image` | `""` | 一张真实图片 Base64；客户端可直接传 bytes |
| `reference_id` | `""` | 已上传的自我或预设参考图 ID |
| `self_reference` | false | 明确使用机器人自身形象，使用当前选图及默认图规则 |
| `stream_id` | `""` | 明确发送到该真实会话；留空只在后台保留结果 |
| `request_id` | `""` | 调用方持久化的 8～80 位请求键 |

有源图、reference_id、自我参考或显式图生图预设时使用图生图，否则文生图。自我图库 ID 会启用本次 required 选图，并检查全局自我参考开关。简易调用不隐式启用聊天取材、网络搜索或主体识别；需要这些能力用高级提交。模型能力、审核、额度、默认预设、图片限制和任务回执与 drawpic_submit 一致。

```python
async def quick_draw(ctx, prompt, saved_request_id, reference_id=""):
    client = DrawingClient(ctx.api)
    handle = await client.draw(prompt, request_id=saved_request_id, reference_id=reference_id)
    return await client.wait(handle, wait_seconds=120)
```

直接 SDK：`await ctx.api.call("maimai-drawpic-plugin.drawpic_draw", prompt="画一只猫", request_id=saved_request_id)`。返回 accepted、task_id、request_id、reused、状态、图片引用和结构化 error，格式与高级提交相同。

## drawpic_submit：提交任务

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
| `reference_options` | 对象 / `null` | 下节的单次参考选项；直接传字典，序列化后最多 60 KiB，最多 16 层、5000 个元素 |

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
| `self_reference_ids` | `[]` | 最多 8 个已存在自我图片 ID，优先于 tag；多选使用已确认组合，或由调用插件先确认后明确声明 |
| `self_reference_tags` | `[]` | 最多 32 个、每个 1～80 字符；未指定 ID 时按规范化 tag/原始请求匹配，未命中用指定默认图 |
| `reference_ids` | `[]` | 本次直接使用的预设图库 ID，最多 8 个；无需保存或修改风格预设；只接受 preset 类型 |
| `multi_reference_confirmed` | false | 调用插件已通过 dialog 确认所用模型支持本次多图组合；只用于该任务，不修改持久确认状态 |
| `material_sources` | `[]` | `chat`、`web` 的子集，不得重复；本次限制不能打开全局关闭的来源 |

未传参考选项的调用不会因管理员打开全局设置而突然读取聊天或联网。聊天工具和工作台按各自显式选择接入这些能力，外部 API 必须主动选择。

### 自我参考

先在工作台或通过下文的参考设置和图库 API 开启自我参考、上传 tag 图片并设置默认图。首张自我图片成为默认图；后续上传不自动更换默认项。图库存在并不代表功能已开启。名称/别称用于 auto 的语义判断；触发关键词仅在 planner 请求中提醒判断绘图，不用于直接认定人物。

聊天工具的 `auto` 只读取宿主随本次调用传入的原始消息段，可提取文本、语音转写和提及对象。仅有模型填写的 `user_request`、宿主处理后的展示文本或图片描述时，会按 `off` 继续绘图，并清除本次自我选图 ID 和 tag。未填或填错模式也按 `off` 处理。明确的 `required` 可直接使用自我图库。

聊天工具的素材取材独立读取请求文本。插件优先使用本轮消息，宿主未传消息时可使用调用方提供的 `user_request`。显式指定 `chat` 或 `web` 仍须有原话；未提供可用文本时不继承全局自动取材来源。

外部联动 API 根据调用方的 `reference_options` 判断**画面是否包含机器人自身**。支持以下三个小写字符串：

| 用户意图 | 填写方式 |
| --- | --- |
| 明确描绘机器人，或机器人与其他人物合照 | `"self_reference": "required"` |
| 画其他人物、动物或场景，或明确不使用自我图库 | `"self_reference": "off"` |
| 无法确定是否描绘机器人自身 | `"self_reference": "auto"`，同时填写非空的 `user_request` 用户原话 |

`true`、`false`、`yes`、`no`、机器人名字及 tag 均不是合法值。`auto` 识别为其他主体时跳过自我图片；识别为自身时才使用选中的自我图片，tag 未命中使用默认图。缺少原话与 tag 未命中不同：聊天工具缺原话时停用 auto，公开 API 显式要求 auto 时仍返回参数校验错误。

- `required` 在全局关闭时明确拒绝；`auto` 在关闭时跳过识别，不注入图片。
- 全局关闭时不能指定自我 ID/tag；`off` 也不能附带自身选图条件。
- 聊天工具会忽略全局关闭时模型传入的自我选项；公开 API 保持严格拒绝。已使用自我图片的在途任务会在素材准备后及绘图平台调用前重新检查开关，关闭后返回 `SELF_REFERENCE_DISABLED`，不继续提交自我图片。
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
| `["web"]` | 仅为具体角色、特定物件或明确参考图请求调用管理员选择的搜索服务 |
| `["chat", "web"]` | 分别按接续前图和具体实体条件触发，已有合适参考时不重复搜索 |

选择 `chat` 必须提供真实可访问的 stream_id；即使没有黑白名单，也不能省略会话校验。**该参数同时沿用结果投递契约**，因此调用前必须确认允许读取该聊天并发送结果。仅填写 stream_id 不等于允许历史搜索。

检查围绕“目标实体 + 图片用途”进行。已有一张机器人图片，不代表同框角色或特定服装已有可靠参考。原创人物、通用海边等通常无需搜索；角色、服装版本或具体物件则需要核对。搜索结果先经过真实图片与尺寸校验，再进行视觉匹配；网页标题和图片描述不作为图片输入。

来源关闭时零调用；显式请求关闭来源时报错。配置或鉴权错误会报告，单个网页或图片不可用时记录原因并检查剩余候选，全部不可用则报错，不会静默换服务。搜索结果不自动写入图库。

当前 SDK 搜索返回网页链接与正文，没有通用搜图候选字段。插件会有界提取正文中的图片链接；必要时按同一代理、地址及跳转规则读取网页图片标记。搜索服务必须由管理员在 MaiBot 配置并分配给联网搜索，插件不读取或复制其凭据。当前 SDK 的 `web.search` / `web.fetch` 只使用统一分配的服务，不支持服务商参数或服务目录查询；更换服务商需在 MaiBot 中调整分配。

工作台另提供独立 DeepSeek Search/Fetch API 路径，选择 `web_search_provider="deepseek"` 后使用工作台私有密钥。默认 `maibot` 路径继续使用宿主服务。调用方不能通过单次选项切换服务、设置密钥或覆盖管理员的识别模型。独立 Search API 返回网页，本次未接入带图输入的以图搜图工具。

取材识别由固定的一次语义分类给出 `chat_followup` 和具体实体需求；检索词必须包含原话中的实体，不对整句分词搜索。不确定或普通新任务不会读取历史。聊天候选优先使用 MaiBot 已识别描述，信息不足时才视图核对。接续前图失败会要求补图，不用网图代替前图。

管理员可选择 planner、replyer、vlm 或具体模型。`material_model` 默认 `vlm`；`task:planner`、`task:replyer` 选择宿主任务，`model:名称` 严格指定具体模型，建议快速多模态模型；调用方不能覆盖识别模型或扩大聊天范围。

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

`source_images` 支持列表，最多 8 张。自我/预设多图及其和其他图片合用前，必须由用户通过 dialog 核实所用服务商模型支持多图。可使用工作台已经确认的配置，也可由外部插件在自己的界面完成确认后，传入本次 `reference_options.multi_reference_confirmed=true`。此声明不自动探测模型、不跳过图生图能力及数量校验，也不能由 LLM 猜测或自动填写；插件自带聊天工具不开放这个确认字段。

生图前至少检查图生图能力，保留已知数量上限、输入方式与体积限制。确认不代表自动探测，也不能覆盖模型已知限制。提供商拒绝时不静默减图。

`task_type="draw"` 始终是纯文生图，不能因为参考选项或图生图预设而静默转换。`edit_image` 可以没有直接传入的 Base64，但生成前必须从显式配置或允许的素材来源得到真实图片，否则失败；不会降级成文生图。

## 任务查询与恢复

### drawpic_task

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

图片已生成、发送回执未知时，任务结束，返回 `status="completed"`、`generation_completed=true`、`delivery.status="unconfirmed"` 和诊断码 `DELIVERY_UNCONFIRMED`。`delivery.sent_count` 仅统计已获回执的图片，零张也可能实际送达。调用方应提示「图片已生成，送达状态未确认」，按 `results_readable` 决定是否读取原任务的图片，并避免自动重画或补发。

### drawpic_request

参数只有 `request_id`，格式与提交一致。只查询保留期内的持久映射，成功直接返回上面的任务快照，**没有额外 `accepted/record` 包装**。

```python
async def recover_receipt(ctx, saved_request_id):
    client = DrawingClient(ctx.api)
    snapshot = await client.request(saved_request_id)
    return await client.wait(snapshot["task_id"], request_id=saved_request_id, wait_seconds=120)
```

找不到时为 `REQUEST_NOT_FOUND`。可能仍在受理、查询了错误实例或记录已淘汰，不能据此认定从未受理。`recover` 内部只读找回并继续等待，不会重新提交提示词或图片。

## drawpic_image：读取图片

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

### drawpic_cancel

参数 `task_id` 必填。返回任务的实际快照，另有 `cancel_requested` 与 `upstream_cancelled`（当前为 null）。客户端：`await client.cancel(task_id)`。

只请求停止本地等待。上游可能已经受理并计费，不能承诺远端撤单；完成与取消竞争时保留实际终态。已完成任务不会为了取消而再次生成或投递。

### drawpic_tasks

| 参数 | 默认值 | 限制 |
| --- | --- | --- |
| `page` | 1 | 整数 1～100，每页固定 12 条 |
| `status` | `""` | 空值或任一任务状态 |
| `search` | `""` | 最多 200 字符，按任务号、模型和消息文字筛选 |

返回 `items/total/page/page_size/error`，items 为任务快照，不夹带缩略图内容。示例：`await client.tasks(page=1, status="running")`。这是当前实例的可信插件管理目录；调用插件不能直接无条件开放给普通聊天用户。

## drawpic_models：模型目录

统一的模型目录接口，没有参数。示例：`await client.models()`。

返回 `models/default_model/default_model_error`。每个模型包含完整 `name`、实例/提供商与真实模型信息，以及：

- `draw/draw_reason`：文生图能力与拒绝原因。
- `edit_image/edit_reason`：整体图生图能力。
- `api_edit_image/api_edit_reason`：是否接受公开 API/网页上传的本地图片输入；要求原图 URL 的模型可能不接受 Base64。
- `max_source_images`：主线已知数量上限与插件 8 张安全上限的交集；不能据此推断未经确认的多图支持。

目录仅供展示和事前检查；提交/生成前仍会重新检查实际模型能力。不增加自动多图试探或虚构的 `supports_multi_reference`。

## 会话偏好读写

### drawpic_preferences

必填参数 `stream_id`，返回 `stream_id/preferences/error`。偏好字段始终是字符串，空值表示没有对应会话覆盖。

### drawpic_preferences_set

必填 `stream_id` 与 `preferences`（字典对象），只部分更新提供的字段：

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

## drawpic_presets：绘图预设管理

参数为 `operation="list"`、`name=""`、`preset=None`、`confirm_multi_reference=false`。名称最多 80 字符，两类预设名称全局唯一。启用图生图预设或设置默认项使用 drawpic_reference_settings_set。

| operation | 参数 | 返回/作用 | 客户端 |
| --- | --- | --- | --- |
| `list` | 无需其他参数 | presets、default_style、image_edit_presets_enabled、default_image_edit_preset、error | `presets()` |
| `get` | name | preset/error | `preset(name)` |
| `save` | preset 对象；更新/重命名时 name 为旧名 | 创建或更新，返回最新目录；省略新增字段保留已有值 | `save_preset(preset, name=旧名)` |
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
| `multi_reference_confirmed` | false | 已确认配置状态；新增/变更多图组合或首次确认时，调用插件须先完成用户 dialog，再使用独立参数 confirm_multi_reference=true 保存 |

每个绑定包含 `asset_id`、`role`、`subject_id`、`note`。role 为 `identity/clothing/scene/lighting/composition/base`；note 最多 500 字符。身份参考标明对应人物，服装参考不额外增加一个出镜人物。同图可承担不同用途，最终编号一致并按真实内容去重。模型参考图数量上限按去重后的图片计算；相同图片来自上传、自我参考或预设时仍保留各来源的多图确认要求。

管理规则：

1. 文生图预设不绑定图片；图生图预设不可勾选跨模式标记。
2. 图生图预设总开关默认关闭，关闭时图生图不自动套用任何预设；显式要求套用则拒绝。总开关不影响图生图能力和独立自我参考。
3. 开启后，图生图使用图生图类型或已勾选兼容的文生图类型；一次只应用一条模板。
4. 显式选择优先；否则匹配当前模式允许的 tag，再使用模式默认项。图生图默认项未设置时，才考虑已勾选兼容的默认文生图预设。配置的默认项无效时明确报错。
5. 不会仅为套默认图生图预设而向纯文生图加入图片。图生图需要真实源图；显式图生图预设可以提供自己的关联图。
6. 关联图可在工作台或通过 drawpic_reference_update 上传。自我图库 ID 不能当作预设资产使用；描绘自身使用 self_reference 选项，并遵循自身开关。
7. 未确认就创建/改变多图配置返回 `MULTI_REFERENCE_CONFIRMATION_REQUIRED`。可在工作台确认，也可由外部插件先通过 dialog 确认，再传 confirm_multi_reference=true 保存；回执未知先 get/list 核对，不自动重试写入。

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

## drawpic_references：参考目录

| 参数 | 默认值 | 限制 |
| --- | --- | --- |
| page | 1 | 1～10，每页 12 条 |
| kind | 空字符串 | 全部；也可指定 self 或 preset |
| search | 空字符串 | 按名称和 tag 子串搜索，最多 200 字符 |

返回 `revision`（图库修订号）、default_reference_id、page/page_size/total、assets、功能状态及 error。total 是筛选后数量，排序沿用图库顺序。每条 asset 包含：

| 字段 | 意义 |
| --- | --- |
| id | 32 位十六进制 ID |
| kind | self 为机器人自身；preset 为场景等其他参考 |
| name/tags/prompt | 名称、匹配 tag、可选参考提示词（最多 500 字符） |
| version | 图片内容 SHA-256，64 位十六进制；只改名称/tag/prompt 不改变图片版本 |
| size | 原图字节数 |
| default | 是否为默认自我参考图 |

目录不含图片字节、任意文件路径、签名链接、候选图或搜索历史。来源状态仍包含 self_reference_enabled、allow_chat_material_search、chat_material_search_limit、material_model、allow_web_material_search、web_search_provider、multi_reference_confirmed，不含密钥。

```python
async def list_self_options(ctx):
    return await DrawingClient(ctx.api).references(page=1, kind="self")
```

聊天搜索上限由管理员设置，单次调用不能扩大。在途任务采用提交时与执行时较小的上限。目录中的状态只供展示，提交和执行仍会检查实际开关。

## drawpic_reference：单张参考图信息

必填 `asset_id`。返回 `{asset, revision, default_reference_id, error}`，asset 字段与目录相同。不存在返回 REFERENCE_NOT_FOUND。不返回文件内容；使用图片读取接口取图。

## drawpic_reference_update：参考图管理

| 参数 | 用法 |
| --- | --- |
| operation | 必填 save/delete/default/move |
| revision | 必填当前**图库**修订号，从 references/reference 或上次图片写入返回读取 |
| reference | 必填对象，按下表填写；不接受 JSON 字符串 |
| image_base64 | 仅 save 可提供，PNG/JPEG/WebP Base64 或 data URL；省略保留原图 |

| operation | reference 对象 | 行为 |
| --- | --- | --- |
| save 新增 | name 必填；kind 默认 self；tags 默认空列表，prompt 可选 | 必须同时上传图片，返回新 asset_id；首张 self 图片自动成为默认图，但不自动开启自我参考 |
| save 编辑 | asset_id 必填，其余 name/tags/prompt 可部分提供 | 未传字段保留；不能修改归属 kind；提供 image_base64 则替换原图 |
| delete | asset_id | 删除；被已保存的自我选图或风格预设引用时拒绝，不自动解除引用 |
| default | asset_id | 必须属于 self 图库，设置为默认自我参考 |
| move | asset_id、position | 在**全部 self/preset 图片混合列表**的零起始位置排序 |

返回 `{saved:true, revision, asset_id, asset, default_reference_id, deleted, error}`；删除时 asset 为 null，其他操作返回最新元数据。图库修改不会改变配置修订号。

名称 1～80 字符，tag 最多 32 个、每个最多 80 字符，prompt 最多 500 字符。单次 RPC 图片编码最多 8 MiB 字符，服务端另验证真实图片、像素及 20 MiB 单图限制；持久图库最多 100 张、总计 128 MiB。接口不接受 URL 下载指令或任意文件路径。

冲突返回 REFERENCE_REVISION_CONFLICT：重新读取图库、重新确认修改后再提交，不能无条件重试。写入响应丢失时先读取图库核对；客户端不会自动重新上传、删除或改默认。删除默认图片且无其他引用时，剩余首张 self 图片成为默认图，全部删除后默认 ID 为空。

## drawpic_reference_image：读取参考图片

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| asset_id | 必填 | 参考图 ID |
| kind | preview | preview 返回 WebP data_url；original 返回原图分块 |
| asset_version | 空字符串 | original 必填元数据中的 version；preview 可省略，或传入期望版本 |
| offset | 0 | original 的字节偏移；每次使用上次 next_offset；预览只允许 0 |

预览返回 asset_id、version、mime、data_url、error。原图返回 asset_id、version、data（本块 Base64）、offset、next_offset、size、mime、filename、done、error；每块最多 192 KiB，直到 done=true。filename 仅供展示，不能直接作为未校验的保存路径。

**参数必须叫 asset_version**：SDK 的 `version` 是接口版本保留参数，不能作为业务图片版本传入。图片在下载中被替换会返回 REFERENCE_VERSION_CONFLICT；客户端不会自动改版本拼接旧图和新图，下载完成后还会校验 SHA-256。

```python
async def copy_reference_image(ctx, asset_id, destination):
    client = DrawingClient(ctx.api)
    info = await client.reference(asset_id)
    return await client.save_reference_image(
        asset_id, destination, asset_version=info["asset"]["version"], overwrite=False,
    )
```

## drawpic_reference_settings：自我参考及预设设置

无参数。返回 `{revision, settings, runtime_refresh_pending, recovery_pending, error}`。这里的 revision 是**工作台配置**修订号，与图库 revision 独立；两个数字不能混用。settings 是持久设置，运行时刷新未完成时 pending 标志为 true。

| settings 字段 | 作用 |
| --- | --- |
| self_reference_enabled | 是否允许使用自身图库，默认 false |
| self_names | 机器人名称及别称，用于自身指向识别 |
| self_keywords | planner 已决定回复时使用的绘图触发关键词，不直接认定人物，不唤醒回复 |
| self_reference_ids | 固定使用的自身图片 ID；留空时按 tag/默认图选一张 |
| multi_reference_confirmed | 只读的持久多图确认状态 |
| image_edit_presets_enabled | 是否启用图生图预设，默认 false |
| default_style | 默认文生图预设名 |
| default_image_edit_preset | 默认图生图预设名 |

这里只包含绘图插件内的设定，不包含 MaiBot 全局人设、联网服务密钥或其他通用设置。

## drawpic_reference_settings_set：部分更新设置

必填 `settings` 对象（非空补丁）、`revision` 配置修订号，可选 `confirm_multi_reference=false`。可写上表除 multi_reference_confirmed 外的字段；未传字段保留，不允许传其他配置或密钥。名称和触发关键词各最多 32 个、每项 1～80 字符；固定自身图最多 8 个，必须是已有 self 资产。默认预设必须存在、已启用且类型匹配；空字符串清除默认。

自我参考关闭时可预先保存多图 ID，无需立即确认；这不会启用识别或图片注入。之后启用时，未确认的多图组合仍返回 `MULTI_REFERENCE_CONFIRMATION_REQUIRED`，须先完成 dialog 再传 `confirm_multi_reference=true`。

改变固定图片组合会清除原组合的确认。多选前须由用户完成 dialog 确认，再用独立 `confirm_multi_reference=true` 写入；这个参数不应由 LLM 决定。传入完整状态对象前应移除只读字段，推荐只发送需要改动的补丁。

返回最新 settings、revision、saved=true 及可能的 warning、runtime_refresh_pending、recovery_pending。已保存但刷新失败仍是已提交状态，应重读并提示重新加载，不能当作未写入而重试。修订号冲突先读取和确认修改；图库与配置都与工作台使用同一份存储和事务协调。

```python
async def configure_self_reference(ctx, image_bytes):
    client = DrawingClient(ctx.api)
    library = await client.references()
    image = await client.save_reference(
        {"name": "日常形象", "kind": "self", "tags": ["日常"], "prompt": "保留白色长发"},
        revision=library["revision"], image=image_bytes,
    )
    await client.set_default_reference(image["asset_id"], revision=image["revision"])
    settings = await client.reference_settings()
    saved = await client.set_reference_settings(
        revision=settings["revision"], self_reference_enabled=True,
        self_names=["麦麦", "小麦"], self_keywords=["画", "自拍"],
    )
    if saved.get("runtime_refresh_pending"):
        raise RuntimeError("设置已保存，请先重新加载绘图插件")
    return image["asset_id"]
```

设置完成后，简易调用 `client.draw("画你的日常自拍", reference_id=asset_id, request_id=...)`。高级调用可用 `reference_options={"self_reference":"required","self_reference_ids":[asset_id]}` 明确选图，或传 `self_reference_tags` 自动匹配；其他场景图用 `reference_ids` 直接引用，不需要修改全局预设。

## DrawingClient 方法与结果

初始化参数：`rpc_timeout=8` 秒（>0 且 ≤30）、`poll_interval=3` 秒（>0 且 ≤60）、`max_image_bytes=64 MiB`、`max_result_bytes=128 MiB`。客户端容量预算不改变服务端缓存或模型输出上限。

| 方法 | 用法/结果 |
| --- | --- |
| `draw(prompt, request_id=..., source_image=..., reference_id=...)` | 简易短提交，自动选择文生图/图生图 |
| `submit(prompt, request_id=..., **request)` | 立即返回 TaskHandle；受理前明确拒绝抛 DrawingError，回执不可信返回 submission_unknown 句柄 |
| `generate(prompt, request_id=..., wait_seconds=120, read_images=True, **request)` | 提交一次，然后在有限预算内等待，返回 DrawingResult |
| `wait(handle_or_task_id, request_id=..., wait_seconds=120, read_images=True)` | 只等待已有任务；预算 >0 且 ≤3600 秒，不提交生成 |
| `task(task_id)` / `request(request_id)` | 一次只读查询，返回业务快照 |
| `recover(request_id, wait_seconds=120, read_images=True)` | 按原键只读找回，再等待同一任务 |
| `read_image(task_id, index=0)` | 分块校验后返回 bytes |
| `save_image(task_id, destination, index=0, overwrite=False)` | 读图并在线程中写入调用方指定文件 |
| `cancel(task_id)` / `tasks(page=1,status="",search="")` | 取消或管理任务 |
| `models()` / `references(page=1,kind="",search="")` | 模型能力或分页参考目录 |
| `reference(asset_id)` / `reference_preview(asset_id,asset_version="")` | 单图信息或预览 |
| `save_reference(reference,revision=...,image=...)` | 新增/部分编辑，image 可直接传 bytes |
| `delete_reference` / `set_default_reference` / `move_reference` | 按图库修订号管理图片 |
| `read_reference_image` / `save_reference_image` | 下载固定 asset_version 原图并验证内容哈希 |
| `reference_settings()` / `set_reference_settings(revision=...,**patch)` | 自我设置及预设默认项读写 |
| `preferences(stream_id)` / `set_preferences(stream_id, **patch)` | 会话绘图覆盖值读写 |
| `presets()` / `preset(name)` / `save_preset(preset,name=...)` / `delete_preset(name)` | 预设目录与管理 |

`DrawingRequest` 支持提交表中的本次参数；`source_images` 可传 bytes 或现成 Base64。参考对象直接用 `reference_options`，与 SDK 直接调用保持一致。

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

全部公开接口的可预期业务错误使用：

```json
{"code":"MATERIAL_SOURCE_DISABLED","message":"素材来源尚未开启：web","retry_query":false,"retry_submit":false}
```

不能从 message 字符串猜测是否重提。`retry_query` 允许继续读同一任务；`retry_submit` 仅说明该明确拒绝类型允许由调用方按其业务规则发起新的请求，**客户端不会自动重提**。传输未知、上游受理后断线、解析/下载失败或聊天发送未知不能触发第二次生成。

| 错误/状态 | 含义与处理 |
| --- | --- |
| `INVALID_REQUEST` | 类型、长度、预设名称/模式等参数不合法；修正输入 |
| `REFERENCE_NOT_FOUND` | 参考图不存在或原图文件缺失；读取图库核对 |
| `REFERENCE_REVISION_CONFLICT` / `CONFIG_REVISION_CONFLICT` | 图库/配置修订号过期；重新读取并确认修改，不无条件重试写入 |
| `REFERENCE_VERSION_CONFLICT` | 下载期间图片已替换；明确选择新版本后重新开始下载，不混合分块 |
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

## 权限与资源边界

- 联动总开关位于“插件设置 → 运行设置”，默认开启。关闭后全部公开 API 拒绝；统一返回 `PERMISSION_DENIED`；工作台私有接口与聊天入口独立。已受理任务继续执行，不据此重提。
- 指定 stream_id 的提交与偏好操作依据宿主真实身份检查群聊/私聊名单。参考搜索的聊天来源额外要求真实会话；调用方参数不能覆盖该身份。调用插件仍负责自己的用户授权，接口不提供跨插件的用户鉴权系统。
- 没有 stream_id 时只生成并保留结果，不扣聊天额度、不自动发送；有 stream_id 时沿用会话权限和额度，调用方不要重复发送同一结果。
- 管理员可以单独开启成功投递生成图同步到 MaiSaka 历史。`delivery.status="sent"` 只确认消息投递，不确认视觉上下文已读取图片；同步失败不构成重发理由。
- 在调用生成前持久化任务/request_id。参数签名包含显式单次参考选项；未启用新参数的历史签名保留。相同键只找回原任务，不受后续 tag、配置或素材更新影响而另画一次。
- 在途任务使用读取到的资产版本；持久图库不进入生成图片缓存清理。重启中断标为待确认，不自动搜索并重放生成。图库总计最多 100 张、128 MiB；任务/request_id 最多保留 500 条。
- 生成缓存默认 300 MB，并受 30 天/500 任务清理；上传输入另有 24 小时/100 文件和容量限制。目录仍有任务记录不代表原图永久可读。
- 运行期参数、日志和错误会脱敏。公开目录不包含密钥、原始提示词/内部会话键或整张源图；不能通过修改 source_images 传服务器路径。
- `ctx.api.call(timeout_ms=...)` 不是 RPC 超时选项，它会作为业务参数传给目标接口。用客户端 rpc_timeout 或调用方 asyncio.timeout；等待预算不能突破外层 Tool/API 的截止时间。

[SDK API 指南](https://docs.mai-mai.org/plugin/api-components)介绍宿主组件机制。本页提供绘图插件的具体契约；复制客户端与服务端应同步升级，不自动降级，也不通过失败重试掩盖不兼容。
