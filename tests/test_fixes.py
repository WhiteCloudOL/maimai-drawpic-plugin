"""maimai-drawpic 插件修复验证测试。

不依赖 MaiBot core，只验证插件内部纯逻辑模块。
运行方式：在插件目录下执行 python tests/test_fixes.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import types
from pathlib import Path
from time import sleep

# 把插件目录加入 sys.path，以便直接 import 插件内部模块
_PLUGIN_DIR = Path(__file__).resolve().parent.parent
if str(_PLUGIN_DIR) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_DIR))

_PKG_NAME = "maimai_drawpic_pkg"
if _PKG_NAME not in sys.modules:
    _pkg = types.ModuleType(_PKG_NAME)
    _pkg.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[_PKG_NAME] = _pkg
for _sub in ("core", "providers"):
    _sub_path = _PLUGIN_DIR / _sub
    _init_file = _sub_path / "__init__.py"
    _full_name = f"{_PKG_NAME}.{_sub}"
    if _full_name in sys.modules:
        continue
    if _init_file.exists():
        _spec = importlib.util.spec_from_file_location(
            _full_name,
            _init_file,
            submodule_search_locations=[str(_sub_path)],
        )
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_full_name] = _mod
        _spec.loader.exec_module(_mod)
    else:
        # 无 __init__.py 的子包按命名空间包注册
        _ns = types.ModuleType(_full_name)
        _ns.__path__ = [str(_sub_path)]
        sys.modules[_full_name] = _ns

from core.image_utils import detect_image_dimensions, detect_image_format, detect_mime_type  # noqa: E402
from core.config import NovelAIModelConfig  # noqa: E402
from core.http_proxy import read_response_bytes, read_response_json  # noqa: E402
from core.message_utils import (  # noqa: E402
    _SOURCE_IMAGE_CACHE,
    _SOURCE_IMAGE_CACHE_ORDER,
    _normalize_stream_ids,
    _remember_source_image,
    find_all_cached_source_images,
)
from core.moderation import DrawpicModerationService  # noqa: E402
from core.stream_service import (  # noqa: E402
    ChatStreamService,
    ImageDeliveryUnconfirmedError,
)
from core.task_store import DrawTaskStore  # noqa: E402
from core.usage_store import UserQuotaStore  # noqa: E402
from maimai_drawpic_pkg.providers.novelai_platform import NovelAIImage  # noqa: E402

# 构造一张最小 PNG 字节用于图片工具测试
_MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeResponseContent:
    """模拟 aiohttp 流式响应体。"""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def iter_chunked(self, chunk_size: int):
        del chunk_size
        for chunk in self.chunks:
            yield chunk


class _FakeResponse:
    """提供响应大小校验所需的最小接口。"""

    def __init__(self, chunks: list[bytes], content_length: str = "") -> None:
        self.content = _FakeResponseContent(chunks)
        self.headers = {"Content-Length": content_length} if content_length else {}
        self.charset = None


class _FakeLogger:
    """记录日志的简易 logger，便于断言。"""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []
        self.debugs: list[str] = []

    def debug(self, message: str, *args: object) -> None:
        self.debugs.append(message % args if args else message)

    def warning(self, message: str, *args: object) -> None:
        self.warnings.append(message % args if args else message)

    def info(self, message: str, *args: object) -> None:
        self.infos.append(message % args if args else message)

    def error(self, message: str, *args: object) -> None:
        self.errors.append(message % args if args else message)


def test_image_utils_detect_mime_type() -> None:
    assert detect_mime_type(_MINIMAL_PNG) == "image/png"
    assert detect_image_format(_MINIMAL_PNG) == "png"
    dims = detect_image_dimensions(_MINIMAL_PNG)
    assert dims == (1, 1), dims
    print("[OK] image_utils: detect_mime_type / detect_image_format / detect_image_dimensions")


def test_provider_response_size_limit_applies_to_json() -> None:
    """图片服务的 JSON 与二进制响应均受统一大小限制。"""

    async def _run() -> None:
        response_json = await read_response_json(_FakeResponse([b'{"ok": true}']))
        assert response_json == {"ok": True}

        oversized_response = _FakeResponse([b"1234", b"5678"])
        try:
            await read_response_bytes(oversized_response, max_bytes=7)
        except RuntimeError as exc:
            assert "超过大小限制" in str(exc)
        else:
            raise AssertionError("超大响应应被拒绝")

    asyncio.run(_run())
    print("[OK] http_proxy: JSON 与二进制响应大小限制")


def test_novelai_v5_payload_uses_v5_parameters() -> None:
    """NovelAI V5 请求使用结构化提示词和官方推荐噪声调度。"""

    provider = NovelAIImage(
        api_key="test-key",
        noise_schedule="native",
        v4_noise_schedule="exponential",
        negative_prompt="low quality",
        quality_toggle=False,
        sm=True,
        sm_dyn=True,
        extra_parameters={
            "params_version": 3,
            "noise_schedule": "exponential",
            "reference_image_multiple": ["unsupported"],
            "skip_cfg_above_sigma": 19,
        },
    )
    payload = provider._build_payload(
        prompt="1girl",
        model="nai-diffusion-5-full",
        action="generate",
        n=1,
    )
    parameters = payload["parameters"]

    assert parameters["params_version"] == 4
    assert parameters["noise_schedule"] == "karras"
    assert parameters["negative_prompt"] == "low quality"
    assert "uc" not in parameters
    assert parameters["cfg_rescale"] == 0
    assert parameters["dynamic_thresholding"] is False
    assert parameters["deliberate_euler_ancestral_bug"] is False
    assert parameters["prefer_brownian"] is True
    assert parameters["v4_prompt"]["caption"]["base_caption"] == "1girl"
    assert parameters["v4_negative_prompt"]["caption"]["base_caption"] == "low quality"
    assert "qualityToggle" not in parameters
    assert "ucPreset" not in parameters
    assert "sm" not in parameters
    assert "sm_dyn" not in parameters
    assert "reference_image_multiple" not in parameters
    assert "skip_cfg_above_sigma" not in parameters
    print("[OK] NovelAI V5: 使用官方参数并清理不支持字段")


def test_novelai_v4_and_v3_payloads_use_supported_parameters() -> None:
    """NovelAI V4 与 V3 请求使用各自支持的参数格式。"""

    provider = NovelAIImage(
        api_key="test-key",
        noise_schedule="native",
        v4_noise_schedule="exponential",
        negative_prompt="low quality",
        quality_toggle=False,
        sm=True,
        sm_dyn=True,
    )
    for model in (
        "nai-diffusion-4-full",
        "nai-diffusion-4-curated-preview",
        "nai-diffusion-4-5-full",
        "nai-diffusion-4-5-curated",
    ):
        v4_parameters = provider._build_payload(
            prompt="1girl",
            model=model,
            action="generate",
            n=1,
        )["parameters"]
        assert v4_parameters["params_version"] == 4
        assert v4_parameters["noise_schedule"] == "exponential"
        assert v4_parameters["prefer_brownian"] is True
        assert v4_parameters["deliberate_euler_ancestral_bug"] is False
        assert "uc" not in v4_parameters
        assert "sm" not in v4_parameters
        assert "sm_dyn" not in v4_parameters
        assert "qualityToggle" not in v4_parameters
        assert "ucPreset" not in v4_parameters

    for model in ("nai-diffusion-3", "nai-diffusion-furry-3"):
        v3_parameters = provider._build_payload(
            prompt="1girl",
            model=model,
            action="generate",
            n=1,
        )["parameters"]
        assert v3_parameters["noise_schedule"] == "native"
        assert "uc" not in v3_parameters
        assert v3_parameters["negative_prompt"] == "low quality"
        assert v3_parameters["params_version"] == 4
        assert v3_parameters["sm"] is True
        assert v3_parameters["sm_dyn"] is True
        assert "qualityToggle" not in v3_parameters
        assert "ucPreset" not in v3_parameters

    v3_img2img_parameters = provider._build_payload(
        prompt="1girl",
        model="nai-diffusion-3",
        action="img2img",
        n=1,
    )["parameters"]
    assert "sm" not in v3_img2img_parameters
    assert "sm_dyn" not in v3_img2img_parameters
    assert v3_img2img_parameters["add_original_image"] is True
    assert v3_img2img_parameters["extra_noise_seed"] == v3_img2img_parameters["seed"]
    print("[OK] NovelAI V4/V3: 使用模型支持的参数格式")


def test_novelai_quality_tags_follow_model_family() -> None:
    """NovelAI 质量增强按模型追加官方质量标签。"""

    provider = NovelAIImage(api_key="test-key", quality_toggle=True)
    quality_suffixes = {
        "nai-diffusion-5-full": "very aesthetic, masterpiece, no text",
        "nai-diffusion-5-curated": "very aesthetic, masterpiece, no text",
        "nai-diffusion-4-5-full": "very aesthetic, masterpiece, no text",
        "nai-diffusion-4-5-curated": (
            "very aesthetic, masterpiece, no text, -0.8::feet::, rating:general"
        ),
        "nai-diffusion-4-full": "no text, best quality, very aesthetic, absurdres",
        "nai-diffusion-4-curated-preview": "rating:general, best quality, very aesthetic, absurdres",
        "nai-diffusion-3": "best quality, amazing quality, very aesthetic, absurdres",
        "nai-diffusion-furry-3": "{best quality}, {amazing quality}",
    }
    for model, suffix in quality_suffixes.items():
        payload = provider._build_payload(
            prompt="1girl",
            model=model,
            action="generate",
            n=1,
        )
        assert payload["input"] == f"1girl, {suffix}"

    v5_payload = provider._build_payload(
        prompt="1girl\nText: HELLO",
        model="nai-diffusion-5-full",
        action="generate",
        n=1,
    )
    assert v5_payload["input"] == "1girl, very aesthetic, masterpiece, no text\nText: HELLO"
    assert v5_payload["parameters"]["v4_prompt"]["caption"]["base_caption"] == v5_payload["input"]

    furry_v3_payload = provider._build_payload(
        prompt="1girl|forest:0.4",
        model="nai-diffusion-furry-3",
        action="generate",
        n=1,
    )
    assert furry_v3_payload["input"] == (
        "1girl, {best quality}, {amazing quality}|forest, {best quality}, {amazing quality}:0.4"
    )
    print("[OK] NovelAI 质量增强：按模型追加标签并保留 Text/混合提示词结构")


def test_novelai_sampler_compatibility_is_model_specific() -> None:
    """NovelAI DDIM 采样器按 V3 与 V4+ 的兼容规则转换。"""

    provider = NovelAIImage(
        api_key="test-key",
        sampler="ddim",
        quality_toggle=False,
    )
    v3_parameters = provider._build_payload(
        prompt="1girl",
        model="nai-diffusion-3",
        action="generate",
        n=1,
    )["parameters"]
    assert v3_parameters["sampler"] == "ddim_v3"
    assert "prefer_brownian" not in v3_parameters
    assert "sm" not in v3_parameters
    assert "sm_dyn" not in v3_parameters

    for model in ("nai-diffusion-4-full", "nai-diffusion-5-full"):
        parameters = provider._build_payload(
            prompt="1girl",
            model=model,
            action="generate",
            n=1,
        )["parameters"]
        assert parameters["sampler"] == "k_euler_ancestral"
        assert parameters["prefer_brownian"] is True
    print("[OK] NovelAI 采样器：V3 与 V4+ 使用对应 DDIM 兼容规则")


def test_novelai_custom_gateway_keeps_legacy_parameters() -> None:
    """NovelAPI 自定义模型继续接收兼容网关所需的旧版字段。"""

    provider = NovelAIImage(
        api_key="test-key",
        uc_preset=2,
        quality_toggle=True,
        sm=True,
        sm_dyn=True,
    )
    parameters = provider._build_payload(
        prompt="1girl",
        model="gateway-custom-model",
        action="generate",
        n=1,
    )["parameters"]
    assert parameters["ucPreset"] == 2
    assert parameters["qualityToggle"] is True
    assert parameters["sm"] is True
    assert parameters["sm_dyn"] is True
    print("[OK] NovelAPI 兼容网关：保留旧版参数")


def test_novelai_defaults_include_v5_models() -> None:
    """NovelAI 默认模型列表包含 V5 Full 与 Curated。"""

    configured_models = NovelAIModelConfig().models
    assert "nai-diffusion-5-full" in configured_models
    assert "nai-diffusion-5-curated" in configured_models
    print("[OK] NovelAI 配置：默认模型列表包含 V5")


def test_task_store_update_missing_task_returns_none() -> None:
    """P0-1: update_task 对不存在的 task_id 返回 None 而非抛 KeyError。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = DrawTaskStore(path=Path(tmp) / "tasks.json", logger=_FakeLogger())
        store.load()
        # 直接调用 update_task，task_id 不存在
        result = store.update_task("nonexistent-id", status="failed", message="test")
        assert result is None, f"期望 None，得到 {result!r}"
        # mark_status_queried 同理
        result2 = store.mark_status_queried("nonexistent-id")
        assert result2 is None, f"期望 None，得到 {result2!r}"
        print("[OK] task_store: update_task / mark_status_queried 对缺失 task 返回 None")


def test_task_store_normal_flow_still_works() -> None:
    """确保正常任务流程未被破坏。"""
    with tempfile.TemporaryDirectory() as tmp:
        logger = _FakeLogger()
        store = DrawTaskStore(path=Path(tmp) / "tasks.json", logger=logger)
        store.load()
        record = store.create_task(
            session_key="qq:group:1",
            stream_id="s1",
            task_type="draw",
            prompt="hello",
            model="m1",
            provider="aliyun",
            message="pending",
        )
        updated = store.update_task(record.task_id, status="running", message="running")
        assert updated is not None and updated.status == "running"
        queried = store.mark_status_queried(record.task_id)
        assert queried is not None and queried.last_status_query_at is not None
        print("[OK] task_store: 正常任务流程仍然工作")


def test_moderation_parse_review_response_robust() -> None:
    """P1-3: 审核结论解析增强鲁棒性。"""
    # 标准格式
    r = DrawpicModerationService._parse_review_response("结论：PASS\n原因：安全")
    assert r.passed is True and r.reason == "安全"
    r = DrawpicModerationService._parse_review_response("结论：REJECT\n原因：违规")
    assert r.passed is False and r.reason == "违规"
    # 半角冒号
    r = DrawpicModerationService._parse_review_response("结论: PASS")
    assert r.passed is True
    # 多行前置说明 + 独立结论行
    r = DrawpicModerationService._parse_review_response("好的，我来审核。\n结论：PASS\n原因：ok")
    assert r.passed is True, "多行前置说明后应识别 PASS"
    r = DrawpicModerationService._parse_review_response("分析完毕。\n结论：REJECT\n原因：不安全")
    assert r.passed is False, "多行前置说明后应识别 REJECT"
    # 否定句和非结构化关键词不能作为审核结论
    for invalid_response in (
        "NOT PASS",
        "This content cannot pass moderation",
        "应当 REJECT 该内容",
        "结论：PASS\n结论：REJECT",
    ):
        try:
            DrawpicModerationService._parse_review_response(invalid_response)
            raise AssertionError("非结构化审核结果应抛 RuntimeError")
        except RuntimeError:
            pass
    # 空结果
    try:
        DrawpicModerationService._parse_review_response("")
        raise AssertionError("空响应应抛 RuntimeError")
    except RuntimeError:
        pass
    # 无法识别
    try:
        DrawpicModerationService._parse_review_response("今天天气不错")
        raise AssertionError("无法识别的内容应抛 RuntimeError")
    except RuntimeError:
        pass
    print("[OK] moderation: _parse_review_response 分层匹配鲁棒性")


def test_source_image_cache_ttl() -> None:
    """P2-7: 源图缓存 TTL 过期。"""
    # 清空缓存确保干净环境
    _SOURCE_IMAGE_CACHE.clear()
    _SOURCE_IMAGE_CACHE_ORDER.clear()
    # 临时把 TTL 调到极小以便测试
    import core.message_utils as mu

    original_ttl = mu._SOURCE_IMAGE_CACHE_TTL_SECONDS
    mu._SOURCE_IMAGE_CACHE_TTL_SECONDS = 0.2
    try:
        _remember_source_image("stream-1", "msg-1", ["base64data"])
        # 立即查找应命中
        found = find_all_cached_source_images("stream-1", "msg-1")
        assert found is not None, "刚写入的缓存应命中"
        assert found[0] == ["base64data"]
        # 等待 TTL 过期
        sleep(0.3)
        found_after = find_all_cached_source_images("stream-1", "msg-1")
        assert found_after is None, "TTL 过期后应返回 None"
    finally:
        mu._SOURCE_IMAGE_CACHE_TTL_SECONDS = original_ttl
        _SOURCE_IMAGE_CACHE.clear()
        _SOURCE_IMAGE_CACHE_ORDER.clear()
    print("[OK] message_utils: 源图缓存 TTL 过期生效")


def test_image_lookup_candidates_stay_in_current_streams() -> None:
    """消息图片查询仅使用明确提供的聊天流。"""

    assert _normalize_stream_ids("stream-1") == ["stream-1"]
    assert _normalize_stream_ids(["stream-1", "stream-2", ""]) == ["stream-1", "stream-2"]
    print("[OK] message_utils: 图片查询候选聊天流保持隔离")


def test_image_delivery_retries_only_remaining_images() -> None:
    """多图部分发送失败时仅续传剩余图片。"""

    class _FakeSend:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        async def image(self, image_base64: str, stream_id: str) -> bool:
            self.calls.append((stream_id, image_base64))
            if stream_id == "stream-1" and len(self.calls) == 2:
                raise RuntimeError("第二张发送失败")
            return True

    class _DeliveryService(ChatStreamService):
        def __init__(self, ctx) -> None:
            super().__init__(ctx)
            self.stream_ids = iter(("stream-1", "stream-2"))

        async def resolve_live_stream_id(self, **kwargs) -> str:
            del kwargs
            return next(self.stream_ids)

    sender = _FakeSend()
    ctx = types.SimpleNamespace(send=sender, logger=_FakeLogger())
    sent_count = asyncio.run(
        _DeliveryService(ctx).send_generated_images_with_fallback(
            "original-stream",
            [b"first", b"second"],
        )
    )
    assert sent_count == 2
    assert [stream_id for stream_id, _ in sender.calls] == ["stream-1", "stream-1", "stream-2"]
    assert sender.calls[0][1] != sender.calls[2][1]
    print("[OK] stream_service: 多图续传不会重复已发送图片")


def test_unconfirmed_image_delivery_is_not_retried() -> None:
    """投递结果未知时停止自动重试。"""

    class _FakeSend:
        def __init__(self) -> None:
            self.calls = 0

        async def image(self, image_base64: str, stream_id: str) -> bool:
            del image_base64, stream_id
            self.calls += 1
            return False

    class _DeliveryService(ChatStreamService):
        async def resolve_live_stream_id(self, **kwargs) -> str:
            del kwargs
            return "stream-1"

    sender = _FakeSend()
    ctx = types.SimpleNamespace(send=sender, logger=_FakeLogger())
    try:
        asyncio.run(_DeliveryService(ctx).send_generated_images_with_fallback("original-stream", [b"image"]))
        raise AssertionError("投递结果未知时应抛出 ImageDeliveryUnconfirmedError")
    except ImageDeliveryUnconfirmedError:
        pass
    assert sender.calls == 1
    print("[OK] stream_service: 投递结果未知时停止自动重试")


def test_provider_router_openai_routes_cache() -> None:
    """P2-8: OpenAI 路由列表缓存。"""
    # 通过包上下文导入，使 provider_router 的相对导入可用
    from maimai_drawpic_pkg.core.provider_router import ProviderRouter

    class _StubConfig:
        class openai:
            enabled = True
            models = ["gpt-image-2"]
            api_key = "k"
            base_url = "https://api.openai.com"
            default_openai_compatibility_mode = "auto"
            default_size = "1024x1024"
            model_size_overrides: list[str] = []
            quality = ""
            response_format = ""
            output_format = ""
            background = ""
            moderation = ""
            max_images = 1
            extra_parameters: list[str] = []
            rewrite_prompt_to_english = False
            instances: list = []

        class aliyun:
            enabled = False
            models: list[str] = []

        class google:
            enabled = False
            models: list[str] = []

        class zhipu:
            enabled = False
            models: list[str] = []

        class volcengine:
            enabled = False
            models: list[str] = []

        class siliconflow:
            enabled = False
            models: list[str] = []

        class novelai:
            enabled = False
            models: list[str] = []

        class comfyui:
            enabled = False

        class general:
            default_model = "gpt-image-2"
            fallback_model = ""
            request_timeout_seconds = 60
            image_edit_unsupported_models: list[str] = []

    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    routes1 = router._iter_openai_routes()
    routes2 = router._iter_openai_routes()
    assert routes1 is routes2, "二次调用应返回同一缓存列表对象"
    assert router._openai_routes_cache is not None
    assert [r.display_model for r in routes1] == ["gpt-image-2"]
    print("[OK] provider_router: OpenAI 路由列表缓存生效")


def test_provider_router_fallback_model_resolution() -> None:
    """生图备选模型解析。"""
    from maimai_drawpic_pkg.core.provider_router import ProviderRouter

    class _StubConfig:
        class openai:
            enabled = True
            models = ["gpt-image-2", "gpt-image-fallback"]
            api_key = "k"
            base_url = "https://api.openai.com"
            default_openai_compatibility_mode = "auto"
            default_size = "1024x1024"
            model_size_overrides: list[str] = []
            quality = ""
            response_format = ""
            output_format = ""
            background = ""
            moderation = ""
            max_images = 1
            extra_parameters: list[str] = []
            rewrite_prompt_to_english = False
            instances: list = []

        class aliyun:
            enabled = False
            models: list[str] = []

        class google:
            enabled = False
            models: list[str] = []

        class zhipu:
            enabled = False
            models: list[str] = []

        class volcengine:
            enabled = False
            models: list[str] = []

        class siliconflow:
            enabled = False
            models: list[str] = []

        class novelai:
            enabled = False
            models: list[str] = []

        class comfyui:
            enabled = False

        class general:
            default_model = "gpt-image-2"
            fallback_model = "gpt-image-fallback"
            request_timeout_seconds = 60
            image_edit_unsupported_models: list[str] = []

    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    assert router.resolve_fallback_model("gpt-image-2") == "gpt-image-fallback"
    assert router.get_fallback_model_unavailable_reason("gpt-image-2") == ""

    router.config.general.fallback_model = "gpt-image-2"
    assert router.resolve_fallback_model("gpt-image-2") == ""
    assert "相同" in router.get_fallback_model_unavailable_reason("gpt-image-2")

    router.config.general.fallback_model = "missing-model"
    assert router.resolve_fallback_model("gpt-image-2") == ""
    assert "未归属于" in router.get_fallback_model_unavailable_reason("gpt-image-2")
    print("[OK] provider_router: 生图备选模型解析与不可用原因")


def _load_drawpic_plugin_class():
    """使用轻量 SDK 桩导入插件入口，避免测试依赖完整 MaiBot 运行时。"""

    if "maibot_sdk" not in sys.modules:
        sdk_module = types.ModuleType("maibot_sdk")

        def _component_decorator(*args, **kwargs):
            del args, kwargs

            def _wrap(func):
                return func

            return _wrap

        class _MaiBotPlugin:
            pass

        sdk_module.CONFIG_RELOAD_SCOPE_SELF = "self"
        sdk_module.ON_BOT_CONFIG_RELOAD = "bot"
        sdk_module.ON_MODEL_CONFIG_RELOAD = "model"
        sdk_module.Command = _component_decorator
        sdk_module.HookHandler = _component_decorator
        sdk_module.MaiBotPlugin = _MaiBotPlugin
        sdk_module.Tool = _component_decorator
        sys.modules["maibot_sdk"] = sdk_module

        sdk_types_module = types.ModuleType("maibot_sdk.types")

        class _HookMode:
            OBSERVE = "observe"

        sdk_types_module.HookMode = _HookMode
        sys.modules["maibot_sdk.types"] = sdk_types_module

    import importlib

    return importlib.import_module(f"{_PKG_NAME}.plugin").DrawpicPlugin


def _build_context_test_plugin():
    """构造只覆盖 ctx 属性的测试插件实例。"""

    plugin_cls = _load_drawpic_plugin_class()

    class _ContextTestPlugin(plugin_cls):
        @property
        def ctx(self):
            return self._test_ctx

        @property
        def config(self):
            return self._test_config

    plugin = object.__new__(_ContextTestPlugin)
    plugin._test_ctx = types.SimpleNamespace(logger=_FakeLogger())
    plugin._test_config = types.SimpleNamespace(
        general=types.SimpleNamespace(
            group_quota_enabled=False,
            group_quota_period="daily",
            group_default_quota=1,
            private_quota_enabled=False,
            private_quota_period="daily",
            private_default_quota=1,
            admin_user_ids=[],
        )
    )
    return plugin


def test_tool_runtime_context_prefers_host_user_id() -> None:
    """工具调用应优先使用主程序注入的 user_id，而不是 LLM 参数。"""

    plugin = _build_context_test_plugin()

    context = plugin._extract_invocation_context(
        kwargs={"stream_id": "stream-1", "group_id": "10000", "user_id": "12345", "platform": "qq"},
        llm_user_id="99999",
    )
    assert context["user_id"] == "12345", context
    assert context["group_id"] == "10000", context
    print("[OK] plugin: 工具上下文优先使用主程序注入 user_id")


def test_tool_runtime_context_reads_generic_message_info() -> None:
    """工具调用可从通用 message_info.user_info 读取发起用户。"""

    plugin = _build_context_test_plugin()

    message = {
        "session_id": "stream-2",
        "platform": "qq",
        "message_info": {
            "user_info": {"user_id": "23456"},
            "group_info": {"group_id": "10000"},
        },
    }
    context = plugin._extract_invocation_context(kwargs={"message": message}, llm_user_id="99999")
    assert context["stream_id"] == "stream-2", context
    assert context["user_id"] == "23456", context
    assert context["group_id"] == "10000", context
    print("[OK] plugin: 工具上下文可读取通用 message_info.user_info")


def test_tool_runtime_context_accepts_qq_official_openids() -> None:
    """QQ 官方 member_openid 与 group_openid 应作为合法运行时身份保留。"""

    plugin = _build_context_test_plugin()
    user_openid = "41B8E83007B26E6011F3243A5D8ECB3A"
    group_openid = "FAE50782C3464EBBCC519DF38F294422"

    context = plugin._extract_invocation_context(
        kwargs={
            "stream_id": "official-stream",
            "group_id": group_openid,
            "user_id": user_openid,
            "platform": "qq",
        }
    )

    assert context["user_id"] == user_openid
    assert context["group_id"] == group_openid
    assert plugin.ctx.logger.warnings == []
    assert ChatStreamService._is_usable_private_target_id(user_openid, "qq") is True
    print("[OK] plugin: 兼容 QQ 官方 OpenID 运行上下文")


def test_tool_runtime_context_uses_llm_user_id_only_as_compat_fallback() -> None:
    """缺少主程序 user_id 时，旧版 LLM 参数仍可作为兼容兜底。"""

    plugin = _build_context_test_plugin()
    logger = plugin.ctx.logger

    context = plugin._extract_invocation_context(
        kwargs={"stream_id": "stream-3", "group_id": "10000", "platform": "qq"},
        llm_user_id="34567",
    )
    assert context["user_id"] == "34567", context
    assert logger.warnings, "使用 LLM user_id 兜底时应记录 warning"

    invalid_context = plugin._extract_invocation_context(
        kwargs={"stream_id": "stream-4", "group_id": "10000", "platform": "qq"},
        llm_user_id="10000",
    )
    assert invalid_context["user_id"] == "", invalid_context
    print("[OK] plugin: LLM user_id 仅作兼容兜底且保持 QQ 校验")


def test_quota_disabled_does_not_require_user_id() -> None:
    """额度关闭时，绘图工具不应强制要求 user_id。"""

    plugin = _build_context_test_plugin()
    plugin._test_config = types.SimpleNamespace(
        general=types.SimpleNamespace(
            group_quota_enabled=False,
            group_quota_period="daily",
            group_default_quota=1,
            private_quota_enabled=False,
            private_quota_period="daily",
            private_default_quota=1,
            admin_user_ids=[],
        )
    )
    plugin._usage_store = UserQuotaStore(path=Path("unused"), logger=plugin.ctx.logger)

    success, message, quota_key = plugin._check_draw_quota("", "10000", "stream-1")
    assert success is True
    assert "未启用" in message
    assert quota_key == ""
    context = plugin._extract_runtime_context(
        kwargs={
            "stream_id": "stream-1",
            "user_id": "不是有效用户身份",
            "group_id": "10000",
            "platform": "qq",
        }
    )
    assert context["user_id"] == ""
    assert plugin.ctx.logger.warnings == []
    print("[OK] plugin: 额度关闭时不强制要求 user_id")


def test_quota_reservation_is_atomic_and_refundable() -> None:
    """绘图额度在任务受理时预留，失败时可退回。"""

    with tempfile.TemporaryDirectory() as tmp:
        plugin = _build_context_test_plugin()
        plugin._test_config = types.SimpleNamespace(
            general=types.SimpleNamespace(
                group_quota_enabled=True,
                group_quota_period="daily",
                group_default_quota=1,
                private_quota_enabled=True,
                private_quota_period="daily",
                private_default_quota=1,
                admin_user_ids=[],
            )
        )
        plugin._usage_store = UserQuotaStore(path=Path(tmp) / "quotas.json", logger=plugin.ctx.logger)

        # group_id 非空 → 群聊，额度键为 qq:group:10000
        success, message, quota_key = plugin._reserve_draw_quota("12345", "10000", "stream-1")
        assert success is True, message
        assert quota_key == "qq:group:10000"
        assert plugin._usage_store.get_remaining("qq:group:10000", period="daily", default_quota=1) == 0

        # 第二个并发任务无法穿透最后一次额度
        second_success, _, second_quota_key = plugin._reserve_draw_quota("12345", "10000", "stream-2")
        assert second_success is False
        assert second_quota_key == ""

        # 失败任务退回预留额度
        plugin._refund_draw_quota(quota_key, "10000", "stream-1", "task-1")
        assert plugin._usage_store.get_remaining("qq:group:10000", period="daily", default_quota=1) == 1
    print("[OK] plugin: 绘图额度预留与失败返还")


def test_task_store_update_task_model_provider() -> None:
    """任务状态可记录实际成功的模型与平台。"""
    with tempfile.TemporaryDirectory() as tmp:
        store = DrawTaskStore(path=Path(tmp) / "tasks.json", logger=_FakeLogger())
        store.load()
        record = store.create_task(
            session_key="qq:group:1",
            stream_id="s1",
            task_type="draw",
            prompt="hello",
            model="primary-model",
            provider="openai",
            message="pending",
        )
        updated = store.update_task(
            record.task_id,
            status="completed",
            message="ok",
            sent_count=1,
            model="fallback-model",
            provider="aliyun",
        )
        assert updated is not None
        assert updated.model == "fallback-model"
        assert updated.provider == "aliyun"
        assert updated.sent_count == 1
    print("[OK] task_store: update_task 可更新实际模型与平台")


def test_task_store_limits_history_and_omits_prompt() -> None:
    """任务存储限制历史数量且不持久化用户提示词。"""

    with tempfile.TemporaryDirectory() as tmp:
        store = DrawTaskStore(path=Path(tmp) / "tasks.json", logger=_FakeLogger())
        store.MAX_TASK_RECORDS = 3
        task_ids = []
        for index in range(4):
            record = store.create_task(
                session_key=f"qq:group:{index}",
                stream_id=f"stream-{index}",
                task_type="draw",
                prompt=f"private prompt {index}",
                model="model",
                provider="openai",
                message="pending",
            )
            task_ids.append(record.task_id)
            assert record.prompt == ""
        assert store.get_task_count() == 3
        assert store.get_task(task_ids[0]) is None
    print("[OK] task_store: 历史数量和提示词持久化受限")


def main() -> None:
    test_image_utils_detect_mime_type()
    test_provider_response_size_limit_applies_to_json()
    test_novelai_v5_payload_uses_v5_parameters()
    test_novelai_v4_and_v3_payloads_use_supported_parameters()
    test_novelai_quality_tags_follow_model_family()
    test_novelai_sampler_compatibility_is_model_specific()
    test_novelai_custom_gateway_keeps_legacy_parameters()
    test_novelai_defaults_include_v5_models()
    test_task_store_update_missing_task_returns_none()
    test_task_store_normal_flow_still_works()
    test_moderation_parse_review_response_robust()
    test_source_image_cache_ttl()
    test_image_lookup_candidates_stay_in_current_streams()
    test_image_delivery_retries_only_remaining_images()
    test_unconfirmed_image_delivery_is_not_retried()
    test_provider_router_openai_routes_cache()
    test_provider_router_fallback_model_resolution()
    test_tool_runtime_context_prefers_host_user_id()
    test_tool_runtime_context_reads_generic_message_info()
    test_tool_runtime_context_accepts_qq_official_openids()
    test_tool_runtime_context_uses_llm_user_id_only_as_compat_fallback()
    test_quota_disabled_does_not_require_user_id()
    test_quota_reservation_is_atomic_and_refundable()
    test_task_store_update_task_model_provider()
    test_task_store_limits_history_and_omits_prompt()
    print("\n[ALL PASS] 所有测试通过")


if __name__ == "__main__":
    main()
