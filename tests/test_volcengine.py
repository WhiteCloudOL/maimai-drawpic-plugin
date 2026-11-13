"""火山引擎模型路由与官方图片接口验证测试。"""
from __future__ import annotations

from pathlib import Path

import asyncio
import base64
import sys
import types

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
_PKG_NAME = "maimai_drawpic_pkg"

if _PKG_NAME not in sys.modules:
    pkg = types.ModuleType(_PKG_NAME)
    pkg.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[_PKG_NAME] = pkg

from maimai_drawpic_pkg.src.maimai_drawpic.application.routing import ProviderRouter  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.infrastructure.providers.volcengine import VolcengineImage  # noqa: E402


_MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class _FakeLogger:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []
        self.errors: list[str] = []

    def warning(self, message, *args):
        self.warnings.append(message % args if args else message)

    def info(self, message, *args):
        self.infos.append(message % args if args else message)

    def error(self, message, *args):
        self.errors.append(message % args if args else message)


class _StubVolcConfig:
    enabled = True
    api_key = "test-key"
    base_url = "https://ark.cn-beijing.volces.com/api/v3"
    models = [
        "doubao-seedream-3-0-t2i-250415",
        "doubao-seededit-3-0-i2i-250628",
        "doubao-seedream-5-0-flash-260915",
    ]
    default_size = "1024x1024"
    model_size_overrides: list[str] = []
    model_endpoint_overrides: list[str] = []
    response_format = "url"
    output_format = ""
    sequential_image_generation = "disabled"
    optimize_prompt_mode = ""
    web_search_enabled = False
    background = ""
    layer_decomposition = False
    guidance_scale = 0.0
    seed = -1
    watermark = False
    max_images = 1
    extra_parameters: list[str] = []
    rewrite_prompt_to_english = False


class _StubGeneralConfig:
    default_model = "doubao-seedream-5-0-flash-260915"
    fallback_model = ""
    request_timeout_seconds = 60
    image_edit_unsupported_models: list[str] = []
    text_to_image_unsupported_models: list[str] = []


class _StubConfig:
    class minimax:
        enabled = False
        models = []

    class agnes:
        enabled = False
        models = []

    volcengine = _StubVolcConfig()
    general = _StubGeneralConfig()

    class openai:
        enabled = False
        models: list[str] = []
        instances: list = []
        default_openai_compatibility_mode = "auto"

    class aliyun:
        enabled = False
        models: list[str] = []

    class google:
        enabled = False
        models: list[str] = []

    class zhipu:
        enabled = False
        models: list[str] = []

    class siliconflow:
        enabled = False
        models: list[str] = []

    class novelai:
        enabled = False
        models: list[str] = []


def _build_provider(**overrides) -> VolcengineImage:
    options = {
        "api_key": "test-key",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "logger": _FakeLogger(),
        "default_size": "2048*2048",
        "response_format": "b64_json",
        "output_format": "png",
        "sequential_image_generation": "disabled",
        "optimize_prompt_mode": "",
        "web_search_enabled": False,
        "background": "",
        "layer_decomposition": False,
        "guidance_scale": 6.0,
        "seed": 42,
        "watermark": False,
        "max_images": 4,
    }
    options.update(overrides)
    return VolcengineImage(**options)


class _RecordingVolcengineImage(VolcengineImage):
    """记录请求体并返回固定 Base64 图片响应。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.requests: list[dict] = []

    async def _post_json(self, url: str, payload: dict) -> dict:
        del url
        self.requests.append(payload)
        return {
            "data": [
                {
                    "b64_json": base64.b64encode(b"generated-image").decode("ascii"),
                }
            ]
        }


def test_volcengine_model_lists() -> None:
    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    t2i = router.get_volcengine_t2i_models()
    i2i = router.get_volcengine_i2i_models()
    all_models = router.get_volcengine_models()
    assert t2i == [
        "doubao-seedream-3-0-t2i-250415",
        "doubao-seedream-5-0-flash-260915",
    ], t2i
    assert i2i == [
        "doubao-seededit-3-0-i2i-250628",
        "doubao-seedream-5-0-flash-260915",
    ], i2i
    assert all_models == _StubVolcConfig.models, all_models
    print("[OK] volcengine model list: suffix-derived task capabilities")


def test_task_suffix_mismatch_is_rejected() -> None:
    """带 t2i/i2i 标记的旧模型不得用于相反任务。"""

    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    for model, task_type in (
        ("doubao-seedream-3-0-t2i-250415", "edit_image"),
        ("doubao-seededit-3-0-i2i-250628", "draw"),
    ):
        try:
            router.resolve_volcengine_model_for_task(model, task_type)
        except ValueError as exc:
            assert "不支持" in str(exc)
        else:
            raise AssertionError(f"{model} 应拒绝任务 {task_type}")
    print("[OK] volcengine task suffix: reject opposite task")


def test_no_switch_when_matching() -> None:
    """模型与任务类型匹配时不切换。"""
    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    assert router.resolve_volcengine_model_for_task(
        "doubao-seedream-3-0-t2i-250415", "draw"
    ) == "doubao-seedream-3-0-t2i-250415"
    assert router.resolve_volcengine_model_for_task(
        "doubao-seededit-3-0-i2i-250628", "edit_image"
    ) == "doubao-seededit-3-0-i2i-250628"
    assert router.resolve_volcengine_model_for_task(
        "doubao-seedream-5-0-flash-260915", "edit_image"
    ) == "doubao-seedream-5-0-flash-260915"
    print("[OK] no switch when model matches task type")


def test_i2i_unsupported_reason_for_t2i() -> None:
    """t2i 模型在图生图检查时返回不支持原因。"""
    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    reason = router.get_image_edit_unsupported_reason("doubao-seedream-3-0-t2i-250415")
    assert reason != "", "t2i 模型应返回不支持原因"
    assert "文生图" in reason or "i2i" in reason, reason
    print("[OK] unsupported reason for t2i model on edit_image")


def test_i2i_supported_for_i2i_model() -> None:
    """i2i 模型在图生图检查时返回空（支持）。"""
    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    reason = router.get_image_edit_unsupported_reason("doubao-seededit-3-0-i2i-250628")
    assert reason == "", f"i2i 模型应支持图生图，得到 {reason!r}"
    print("[OK] i2i model supports edit_image")


def test_global_task_blacklist_is_applied() -> None:
    """全局任务黑名单应覆盖未带后缀的统一模型。"""

    config = _StubConfig()
    config.general = types.SimpleNamespace(
        default_model="doubao-seedream-5-0-flash-260915",
        fallback_model="",
        request_timeout_seconds=60,
        image_edit_unsupported_models=["doubao-seedream-5-0-flash-260915"],
        text_to_image_unsupported_models=[],
    )
    router = ProviderRouter(config, logger=_FakeLogger())
    try:
        router.resolve_volcengine_model_for_task(
            "doubao-seedream-5-0-flash-260915", "edit_image"
        )
    except ValueError as exc:
        assert "仅支持文生图" in str(exc)
    else:
        raise AssertionError("全局图生图黑名单应拒绝图生图")
    print("[OK] volcengine task capability: global blacklist applied")


def test_config_migration_legacy_models() -> None:
    """旧版分组字段自动合并到 models。"""
    from maimai_drawpic_pkg.src.maimai_drawpic.domain.configuration.models import _migrate_legacy_volcengine_models

    config_data = {
        "volcengine": {
            "models": ["existing-model"],
            "unified_models": ["unified-model"],
            "t2i_models": ["legacy-t2i"],
            "i2i_models": ["legacy-i2i", "existing-model"],
        }
    }
    _migrate_legacy_volcengine_models(config_data)
    volc = config_data["volcengine"]
    assert volc["models"] == [
        "existing-model",
        "unified-model",
        "legacy-t2i",
        "legacy-i2i",
    ], volc["models"]
    assert "unified_models" not in volc
    assert "t2i_models" not in volc
    assert "i2i_models" not in volc
    print("[OK] config migration: grouped model fields -> models")


def test_default_models_cover_seedream_5_image_variants() -> None:
    """默认模型列表覆盖用户要求的 Seedream 5 图片模型。"""

    from maimai_drawpic_pkg.src.maimai_drawpic.domain.configuration.models import VolcengineModelConfig

    assert VolcengineModelConfig().models == [
        "doubao-seedream-5-0-flash-260915",
        "doubao-seedream-5-0-pro-260628",
        "doubao-seedream-5-0-260128",
    ]
    print("[OK] volcengine defaults: Seedream 5 flash/pro/lite images")


def test_official_payload_omits_openai_n_and_normalizes_size() -> None:
    """官方 Body 不应发送 n，旧尺寸分隔符应转换为小写 x。"""

    provider = _build_provider()
    payload = provider._build_payload(
        prompt="test",
        model="doubao-seedream-5-0-flash-260915",
        n=1,
        source_image_count=0,
    )
    assert "n" not in payload
    assert payload["size"] == "2048x2048"
    assert payload["output_format"] == "png"
    assert "seed" not in payload
    assert "guidance_scale" not in payload
    assert "sequential_image_generation" not in payload
    print("[OK] volcengine payload: 删除 n、规范尺寸并过滤模型不支持参数")


def test_configurable_base_url_supports_plan_and_direct_endpoints() -> None:
    """Base URL 可覆盖直调、Agent Plan、完整地址和按模型特殊路径。"""

    model = "doubao-seedream-5-0-flash-260915"
    assert _build_provider()._resolve_endpoint_url(model) == (
        "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    )
    assert _build_provider(
        base_url="https://ark.cn-beijing.volces.com/api/plan/v3/"
    )._resolve_endpoint_url(model) == (
        "https://ark.cn-beijing.volces.com/api/plan/v3/images/generations"
    )
    full_endpoint = "https://gateway.example/v1/images/generations"
    assert _build_provider(base_url=full_endpoint)._resolve_endpoint_url(model) == full_endpoint
    overridden = _build_provider(
        base_url="https://gateway.example/root/v3",
        model_endpoint_overrides={model: "/custom/images/generations"},
    )
    assert overridden._resolve_endpoint_url(model) == (
        "https://gateway.example/custom/images/generations"
    )
    print("[OK] volcengine endpoint: 支持直调、Agent Plan、完整地址和模型覆盖")


def test_model_specific_parameters_are_filtered() -> None:
    """不同 Seedream 版本只接收官方声明支持的参数。"""

    legacy_payload = _build_provider(
        optimize_prompt_mode="standard",
        sequential_image_generation="auto",
        web_search_enabled=True,
    )._build_payload(
        prompt="legacy",
        model="doubao-seedream-3-0-t2i-250415",
        n=1,
        source_image_count=0,
    )
    assert legacy_payload["seed"] == 42
    assert legacy_payload["guidance_scale"] == 6.0
    assert "output_format" not in legacy_payload
    assert "sequential_image_generation" not in legacy_payload
    assert "optimize_prompt_options" not in legacy_payload
    assert "tools" not in legacy_payload

    lite_payload = _build_provider(
        sequential_image_generation="auto",
        optimize_prompt_mode="standard",
        web_search_enabled=True,
    )._build_payload(
        prompt="series",
        model="doubao-seedream-5-0-260128",
        n=1,
        source_image_count=2,
    )
    assert lite_payload["sequential_image_generation"] == "auto"
    assert lite_payload["sequential_image_generation_options"] == {"max_images": 4}
    assert lite_payload["optimize_prompt_options"] == {"mode": "standard"}
    assert lite_payload["tools"] == [{"type": "web_search"}]
    assert "seed" not in lite_payload
    assert "guidance_scale" not in lite_payload
    print("[OK] volcengine payload: 按模型能力发送组图、旧版和联网参数")


def test_fast_prompt_optimization_falls_back_only_when_required() -> None:
    """fast 仅在支持模型保留，其余支持模型切换为 standard。"""

    flash_provider = _build_provider(optimize_prompt_mode="fast")
    flash_payload = flash_provider._build_payload(
        prompt="flash",
        model="doubao-seedream-5-0-flash-260915",
        n=1,
        source_image_count=0,
    )
    assert flash_payload["optimize_prompt_options"] == {"mode": "standard"}
    assert flash_provider.logger.warnings

    pro_payload = _build_provider(optimize_prompt_mode="fast")._build_payload(
        prompt="pro",
        model="doubao-seedream-5-0-pro-260628",
        n=1,
        source_image_count=0,
    )
    assert pro_payload["optimize_prompt_options"] == {"mode": "fast"}
    print("[OK] volcengine payload: 提示词优化模式按模型兼容")


def test_multi_image_edit_uses_single_official_request() -> None:
    """多图图生图应使用 image 数组发起一次官方请求，不能静默丢图或多次试错。"""

    provider = _RecordingVolcengineImage(
        api_key="test-key",
        response_format="b64_json",
    )
    images = asyncio.run(
        provider.edit_images(
            "merge",
            "doubao-seedream-5-0-flash-260915",
            [_MINIMAL_PNG, _MINIMAL_PNG],
        )
    )
    assert images == [b"generated-image"]
    assert len(provider.requests) == 1
    request_images = provider.requests[0]["image"]
    assert isinstance(request_images, list)
    assert len(request_images) == 2
    assert all(image.startswith("data:image/") for image in request_images)
    assert "image_url" not in provider.requests[0]
    assert "images" not in provider.requests[0]
    assert "messages" not in provider.requests[0]
    print("[OK] volcengine edit: 多张源图通过官方 image 数组单次提交")


def test_advanced_edit_parameters_are_validated() -> None:
    """透明通道与图层拆分只在支持的单图编辑场景发送。"""

    provider = _build_provider(
        output_format="png",
        background="transparent",
        layer_decomposition=True,
    )
    payload = provider._build_payload(
        prompt="split",
        model="doubao-seedream-5-0-pro-260628",
        n=1,
        source_image_count=1,
    )
    assert payload["background"] == "transparent"
    assert payload["layer_decomposition"] is True

    try:
        provider._build_payload(
            prompt="split",
            model="doubao-seedream-5-0-pro-260628",
            n=1,
            source_image_count=2,
        )
    except ValueError as exc:
        assert "一张图片" in str(exc)
    else:
        raise AssertionError("透明背景或图层拆分的多图请求应被拒绝")
    print("[OK] volcengine edit: 透明通道和图层拆分参数校验")


def test_reference_image_limits_are_model_aware() -> None:
    """官方模型在请求前校验参考图上限，自定义 Endpoint 保持兼容。"""

    provider = _build_provider()
    for model, maximum in (
        ("doubao-seedream-5-0-pro-260628", 10),
        ("doubao-seedream-5-0-flash-260915", 10),
        ("doubao-seedream-5-0-260128", 14),
        ("doubao-seedream-4-5-251128", 14),
        ("doubao-seedream-4-0-250828", 14),
    ):
        try:
            provider._build_payload(
                prompt="too many references",
                model=model,
                n=1,
                source_image_count=maximum + 1,
            )
        except ValueError as exc:
            assert str(maximum) in str(exc)
        else:
            raise AssertionError(f"{model} 应拒绝超过 {maximum} 张参考图")

    custom_payload = provider._build_payload(
        prompt="custom endpoint",
        model="ep-custom-image-model",
        n=1,
        source_image_count=15,
    )
    assert custom_payload["model"] == "ep-custom-image-model"
    print("[OK] volcengine edit: 按官方模型校验参考图上限并兼容自定义 Endpoint")


def test_partial_series_errors_keep_successful_images() -> None:
    """组图部分失败时保留成功图片，并在全失败时暴露具体原因。"""

    provider = _build_provider()
    response = {
        "data": [
            {"b64_json": base64.b64encode(b"ok").decode("ascii")},
            {"error": {"code": "ContentFilter", "message": "审核未通过"}},
        ]
    }
    images = asyncio.run(provider._extract_images(response))
    assert images == [b"ok"]
    assert provider.logger.warnings

    try:
        asyncio.run(
            provider._extract_images(
                {"data": [{"error": {"code": "InternalError", "message": "生成失败"}}]}
            )
        )
    except RuntimeError as exc:
        assert "InternalError" in str(exc)
        assert "生成失败" in str(exc)
    else:
        raise AssertionError("全部组图失败时应抛出具体错误")
    print("[OK] volcengine response: 保留部分成功并暴露单图错误")


def test_empty_top_level_error_is_not_a_failure() -> None:
    """部分兼容网关会在成功响应附带空 error 对象，不应误判为失败。"""

    assert VolcengineImage._extract_response_error({"data": [], "error": {}}) is None
    assert VolcengineImage._extract_response_error({"data": [], "error": ""}) is None
    assert VolcengineImage._extract_response_error(
        {"error": {"code": "InvalidParameter", "message": "参数错误"}}
    ) == ("InvalidParameter", "参数错误")
    print("[OK] volcengine response: 兼容成功响应中的空 error 对象")


def main() -> None:
    test_volcengine_model_lists()
    test_task_suffix_mismatch_is_rejected()
    test_no_switch_when_matching()
    test_i2i_unsupported_reason_for_t2i()
    test_i2i_supported_for_i2i_model()
    test_global_task_blacklist_is_applied()
    test_config_migration_legacy_models()
    test_default_models_cover_seedream_5_image_variants()
    test_official_payload_omits_openai_n_and_normalizes_size()
    test_configurable_base_url_supports_plan_and_direct_endpoints()
    test_model_specific_parameters_are_filtered()
    test_fast_prompt_optimization_falls_back_only_when_required()
    test_multi_image_edit_uses_single_official_request()
    test_advanced_edit_parameters_are_validated()
    test_reference_image_limits_are_model_aware()
    test_partial_series_errors_keep_successful_images()
    test_empty_top_level_error_is_not_a_failure()
    print("\n[ALL PASS] 所有火山引擎图片接口测试通过")


if __name__ == "__main__":
    main()
