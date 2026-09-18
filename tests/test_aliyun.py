"""阿里云百炼图像模型能力与协议测试。"""
from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any

import importlib.util
import sys
import types


_PLUGIN_DIR = Path(__file__).resolve().parent.parent
_PKG_NAME = "maimai_drawpic_pkg"


def _bootstrap_plugin_package() -> None:
    """建立不依赖插件运行时的包导入环境。"""

    if _PKG_NAME not in sys.modules:
        package = types.ModuleType(_PKG_NAME)
        package.__path__ = [str(_PLUGIN_DIR)]
        sys.modules[_PKG_NAME] = package

    for subpackage_name in ("core", "providers"):
        full_name = f"{_PKG_NAME}.{subpackage_name}"
        if full_name in sys.modules:
            continue
        subpackage_path = _PLUGIN_DIR / subpackage_name
        init_path = subpackage_path / "__init__.py"
        if not init_path.exists():
            module = types.ModuleType(full_name)
            module.__path__ = [str(subpackage_path)]
            sys.modules[full_name] = module
            continue
        spec = importlib.util.spec_from_file_location(
            full_name,
            init_path,
            submodule_search_locations=[str(subpackage_path)],
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"无法加载测试包：{full_name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[full_name] = module
        spec.loader.exec_module(module)


def _aliyun_models() -> Any:
    _bootstrap_plugin_package()
    return import_module(f"{_PKG_NAME}.providers.aliyun_models")


def _request_options(**overrides: Any) -> Any:
    models = _aliyun_models()
    values: dict[str, Any] = {
        "default_size": "1024*1024",
        "model_size_overrides": {},
        "negative_prompt": "模糊",
        "prompt_extend": True,
        "qwen_prompt_extend_mode": "direct",
        "qwen_enable_thinking": True,
        "zimage_prompt_extend": False,
        "seed": 42,
        "watermark": False,
        "max_images": 6,
        "kling_aspect_ratio": "1:1",
        "kling_resolution": "1k",
        "kling_result_type": "single",
        "kling_series_amount": 4,
        "qwen_extra_parameters": {},
        "zimage_extra_parameters": {},
        "kling_extra_parameters": {},
        "vidu_extra_parameters": {},
        "legacy_extra_parameters": {},
    }
    values.update(overrides)
    return models.AliyunRequestOptions(**values)


def test_builtin_models_have_expected_families_and_capabilities() -> None:
    """模型注册错误会把任务发往不兼容接口或允许不支持的能力。"""

    models = _aliyun_models()
    qwen = models.resolve_aliyun_model_profile("qwen-image-3.0-pro")
    zimage = models.resolve_aliyun_model_profile("z-image-turbo")
    kling = models.resolve_aliyun_model_profile("kling/kling-v3-image-generation")
    vidu = models.resolve_aliyun_model_profile("vidu/viduq3-fast_reference2image")

    assert (qwen.family, qwen.supports_draw, qwen.supports_edit, qwen.is_async) == (
        "qwen",
        True,
        True,
        False,
    )
    assert (zimage.family, zimage.supports_draw, zimage.supports_edit) == (
        "zimage",
        True,
        False,
    )
    assert (kling.family, kling.max_input_images, kling.is_async) == ("kling", 1, True)
    assert (vidu.family, vidu.max_input_images, vidu.max_output_images, vidu.is_async) == (
        "vidu",
        14,
        1,
        True,
    )


def test_qwen_generation_and_edit_only_models_are_distinguished() -> None:
    """千问纯生成与纯编辑型号不能被误判为双能力模型。"""

    models = _aliyun_models()
    generation = models.resolve_aliyun_model_profile("qwen-image-max")
    editing = models.resolve_aliyun_model_profile("qwen-image-edit-plus")

    assert (generation.supports_draw, generation.supports_edit) == (True, False)
    assert (editing.supports_draw, editing.supports_edit) == (False, True)


def test_default_models_cover_requested_families_without_wan_models() -> None:
    """默认模型列表遗漏目标族或混入万象都会产生错误的 WebUI 默认配置。"""

    models = _aliyun_models()
    defaults = models.DEFAULT_ALIYUN_MODELS

    assert "qwen-image-3.0" in defaults
    assert "z-image-turbo" in defaults
    assert "kling/kling-v3-omni-image-generation" in defaults
    assert "vidu/viduq2-pro_reference2image" in defaults
    assert not any(model.startswith("wan") for model in defaults)
    assert len(defaults) == len(set(defaults))


def test_auto_input_mode_uses_url_only_for_url_models() -> None:
    """自动输入模式必须保持千问 Base64，并为可灵/Vidu 选择 URL。"""

    models = _aliyun_models()
    qwen = models.resolve_aliyun_model_profile("qwen-image-3.0")
    kling = models.resolve_aliyun_model_profile("kling/kling-v3-image-generation")
    vidu = models.resolve_aliyun_model_profile("vidu/vidu-image_reference2image")

    assert models.resolve_aliyun_image_input_mode(qwen, "auto") == "base64"
    assert models.resolve_aliyun_image_input_mode(kling, "auto") == "url"
    assert models.resolve_aliyun_image_input_mode(vidu, "auto") == "url"


def test_forced_unsupported_input_mode_is_rejected() -> None:
    """强制可灵使用 Base64 不能静默回退到未受支持的格式。"""

    models = _aliyun_models()
    kling = models.resolve_aliyun_model_profile("kling/kling-v3-image-generation")

    try:
        models.resolve_aliyun_image_input_mode(kling, "base64")
    except ValueError as exc:
        assert "kling/kling-v3-image-generation" in str(exc)
        assert "Base64" in str(exc)
    else:
        raise AssertionError("可灵 Base64 输入应被拒绝")


def test_family_parameters_do_not_leak_between_models() -> None:
    """族参数串用会让百炼以 InvalidParameter 拒绝请求。"""

    models = _aliyun_models()
    options = _request_options()

    qwen_parameters = models.build_aliyun_parameters(
        "qwen-image-3.0",
        "draw",
        2,
        options,
    )
    kling_parameters = models.build_aliyun_parameters(
        "kling/kling-v3-image-generation",
        "draw",
        2,
        options,
    )
    zimage_parameters = models.build_aliyun_parameters(
        "z-image-turbo",
        "draw",
        5,
        options,
    )
    vidu_parameters = models.build_aliyun_parameters(
        "vidu/viduq3-fast_reference2image",
        "draw",
        5,
        options,
    )

    assert qwen_parameters == {
        "n": 2,
        "watermark": False,
        "negative_prompt": "模糊",
        "prompt_extend": True,
        "prompt_extend_mode": "direct",
        "enable_thinking": True,
        "size": "1024*1024",
        "seed": 42,
    }
    assert kling_parameters == {
        "n": 2,
        "aspect_ratio": "1:1",
        "resolution": "1k",
    }
    assert zimage_parameters == {
        "size": "1024*1024",
        "prompt_extend": False,
        "seed": 42,
    }
    assert vidu_parameters == {
        "size": "1024*1024",
        "n": 1,
        "seed": 42,
        "watermark": False,
    }


def test_kling_omni_series_parameters_replace_single_count() -> None:
    """Omni 组图模式错误携带 n 会导致参数组合不合法。"""

    models = _aliyun_models()
    parameters = models.build_aliyun_parameters(
        "kling/kling-v3-omni-image-generation",
        "draw",
        1,
        _request_options(kling_result_type="series", kling_series_amount=6, kling_resolution="4k"),
    )

    assert parameters == {
        "result_type": "series",
        "series_amount": 6,
        "aspect_ratio": "1:1",
        "resolution": "4k",
    }


def test_qwen_agent_prompt_extension_is_rejected_for_editing() -> None:
    """千问 3.0 图生图不支持 agent 改写模式，必须请求前拒绝。"""

    models = _aliyun_models()

    try:
        models.build_aliyun_parameters(
            "qwen-image-3.0",
            "edit_image",
            1,
            _request_options(qwen_prompt_extend_mode="agent"),
        )
    except ValueError as exc:
        assert "agent" in str(exc)
        assert "图生图" in str(exc)
    else:
        raise AssertionError("千问 3.0 图生图 agent 模式应被拒绝")


def test_task_validation_checks_capability_and_image_count() -> None:
    """能力或源图数量错误必须在付费 API 请求前被发现。"""

    models = _aliyun_models()

    try:
        models.validate_aliyun_task("z-image-turbo", "edit_image", 1, "auto")
    except ValueError as exc:
        assert "不支持图生图" in str(exc)
    else:
        raise AssertionError("Z-Image 图生图应被拒绝")

    try:
        models.validate_aliyun_task(
            "kling/kling-v3-image-generation",
            "edit_image",
            2,
            "auto",
        )
    except ValueError as exc:
        assert "最多接收 1 张" in str(exc)
    else:
        raise AssertionError("普通可灵 V3 多参考图应被拒绝")
