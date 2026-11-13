"""持久参考资产、实际任务模式与显式开关；不调用真实模型。"""

from pathlib import Path
import importlib
import json

import pytest

from test_workspace import _PACKAGE, image_bytes


def module(name):
    return importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.{name}")


def test_gallery_default_tags_revision_and_frozen_content(tmp_path):
    store = module("infrastructure.storage.reference_assets").ReferenceAssetStore(tmp_path)
    raw = image_bytes()
    first = store.update(revision=0, operation="save", name="默认", tags=["居家"], raw=raw)
    identifier = first["assets"][0]["id"]
    assert first["default_reference_id"] == identifier
    second = store.update(revision=1, operation="save", name="冬装", tags=["冬装"], raw=raw)
    winter = second["assets"][1]["id"]
    assert second["default_reference_id"] == identifier
    assert store.select_self(["冬装"]) == winter
    assert store.select_self([], "画你穿冬装") == winter
    assert store.select_self(["没有命中"]) == identifier
    with pytest.raises(ValueError, match="刷新"):
        store.update(revision=1, operation="default", asset_id=winter)
    frozen = store.read(identifier, kind="self")
    store.update(revision=2, operation="save", asset_id=identifier, name="替换", tags=[], raw=raw + b"version2")
    assert frozen.raw == raw and frozen.version != store.read(identifier, kind="self").version
    current = store.update(revision=3, operation="delete", asset_id=identifier)
    assert current["default_reference_id"] == winter
    with pytest.raises(ValueError, match="引用"):
        store.update(revision=4, operation="delete", asset_id=winter, referenced_ids=[winter])
    assert store.update(revision=4, operation="delete", asset_id=winter)["default_reference_id"] == ""


def test_gallery_corruption_and_asset_scope_are_not_defaulted(tmp_path):
    store = module("infrastructure.storage.reference_assets").ReferenceAssetStore(tmp_path)
    result = store.update(revision=0, operation="save", name="场景", tags=[], kind="preset", raw=image_bytes())
    with pytest.raises(ValueError, match="用途"):
        store.read(result["assets"][0]["id"], kind="self")
    with pytest.raises(ValueError, match="ID"):
        store.read("../outside", kind="preset")
    original = store.index.read_text(encoding="utf-8")
    store.index.write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError):
        store.snapshot()
    assert store.index.read_text(encoding="utf-8") == "{broken"
    store.index.write_text(original, encoding="utf-8")
    image = result["assets"][0]
    store._path(image["id"], image["version"]).write_bytes(b"broken")
    with pytest.raises(ValueError, match="版本"):
        store.read(image["id"], kind="preset")


def test_presets_mode_defaults_and_legacy_contract():
    styles = module("domain.styles")
    config = module("domain.configuration.models")
    current = config.StyleConfig(default_style="水彩", presets=[
        config.StylePresetConfig(name="水彩", positive_prompt_template="watercolor, {prompt}"),
        config.StylePresetConfig(name="夜景", preset_type="image_to_image", positive_prompt_template="night, {prompt}"),
    ])
    resolver = styles.StylePromptResolver(current)
    assert resolver.resolve(style_name="", user_prompt="cat", task_type="draw").positive_prompt == "watercolor, cat"
    assert resolver.resolve(style_name="", user_prompt="cat", task_type="edit_image").positive_prompt == "cat"
    with pytest.raises(ValueError, match="未启用"):
        resolver.resolve(style_name="夜景", user_prompt="cat", task_type="edit_image")
    # 旧 API 未传任务模式，保留历史文字模板行为。
    assert resolver.resolve(style_name="", user_prompt="cat").positive_prompt == "watercolor, cat"
    current.image_edit_presets_enabled = True
    assert resolver.select_for_task("", "edit_image") is None
    current.presets[0].apply_to_image_edit = True
    assert resolver.select_for_task("", "edit_image").name == "水彩"
    current.default_image_edit_preset = "夜景"
    assert resolver.select_for_task("", "edit_image").name == "夜景"
    assert resolver.select_for_task("none", "edit_image") is None
    with pytest.raises(ValueError, match="不兼容"):
        resolver.select_for_task("夜景", "draw")
    current.default_image_edit_preset = "失效"
    with pytest.raises(ValueError):
        resolver.select_for_task("", "edit_image")


@pytest.mark.parametrize("values", [
    {"preset_type": "text_to_image", "reference_bindings": [{"asset_id": "id"}]},
    {"preset_type": "image_to_image", "apply_to_image_edit": True},
    {"preset_type": "image_to_image", "reference_bindings": [{"asset_id": "a"}, {"asset_id": "b"}]},
])
def test_invalid_preset_configuration_is_rejected(values):
    with pytest.raises(ValueError):
        module("domain.configuration.models").StylePresetConfig(**values)


@pytest.mark.parametrize("values", [
    {"self_reference": "auto"},
    {"self_reference_ids": ["id"]},
    {"material_sources": ["chat", "chat"], "user_request": "画猫"},
    {"material_sources": ["web"]},
    {"unknown": True},
])
def test_reference_options_reject_ambiguous_or_unknown_input(values):
    with pytest.raises(ValueError):
        module("domain.references").ReferenceOptions.model_validate(values)
