"""智谱 GLM-Image 配置与请求参数测试。"""

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

    for subpackage_name in ("core", "models", "providers"):
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


def _zhipu_provider_class() -> Any:
    _bootstrap_plugin_package()
    return import_module(f"{_PKG_NAME}.providers.zhipu_platform").ZhipuImage


def _config_module() -> Any:
    _bootstrap_plugin_package()
    return import_module(f"{_PKG_NAME}.core.config")


def _provider_router_class() -> Any:
    _bootstrap_plugin_package()
    return import_module(f"{_PKG_NAME}.core.provider_router").ProviderRouter


def test_glm_image_payload_matches_current_zhipu_api() -> None:
    """参数名回退到旧版会导致 GLM-Image 请求被上游拒绝。"""

    provider = _zhipu_provider_class()(
        api_key="test-key",
        quality="hd",
        size="1568x1056",
        watermark_enabled=False,
        user_id="user-123456",
        extra_parameters={"future_option": 42},
    )

    payload = provider._build_payload(prompt="一只猫", model="glm-image")

    assert payload == {
        "model": "glm-image",
        "prompt": "一只猫",
        "quality": "hd",
        "size": "1568x1056",
        "watermark_enabled": False,
        "user_id": "user-123456",
        "future_option": 42,
    }
    assert "response_format" not in payload
    assert "user" not in payload


def test_glm_image_defaults_are_selected() -> None:
    """智谱配置必须默认选中 GLM-Image，并使用官方推荐参数。"""

    config = _config_module().DrawpicConfig()

    assert config.plugin.config_version == "2.26.0"
    assert config.general.default_model == "gpt-image-2"
    assert config.zhipu.models == ["glm-image"]
    assert config.zhipu.quality == ""
    assert config.zhipu.size == "1280x1280"
    assert config.zhipu.watermark_enabled is True
    assert config.zhipu.user_id == ""
    assert config.zhipu.extra_parameters == []


def test_blank_zhipu_optional_strings_are_omitted() -> None:
    """空的可选字符串不得覆盖智谱按模型提供的上游默认值。"""

    provider = _zhipu_provider_class()(
        api_key="test-key",
        quality="",
        size="",
        user_id="",
    )

    assert provider._build_payload("风景", "cogview-4") == {
        "model": "cogview-4",
        "prompt": "风景",
        "watermark_enabled": True,
    }


def test_router_forwards_zhipu_parameters() -> None:
    """路由遗漏新字段会让用户配置无法进入智谱请求体。"""

    config = _config_module().DrawpicConfig()
    config.zhipu.quality = "standard"
    config.zhipu.size = "1024x1024"
    config.zhipu.watermark_enabled = False
    config.zhipu.user_id = "user-654321"
    config.zhipu.extra_parameters = ["future_option=true"]

    provider = _provider_router_class()(config).create_zhipu_provider()

    assert provider._build_payload("风景", "cogview-4") == {
        "model": "cogview-4",
        "prompt": "风景",
        "quality": "standard",
        "size": "1024x1024",
        "watermark_enabled": False,
        "user_id": "user-654321",
        "future_option": True,
    }
