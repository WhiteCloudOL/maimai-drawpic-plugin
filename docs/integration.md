# 其他插件开发者接入

适合开发同一 MaiBot 实例内其他插件的开发者。本页说明任务 API、正式客户端、四类调用示例与失败恢复；仅使用工作台的用户请看[使用指南](usage.md)。

目录：[范围与依赖](#适用范围与依赖) · [最小提交](#最小提交示例) · [接入路径](#两条接入路径) · [完整示例](#完整示例) · [v2 参考](#v2-api-参考) · [错误](#结构化错误) · [超时与幂等](#超时幂等与恢复) · [v1 兼容](#v1-api-一览) · [接入排错](#常见接入错误)

## 适用范围与依赖

插件 ID：`maimai-drawpic-plugin`。调用由当前 Host 经 SDK 转发，不增加 HTTP 服务、独立令牌或跨实例客户端。仅供同实例的可信插件使用。

管理员可在 **偏好与预设 → 通用配置** 关闭默认开启的 `general.integration_api_enabled`，此时所有公开 v1 API 返回权限错误，v2 API 返回不可重试的 `PERMISSION_DENIED`；提交接口的 `accepted` 为 `false`，不创建任务。重新开启后可继续查询原任务，请勿据此自动重新生成。

仍在等待受理的提交会在创建任务前复查联动开关和会话名单；等待期间权限被撤销时返回 `PERMISSION_DENIED`，已预留的额度退回。已受理任务继续执行，不因关闭开关而重新生成或自动取消。

指定 `stream_id` 的新任务和会话偏好操作同时遵守群聊/私聊黑白名单，依据宿主真实会话中的群号、QQ 号或官方 OpenID 判断，调用方提供的用户/群参数不能覆盖此身份。管理员在界面填写这些原始 ID，无需填写会话哈希；API 的 `stream_id` 仍要求真实会话 ID。无目标会话的仅生成任务不匹配聊天名单，仍受联动开关控制。已受理任务继续执行，名单不会取消任务。详见[访问控制](configuration.md#插件联动与黑白名单)。

调用方 manifest 声明：

```json
{"capabilities": ["api.call"]}
```

还需要发现接口时再声明 `api.list` 或 `api.get`。绘图服务当前分支要求 MaiBot ≥1.3.19、SDK ≥2.20.0、Python ≥3.12 和配套 Dashboard；可用版本范围以插件清单为准。[MaiBot 1.3.19](https://github.com/Mai-with-u/MaiBot/blob/v1.3.19/pyproject.toml) 是首个将 SDK 依赖提升至 2.20.0 的正式版本。

管理员可在工作台通用配置中开启默认关闭的 `general.sync_generated_images_to_history`。开启后，仅成功投递到真实 `stream_id` 的生成图会由 Host 同步到当前 MaiSaka 历史；不指定会话的任务只生成结果。此选项可能增加视觉上下文和后台识图开销，且依赖对应会话的活动 MaiSaka 运行时。API 的 `delivery.status="sent"` 仅确认投递，不确认 Planner 已读取图片；同步失败或投递回执未知都不能成为重复发送的依据。详见[配置说明](configuration.md#生成图片与会话历史)。

正式 **`DrawingClient` 随插件 2.0.0 提供**，可整体复制 [clients/maimai_drawing_client](../clients/maimai_drawing_client)，仅依赖标准库。安装到调用插件的 `vendor/` 后：

```python
from .vendor.maimai_drawing_client import DrawingClient, DrawingError
```

下面函数中的 `ctx` 是**调用方插件**的上下文；它们可以作为插件内部方法委托的函数，不是新增 RPC。调用方在调用前持久保存 `request_id`、完整原始请求参数、用户/会话授权关联，收到响应后补存 `task_id`。客户端生成随机 request_id 仅为便利，不代替调用方的持久化。

### 版本约定

- v1 原有七个 API 名称、参数和取消返回保持兼容；显式传 `version="1"`。
- 新协议使用 `drawpic_submit_v2`、`drawpic_task_v2`、`drawpic_image_v2`、`drawpic_cancel_v2`、`drawpic_tasks_v2`，同时传 `version="2"`。
- 使用新名称是为了保留旧的无版本调用：当前 Host 对同名多版本且未给 version 的调用会报歧义。正式客户端显式使用新名称和版本，不自动降级。
- 模型发现 `drawpic_models` 继续是 v1；旧预设接口 `drawpic_presets` 保持兼容。
- 这些能力要求绘图插件 2.0.0；旧版本可能没有相同接口。没有新增长时间阻塞的 `drawpic_generate` RPC。
- **2.1.1 起**另增 `drawpic_request_v2`、会话偏好读写和 `drawpic_presets_v2`，并扩展单次模式参数。下文对应的新客户端方法要求绘图服务 ≥2.1.1，2.1.0 尚无这些新接口；没有接口时明确报错，不自动降级或重新生成。

## 最小提交示例

在调用插件的 Tool/Command/API 方法中委托此函数。`request_id` 由调用方在首次调用前保存，不从 LLM 自由文本中取得。

```python
from .vendor.maimai_drawing_client import DrawingClient

async def submit_drawing(ctx, prompt, request_id):
    client = DrawingClient(ctx.api)
    handle = await client.submit(prompt, request_id=request_id)
    # 保存 handle.task_id 与原 request_id 的对应关系。
    return {
        "task_id": handle.task_id,
        "request_id": handle.request_id,
        "status": handle.status,
        "message": "已提交" if handle.task_id else "提交响应未确认，请保留原请求键",
    }
```

受理成功只表示任务与幂等信息已落盘，不表示生成、缓存或发送成功。`task_id=None/status=submission_unknown` 表示未取得可信提交响应，应保留请求键，不能换键重画。

直接使用底层 API 时，SDK 已处理 Host 包装，`ctx.api.call` 直接返回目标 API 的业务结果；调用异常仍需保留原请求键，不能据此认定未受理：

```python
async def call_v2(ctx, operation, **args):
    return await ctx.api.call(
        f"maimai-drawpic-plugin.drawpic_{operation}_v2",
        version="2", **args,
    )
```

返回后继续检查业务 `error/accepted/status`，不再读取额外的 `success/result` 层。

## 两条接入路径

**普通后台协程**使用 `await client.generate(...)`：内部提交、多次短查询、分块取图，拿到 `DrawingResult`。它有有限总预算；到期返回句柄，调用者决定何时继续等待。

**LLM 工具**默认使用 `submit`，快速返回“已提交”和任务编号，由稍后的查询工具取状态。需要长时间等待时由调用插件的生命周期管理后台工作：保留任务引用、记录异常，卸载时取消并等待；不要在即将超时的工具里随手 `create_task`。

默认仅生成。用户明确要求回传当前聊天时，调用插件先校验真实会话与用户授权，再显式传 `stream_id`；此时绘图服务负责发送，调用插件不重复发送同一结果。

## 完整示例

四个函数共享正式客户端与同一任务/幂等机制。导入 `DrawingClient` 后即可嵌入调用插件；`request_id`、`task_id`、源图与路径均由调用方管理。业务拒绝等明确 API 错误为 `DrawingError`，按下面方式处理，不自动创建新请求。

### 普通后台：提交、等待、取图与失败处理

适合由插件生命周期管理的后台协程。`output` 是调用方授予目录下的明确目标路径，`request_id` 已持久化。

```python
import asyncio
from .vendor.maimai_drawing_client import DrawingClient, DrawingError

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

上例直接保存 generate 已读到的字节，`output` 为调用方提供的 `Path`，扩展名应与结果 `image_references[0]["format"]` 对应。若只需要引用，可传 `read_images=False`，之后使用 `await client.save_image(task_id, destination)` 在线程中排他、原子保存。后者默认不覆盖，目标文件系统需支持硬链接；显式 `overwrite=True` 才替换。

### LLM 工具：快速提交，稍后查询

函数是工具实现内部逻辑，注册装饰器和参数定义由调用插件提供。`remaining_seconds` 是调用方确认的剩余预算，预留至少 1 秒；`stream_id` 必须已验证归属，默认不发送。

```python
from .vendor.maimai_drawing_client import DrawingClient

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

async def llm_query(ctx, task_id):
    # 调用前按自己保存的映射校验当前用户/会话是否有权访问此 task_id。
    return await DrawingClient(ctx.api).task(task_id)
```

后续查询工具不等待整次生图，也不夹带整张图片。需要向聊天输出图片时决定由哪一方发送：已经选择 `auto_send=True` 时，查询 `delivery`，不要再次发送。

### 图生图：使用真实源图

适合普通后台，`source` 为调用方已校验、获准使用的图片 bytes，`model` 为 models 接口返回的完整名称。源图片与原始参数需要保存到调用方获授目录，以便恢复相同请求。

```python
import asyncio
import base64
from .vendor.maimai_drawing_client import DrawingClient

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

要求原图公网 URL 的模型不能通过此 Base64 接口编辑；缺能力或源图数量不符会在创建任务前拒绝。

### 等待结束或提交响应不确定后的恢复

`saved` 是调用方此前持久保存的对象，包含 `request_id`、可空 `task_id`、**完整且相同**的 `request` 参数（包括 prompt、模型、风格、源图和发送去向）。恢复前校验用户/会话归属。

```python
from .vendor.maimai_drawing_client import DrawingClient

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

去重记录已淘汰时，相同请求键可能重新产生任务，因此恢复前也需核对记录保留范围及提供商记录；`request_id` 不是永久幂等保证。

## v2 API 参考

以下接口名均带 `_v2` 且 `version="2"`。每次是短 RPC，无长等待接口。

| 接口 | 用途 |
| --- | --- |
| `drawpic_submit_v2` | 校验并持久受理，返回句柄与 accepted/reused |
| `drawpic_task_v2` | 查询任务状态、结构化错误、图片引用 |
| `drawpic_image_v2` | 读取预览或原图分块 |
| `drawpic_cancel_v2` | 请求取消并返回实际状态 |
| `drawpic_tasks_v2` | 分页恢复/管理任务，不夹带缩略图 |
| `drawpic_request_v2` | 按原 request_id 只读找回任务，不提交生成 |
| `drawpic_preferences_v2` | 读取真实会话的绘图偏好覆盖值 |
| `drawpic_preferences_set_v2` | 部分更新会话模型、兼容模式与 NAI 偏好 |
| `drawpic_presets_v2` | 风格预设查询、保存、重命名与删除，返回结构化错误 |

### submit 参数与返回

基础参数与 v1 相同，完整约束见下方 [drawpic_submit 参数表](#drawpic_submit)。默认 `stream_id=""` 不发送；显式回传只接受当前 Host 已存在的真实会话 ID，不能传 QQ 号或 OpenID 来创建会话。`source_images` 在底层只接受 Base64；客户端还接受图片 bytes 列表/元组，在线程中编码，单张编码仍最多 8 MiB。调用者不能指定本机文件路径或伪造 owner。客户端省略 request_id 时生成 UUID；底层允许空键，但不适合超时恢复。

2.1.1 起增加以下**仅本次任务生效**的参数，不修改会话、平台或默认配置：

| 参数 | 含义 |
| --- | --- |
| `openai_compatibility_mode=""` | `auto`、`images_api`、`chat_completions`、`rinkoai`；空值在回传会话时继承会话偏好，否则跟随平台默认 |
| `novelai_mode=""` | `anime`、`furry`、`background`；空值的继承规则同上 |
| `novelai_artist_tags=None` | `None` 在回传会话时继承会话画师偏好；文本覆盖，空文本跳过会话画师偏好并跟随平台默认 |

模型省略时继续使用工作台默认模型，不自动改为会话模型；需使用会话偏好模型时先读取偏好再显式传入。风格使用 `style` 预设名，未指定时遵循工作台默认风格；反向提示词使用 `negative_prompt`，仅在目标实例开启反向提示词后接受，并追加该实例默认词、与风格词去重及参与英文改写。关闭实例反向词时仍保留风格预设自己的内容；备选实例各自解析开关与默认词。模式只对对应平台生效。相同 request_id 下改变显式参数会返回冲突；未指定新参数的历史请求仍保持原签名。

`style` 省略或传空字符串均采用当前配置的默认风格；没有配置默认风格时使用原始描述。显式传入 `style="none"` 可跳过默认风格，传入其他预设名则只套用指定风格一次。

`negative_prompt` 提供本次全图反向文本。NovelAI 实例扩展参数中的多角色 `char_captions` 由该实例分别处理，保留角色顺序与坐标，并遵循反向词开关和英文改写设置；每个备选实例读取自己的角色配置。某个角色改写失败时任务终止，错误消息包含角色序号。

成功返回 `accepted=True`、`task_id`、`request_id`、`reused`，并附 task 结构。明确未受理返回 `accepted=False`、`task_id=None`、`status="not_accepted"` 和结构化 error。磁盘/Host/IPC 故障可能没有可信业务回执，客户端保留原请求键返回 submission_unknown，不假定未受理。

### task 返回结构

```json
{
  "task_id": "abcdef123456",
  "request_id": "persisted-request-01",
  "status": "completed",
  "images": [{
    "task_id": "abcdef123456", "index": 0, "format": "png",
    "mime": "image/png", "width": 1024, "height": 1024, "size": 123456,
    "expires_at": "2026-11-01T00:00:00+00:00", "available": true
  }],
  "error": null,
  "retry_after_ms": 0,
  "generation_completed": true,
  "results_readable": true,
  "delivery": {"requested": false, "status": "not_requested", "sent_count": 0}
}
```

这是**结构示意**，不表示固定输出格式或有效期限；其余兼容字段包括 model/provider/task_type/message/result_count/generated_count/sent_count 及时间。

状态为 `pending`、`running`、`completed`、`failed`、`rejected`、`cancelled`、`unconfirmed`。最后一项表示远端受理/结果未确认或重启中断本地等待，不能自动换键再生成。不存在/淘汰返回 `TASK_NOT_FOUND`，非法参数为 `INVALID_REQUEST`。查询不会启动绘图。

`images` 只含引用，不包含 data/data_url、内部路径或原始提示词。容量清理可能早于 expires_at，所以该时间是时间保留策略上限，不是可用承诺。没有缓存、旧任务无图片、已清理分别以结果错误表示；图片被清理不把已完成的生成改成失败。

`delivery.status` 为 `not_requested`、`pending`、`sent`、`partial`、`failed` 或 `unconfirmed`；查看它和 sent_count，不能把生成完成当作聊天发送成功。`unconfirmed` 表示发送未取得可靠回执，或旧记录不足以确定是否全部送达；即使部分图片已确认送达，也不能直接补发。`expected_delivery_count` 是审核后应发送的图片数，审核拦截的图片不计入“部分投递”；`generated_count` 仍表示原始生成数量。旧记录缺少精确预期数量但已有 sent_count 时保守返回 `unconfirmed`，不据此自动补发。

### image 参数与返回

`task_id` 必填；`index=0` 为零起点，必须是非负整数（不接受 bool）；`kind="original"`，还支持 `preview`、`thumbnail`；`offset=0` 为非负字节偏移。

原图每次最多读取 **192 KiB 原始字节**，编码后的 Base64 `data` 字段最多 **256 KiB**，另加 JSON 元数据。返回 `data/offset/next_offset/size/mime/filename/done/error`；offset、next_offset、size 均以原始字节为单位。从 0 开始，使用 next_offset；done=True 时解码后总长度必须等于 size。预览返回 `data_url/index/width/height/size/mime/expires_at/error`，data_url 自带实际 MIME；元数据 size/mime 描述原文件，不能假定预览为 JPEG。

图片未生成返回 `RESULT_NOT_READY`；不存在/清理返回 `RESULT_EXPIRED`；错误索引/偏移返回 `INVALID_REQUEST`。客户端校验总容量、分块大小、来源标记、偏移与终止标记；只重试读取同一分块，不重新提交绘图。

### cancel 参数与返回

只接受 task_id，返回当前 task 结构、`cancel_requested` 与 `upstream_cancelled=null`。已终结任务不报成“取消成功”，cancel_requested=False，状态保持原值；请求取消与完成竞争时查询实际状态。取消不保证远端撤单、线程停止或停止计费。

### tasks 参数与返回

`page=1`：整数 1～100；`status=""`：不筛选或上述任务状态；`search=""`：最多 200 字，匹配任务 ID、模型或消息。返回 `items/total/page/page_size=12/error`，每项为 task 结构，不夹带缩略图。

### request 与模型能力

`drawpic_request_v2(request_id)` 在持久化去重记录中查询，返回同一 task 结构。未找到为 `REQUEST_NOT_FOUND`，可能尚未受理完毕或已超出最多 500 条记录的保留范围，**不能据此自动重画**。`client.recover` 只查询、等待和读取原任务，任何情况下都不调用 submit；RPC 失败或预算结束仍保留原键。

`client.models()` 读取 v1 模型目录，新增 `draw_reason`、`api_edit_image`、`api_edit_reason`、`max_source_images`。`edit_image` 表示模型总体编辑能力；`api_edit_image` 表示当前 Base64 API 能否提供所需输入。例如百炼只接受原图 URL 的模型会单独说明限制。`max_source_images` 是模型已知上限与 API 上限 8 的较小值，未知模型按 API 上限；仍需先检查编辑能力，数量值不代表支持编辑。

### 绘图偏好与风格写入

`drawpic_preferences_v2(stream_id)` 返回 `stream_id/preferences/error`，preferences 包含以下四个字符串字段。`drawpic_preferences_set_v2(stream_id, preference_json)` 使用 JSON 对象**部分更新**，未给出的字段保留，空字符串清除会话覆盖并恢复默认行为：

| 字段 | 约束 |
| --- | --- |
| `model` | 已启用的完整 `平台名称/模型名称`，最多 200 字；不接受短名或索引 |
| `openai_compatibility_mode` | 上述四种 OpenAI 模式 |
| `novelai_mode` | `anime`、`furry`、`background` |
| `novelai_artist_tags` | 最多 16000 字 |

查询和写入均要求真实已有会话，不创建聊天流。群聊偏好作用于该群，私聊偏好作用于该用户；写入不能由未授权的群成员通过调用方插件越权触发。模型暂时停用时保留旧偏好，新的显式模型设置必须有效。

`drawpic_presets_v2(operation="list", name="", preset_json="")` 沿用下方 v1 预设字段与操作；客户端提供 `presets/preset/save_preset/delete_preset`。`save_preset(preset, name="旧名称")` 可重命名，同时更新默认风格引用；省略 name 时按 preset.name 创建或更新。预设是当前实例共享数据，删除当前默认预设会清空默认选择。保存响应可能含 `warning/runtime_refresh_pending/recovery_pending`，表示已保存但刷新或同步尚未完成，不能当作未保存再次盲写。

这三个设置 API 的预期错误统一返回 `error.code/message/retry_query/retry_submit`，成功 `error=null`；未知运行和存储异常继续由 SDK 报错。客户端写入不会自动重试，RPC 结果未知时先重新读取核对。

```python
async def configure_drawing(ctx, stream_id, model):
    client = DrawingClient(ctx.api)
    await client.set_preferences(stream_id, model=model, openai_compatibility_mode="images_api")
    await client.save_preset({"name": "水彩", "positive_prompt_template": "watercolor, {prompt}"})
    return await client.preferences(stream_id)
```

## 结构化错误

error 为 null 或对象：`code/message/retry_query/retry_submit`。message 为脱敏诊断，代码稳定；两个重试字段不能混为笼统 retryable。

`retry_query=True` 表示可继续查询或读取原任务。`retry_submit=True` 只表示该错误允许调用方决定是否再发起生成，不会自动重画：已经受理的终态仍绑定原键，重复原键会返回旧任务；只有明确未受理的容量拒绝等情形，才可稍后用原键重试受理。

| code | 含义与处理 |
| --- | --- |
| INVALID_REQUEST | 参数或模型能力不符，修正请求 |
| STREAM_UNAVAILABLE | 受理前已确认聊天流不可用，校验发送去向；不是提交状态未知 |
| REQUEST_ID_CONFLICT | 相同键配不同参数，停止并核对调用方状态 |
| CONCURRENCY_LIMIT | 4 个后台任务已满，稍后用原参数/键提交 |
| PERMISSION_DENIED | 聊天额度或权限拒绝 |
| TASK_NOT_FOUND | 记录不存在或被淘汰，核对保留范围 |
| REQUEST_NOT_FOUND | 原请求记录未找到，先核对受理进度、保留范围及提供商记录，不自动重画 |
| MODERATION_REJECTED | 审核拒绝，不自动重画 |
| UPSTREAM_REJECTED / UPSTREAM_UNREACHABLE | 明确上游拒绝或未建立连接，按错误标记决定人工恢复 |
| UPSTREAM_UNCONFIRMED / RESTART_UNCONFIRMED | 待确认，核对原提供商任务，不换键重画 |
| RESULT_NOT_READY | 尚无结果，可稍后查询 |
| RESULT_UNAVAILABLE / RESULT_EXPIRED | 生成后结果不可读，不能因此重新生图 |
| RESULT_TOO_LARGE | 客户端读取容量限制，任务仍保留；使用原 task_id 获取引用、逐张读取或调整本地上限，不重新提交 |
| DELIVERY_FAILED | 图片已生成但聊天发送失败，检查 delivery |
| DELIVERY_UNCONFIRMED | 发送未获得可靠回执，图片可能已送达；保留已确认 sent_count，先核对发送记录，不自动补发 |
| CANCELLED / SUBMISSION_INTERRUPTED | 本地等待取消或持久受理后尚未执行即中断 |
| EXECUTION_FAILED | 其他执行错误，保留任务诊断 |

`SUBMISSION_UNKNOWN` 属于客户端：未得到提交回执，保留 request_id。查询/读取 RPC 故障为 `DrawingTransportError`；generate 中读取失败转换为携带句柄的 RESULT_UNAVAILABLE。业务终态通过 DrawingResult.status/error 表达，明确无效提交等抛 DrawingError。`wait_expired` 是客户端等待结束，不是绘图失败。

## 超时、幂等与恢复

- 客户端单次 RPC 默认 8 秒，总等待默认 120 秒，必须有限且大于 0，最大 3600 秒；总预算包括提交、查询、sleep 和取图。调用方自带的任务/工具截止时间仍然生效。
- 当前 Host Tool/API 默认 60 秒，SDK capability 默认 30 秒，WebUI 绑定另有 10 秒边界。内部拆短 RPC 不能突破外层总截止时间。即将超时的工具只提交或留待后续调用，不能盲用 120 秒 generate。
- `ctx.api.call(timeout_ms=...)` 不是能力超时选项，会作为业务参数传递。绘图设置 request_timeout_seconds 是单次平台尝试预算，备选与安全重试会延长任务总时间。
- 任务记录、请求键、参数签名在同一次原子文件写入后才启动执行。写入失败不启动任务，也不留下可被误认为已受理的内存映射。提交协程取消会等待该次落盘结束，再记录尚未启动的中断。
- 去重保留范围是当前保留的**最多 500 条任务记录**，没有独立固定时间保证；相同键配不同参数报冲突。旧元数据兼容读取，重启后可从主任务文件恢复新映射。损坏文件停止加载，避免静默丢失幂等信息。
- 先前任务 pending/running 在重启后变为待确认，不自动重放；不承诺进程崩溃下 exactly-once，也不承诺已有远端任务能自动跨重启恢复。
- 上游已受理后只恢复同 ID 查询、同结果下载，不重新生成。恢复仍失败或受理未知时保留待确认/结果错误，人工核对提供商记录。
- 取消协程和本地任务不强制停止已经运行的同步线程。同步请求真正退出前继续占用本地任务名额；取消接口最多等待约 1 秒，仍在收尾时返回实际运行状态，不应误解为取消请求未收到。最多 4 个活动后台任务，没有持久化等待队列，满额直接拒绝。这仍不是上游物理请求计数或撤单保证。
- 终态写盘暂时失败时，只重试相同的状态保存，不重绘、不重新发图。持续失败会保留已知终态并附加 `persistence_pending=True`；后续查询或卸载会尝试补写。该标记清除前，进程崩溃可能丢失尚未落盘的终态，重启仍按未确认任务处理，不能据此自动重放。
- 卸载会等待仍持有的同步请求退出；超过每个服务约 5 秒的清理等待会明确报告卸载未完成，并保留资源引用。先检查原任务和提供商记录，避免在旧请求仍运行时启动重复任务。

### 任务归属

当前 Host 验证 API 可见性，但没有向静态 API 方法注入可供插件信赖的调用方身份，因此**不提供插件间逐任务隔离承诺**。不接受 owner 字符串来伪装鉴权。这是同实例可信插件接口；调用方必须校验用户/会话授权并保存自己的任务关联，预设写入属于管理能力。

保存图片只在调用方获授目录中进行。公开接口不读取任意路径，不开放平台密钥、原始日志或全局管理配置；写入范围限绘图会话偏好、共享风格预设和本次任务参数。`stream_id` 必须是真实已有聊天流，不自行哈希/构造。发送只在显式传入 stream_id 时发生。

## v1 API 一览

旧接口继续使用原名称和 `version="1"`。下面的预设示例在调用插件的异步方法中执行，`self` 是调用插件实例；共享这个短调用包装：

```python
import asyncio

async def call_drawpic(plugin, name, **args):
    async with asyncio.timeout(8):
        return await plugin.ctx.api.call(
            f"maimai-drawpic-plugin.{name}", version="1", **args
        )
```

SDK 同样直接返回 v1 业务结果；v1 错误沿用原有异常处理，不具有 v2 的结构化错误保证。修改预设属于管理操作，调用前应验证用户权限；超时后先读取预设确认结果，不能假定写入没有发生。

| 名称 | 参数 | 主要返回 |
| --- | --- | --- |
| `drawpic_models` | 无 | `models`：名称、平台实例名、上游模型名、`draw`/`edit_image` 能力和编辑限制原因；`default_model` |
| `drawpic_submit` | 见下表 | `task_id`、`reused` |
| `drawpic_task` | `task_id` | 状态、模型、平台、任务类型、消息、时间、发送数量、图片元数据 |
| `drawpic_tasks` | `page=1`、`status=""`、`search=""` | `items`、`total`、`page`、`page_size=12`、状态计数 `counts` |
| `drawpic_image` | `task_id`、`index=0`、`kind="preview"`、`offset=0` | 缩略图/预览的 `data_url`，或原图分块 |
| `drawpic_cancel` | `task_id` | `task_id`、`cancelled` |
| `drawpic_presets` | `operation="list"`、`name=""`、`preset_json=""` | 预设列表、单个预设或保存结果 |

`task_id` 为当前实例生成的 12 位十六进制 ID。不存在的任务、非法 ID、非法状态/页码/图片索引会报错。状态是 `pending`、`running`、`completed`、`failed`、`rejected`；取消后状态为 `failed`，消息为“任务已取消”。查询只读取状态，不执行重新绘图。列表带缩略图，单任务结果不包含原始提示词、平台密钥或内部文件路径。

### drawpic_submit

| 参数 | 默认值与约束 |
| --- | --- |
| `prompt` | 必填字符串，1～16000 字符 |
| `model` | `""` 使用当前默认模型，最多 200 字符；必须归属已启用平台，优先使用 models 接口返回的完整“实例名 / 模型名” |
| `negative_prompt` | `""`，最多 16000 字符 |
| `style` | `""` 不套用风格，最多 80 字符；可填写已启用的预设名 |
| `task_type` | `"draw"` 或 `"edit_image"` |
| `stream_id` | `""` 仅保存结果，最多 200 字符；填写真实聊天流 ID 时发送到聊天并沿用聊天额度规则 |
| `source_images` | `None` 或真实图片 Base64 字符串列表，不接受文件路径；最多 8 张，每张编码最多 8 MiB，总解码大小最多 40 MiB |
| `request_id` | `""` 或 8～80 位字母、数字、下划线、横线，用于安全重试 |

文生图不能附源图，图生图必须附真实源图；能力、数量和本地输入形式在创建任务前校验。要求公网原图 URL 的模型不能从此 Base64 接口发起图生图。只支持 PNG/JPEG/WebP 等实际可解码图片，输出保留经过审核的图片。

不填写 `stream_id` 时仍沿用插件的提示词与图片审核，不扣聊天额度。填写时必须是当前实例已有的聊天流，不要自行计算 session_id。SDK 调用方自行负责用户授权、会话归属和滥用限制；不应把提交、取消或预设写接口无条件提供给普通聊天用户。

### 图片读取

`kind="thumbnail"` 返回小缩略图；`kind="preview"` 返回压缩预览，两者均包含 `data_url`、`index`、`width`、`height`、原文件 `size` 与 `mime`。

`kind="original"` 每次返回最多 192 KiB 原文件的 Base64，字段为 `data`、`offset`、`next_offset`、`size`、`mime`、安全文件名 `filename` 与 `done`。从 0 开始，严格使用返回的 `next_offset`；按顺序拼接到 `done=True`。调用方应限制读取总量并在工作线程中进行文件写入，不阻塞事件循环。索引从 0 开始。

旧任务可能只有状态而没有图片。接口只读取当前实例结果目录的受校验文件，不接受任意路径。网页原图仅提供预览；插件调用方可以把分块内容保存到自己获授的数据目录。

### 预设管理

`operation` 可取 `list`、`get`、`save`、`delete`。`get` 和 `delete` 用 `name` 选择已有预设；`save` 的 `name` 用于选择要替换的旧预设，留空表示新建，`preset_json` 是 JSON 对象字符串。

```python
import json

preset = {
    "name": "水彩",
    "enabled": True,
    "description": "柔和的透明水彩质感",
    "positive_prompt_template": "watercolor, {prompt}",
    "negative_prompt_template": "3d render, {negative_prompt}",
}
await call_drawpic(self, "drawpic_presets", operation="save",
                   preset_json=json.dumps(preset, ensure_ascii=False))
styles = await call_drawpic(self, "drawpic_presets", operation="list")
await call_drawpic(self, "drawpic_presets", operation="delete", name="水彩")
```

预设名 1～80 字符，不区分大小写检查重名，最多 100 个。重命名时传旧名称作为 `name`；不接受未知字段。删除默认风格时会清空默认风格选择。写操作立即持久化并应用于之后的新任务。

## 安全与错误边界

这些公开 API 仅供同一个 Host 管理的可信插件使用，不是用户身份鉴权系统。Host 按调用方插件身份转发，其他 MaiBot 实例无法把自身 SDK 调用转发到此实例。请不要自行搭建网络转发层。

公开接口不暴露平台配置、API Key、代理密码、原始日志或任意文件访问；平台与全局设置修改只绑定到本插件 WebUI 的私有 API。同一类型的平台可有多个命名实例，完整模型名称用于精确选择实例；旧模型短名仅在唯一匹配时可用。任务和源图都限制在当前实例，参数长度、模型能力、源图片、并发和读取分块有固定限制；公开调用受通用配置中的联动开关控制。

参数错误、配置冲突、任务不存在、审核/平台失败应向调用者明确呈现。取消不保证上游平台停止计费；插件重启时会把未完成的旧任务标记为中断。配置变更后，执行中的任务继续使用提交时的服务，之后的新任务使用新配置。

生成图片与源图遵循 README 中的容量与过期清理策略，图片缓存默认 300 MB、日志默认 10 MB，由 MaiBot 插件配置页管理。新图片缓存在 SDK 临时目录，缩略图与预览使用 WebP；`data_url` 自带实际 MIME，调用方不应假定为 JPEG。任务状态可能仍存在而图片已清理，调用方应处理图片不可用；需要长期保存时及时复制到自己获授的数据目录。备选顺序和重试次数由工作台统一配置，公开 API 不能修改宿主网络代理、插件开关或缓存容量。

ComfyUI、阿里云异步任务受理后的查询连接失败只重试原远端 ID，不重新生成或改用备选；查询重试耗尽时本地任务为 `failed`，消息保留远端 ID 供检查。若总超时提前取消等待，任务消息可能只有超时原因，远端 ID 可从提交日志查找。此状态不代表上游任务已经终止。调用方不要因为查询失败而换用新的 `request_id` 重绘，先核对原任务的提供商记录。

## 常见接入错误

- **找不到 v2 API**：确认绘图插件已更新至 2.0.0，名称带 `_v2` 且 version 为 `"2"`；客户端不静默降级。
- **API 调用返回却未出图**：继续检查 accepted/status/error、results_readable 与 delivery；SDK 已解开 Host 包装，不应再读取 RPC success/result。
- **工具一直超时**：改为 submit 后返回 task_id，不把整次等待塞进工具/RPC；生命周期后台协程再用 generate/wait。
- **重复图片或重复发送**：持久保存 request_id 和完整参数，恢复不换键；只有一方负责发送。
- **读取失败后直接重画**：先检查 RESULT_NOT_READY、RESULT_EXPIRED、容量和提供商记录，读取故障不证明需要重新生成。
- **模型短名冲突**：通过 models 发现并使用完整“实例名 / 模型名”。

[SDK API 官方指南](https://docs.mai-mai.org/plugin/api-components)说明框架调用；本页的包装、版本和超时细节以目标环境的实际 Host/SDK 契约为准。

相关文档：[客户端复制与方法](../clients/README.md) · [平台能力](platforms.md) · [缓存与恢复](configuration.md) · [用户指南](usage.md) · [返回首页](../README.md)。
