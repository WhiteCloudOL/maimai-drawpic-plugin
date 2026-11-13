"""工作台配置、安全边界和后台绘图回归验证，不调用外部平台。"""

from io import BytesIO
from pathlib import Path
from types import ModuleType
from maibot_sdk import PluginContext
from maibot_sdk.components import collect_components
from maibot_sdk.config import rebuild_plugin_config_data
from maibot_sdk.context import PluginPaths
from PIL import Image
import asyncio
import base64
import importlib
import json
import sys
import tomlkit
import pytest

_PACKAGE = "drawpic_workspace_test"
package = ModuleType(_PACKAGE)
package.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules[_PACKAGE] = package
plugin_module = importlib.import_module(f"{_PACKAGE}.plugin")
storage = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.storage.platforms")
DrawpicConfig = storage.DrawpicConfig


def image_bytes() -> bytes:
    result = BytesIO()
    Image.new("RGB", (640, 400), "#c8788c").save(result, "PNG")
    return result.getvalue()


@pytest.fixture
def make_plugin(tmp_path, monkeypatch):
    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    monkeypatch.setitem(plugin_module.DrawpicPlugin.on_load.__globals__, "PLUGIN_DIR", plugin_dir)

    def create(configured=True):
        plugin = plugin_module.create_plugin()
        plugin._set_context(
            PluginContext(
                "maimai-drawpic-plugin", paths=PluginPaths(data_dir=tmp_path / "data", runtime_dir=tmp_path / "runtime")
            )
        )
        config = DrawpicConfig().model_dump(mode="json")
        config["general"].update(prompt_review_enabled=False, image_review_enabled=False)
        if configured:
            config["openai"].update(api_key="secret-fixture-key", models=["sample-image"])
            config["general"]["default_model"] = "sample-image"
        plugin.set_plugin_config(config)
        return plugin

    return create


def test_fresh_host_defaults_do_not_create_workspace_sections(make_plugin):
    plugin = make_plugin(configured=False)
    defaults = plugin.get_default_config()
    assert set(defaults) == {"plugin", "proxy"}
    normalized, _ = plugin.normalize_plugin_config(defaults)
    assert set(normalized) == {"plugin", "proxy"}
    assert set(plugin.get_webui_config_schema()["sections"]) == {"plugin", "proxy"}


def test_host_version_upgrade_preserves_json_settings(make_plugin):
    plugin = make_plugin(configured=False)
    config_path = plugin_module.DrawpicPlugin.on_load.__globals__["PLUGIN_DIR"] / "config.toml"
    store = storage.WorkspaceConfigStore(plugin.ctx.paths.data_dir, config_path)
    store.initialize({})
    store.save_provider(
        {"kind": "openai", "name": "Saved", "config": {"api_key": "fixture-saved-key", "models": ["image-a"]}},
        store.revision,
    )
    values = store.settings.values.copy()
    values["general"] = {**values["general"], "default_model": "Saved/image-a", "request_retry_count": 0}
    store.save_common(values, values, store.revision)
    originals = {p: p.read_bytes() for p in (store.path, store.settings.path)}
    raw = storage.host_config(DrawpicConfig().model_dump(mode="json"))
    raw["plugin"]["config_version"] = "2.37.0"
    config_path.write_text(tomlkit.dumps(raw), encoding="utf-8")

    # Runner 先按默认结构重建并写回，再调用 on_load；不能只验证直接加载模型。
    defaults = plugin.get_default_config()
    assert set(defaults) == {"plugin", "proxy"}
    rebuilt = rebuild_plugin_config_data(defaults, raw)
    normalized, _ = plugin.normalize_plugin_config(rebuilt)
    config_path.write_text(tomlkit.dumps(normalized), encoding="utf-8")
    plugin.set_plugin_config(normalized)

    async def run():
        await plugin.on_load()
        try:
            assert plugin.config.general.default_model == "Saved/image-a"
            assert plugin.config.general.request_retry_count == 0
            assert plugin._platform_store.providers == store.providers
            assert set(tomlkit.parse(config_path.read_text(encoding="utf-8"))) == {"plugin", "proxy"}
            assert {p: p.read_bytes() for p in originals} == originals
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_legacy_defaults_preserve_original_until_backup_and_migration(make_plugin):
    plugin = make_plugin(configured=False)
    config_path = plugin_module.DrawpicPlugin.on_load.__globals__["PLUGIN_DIR"] / "config.toml"
    original = (
        b'[plugin]\r\nconfig_version="2.34.0"\r\n[openai]\r\napi_key="fixture-original-key"\r\n'
        b'models=["original-image"]\r\n[general]\r\ndefault_model="original-image"\r\nrequest_retry_count=0\r\n'
        b'[prompt_review]\r\nenabled=true\r\nreview_prompt="fixture-original-review"\r\n'
    )
    config_path.write_bytes(original)
    raw = tomlkit.parse(original.decode())
    defaults = plugin.get_default_config()
    assert set(defaults) == {"plugin", "proxy", "general", "openai", "prompt_review"}
    assert defaults["plugin"]["config_version"] == raw["plugin"]["config_version"]
    assert "fixture-original-key" not in json.dumps(defaults)
    # 版本不提前升级，Runner 不会在迁移备份之前写回原文件。
    normalized, _ = plugin.normalize_plugin_config(raw)
    plugin.set_plugin_config(normalized)

    async def run():
        await plugin.on_load()
        try:
            assert plugin._platform_store.providers[0]["config"]["api_key"] == "fixture-original-key"
            assert plugin.config.general.request_retry_count == 0
            assert plugin.config.general.prompt_review_enabled is True
            assert plugin.config.general.prompt_review_prompt == "fixture-original-review"
            backups = (plugin.ctx.paths.data_dir / "migration_backups").glob("*.toml")
            assert any(p.read_bytes() == original for p in backups)
            assert set(tomlkit.parse(config_path.read_text(encoding="utf-8"))) == {"plugin"}
            assert set(plugin.get_default_config()) == {"plugin", "proxy"}
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_migration_masking_revision_and_key_preservation(tmp_path):
    config_path = tmp_path / "config.toml"
    original = b'[plugin]\r\nconfig_version = "2.30.0"\r\n[openai]\r\napi_key = "fixture-key"\r\n'
    config_path.write_bytes(original)
    store = storage.WorkspaceConfigStore(tmp_path / "data", config_path)
    config = DrawpicConfig().model_dump(mode="json")
    config["openai"]["api_key"] = "fixture-key"
    store.initialize(config)
    assert len(store.providers) == 1
    assert "openai" not in tomlkit.parse(config_path.read_text(encoding="utf-8"))
    backups = list((tmp_path / "data/migration_backups").glob("*.toml"))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    snapshot = store.public_snapshot()
    assert "fixture-key" not in json.dumps(snapshot)
    record = snapshot["providers"][0]
    payload = {key: record[key] for key in ("id", "kind", "name", "config")}
    store.save_provider(payload, snapshot["revision"])
    assert store.providers[0]["config"]["api_key"] == "fixture-key"
    with pytest.raises(ValueError, match="更新"):
        store.save_provider(payload, snapshot["revision"])
    payload["clear_api_key"] = True
    store.save_provider(payload, store.revision)
    assert not store.providers[0]["config"]["api_key"]
    restarted = storage.WorkspaceConfigStore(store.path.parent, config_path)
    restarted.initialize(config)
    assert restarted.providers == store.providers
    effective = restarted.effective_config({})
    assert not effective.google.enabled and not effective.zhipu.enabled


def test_config_rejects_unknown_fields_and_nonfinite_values():
    for value in ('{"x":NaN}', '{"x":Infinity}', "[]"):
        with pytest.raises(ValueError):
            storage.parse_json_object(value)
    with pytest.raises(ValueError, match="未知"):
        storage._validate_fields(storage.WorkspaceConfigStore.platform_model("openai"), {"typo": "secret"})
    with pytest.raises(ValueError) as failure:
        storage._validate_fields(
            storage.WorkspaceConfigStore.platform_model("openai"), {"max_images": "secret-do-not-return"}
        )
    assert "secret-do-not-return" not in str(failure.value)
    with pytest.raises(ValueError, match="嵌套"):
        storage._validate_fields(
            DrawpicConfig.model_fields["style"].annotation, {"presets": [{"name": "a", "typo": 1}]}
        )


def test_component_bindings_are_private_and_public_api_is_limited():
    declarations = {item["name"]: item for item in collect_components(plugin_module.create_plugin())}
    document = json.loads((Path(__file__).parents[1] / "webui.json").read_text(encoding="utf-8"))
    page = document["pages"][0]
    for binding in [*page["queries"].values(), *page["actions"].values()]:
        component = declarations[binding["api"]]
        assert component["type"] == "API"
        assert not component["metadata"]["public"]
        assert component["metadata"]["version"] == binding["version"]
    public = {name for name, declaration in declarations.items() if declaration["metadata"].get("public")}
    assert public == {
        "drawpic_models",
        "drawpic_submit",
        "drawpic_task",
        "drawpic_tasks",
        "drawpic_image",
        "drawpic_cancel",
        "drawpic_presets",
        "drawpic_submit_v2",
        "drawpic_task_v2",
        "drawpic_request_v2", "drawpic_preferences_v2", "drawpic_preferences_set_v2", "drawpic_presets_v2",
        "drawpic_image_v2",
        "drawpic_cancel_v2",
        "drawpic_tasks_v2",
        "drawpic_references_v2",
    }
    assert (Path(__file__).parents[1] / page["entry"]).is_file()


def test_empty_workspace_load_and_presets(make_plugin):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            bootstrap = await plugin.workspace_bootstrap()
            assert not bootstrap["providers"] and not bootstrap["models"]
            openai = next(item for item in bootstrap["catalog"] if item["kind"] == "openai")
            assert openai["name"] == "OpenAI / 兼容服务"
            assert openai["default_name"] == "OpenAI_Compatible"
            assert len(json.dumps(bootstrap, ensure_ascii=False).encode()) < 512 * 1024
            await plugin.drawpic_presets(
                "save",
                preset_json=json.dumps({"name": "watercolor", "positive_prompt_template": "watercolor, {prompt}"}),
            )
            result = await plugin.drawpic_presets("get", "watercolor")
            assert result["preset"]["positive_prompt_template"] == "watercolor, {prompt}"
            with pytest.raises(ValueError, match="同名"):
                await plugin.drawpic_presets("save", preset_json='{"name":"WATERCOLOR"}')
            await plugin.drawpic_presets("delete", "watercolor")
            assert (await plugin.drawpic_presets())["presets"] == []
            with pytest.raises(ValueError, match="模型"):
                await plugin.drawpic_submit("test")
            assert plugin._task_store.get_task_count() == 0
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_tasks_images_idempotency_and_config_refresh(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        service = plugin._require_draw_service()
        calls = []
        ready = asyncio.Event()

        async def generate(**kwargs):
            calls.append(kwargs)
            await ready.wait()
            return [image_bytes()]

        monkeypatch.setattr(service, "_run_image_request_attempt", generate)
        try:
            first = await plugin.drawpic_submit("a cat", request_id="test-unique-1")
            second = await plugin.drawpic_submit("a cat", request_id="test-unique-1")
            assert second["reused"] and first["task_id"] == second["task_id"]
            with pytest.raises(ValueError, match="request_id"):
                await plugin.drawpic_submit("another cat", request_id="test-unique-1")
            old_tasks = list(service.background_tasks)
            await plugin._workspace_service.refresh()
            assert service in plugin._retired_draw_services
            ready.set()
            await asyncio.gather(*old_tasks)
            result = await plugin.drawpic_task(first["task_id"])
            assert result["status"] == "completed" and result["images"][0]["width"] == 640
            assert len(calls) == 1 and "prompt" not in result and "session_key" not in result
            before = plugin._task_store.path.read_bytes()
            listing = await plugin.drawpic_tasks()
            assert listing["items"][0]["thumbnail"].startswith("data:image/webp;base64,")
            cached = plugin.ctx.paths.runtime_dir / "results" / first["task_id"]
            assert (cached / "0.preview.webp").exists()
            assert not (plugin.ctx.paths.data_dir / "results" / first["task_id"]).exists()
            assert plugin._task_store.path.read_bytes() == before
            raw, offset = bytearray(), 0
            while True:
                chunk = await plugin.drawpic_image(first["task_id"], kind="original", offset=offset)
                assert len(json.dumps(chunk).encode()) < 512 * 1024
                raw.extend(base64.b64decode(chunk["data"]))
                offset = chunk["next_offset"]
                if chunk["done"]:
                    break
            assert bytes(raw) == image_bytes()
            with pytest.raises(ValueError):
                await plugin.drawpic_image("../outside", kind="original")
            with pytest.raises(ValueError):
                await plugin.drawpic_image(first["task_id"], index=True)
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_source_modes_reject_before_task_and_cancel(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            encoded = base64.b64encode(image_bytes()).decode()
            with pytest.raises(ValueError, match="文生图"):
                await plugin.drawpic_submit("cat", source_images=[encoded])
            with pytest.raises(ValueError, match="真实源"):
                await plugin.drawpic_submit("cat", task_type="edit_image")
            with pytest.raises(ValueError, match="列表"):
                await plugin.drawpic_submit("cat", source_images="wrong")
            assert plugin._task_store.get_task_count() == 0

            async def wait(**kwargs):
                await asyncio.Event().wait()

            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", wait)
            result = await plugin.drawpic_submit("cat")
            await asyncio.sleep(0.02)
            await plugin.drawpic_cancel(result["task_id"])
            assert (await plugin.drawpic_task(result["task_id"]))["message"] == "任务已取消"
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_same_kind_instances_keep_independent_credentials(tmp_path):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize({})
    defaults = store.platform_model("google")().model_dump(mode="json")
    for name, key in [("Google_A", "key-A"), ("Google_B", "key-B")]:
        store.save_provider({"kind": "google", "name": name, "config": {**defaults, "api_key": key}}, store.revision)
    with pytest.raises(ValueError, match="不能重复"):
        store.save_provider({"kind": "openai", "name": "google_a", "config": {}}, store.revision)
    router_class = importlib.import_module(
        f"{_PACKAGE}.src.maimai_drawpic.application.routing.instances"
    ).InstanceProviderRouter
    config = store.effective_config({})
    router = router_class(config, [(item, store.effective_config({}, [item])) for item in store.providers])
    models = router.get_google_models()
    first = next(model for model in models if model.startswith("Google_A/"))
    second = next(model for model in models if model.startswith("Google_B/"))
    provider_a, _ = router.require_platform_for_model(first)
    provider_b, _ = router.require_platform_for_model(second)
    assert provider_a.provider.api_key == "key-A"
    assert provider_b.provider.api_key == "key-B"
    assert provider_a.model == provider_b.model
    with pytest.raises(ValueError, match="多个平台"):
        router.resolve_model_name(provider_a.model)


def test_ordered_fallbacks_obey_retry_limit(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            record = (await plugin.workspace_bootstrap())["providers"][0]
            record["config"]["models"] = ["sample-image", "backup-one", "backup-two"]
            payload = {key: record[key] for key in ("id", "kind", "name", "config")}
            await plugin.workspace_provider_save(json.dumps(payload), plugin._platform_store.revision)
            current = storage.common_config(plugin.config.model_dump(mode="json"))
            current.pop("plugin", None)
            current["general"]["fallback_models"] = [f"{record['name']}/backup-one", f"{record['name']}/backup-two"]
            current["general"]["request_retry_count"] = 1
            await plugin.workspace_settings_save(json.dumps(current), plugin._platform_store.revision)
            service = plugin._require_draw_service()
            calls = []

            async def generate(**kwargs):
                model = kwargs["attempt"].model.rsplit("/", 1)[1]
                calls.append(model)
                if model != "backup-two":
                    errors = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.domain.errors")
                    raise errors.ProviderConnectionError("temporary fixture connection failure")
                return [image_bytes()]

            monkeypatch.setattr(service, "_run_image_request_attempt", generate)
            result = await plugin.drawpic_submit("cat")
            await asyncio.gather(*list(service.background_tasks))
            assert calls == ["sample-image", "sample-image", "backup-one", "backup-one", "backup-two"]
            assert (await plugin.drawpic_task(result["task_id"]))["status"] == "completed"
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_legacy_fallback_is_migrated_and_reset_defaults_are_safe(make_plugin):
    plugin = make_plugin()
    config = DrawpicConfig().model_dump(mode="json")
    config["general"]["fallback_model"] = "legacy-model"
    config["general"]["fallback_models"] = []
    plugin.set_plugin_config(config)
    common = storage.common_config(plugin.get_plugin_config_data())
    assert common["general"]["fallback_models"] == ["legacy-model"]
    assert "fallback_model" not in common["general"]
    assert DrawpicConfig().general.default_model == ""
    assert DrawpicConfig().openai.models == ["gpt-image-2.5"]


def test_artifact_retention_respects_capacity_age_and_owned_directories(tmp_path):
    from time import time
    import os

    cls = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.storage.retention").ArtifactRetention
    retention = cls(tmp_path)
    retention.INPUT_MAX_BYTES = 100
    retention.INPUT_MAX_AGE = 10
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    old = inputs / "old.image"
    old.write_bytes(b"x" * 50)
    os.utime(old, (time() - 20, time() - 20))
    recent = inputs / "recent.image"
    recent.write_bytes(b"x" * 60)
    retention.prune_inputs(60)
    assert not old.exists() and not recent.exists()
    workflow = tmp_path / "workflows/t2i.json"
    workflow.parent.mkdir()
    workflow.write_bytes(b"user owned workflow")
    backup = tmp_path / "migration_backups/original.toml"
    backup.parent.mkdir()
    backup.write_bytes(b"user owned backup")
    root = tmp_path / "results"
    root.mkdir()
    for identifier in ("a" * 12, "b" * 12):
        path = root / identifier
        path.mkdir()
        (path / "result.png").write_bytes(b"x" * 80)
    retention.RESULT_MAX_BYTES = 100
    retention.prune_results({"b" * 12})
    assert not (root / ("a" * 12)).exists() and (root / ("b" * 12)).exists()
    assert workflow.read_bytes() == b"user owned workflow"
    assert backup.read_bytes() == b"user owned backup"
    with pytest.raises(ValueError, match="容量"):
        retention.prune_results(set(), 101)


def test_log_queries_are_bounded_cached_and_redacted(tmp_path):
    import logging

    module = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.observability.logging")
    logger = logging.getLogger("drawpic-log-query-test")
    store = module.WorkspaceLogStore(tmp_path, logger, lambda: ["secret-fixture"])
    try:
        for index in range(200):
            record = logging.LogRecord(
                "drawpic",
                logging.INFO,
                "",
                0,
                f"task_id=aaaaaaaaaaaa row={index} secret-fixture https://example.com/a?token=secret",
                (),
                None,
            )
            store.file_handler.emit(record)
        result = store.query("a" * 12, "INFO", 10)
        assert len(result["lines"]) == 10 and "row=199" in result["lines"][-1]
        assert "secret-fixture" not in "\n".join(result["lines"])
        assert "?token=secret" not in "\n".join(result["lines"])
        assert store.query("a" * 12, "INFO", 10, result["cursor"])["unchanged"]
        assert not store.query("", "WARNING", 10, result["cursor"])["unchanged"]
    finally:
        store.close()


def test_legacy_and_temporary_images_share_capacity_and_preserve_originals(tmp_path):
    results_module = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.storage.results")
    data, runtime = tmp_path / "data", tmp_path / "runtime"
    legacy = results_module.ImageResultStore(data)
    legacy.save("a" * 12, [image_bytes()])
    store = results_module.ImageResultStore(data, runtime_dir=runtime)
    assert store.original_chunk("a" * 12, 0, 0)["done"]
    store.save("b" * 12, [image_bytes()])
    assert store.images("a" * 12) and store.images("b" * 12)
    assert (runtime / "results" / ("b" * 12) / "0.preview.webp").exists()
    # 调低容量后跨新旧目录清理，仍保留受保护任务及元数据所在的数据目录。
    store.retention.RESULT_MAX_BYTES = 4000
    store.cleanup({"b" * 12})
    assert not store.images("a" * 12) and store.images("b" * 12)
    assert sum(path.stat().st_size for path in runtime.rglob("*") if path.is_file()) <= 4000


def test_log_capacity_includes_backups_and_applies_reduced_limits(tmp_path):
    import logging

    module = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.observability.logging")
    logger = logging.getLogger("drawpic-log-capacity-test")
    store = module.WorkspaceLogStore(tmp_path, logger, lambda: [], 10)
    try:
        for index in range(8000):
            store.file_handler.emit(
                logging.LogRecord("drawpic", logging.INFO, "", 0, f"{index}:" + "sample log " * 45, (), None)
            )
        assert sum(path.stat().st_size for path in store.path.parent.glob("drawpic.log*")) > 1024 * 1024
        store.configure_limit(1)
        for index in range(3000):
            store.file_handler.emit(
                logging.LogRecord("drawpic", logging.INFO, "", 0, f"new-{index}:" + "sample log " * 45, (), None)
            )
        assert sum(path.stat().st_size for path in store.path.parent.glob("drawpic.log*")) <= 1024 * 1024
        assert "new-2999" in store.query(limit=1)["lines"][-1]
    finally:
        store.close()


def test_cache_capacity_does_not_turn_successful_generation_into_failure(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        service = plugin._require_draw_service()

        async def generate(**kwargs):
            return [image_bytes()]

        monkeypatch.setattr(service, "_run_image_request_attempt", generate)
        plugin._result_store.retention.RESULT_MAX_BYTES = 1
        try:
            result = await plugin.drawpic_submit("cat")
            await asyncio.gather(*list(service.background_tasks))
            task = await plugin.drawpic_task(result["task_id"])
            assert task["status"] == "completed" and not task["images"]
            assert "图片未缓存" in task["message"] and "缓存上限" in task["message"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_workspace_owns_drawing_settings_and_ignores_old_host_fields(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            bootstrap = await plugin.workspace_bootstrap()
            assert set(bootstrap["settings"]) == {"general", "style"}
            assert set(plugin.get_plugin_config_data()) == {"plugin", "proxy"}
            assert set(plugin.get_webui_config_schema()["sections"]) == {"plugin", "proxy"}
            before = plugin.get_plugin_config_data()
            values = bootstrap["settings"]
            values["general"]["request_retry_count"] = 2
            values["plugin"] = {"enabled": False}
            values["proxy"] = {"enabled": True, "host": "do-not-apply"}
            values["clear_proxy_password"] = True
            await plugin.workspace_settings_save(json.dumps(values), bootstrap["revision"])
            assert plugin.get_plugin_config_data() == before
            assert plugin.config.general.request_retry_count == 2
            saved = json.loads((plugin.ctx.paths.data_dir / "workspace_settings.json").read_text(encoding="utf-8"))
            assert set(saved["settings"]) == {"general", "style"}
            assert saved["settings"]["general"]["request_retry_count"] == 2
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_workspace_settings_migration_preserves_toml_host_values(tmp_path):
    config_path = tmp_path / "config.toml"
    original = b'[plugin]\r\nconfig_version="2.34.0"\r\n[proxy]\r\nenabled=false\r\n[general]\r\ndefault_model="existing-model"\r\n[style]\r\ndefault_style=""\r\n'
    config_path.write_bytes(original)
    config = DrawpicConfig().model_dump(mode="json")
    config["general"]["default_model"] = "existing-model"
    store = storage.WorkspaceConfigStore(tmp_path / "data", config_path)
    store.initialize(config)
    assert set(tomlkit.parse(config_path.read_text(encoding="utf-8"))) == {"plugin", "proxy"}
    assert store.settings.values["general"]["default_model"] == "existing-model"
    assert any(path.read_bytes() == original for path in (tmp_path / "data/migration_backups").glob("*.toml"))
    restarted = storage.WorkspaceConfigStore(tmp_path / "data", config_path)
    restarted.initialize({"plugin": config["plugin"], "proxy": config["proxy"]})
    assert restarted.effective_config({}).general.default_model == "existing-model"
