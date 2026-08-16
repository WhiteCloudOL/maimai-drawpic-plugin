"""火山引擎文生图/图生图模型分离与自动切换验证测试。"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

_PLUGIN_DIR = Path(__file__).resolve().parent.parent
_PKG_NAME = "maimai_drawpic_pkg"

if _PKG_NAME not in sys.modules:
    pkg = types.ModuleType(_PKG_NAME)
    pkg.__path__ = [str(_PLUGIN_DIR)]
    sys.modules[_PKG_NAME] = pkg
for sub in ("core", "providers"):
    sub_path = _PLUGIN_DIR / sub
    init_file = sub_path / "__init__.py"
    full = f"{_PKG_NAME}.{sub}"
    if full in sys.modules:
        continue
    if init_file.exists():
        spec = importlib.util.spec_from_file_location(
            full, init_file, submodule_search_locations=[str(sub_path)]
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[full] = mod
        spec.loader.exec_module(mod)
    else:
        ns = types.ModuleType(full)
        ns.__path__ = [str(sub_path)]
        sys.modules[full] = ns

from maimai_drawpic_pkg.core.provider_router import ProviderRouter  # noqa: E402


class _FakeLogger:
    def warning(self, message, *args): pass
    def info(self, message, *args): pass
    def error(self, message, *args): pass


class _StubVolcConfig:
    enabled = True
    api_key = "test-key"
    models: list[str] = []  # 旧字段留空
    unified_models: list[str] = []
    t2i_models = ["doubao-seedream-3-0-t2i"]
    i2i_models = ["doubao-seedream-3-0-i2i"]
    default_size = "1024x1024"
    model_size_overrides: list[str] = []
    model_endpoint_overrides: list[str] = []
    response_format = "url"
    guidance_scale = 0.0
    seed = -1
    watermark = False
    max_images = 1
    extra_parameters: list[str] = []
    rewrite_prompt_to_english = False


class _StubGeneralConfig:
    default_model = "doubao-seedream-3-0-t2i"
    fallback_model = ""
    request_timeout_seconds = 60
    image_edit_unsupported_models: list[str] = []


class _StubConfig:
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


def test_volcengine_model_lists() -> None:
    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    t2i = router.get_volcengine_t2i_models()
    i2i = router.get_volcengine_i2i_models()
    all_models = router.get_volcengine_models()
    assert t2i == ["doubao-seedream-3-0-t2i"], t2i
    assert i2i == ["doubao-seedream-3-0-i2i"], i2i
    assert all_models == ["doubao-seedream-3-0-t2i", "doubao-seedream-3-0-i2i"], all_models
    print("[OK] volcengine model lists: t2i / i2i / combined")


def test_auto_switch_t2i_to_i2i() -> None:
    """文生图模型做图生图时自动切换到对应的 i2i 模型。"""
    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    resolved = router.resolve_volcengine_model_for_task("doubao-seedream-3-0-t2i", "edit_image")
    assert resolved == "doubao-seedream-3-0-i2i", f"期望 i2i，得到 {resolved}"
    print("[OK] auto switch: t2i model -> i2i for edit_image")


def test_auto_switch_i2i_to_t2i() -> None:
    """图生图模型做文生图时自动切换到对应的 t2i 模型。"""
    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    resolved = router.resolve_volcengine_model_for_task("doubao-seedream-3-0-i2i", "draw")
    assert resolved == "doubao-seedream-3-0-t2i", f"期望 t2i，得到 {resolved}"
    print("[OK] auto switch: i2i model -> t2i for draw")


def test_no_switch_when_matching() -> None:
    """模型与任务类型匹配时不切换。"""
    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    assert router.resolve_volcengine_model_for_task("doubao-seedream-3-0-t2i", "draw") == "doubao-seedream-3-0-t2i"
    assert router.resolve_volcengine_model_for_task("doubao-seedream-3-0-i2i", "edit_image") == "doubao-seedream-3-0-i2i"
    print("[OK] no switch when model matches task type")


def test_i2i_unsupported_reason_for_t2i() -> None:
    """t2i 模型在图生图检查时返回不支持原因。"""
    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    reason = router.get_image_edit_unsupported_reason("doubao-seedream-3-0-t2i")
    assert reason != "", "t2i 模型应返回不支持原因"
    assert "文生图" in reason or "i2i" in reason, reason
    print("[OK] unsupported reason for t2i model on edit_image")


def test_i2i_supported_for_i2i_model() -> None:
    """i2i 模型在图生图检查时返回空（支持）。"""
    router = ProviderRouter(_StubConfig(), logger=_FakeLogger())
    reason = router.get_image_edit_unsupported_reason("doubao-seedream-3-0-i2i")
    assert reason == "", f"i2i 模型应支持图生图，得到 {reason!r}"
    print("[OK] i2i model supports edit_image")


def test_empty_i2i_models_raises() -> None:
    """i2i_models 为空时图生图应抛 ValueError。"""
    config = _StubConfig()
    config.volcengine.i2i_models = []
    router = ProviderRouter(config, logger=_FakeLogger())
    try:
        router.resolve_volcengine_model_for_task("doubao-seedream-3-0-t2i", "edit_image")
        raise AssertionError("应抛 ValueError")
    except ValueError as exc:
        assert "i2i" in str(exc).lower() or "图生图" in str(exc), str(exc)
    print("[OK] empty i2i_models raises ValueError for edit_image")


def test_config_migration_legacy_models() -> None:
    """旧版 models 字段自动迁移到 t2i_models / i2i_models。"""
    from maimai_drawpic_pkg.core.config import _migrate_legacy_volcengine_models

    config_data = {
        "volcengine": {
            "models": ["doubao-seedream-3-0-t2i", "doubao-seedream-3-0-i2i", "some-other-model"],
        }
    }
    _migrate_legacy_volcengine_models(config_data)
    volc = config_data["volcengine"]
    assert volc["t2i_models"] == ["doubao-seedream-3-0-t2i", "some-other-model"], volc["t2i_models"]
    assert volc["i2i_models"] == ["doubao-seedream-3-0-i2i", "some-other-model"], volc["i2i_models"]
    print("[OK] config migration: legacy models -> t2i/i2i split")


def test_config_migration_skipped_when_new_fields_set() -> None:
    """新字段已填写时不触发迁移。"""
    from maimai_drawpic_pkg.core.config import _migrate_legacy_volcengine_models

    config_data = {
        "volcengine": {
            "models": ["old-t2i", "old-i2i"],
            "t2i_models": ["new-t2i"],
        }
    }
    _migrate_legacy_volcengine_models(config_data)
    volc = config_data["volcengine"]
    assert volc["t2i_models"] == ["new-t2i"], volc["t2i_models"]
    print("[OK] config migration: skipped when t2i_models already set")


def main() -> None:
    test_volcengine_model_lists()
    test_auto_switch_t2i_to_i2i()
    test_auto_switch_i2i_to_t2i()
    test_no_switch_when_matching()
    test_i2i_unsupported_reason_for_t2i()
    test_i2i_supported_for_i2i_model()
    test_empty_i2i_models_raises()
    test_config_migration_legacy_models()
    test_config_migration_skipped_when_new_fields_set()
    print("\n[ALL PASS] 所有火山引擎模型分离测试通过")


if __name__ == "__main__":
    main()
