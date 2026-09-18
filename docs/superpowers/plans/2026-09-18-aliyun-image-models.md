# 阿里云百炼图像模型完整支持实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不修改 MaiBot 主程序的前提下，让绘图插件完整支持千问 3.0/2.0/早期图像模型、Z-Image、可灵与 Vidu 图像模型，并正确处理同步/异步协议及适配器原始图片 URL。

**Architecture:** 新增纯模型能力模块，把模型族、任务能力、输入形式和参数构造从 HTTP 传输中分离；阿里云 Provider 共享鉴权、请求、轮询、解析和下载逻辑。消息链路使用结构化源图对象同时保留 Base64 与原始 URL，默认按模型选择输入形式，且保持其他平台现有字节调用不变。

**Tech Stack:** Python 3.12、aiohttp、Pydantic/maibot-sdk 配置模型、pytest、uv。

**Spec:** `docs/superpowers/specs/2026-09-18-aliyun-image-models-design.md`

## Global Constraints

- 只修改 `/Users/whitecloud/coding/Python/MaiBot/plugins/maimai-drawpic-plugin` 内文件，不修改 MaiBot 主程序。
- 遵循仓库 `AGENTS.md` 的 PEP8、导入顺序、类型注解、中文注释与精确报错要求。
- 不支持万象和创意工具，不新增视频生成功能。
- DashScope `base_url` 必须可配置，格式包含 `/api/v1`，不得硬编码用户工作空间地址。
- API Key 不得写入代码、测试、文档、日志或 Git 历史。
- 可灵/Vidu 图生图使用适配器原始 HTTP(S) URL；千问默认保持 Base64。
- 生产代码必须遵循 RED-GREEN-REFACTOR；每个新增行为先看到对应测试因缺少该行为而失败。
- 付费实测最多默认执行一次同步和一次异步请求，只有协议不一致时才追加一次针对性请求。

---

### Task 1: 建立阿里云模型能力注册表和参数构造器

**Files:**
- Create: `models/aliyun_models.py`
- Create: `tests/test_aliyun.py`
- Modify: `tests/test_imports.py`

**Interfaces:**
- Produces: `DEFAULT_ALIYUN_MODELS: tuple[str, ...]`
- Produces: `AliyunModelProfile`，字段为 `family`、`supports_draw`、`supports_edit`、`max_input_images`、`max_output_images`、`is_async`、`supported_input_modes`
- Produces: `AliyunRequestOptions`
- Produces: `resolve_aliyun_model_profile(model: str) -> AliyunModelProfile`
- Produces: `resolve_aliyun_image_input_mode(profile: AliyunModelProfile, configured_mode: str) -> str`
- Produces: `validate_aliyun_task(model: str, task_type: str, image_count: int, configured_input_mode: str) -> str`
- Produces: `build_aliyun_parameters(model: str, task_type: str, n: int, options: AliyunRequestOptions) -> dict[str, Any]`

- [x] **Step 1: 编写模型族、能力、输入模式和参数的失败测试**

在 `tests/test_aliyun.py` 建立与现有测试相同的包加载引导，测试至少包含：

```python
def test_builtin_models_have_expected_families_and_capabilities() -> None:
    assert resolve_aliyun_model_profile("qwen-image-3.0-pro").family == "qwen"
    assert resolve_aliyun_model_profile("qwen-image-3.0-pro").supports_edit is True
    assert resolve_aliyun_model_profile("z-image-turbo").supports_edit is False
    assert resolve_aliyun_model_profile("kling/kling-v3-image-generation").max_input_images == 1
    assert resolve_aliyun_model_profile("vidu/viduq3-fast_reference2image").max_input_images == 14


def test_auto_input_mode_uses_url_only_for_url_models() -> None:
    qwen = resolve_aliyun_model_profile("qwen-image-3.0")
    kling = resolve_aliyun_model_profile("kling/kling-v3-image-generation")
    assert resolve_aliyun_image_input_mode(qwen, "auto") == "base64"
    assert resolve_aliyun_image_input_mode(kling, "auto") == "url"


def test_family_parameters_do_not_leak_between_models() -> None:
    qwen_parameters = build_aliyun_parameters(
        "qwen-image-3.0",
        "draw",
        2,
        _request_options(),
    )
    kling_parameters = build_aliyun_parameters(
        "kling/kling-v3-image-generation",
        "draw",
        2,
        _request_options(),
    )
    assert qwen_parameters["prompt_extend_mode"] == "direct"
    assert "aspect_ratio" not in qwen_parameters
    assert kling_parameters["aspect_ratio"] == "1:1"
    assert "prompt_extend" not in kling_parameters
```

同时覆盖千问纯文生图/纯编辑模型、Z-Image 固定 `n=1`、Vidu 固定 `n=1`、可灵 Omni 组图参数以及无效 `image_input_mode`。

- [x] **Step 2: 运行测试并确认因新模块缺失而失败**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests/test_aliyun.py -q`

Expected: FAIL，原因是 `providers.aliyun_models` 不存在，而不是测试引导或依赖错误。

- [x] **Step 3: 实现最小模型注册表与参数构造器**

使用冻结 dataclass 和 `Literal` 类型，不执行网络操作。内置稳定及日期模型 ID，未知自定义模型返回 `legacy` profile 以兼容现有同步多模态行为。实现必须让族专用 `extra_parameters` 最后合并到对应族参数中，旧 `extra_parameters` 只供 `legacy` 使用。

- [x] **Step 4: 运行阿里云模型测试并确认通过**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests/test_aliyun.py -q`

Expected: PASS。

- [ ] **Step 5: 提交模型能力模块**

```bash
git add models/aliyun_models.py tests/test_aliyun.py tests/test_imports.py
git commit -m "feat(aliyun): add image model capability registry"
```

### Task 2: 保留适配器原始图片 URL

**Files:**
- Modify: `core/message_utils.py`
- Modify: `tests/test_fixes.py`

**Interfaces:**
- Produces: `SourceImageInput(base64_data: str, url: str = "")`
- Produces: `extract_source_images_from_message(message: dict[str, Any]) -> list[SourceImageInput]`
- Produces: `find_source_image_inputs(...) -> tuple[list[SourceImageInput], str]`
- Produces: `collect_command_source_image_inputs(...) -> list[SourceImageInput]`
- Preserves: `extract_all_image_base64_from_message`、`find_source_images` 与 `collect_command_source_images` 的现有返回类型，作为兼容包装器

- [x] **Step 1: 编写 URL 提取、去重、缓存和引用查找失败测试**

新增测试消息段同时包含 `binary_data_base64` 和 URL：

```python
def test_extract_source_images_preserves_adapter_url() -> None:
    message = {
        "message_segments": [
            {
                "type": "image",
                "binary_data_base64": _png_base64(),
                "url": "https://example.com/source.png",
            }
        ]
    }
    images = extract_source_images_from_message(message)
    assert images == [
        SourceImageInput(
            base64_data=_png_base64(),
            url="https://example.com/source.png",
        )
    ]
```

再覆盖 `data.url`、`image_url` 字符串/字典、`file_url`、`download_url`、非 HTTP(S) 地址过滤、`message_segments` 与 `raw_message` 重复数据去重，以及缓存后仍保留 URL。

- [x] **Step 2: 运行目标测试并确认缺少结构化源图接口**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests/test_fixes.py -k "source_image" -q`

Expected: FAIL，原因是新 dataclass/函数尚不存在。

- [x] **Step 3: 实现结构化源图和兼容包装器**

缓存值改为 `list[SourceImageInput]`。验证 Base64 时保留同一消息段中的 URL；只接受 `http://` 和 `https://`。兼容函数从结构化结果映射回 Base64 列表，确保现有调用者不被破坏。

- [x] **Step 4: 运行消息工具相关测试**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests/test_fixes.py -k "source_image or command_source" -q`

Expected: PASS。

- [x] **Step 5: 提交原始 URL 保留能力**

```bash
git add core/message_utils.py tests/test_fixes.py
git commit -m "feat(images): preserve adapter source URLs"
```

### Task 3: 重构阿里云 Provider 的同步、异步和 URL 输入

**Files:**
- Modify: `providers/aliyun_platform.py`
- Modify: `tests/test_aliyun.py`

**Interfaces:**
- Changes: `AliyunImage.__init__(..., base_url: str, image_input_mode: str, async_poll_interval_seconds: float, qwen_extra_parameters: dict[str, Any], zimage_extra_parameters: dict[str, Any], kling_extra_parameters: dict[str, Any], vidu_extra_parameters: dict[str, Any])`
- Produces: `AliyunImage.edit_images_with_urls(prompt: str, model: str, image_bytes_list: list[bytes], image_urls: list[str], n: int = 1) -> list[bytes]`
- Preserves: `AliyunImage.edit_images(...)`，内部以空 URL 列表调用新方法

- [x] **Step 1: 编写 Base URL、请求体和同步/异步行为失败测试**

使用测试子类覆写 `_post_json`、`_get_json`、`_download_image`，禁止真实网络。至少验证：

```python
def test_configured_base_url_builds_all_endpoints() -> None:
    provider = _provider(base_url="https://workspace.example/api/v1/")
    assert provider._build_url("services/aigc/multimodal-generation/generation") == (
        "https://workspace.example/api/v1/services/aigc/multimodal-generation/generation"
    )
    assert provider._build_url("tasks/task-1") == "https://workspace.example/api/v1/tasks/task-1"


def test_kling_edit_uses_adapter_url_in_async_payload() -> None:
    provider = _recording_provider()
    asyncio.run(
        provider.edit_images_with_urls(
            "保持主体",
            "kling/kling-v3-image-generation",
            [_png_bytes()],
            ["https://cdn.example/source.png"],
        )
    )
    assert provider.submitted_payload["input"]["messages"][0]["content"][1] == {
        "image": "https://cdn.example/source.png"
    }
```

覆盖千问 Base64、强制 URL 模式、可灵/Vidu 缺 URL 报错、异步提交头、任务状态变化、成功解析和四种终态错误。

错误测试还要断言异常包含模型、业务 `code`、`message` 与 `request_id`，日志中的 URL 不含查询参数，且不出现 Authorization、API Key、Base64 或签名值。

- [x] **Step 2: 运行测试并确认现有 Provider 不支持这些行为**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests/test_aliyun.py -q`

Expected: FAIL，原因包括构造参数、URL 构建或异步方法缺失。

- [x] **Step 3: 实现共享传输层**

保留现有 MIME 检测、图片下载和日志方法。新增 `_build_url`、去除查询参数的日志 URL 格式化、带可选额外请求头的 `_post_json`、`_get_json`、`_submit_async_task`、`_poll_async_task`。轮询仅在状态变化时记录模型、任务 ID、状态迁移和耗时，使用 `asyncio.sleep`，总时限交给外层 DrawService。HTTP 与业务错误统一携带 `request_id`，不得记录鉴权头、Base64 或签名查询参数。

`generate_images` 和 `edit_images_with_urls` 先解析 profile、校验任务、构造族专用请求，再按 `profile.is_async` 选择同步或异步。成功响应统一交给 `_extract_images`。

- [x] **Step 4: 运行 Provider 测试并确认通过**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests/test_aliyun.py -q`

Expected: PASS，且没有真实网络请求。

- [x] **Step 5: 提交 Provider 重构**

```bash
git add providers/aliyun_platform.py tests/test_aliyun.py
git commit -m "feat(aliyun): support sync and async image APIs"
```

### Task 4: 补齐配置并接入路由能力判断

**Files:**
- Modify: `core/config.py`
- Modify: `core/provider_router.py`
- Modify: `tests/test_aliyun.py`

**Interfaces:**
- Changes: `AliyunModelConfig` 增加 `base_url`、`seed`、`async_poll_interval_seconds`、`image_input_mode`、千问/Z-Image/可灵/Vidu 族专用字段
- Changes: `ProviderRouter.create_aliyun_provider()` 传递所有字段
- Changes: `GeneralConfig.text_to_image_unsupported_models` 增加“仅支持图生图模型”人工名单；现有 `image_edit_unsupported_models` 明确为“仅支持文生图模型”名单
- Produces: `ModelTaskCapability(allowed: bool, reason: str, source: str)`
- Produces: `ProviderRouter.evaluate_model_task_capability(model: str, task_type: str) -> ModelTaskCapability`
- Produces: `ProviderRouter.get_task_unsupported_reason(model: str, task_type: str) -> str`

- [ ] **Step 1: 编写配置默认值、Schema 标签、路由传参和能力失败测试**

验证 `base_url` 默认值为 `https://dashscope.aliyuncs.com/api/v1`，默认模型含规格列出的全部 ID 且不含 `wan`；必填字段标签含“必填”，可选参数提示含“可选”；路由创建的 Provider 获得自定义 Base URL 与四族参数。

验证 `z-image-turbo` 图生图、`qwen-image-edit` 文生图被自动提前拒绝，可灵/Vidu 文生图和图生图允许进入 Provider。再验证人工名单优先于自动识别：`image_edit_unsupported_models` 中的模型只允许文生图，`text_to_image_unsupported_models` 中的模型只允许图生图；同一模型同时出现在两张名单时返回配置冲突。能力结果需要同时返回面向用户的原因和判断来源，供日志使用。

- [ ] **Step 2: 运行测试并确认配置字段缺失**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests/test_aliyun.py -q`

Expected: FAIL，原因是配置或路由接口缺失。

- [ ] **Step 3: 实现配置与路由接线**

将 `PluginSectionConfig.config_version` 提升为 `2.24.0`。`AliyunModelConfig` 使用 `Literal["auto", "base64", "url"]`，数值字段添加 Pydantic 范围约束。保留旧字段名以兼容现有配置；旧通用 `extra_parameters` 仅传给 legacy profile。

路由能力提示调用模型注册表，不用字符串散落判断。已有 `general.image_edit_unsupported_models` 作为“仅支持文生图”人工覆盖，新增 `general.text_to_image_unsupported_models` 作为“仅支持图生图”人工覆盖；人工覆盖优先于自动结果，两张名单冲突时直接报错。

- [ ] **Step 4: 运行阿里云与路由回归测试**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests/test_aliyun.py plugins/maimai-drawpic-plugin/tests/test_volcengine.py -q`

Expected: PASS。

- [ ] **Step 5: 提交配置与路由**

```bash
git add core/config.py core/provider_router.py tests/test_aliyun.py
git commit -m "feat(aliyun): expose model family configuration"
```

### Task 5: 在后台绘图链路中传递原始 URL

**Files:**
- Modify: `core/draw_service.py`
- Modify: `plugin.py`
- Modify: `tests/test_fixes.py`
- Modify: `tests/test_aliyun.py`

**Interfaces:**
- Changes: `DrawService.start_background_image_request(..., source_image_urls: list[str] | None = None)`
- Changes: `DrawService._background_image_request(..., source_image_urls: list[str] | None = None)`
- Changes: `DrawService._run_image_request_attempt(..., source_image_urls: list[str])`
- Changes: `DrawpicPlugin._start_background_image_request(..., source_image_urls: list[str] | None = None)`

- [ ] **Step 1: 编写端到端链路失败测试**

构造 `SourceImageInput` 列表，验证插件拆出字节与 URL 后传给 DrawService；DrawService 在 `provider_name == "aliyun"` 时调用 `AliyunImage.edit_images_with_urls`，其他 provider 仍调用原 `edit_images`，不改变其签名。

覆盖首选阿里云失败后切换到非阿里云备选模型，以及非阿里云首选切换到阿里云备选时 URL 仍保留。

增加能力拒绝测试：中央插件入口在提示词审核、额度预留与任务创建前拒绝；聊天命令收到明确中文提示；工具返回 `{"success": False, "message": "..."}`；日志为 warning 且包含模型、任务类型与判断来源。DrawService 对首选和备选尝试均二次校验。

- [ ] **Step 2: 运行目标测试并确认 URL 在当前链路丢失**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests/test_fixes.py plugins/maimai-drawpic-plugin/tests/test_aliyun.py -k "source_url or aliyun" -q`

Expected: FAIL，原因是后台方法没有 URL 参数或调用了旧 `edit_images`。

- [ ] **Step 3: 实现最小 URL 透传**

插件收集源图时改用结构化接口，并分别生成 `source_image_bytes_list` 与等长的 `source_image_urls`。任务记录仍只持久化数量，不持久化临时 URL 或图片内容。DrawService 仅对真实 `AliyunImage` 调用 URL-aware 方法；其他 provider 完全保持现有调用。

在中央插件入口使用通用任务能力检查，确保失败时不扣额度、不创建任务；现有工具/指令异常处理负责分别生成工具失败返回和用户提示。在 `_build_image_request_attempt` 中对首选和备选模型再次使用相同检查，使编辑专用千问模型不能执行文生图，并防止配置热更新绕过校验。

- [ ] **Step 4: 运行绘图链路测试**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests/test_fixes.py plugins/maimai-drawpic-plugin/tests/test_aliyun.py -q`

Expected: PASS。

- [ ] **Step 5: 提交 URL 透传**

```bash
git add core/draw_service.py plugin.py tests/test_fixes.py tests/test_aliyun.py
git commit -m "feat(aliyun): pass adapter image URLs to providers"
```

### Task 6: 更新用户文档与版本

**Files:**
- Modify: `README.md`
- Modify: `_manifest.json`

**Interfaces:**
- Documents: 阿里云必填/可选字段、模型清单、同步/异步行为、URL/Base64 模式、限制与示例
- Changes: 插件版本 `1.11.2` -> `1.12.0`

- [ ] **Step 1: 编写文档完整性失败检查**

Run:

```bash
rg -n "qwen-image-3\.0|z-image-turbo|kling/kling-v3|vidu/viduq3|base_url|image_input_mode" README.md
```

Expected: 至少部分关键项缺失，证明 README 尚未覆盖新增能力。

- [ ] **Step 2: 更新 README 与 manifest**

README 明确：

- `api_key`、`base_url`、`models` 为必填；
- 其余字段为可选，并列出默认值和适用模型族；
- 自动能力识别规则，以及“仅支持文生图/仅支持图生图”两张人工覆盖名单；
- 工作空间专属地址示例使用占位符，不写用户实际 Host；
- `auto` 默认使千问使用 Base64、可灵/Vidu 使用适配器 URL；
- URL 缺失或过期时的明确错误及处理方式；
- 万象、创意工具、视频模型不在本版本范围。

将 `_manifest.json` 版本改为 `1.12.0`，不改依赖。

- [ ] **Step 3: 检查 JSON 与文档关键项**

Run:

```bash
uv run --project /Users/whitecloud/coding/Python/MaiBot python -m json.tool plugins/maimai-drawpic-plugin/_manifest.json >/dev/null
rg -n "qwen-image-3\.0|z-image-turbo|kling/kling-v3|vidu/viduq3|base_url|image_input_mode" plugins/maimai-drawpic-plugin/README.md
```

Expected: JSON 有效，所有关键项均命中。

- [ ] **Step 4: 提交文档与版本**

```bash
git add README.md _manifest.json
git commit -m "docs: document aliyun image model support"
```

### Task 7: 全量验证与最小付费实测

**Files:**
- Modify only if verification exposes a defect; every fix must first add a reproducing test

**Interfaces:**
- Consumes: Tasks 1-6 的全部实现
- Produces: 可重复的自动化验证证据和不包含密钥的实测结论

- [ ] **Step 1: 运行格式与静态检查**

Run:

```bash
uv run --project /Users/whitecloud/coding/Python/MaiBot ruff check \
  plugins/maimai-drawpic-plugin/models/aliyun_models.py \
  plugins/maimai-drawpic-plugin/providers/aliyun_platform.py \
  plugins/maimai-drawpic-plugin/core/message_utils.py \
  plugins/maimai-drawpic-plugin/core/config.py \
  plugins/maimai-drawpic-plugin/core/provider_router.py \
  plugins/maimai-drawpic-plugin/core/draw_service.py \
  plugins/maimai-drawpic-plugin/plugin.py \
  plugins/maimai-drawpic-plugin/tests/test_aliyun.py
```

Expected: PASS，不对无关文件执行批量格式化。

- [ ] **Step 2: 运行插件全量测试**

Run: `uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests -q`

Expected: PASS，无 warning/error。

- [ ] **Step 3: 搜索密钥、硬编码 Host 与越界修改**

Run:

```bash
git diff HEAD~6 -- . ':!docs/superpowers/**' | rg "sk-ws-|llm-s70v7wv74xyg1ez7" && exit 1 || true
git status --short
git diff --check HEAD~6
```

Expected: 不命中密钥或用户 Host；仅插件目录内预期文件发生变化；无空白错误。

- [ ] **Step 4: 使用临时环境变量执行一次同步真实请求**

仅在前述检查通过后，以不回显方式注入测试 Key 和用户提供的 `base_url`，调用 `qwen-image-3.0` 或账号实际开通的千问 3.0 型号生成 1 张低成本测试图。下载并校验返回内容为真实图片，不保存 Key，不提交生成图片。

Expected: 成功得到 1 张图片；若返回“模型未开通/无权限”，记录为账号能力限制，不修改协议实现。

- [ ] **Step 5: 使用同一临时环境执行一次异步真实请求**

选择账号已开通且价格较低的可灵或 Vidu 文生图模型，只生成 1 张最低分辨率图片，验证 `PENDING/RUNNING -> SUCCEEDED` 与下载。若服务未开通则不尝试另一个收费模型，避免无谓费用。

Expected: 成功得到 1 张图片，或得到可明确归因的开通/权限错误。

- [ ] **Step 6: 最终回归与工作区审计**

Run:

```bash
uv run --project /Users/whitecloud/coding/Python/MaiBot pytest plugins/maimai-drawpic-plugin/tests -q
git status --short
git log --oneline -8
```

Expected: 全部测试通过，工作区无未提交实现文件，提交均为 Conventional Commit。
