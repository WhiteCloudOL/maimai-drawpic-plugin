"""插件配置 WebUI Schema 国际化覆盖测试。"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any
from maibot_sdk.config import generate_plugin_config_schema
import json
import sys
import types


_PLUGIN_DIR = Path(__file__).resolve().parent.parent
_PKG_NAME = "maimai_drawpic_pkg"
_SUPPORTED_SCHEMA_LOCALES = ("en_US", "ja_JP", "ko_KR")


def _bootstrap_plugin_package() -> None:
    """建立不依赖插件运行时的包导入环境。"""

    if _PKG_NAME not in sys.modules:
        package = types.ModuleType(_PKG_NAME)
        package.__path__ = [str(_PLUGIN_DIR)]
        sys.modules[_PKG_NAME] = package



def _config_schema() -> dict[str, Any]:
    _bootstrap_plugin_package()
    config_module = import_module(f"{_PKG_NAME}.src.maimai_drawpic.domain.configuration.models")
    return generate_plugin_config_schema(config_module.DrawpicConfig)


def _assert_field_i18n(field_path: str, field: dict[str, Any]) -> None:
    """校验字段及列表对象子字段的本地化元数据。"""

    translations = field.get("i18n", {})
    for locale in _SUPPORTED_SCHEMA_LOCALES:
        localized = translations.get(locale, {})
        assert localized.get("label"), f"{field_path} 缺少 {locale} label"
        if field.get("hint"):
            assert localized.get("hint"), f"{field_path} 缺少 {locale} hint"
        if field.get("placeholder"):
            assert localized.get("placeholder"), f"{field_path} 缺少 {locale} placeholder"

    for item_name, item_field in (field.get("item_fields") or {}).items():
        _assert_field_i18n(f"{field_path}.{item_name}", item_field)


def test_all_config_sections_and_fields_have_i18n() -> None:
    """新增或现有配置漏译时，WebUI 不应静默回退为混合语言。"""

    schema = _config_schema()

    for section_name, section in schema["sections"].items():
        translations = section.get("i18n", {})
        for locale in _SUPPORTED_SCHEMA_LOCALES:
            localized = translations.get(locale, {})
            assert localized.get("title"), f"{section_name} 缺少 {locale} title"
            assert localized.get("description"), f"{section_name} 缺少 {locale} description"
        for field_name, field in section["fields"].items():
            _assert_field_i18n(f"{section_name}.{field_name}", field)


def test_config_select_choices_do_not_include_empty_strings() -> None:
    """配置 Schema 中的空下拉选项会使宿主 Select 组件崩溃。"""

    def _check_fields(fields: dict[str, Any], parent: str) -> None:
        for name, field in fields.items():
            field_path = f"{parent}.{name}"
            assert "" not in (field.get("choices") or []), field_path
            _check_fields(field.get("item_fields") or {}, field_path)

    for name, section in _config_schema()["sections"].items():
        _check_fields(section["fields"], name)


def test_all_config_classes_have_section_i18n() -> None:
    """根配置节和嵌套列表模型都必须保留完整的节级多语言元数据。"""

    _bootstrap_plugin_package()
    config_module = import_module(f"{_PKG_NAME}.src.maimai_drawpic.domain.configuration.models")
    class_names = (
        "PluginSectionConfig",
        "GeneralConfig",
        "StylePresetConfig",
        "StyleConfig",
        "ProxyConfig",
        "OpenAICompatibleInstanceConfig",
        "OpenAIModelConfig",
        "GoogleModelConfig",
        "ZhipuModelConfig",
        "MiniMaxModelConfig",
        "AliyunModelConfig",
        "VolcengineModelConfig",
        "SiliconFlowModelConfig",
        "NovelAIModelConfig",
        "ComfyUIModelConfig",
        "PromptModerationConfig",
        "ImageModerationConfig",
    )

    for class_name in class_names:
        translations = getattr(config_module, class_name).__ui_i18n__
        for locale in _SUPPORTED_SCHEMA_LOCALES:
            assert translations[locale]["title"]
            assert translations[locale]["description"]


def test_contextual_labels_preserve_required_and_provider_meaning() -> None:
    """共享字段名不得抹掉平台名称、必填性或审核类型。"""

    sections = _config_schema()["sections"]

    assert sections["zhipu"]["fields"]["api_key"]["i18n"]["en_US"]["label"] == ("Zhipu API Key (Required)")
    assert sections["zhipu"]["fields"]["models"]["i18n"]["ja_JP"]["label"] == ("智譜モデル一覧（必須）")
    assert sections["zhipu"]["fields"]["quality"]["i18n"]["ko_KR"]["label"] == ("생성 품질(선택 사항)")
    assert sections["aliyun"]["fields"]["base_url"]["i18n"]["en_US"]["label"] == ("DashScope Base URL (Required)")
    assert sections["volcengine"]["fields"]["base_url"]["i18n"]["en_US"]["label"] == ("Volcengine Base URL")
    assert sections["volcengine"]["fields"]["models"]["i18n"]["en_US"]["label"] == (
        "Volcengine Image Models"
    )
    assert sections["plugin"]["fields"]["enabled"]["i18n"]["en_US"]["label"] == ("Enable Plugin")
    assert (
        sections["prompt_review"]["fields"]["review_prompt"]["i18n"]["en_US"]["label"] == "Prompt Review Instructions"
    )
    assert sections["image_review"]["fields"]["review_prompt"]["i18n"]["en_US"]["label"] == "Image Review Instructions"


def test_manifest_declares_all_config_locales() -> None:
    """Manifest 必须声明配置 Schema 实际提供的全部语言。"""

    manifest = json.loads((_PLUGIN_DIR / "_manifest.json").read_text(encoding="utf-8"))

    assert manifest["i18n"]["default_locale"] == "zh-CN"
    assert manifest["i18n"]["supported_locales"] == [
        "zh-CN",
        "en-US",
        "ja-JP",
        "ko-KR",
    ]


def test_manifest_requires_current_maibot_and_sdk() -> None:
    """发布清单必须拒绝未核对当前扩展页面和标准路径 API 的旧运行时。"""

    manifest = json.loads((_PLUGIN_DIR / "_manifest.json").read_text(encoding="utf-8"))

    assert manifest["host_application"]["min_version"] == "1.3.6"
    assert manifest["sdk"]["min_version"] == "2.12.0"
