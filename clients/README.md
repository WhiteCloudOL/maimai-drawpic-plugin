# 独立 DrawingClient

面向其他 MaiBot 插件开发者，封装短 RPC 的提交、查询、分块读取与保存。Python ≥3.12，仅依赖标准库；运行时注入自己的 `ctx.api`，不导入绘图插件内部目录。

当前绘图服务最低要求 MaiBot 1.3.19、插件 SDK 2.20.0。SDK 的 `ctx.api.call` 已返回解包后的业务结果，客户端直接校验该结果。

## 复制使用

把本目录的 **`maimai_drawing_client/` 整个目录**复制到调用插件的 `vendor/` 中，保留随包的 AGPL-3.0 许可证：

```text
my_plugin/
  plugin.py
  vendor/
    maimai_drawing_client/
      __init__.py
      client.py
      transport.py
      images.py
      models.py
      protocol.py
      LICENSE
```

在调用插件中使用显式相对导入：

```python
from .vendor.maimai_drawing_client import DrawingClient

# 在已注入 ctx 的插件后台协程中使用。
client = DrawingClient(self.ctx.api)
result = await client.generate(
    "海边的灯塔，水彩", request_id=saved_request_id, wait_seconds=120
)
```

`saved_request_id` 由调用方在首次请求前持久化；结果中的 task_id 也需要保存。完整运行函数、LLM 工具、图生图和超时恢复见[联动指南](../docs/integration.md)。

这是随绘图插件 **2.0.0** 提供的正式源码客户端，需要相应的 **v2 任务接口**；未发布到 PyPI，也不要求创建 pyproject.toml。复制代码与服务需要保持协议兼容，不自动回退至 v1。

**2.1.1 起**新增 request/recover、模型和任务目录、偏好读写与风格方法，以及单次任务模式参数；新增方法及参数要求绘图服务 ≥2.1.1，2.1.0 尚无对应新增接口。原有生成、等待与图片读取方法仍使用原 v2 协议。

## 方法

- `submit(prompt, request_id=..., **request)`：短调用，返回 `TaskHandle`，响应未知时保留请求键。
- `generate(..., wait_seconds=120, read_images=True)`：有限总预算内提交、等待并读取图片字节。
- `wait(handle_or_task_id, request_id=..., wait_seconds=120)`：只等待已有任务，不提交。
- `task(task_id)`、`cancel(task_id)`：读取结构化状态或请求取消。
- `request(request_id)`、`recover(request_id, wait_seconds=120)`：按原键只读找回任务，后者继续等待和取图，绝不重新提交。
- `models()`、`tasks(page=1, status="", search="")`：模型能力与任务分页；模型目录区分总体图生图能力和 Base64 API 编辑能力。
- `preferences(stream_id)`、`set_preferences(stream_id, **patch)`：读取或部分更新会话模型、OpenAI 模式、NAI 模式与画师；空字符串清除会话覆盖。
- `presets()`、`preset(name)`、`save_preset(preset, name=None)`、`delete_preset(name)`：管理实例共享风格；指定旧 name 可以重命名。
- `read_image(task_id, index=0)`：校验并拼接原图分块。
- `save_image(task_id, destination, index=0, overwrite=False)`：在工作线程中写入调用方指定路径；默认不覆盖。

构造参数：单次 RPC 默认 8 秒（大于 0、最多 30 秒），查询间隔默认 3 秒（大于 0、最多 60 秒），单图上限 64 MiB、单次结果上限 128 MiB。`generate`/`wait` 的总预算需大于 0、最多 3600 秒，包括 RPC、sleep 与取图，不能突破外层组件超时。

`DrawingRequest` 和 `DrawingPreferences` 提供编辑器可见的参数类型。提交支持图片 bytes 或 Base64 的列表/元组；底层仍传 Base64。`openai_compatibility_mode`、`novelai_mode`、`novelai_artist_tags` 可覆盖单次任务；详见[参数继承规则](../docs/integration.md#submit-参数与返回)。设置写入不自动重试；`DrawingTransportError` 表示结果可能未确认，应重新读取核对。没有平台、密钥或全局配置写入方法。

保存使用同目录临时文件；默认通过排他硬链接建立目标，需要目标文件系统支持硬链接（常见 NTFS/ext4 支持）。显式 `overwrite=True` 原子替换目标。路径必须由调用方限制在自己的获授目录；不采用上游文件名拼路径。

## 结果与错误

`DrawingResult` 分别提供 `status`、`wait_expired`、`generation_completed`、`results_readable`、`delivery`、`task_id`、`request_id`、`image_references`、`images` 与 `error`。成功取图后读取 `result.images[0].data`；图片字节不会进入默认 repr。

业务终态（拒绝、失败、待确认、图片过期）通过 `result.status/error` 表达。无效提交等明确 API 错误抛 `DrawingError`，含 `code`、`retry_query`、`retry_submit` 和句柄。单独 `task/read_image/save_image` 的 RPC 失败抛 `DrawingTransportError`；提交响应未知返回 `submission_unknown`，不会自动重新提交。

生成完成后若图片超过客户端单图或总容量限制，`generate`/`wait` 返回 `RESULT_TOO_LARGE` 并保留任务句柄、生成状态和图片引用。可以通过原 `task_id` 仅获取引用、逐张读取，或提高本地容量限制；这不是生成失败，不需要新请求。`DrawingTransportError` 在已有任务上下文时也保留句柄；不完整的任务或错误回执按协议错误处理，不泄漏原始 `KeyError`。

等待结束不取消任务、不换新 request_id；外部取消协程时保留 asyncio 的取消语义。LLM 工具应使用 `submit` 并快速返回，通过后续工具取结果；不要在临近超时的工具中创建无人管理的后台任务。

相关文档：[API 与四类示例](../docs/integration.md) · [用户指南](../docs/usage.md)。

## 主线新增：参考与素材

本次主线扩展 `DrawingRequest.reference_options` 并新增 `references(page=1)`。原 2.2.1 release 不包含这些新增参数/API；先确认服务端已经更新，不向旧服务端静默降级重试。

```python
handle = await client.submit(
    "麦麦穿冬装在海边", task_type="edit_image", request_id=saved_request_id,
    reference_options={"self_reference": "required", "self_reference_tags": ["冬装"]},
)
```

`reference_options` 使用可导出的 `DrawingReferenceOptions` 类型，包含 `self_reference`、`user_request`、`self_reference_ids`、`self_reference_tags`、`material_sources`。客户端自动序列化 JSON；未提供选项时不启用自我参考或自动搜索。全局开关、真实会话权限及多图 dialog 确认不能被参数绕过。

`style` 仍是统一预设名。`presets/preset/save_preset/delete_preset` 继续使用原方法，支持两类预设及跨模式标记；资源目录返回状态不代表授权。每个 API 的完整参数、返回值、错误及示例见[完整接口目录](../docs/integration.md#接口目录)。
