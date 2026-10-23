"""NovelAI 统一模型列表的保存、旧配置合并与重载，不访问真实平台。"""

from test_workspace import DrawpicConfig, make_plugin as make_plugin, storage
import asyncio
import json
import pytest


def test_novelai_editor_schema_and_save_round_trip(make_plugin):
    async def run():
        plugin = make_plugin(configured=False)
        await plugin.on_load()
        try:
            data = await plugin.workspace_bootstrap()
            fields = data["schema"]["sections"]["novelai"]["fields"]
            assert fields["models"]["type"] == "array" and not fields["models"].get("multiple")
            assert fields["custom_models"]["hidden"]
            catalog = next(item for item in data["catalog"] if item["kind"] == "novelai")
            assert catalog["model_discovery"] is False
            assert catalog["model_presets"][:2] == ["nai-diffusion-5-full", "nai-diffusion-5-curated"]
            assert "不是在线接口结果" in catalog["model_presets_hint"]
            defaults = catalog["defaults"]
            assert defaults["models"] == ["nai-diffusion-5-full", "nai-diffusion-5-curated"]
            defaults.update(api_key="fixture-nai-key", models=["nai-diffusion-5-full", "gateway-custom-image"])
            saved = await plugin.workspace_provider_save(json.dumps({
                "kind": "novelai", "name": "novelai", "config": defaults,
            }), data["revision"])
            assert saved["saved"]
            models = [item["name"] for item in (await plugin.drawpic_models())["models"]]
            assert models == ["novelai/nai-diffusion-5-full", "novelai/gateway-custom-image"]
            record = (await plugin.workspace_bootstrap())["providers"][0]
            assert record["has_api_key"] and not record["config"]["api_key"]
            assert "custom_models" not in record["config"]
            # 编辑时空密钥保留原值；同一列表允许继续添加自定义模型。
            record["config"]["models"].append("another-custom-image")
            await plugin.workspace_provider_save(json.dumps({
                key: record[key] for key in ("id", "kind", "name", "config")
            }), saved["revision"])
            assert plugin._platform_store.providers[0]["config"]["api_key"] == "fixture-nai-key"
            disk = json.loads(plugin._platform_store.path.read_text(encoding="utf-8"))
            assert "custom_models" not in disk["providers"][0]["config"]
            assert disk["providers"][0]["config"]["models"] == defaults["models"] + ["another-custom-image"]
        finally:
            await plugin.on_unload()
        reloaded = make_plugin(configured=False)
        await reloaded.on_load()
        try:
            record = reloaded._platform_store.providers[0]["config"]
            assert record["models"][-1] == "another-custom-image"
            assert record["api_key"] == "fixture-nai-key"
        finally:
            await reloaded.on_unload()
    asyncio.run(run())


def test_novelai_legacy_custom_models_merge_without_overwriting_file(tmp_path):
    path = tmp_path / "platforms.json"
    config = DrawpicConfig().novelai.model_dump(mode="json")
    config.update(api_key="fixture-legacy-key", models=["nai-diffusion-4-5-full"],
                  custom_models=["legacy-custom", "nai-diffusion-4-5-full", "legacy-other"])
    payload = {"schema_version": 1, "revision": 3, "providers": [{
        "id": "a" * 32, "kind": "novelai", "name": "legacy", "config": config,
    }]}
    original = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    path.write_bytes(original)
    store = storage.WorkspaceConfigStore(tmp_path, tmp_path / "config.toml")
    store.initialize({})
    record = store.providers[0]
    assert record["config"]["models"] == ["nai-diffusion-4-5-full", "legacy-custom", "legacy-other"]
    assert "custom_models" not in record["config"]
    assert path.read_bytes() == original  # 读取只规范化内存，不覆盖用户原文件。
    store.save_provider(record, store.revision)
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert disk["providers"][0]["config"]["models"] == record["config"]["models"]
    assert disk["providers"][0]["config"]["api_key"] == "fixture-legacy-key"
    assert "custom_models" not in disk["providers"][0]["config"]


@pytest.mark.parametrize("custom_models", [None, "not-a-list", [False]])
def test_novelai_invalid_legacy_models_are_not_discarded(tmp_path, custom_models):
    store = storage.WorkspaceConfigStore(tmp_path, tmp_path / "config.toml")
    store.initialize({})
    original = store.path.read_bytes()
    with pytest.raises(ValueError, match="custom_models"):
        store.save_provider({"kind": "novelai", "name": "invalid", "config": {
            "api_key": "fixture-key", "custom_models": custom_models,
        }}, store.revision)
    assert store.path.read_bytes() == original
