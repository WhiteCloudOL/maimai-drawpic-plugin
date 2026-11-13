"""配置与修订号原子提交、重命名恢复及旧格式迁移；只使用临时目录和模拟服务。"""

from copy import deepcopy
from pathlib import Path
import asyncio
import importlib
import json

import pytest
import tomlkit

from test_workspace import _PACKAGE, make_plugin, storage

settings_module = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.storage.settings")


def new_store(tmp_path):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize({})
    return store


def renamed_fixture(tmp_path):
    store = new_store(tmp_path)
    store.save_provider({"kind": "openai", "name": "Original", "config": {
        "api_key": "fixture-transaction-key", "models": ["image-a", "image-b"],
    }}, store.revision)
    values = deepcopy(store.settings.values)
    values["general"].update(
        default_model="Original/image-a",
        fallback_models=["Original/image-b", "Elsewhere/image-a"],
        image_edit_unsupported_models=["Original/image-a"],
        text_to_image_unsupported_models=["Original/image-b"],
    )
    store.save_common(values, values, store.revision)
    payload = deepcopy(store.providers[0])
    payload["name"] = "Renamed"
    payload["config"]["api_key"] = ""
    return store, payload


def snapshot_bytes(store):
    paths = [store.path, store.settings.path, store.transaction_path]
    return {path: path.read_bytes() if path.exists() else None for path in paths}


def assert_renamed(store, revision):
    assert store.revision == revision
    assert store.providers[0]["name"] == "Renamed"
    assert store.providers[0]["config"]["api_key"] == "fixture-transaction-key"
    general = store.settings.values["general"]
    assert general["default_model"] == "Renamed/image-a"
    assert general["fallback_models"] == ["Renamed/image-b", "Elsewhere/image-a"]
    assert general["image_edit_unsupported_models"] == ["Renamed/image-a"]
    assert general["text_to_image_unsupported_models"] == ["Renamed/image-b"]
    assert "fixture-transaction-key" not in json.dumps(store.public_snapshot())


def test_settings_failure_keeps_content_and_revision_after_refresh_restart(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        store = plugin._platform_store
        original_save = store.settings._save
        try:
            initial = await plugin.workspace_bootstrap()
            before = snapshot_bytes(store)
            values = deepcopy(initial["settings"])
            values["general"]["request_retry_count"] = 2

            def fail(*args, **kwargs):
                raise OSError("mock settings write failure")

            monkeypatch.setattr(store.settings, "_save", fail)
            with pytest.raises(OSError):
                await plugin.workspace_settings_save(json.dumps(values), initial["revision"])
            assert snapshot_bytes(store) == before
            assert store.revision == initial["revision"]
            assert store.settings.values == initial["settings"]
            await plugin._workspace_service.refresh()
            assert plugin.config.general.request_retry_count == 1
            restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
            restarted.initialize({})
            assert restarted.revision == initial["revision"]
            assert restarted.settings.values == initial["settings"]
        finally:
            monkeypatch.setattr(store.settings, "_save", original_save)
            await plugin.on_unload()

    asyncio.run(run())


def test_settings_save_needs_no_second_platform_write(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        store = plugin._platform_store
        try:
            initial = await plugin.workspace_bootstrap()
            platform_bytes = store.path.read_bytes()

            def forbidden(*args, **kwargs):
                raise OSError("the former second write is unavailable")

            monkeypatch.setattr(store, "_save", forbidden)
            values = initial["settings"]
            values["general"]["request_retry_count"] = 2
            result = await plugin.workspace_settings_save(json.dumps(values), initial["revision"])
            payload = json.loads(store.settings.path.read_text(encoding="utf-8"))
            assert result["saved"] and result["revision"] == initial["revision"] + 1
            assert payload["revision"] == result["revision"]
            assert payload["settings"]["general"]["request_retry_count"] == 2
            assert plugin.config.general.request_retry_count == 2
            assert store.path.read_bytes() == platform_bytes
            restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
            restarted.initialize({})
            assert restarted.revision == result["revision"]
            with pytest.raises(ValueError, match="更新"):
                restarted.save_common(values, values, initial["revision"])
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("operation", ["save", "delete"])
def test_preset_failure_has_no_hidden_change(make_plugin, monkeypatch, operation):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        store = plugin._platform_store
        try:
            await plugin._workspace_service.presets("save", "", json.dumps({"name": "Test preset"}))
            before = snapshot_bytes(store)
            values, revision = deepcopy(store.settings.values), store.revision

            def fail(*args, **kwargs):
                raise OSError("mock preset write failure")

            monkeypatch.setattr(store.settings, "_save", fail)
            with pytest.raises(OSError):
                await plugin._workspace_service.presets(operation, "Test preset", json.dumps({"name": "Changed preset"}))
            assert snapshot_bytes(store) == before
            assert store.revision == revision and store.settings.values == values
            await plugin._workspace_service.refresh()
            assert plugin.config.style.model_dump(mode="json") == values["style"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_shared_revision_is_monotonic_across_independent_files(tmp_path):
    store = new_store(tmp_path)
    revisions = [store.revision]
    for _ in range(2):
        store.save_common(store.settings.values, store.settings.values, store.revision)
        revisions.append(store.revision)
    store.save_provider({"kind": "google", "name": "Primary", "config": {}}, store.revision)
    revisions.append(store.revision)
    store.save_common(store.settings.values, store.settings.values, store.revision)
    revisions.append(store.revision)
    store.delete_provider(store.providers[0]["id"], store.revision)
    revisions.append(store.revision)
    assert revisions == list(range(revisions[0], revisions[0] + len(revisions)))
    restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
    restarted.initialize({})
    assert restarted.revision == revisions[-1]
    assert restarted.settings.revision == revisions[-2]
    with pytest.raises(ValueError, match="更新"):
        restarted.save_common(store.settings.values, store.settings.values, revisions[-2])


def test_rename_updates_all_model_references_in_one_revision(tmp_path):
    store, payload = renamed_fixture(tmp_path)
    revision = store.revision + 1
    result = store.save_provider(payload, store.revision)
    assert result["saved"] and not result["recovery_pending"]
    assert not store.transaction_path.exists()
    assert_renamed(store, revision)
    assert json.loads(store.path.read_text(encoding="utf-8"))["revision"] == revision
    assert json.loads(store.settings.path.read_text(encoding="utf-8"))["revision"] == revision
    restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
    restarted.initialize({})
    assert_renamed(restarted, revision)


def test_rename_journal_write_failure_leaves_everything_unchanged(tmp_path, monkeypatch):
    store, payload = renamed_fixture(tmp_path)
    before, revision = snapshot_bytes(store), store.revision
    providers, values = deepcopy(store.providers), deepcopy(store.settings.values)
    original = storage.write_json_atomically

    def write(path, value):
        if path == store.transaction_path:
            raise OSError("mock journal write failure")
        original(path, value)

    monkeypatch.setattr(storage, "write_json_atomically", write)
    with pytest.raises(OSError):
        store.save_provider(payload, revision)
    assert snapshot_bytes(store) == before
    assert store.providers == providers and store.settings.values == values and store.revision == revision
    restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
    restarted.initialize({})
    assert restarted.providers == providers and restarted.settings.values == values


@pytest.mark.parametrize("target", ["platforms", "settings", "cleanup"])
def test_rename_materialization_failure_is_committed_and_recoverable(tmp_path, monkeypatch, target):
    store, payload = renamed_fixture(tmp_path)
    revision = store.revision + 1
    original_write, original_unlink = storage.write_json_atomically, Path.unlink
    failed_path = store.path if target == "platforms" else store.settings.path

    def write(path, value):
        if target != "cleanup" and path == failed_path:
            raise OSError("mock materialization write failure")
        original_write(path, value)

    def unlink(path, *args, **kwargs):
        if target == "cleanup" and path == store.transaction_path:
            raise OSError("mock journal cleanup failure")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(storage, "write_json_atomically", write)
        patch.setattr(Path, "unlink", unlink)
        result = store.save_provider(payload, store.revision)
        assert result["saved"] and result["recovery_pending"]
        assert store.transaction_path.exists()
        assert_renamed(store, revision)
        with pytest.raises(OSError):
            store.save_common(store.settings.values, store.settings.values, revision)
        assert store.revision == revision
    restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
    restarted.initialize({})
    assert_renamed(restarted, revision)
    assert not restarted.transaction_path.exists()
    # 恢复是幂等的，不额外消耗修订号。
    restarted.initialize({})
    assert_renamed(restarted, revision)


@pytest.mark.parametrize("cut_after", ["journal", "platforms", "settings"])
def test_process_interruption_after_commit_recovers_both_files(tmp_path, monkeypatch, cut_after):
    store, payload = renamed_fixture(tmp_path)
    revision = store.revision + 1
    paths = {"journal": store.transaction_path, "platforms": store.path, "settings": store.settings.path}
    original = storage.write_json_atomically

    def crash(path, value):
        original(path, value)
        if path == paths[cut_after]:
            raise SystemExit("simulated process interruption")

    with monkeypatch.context() as patch:
        patch.setattr(storage, "write_json_atomically", crash)
        with pytest.raises(SystemExit):
            store.save_provider(payload, store.revision)
    restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
    restarted.initialize({})
    assert_renamed(restarted, revision)
    assert not restarted.transaction_path.exists()


def pending_transaction(tmp_path, monkeypatch):
    store, payload = renamed_fixture(tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(store, "_materialize_transaction", lambda *_: (_ for _ in ()).throw(OSError("defer")))
        store.save_provider(payload, store.revision)
    return store


@pytest.mark.parametrize("damage", ["truncated", "unknown_field", "missing_settings"])
def test_invalid_transaction_is_preserved_without_touching_sources(tmp_path, monkeypatch, damage):
    store = pending_transaction(tmp_path, monkeypatch)
    transaction = json.loads(store.transaction_path.read_text(encoding="utf-8"))
    if damage == "unknown_field":
        transaction["unrecognized"] = "keep this original"
    elif damage == "missing_settings":
        del transaction["settings"]
    store.transaction_path.write_text("{" if damage == "truncated" else json.dumps(transaction))
    before = snapshot_bytes(store)
    with pytest.raises(ValueError):
        storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize({})
    assert snapshot_bytes(store) == before


@pytest.mark.parametrize("target", ["platforms", "settings"])
def test_recovery_refuses_conflicting_target_before_any_rewrite(tmp_path, monkeypatch, target):
    store = pending_transaction(tmp_path, monkeypatch)
    damaged = store.path if target == "platforms" else store.settings.path
    damaged.write_text('{"unknown_config": "preserve me"}')
    before = snapshot_bytes(store)
    with pytest.raises(ValueError, match="冲突"):
        storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize({})
    assert snapshot_bytes(store) == before


def test_legacy_settings_upgrade_backs_up_original_bytes(tmp_path):
    store = new_store(tmp_path)
    legacy = {"schema_version": 1, "settings": store.settings.values}
    original = (json.dumps(legacy, ensure_ascii=False, indent=4) + "\r\n").encode()
    store.settings.path.write_bytes(original)
    platforms_before = store.path.read_bytes()
    restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
    restarted.initialize({})
    upgraded = json.loads(restarted.settings.path.read_text(encoding="utf-8"))
    assert upgraded["schema_version"] == 2 and upgraded["revision"] == 0
    assert upgraded["settings"] == legacy["settings"]
    assert restarted.revision == store.revision
    assert store.path.read_bytes() == platforms_before
    assert any(path.read_bytes() == original for path in (store.path.parent / "migration_backups").glob("*.json"))
    assert set(upgraded) == {"schema_version", "revision", "settings"}
    assert set(upgraded["settings"]) == {"general", "style"}


@pytest.mark.parametrize("damage", ["unknown_field", "missing_section", "bad_revision"])
def test_invalid_settings_not_overwritten_during_migration(tmp_path, damage):
    store = new_store(tmp_path)
    payload = json.loads(store.settings.path.read_text(encoding="utf-8"))
    if damage == "unknown_field":
        payload["settings"]["general"]["unrecognized"] = "keep this data"
    elif damage == "missing_section":
        del payload["settings"]["style"]
    else:
        payload["revision"] = "one"
    store.settings.path.write_text(json.dumps(payload))
    before = snapshot_bytes(store)
    with pytest.raises(ValueError):
        storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize({})
    assert snapshot_bytes(store) == before
    assert not (store.path.parent / "migration_backups").exists()


def test_migration_resumes_after_settings_write_interruption(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    original = b'[plugin]\r\nconfig_version="2.34.0"\r\n[openai]\r\napi_key="fixture-migration-key"\r\nmodels=["sample-image"]\r\n[general]\r\ndefault_model="sample-image"\r\nrequest_retry_count=1\r\n[style]\r\ndefault_style=""\r\n'
    path.write_bytes(original)
    store = storage.WorkspaceConfigStore(tmp_path / "data", path)

    def fail():
        raise OSError("mock interrupted settings migration")

    monkeypatch.setattr(store.settings, "_save", fail)
    with pytest.raises(OSError):
        store.initialize(tomlkit.parse(original.decode()))
    assert "openai" not in tomlkit.parse(path.read_text(encoding="utf-8"))
    assert "general" in tomlkit.parse(path.read_text(encoding="utf-8"))
    assert any(p.read_bytes() == original for p in (tmp_path / "data/migration_backups").glob("*.toml"))
    restarted = storage.WorkspaceConfigStore(tmp_path / "data", path)
    restarted.initialize(tomlkit.parse(path.read_text(encoding="utf-8")))
    assert restarted.settings.values["general"]["request_retry_count"] == 1
    assert restarted.providers[0]["config"]["api_key"] == "fixture-migration-key"
    assert set(tomlkit.parse(path.read_text(encoding="utf-8"))) == {"plugin"}


def test_settings_conflict_aborts_before_platform_migration(tmp_path):
    store = new_store(tmp_path)
    legacy = '[plugin]\nconfig_version="2.34.0"\n[general]\nrequest_retry_count=2\n[openai]\napi_key="fixture-migration-key"\n'
    store.config_path.write_text(legacy)
    before = snapshot_bytes(store)
    with pytest.raises(ValueError, match="存在冲突"):
        storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize(tomlkit.parse(legacy))
    assert snapshot_bytes(store) == before and store.config_path.read_text(encoding="utf-8") == legacy
    assert not (store.path.parent / "migration_backups").exists()


@pytest.mark.parametrize("operation", ["settings", "preset", "provider", "delete_provider"])
def test_refresh_failure_reports_saved_and_bootstrap_uses_committed_settings(make_plugin, monkeypatch, operation):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        store, workspace = plugin._platform_store, plugin._workspace_service
        revision = store.revision

        async def fail():
            raise OSError("mock runtime refresh failure")

        monkeypatch.setattr(workspace, "refresh", fail)
        monkeypatch.setattr(workspace, "apply_settings", lambda _: fail())
        try:
            if operation == "settings":
                values = deepcopy(store.settings.values)
                values["general"]["request_retry_count"] = 2
                result = await workspace.save_settings(json.dumps(values), revision)
            elif operation == "preset":
                result = await workspace.presets("save", "", json.dumps({"name": "New preset"}))
            elif operation == "provider":
                result = await workspace.save_provider(json.dumps({"kind": "google", "name": "New_provider", "config": {}}), revision)
            else:
                result = await workspace.delete_provider(store.providers[0]["id"], revision)
            assert result["saved"] and result["runtime_refresh_pending"]
            assert result["revision"] == revision + 1 and "已保存" in result["warning"]
            bootstrap = await workspace.bootstrap()
            assert bootstrap["settings"] == store.settings.values
            assert bootstrap["revision"] == result["revision"]
            if operation == "settings":
                assert plugin.config.general.request_retry_count == 1
                assert bootstrap["settings"]["general"]["request_retry_count"] == 2
            if operation == "preset":
                assert (await workspace.presets("get", "New preset"))["preset"]["name"] == "New preset"
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_rename_api_reports_pending_recovery_without_claiming_failure(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        store, workspace = plugin._platform_store, plugin._workspace_service
        payload = deepcopy(store.providers[0])
        payload["name"] = "Renamed"
        revision = store.revision
        try:
            def fail(*args):
                raise OSError("mock materialization failure")

            with monkeypatch.context() as patch:
                patch.setattr(store, "_materialize_transaction", fail)
                result = await workspace.save_provider(json.dumps(payload), revision)
            assert result["saved"] and result["recovery_pending"]
            assert result["revision"] == revision + 1 and "已保存" in result["warning"]
            assert store.transaction_path.exists()
            assert "fixture-key" not in json.dumps(result)
            bootstrap = await workspace.bootstrap()
            assert bootstrap["providers"][0]["name"] == "Renamed"
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_concurrent_pages_cannot_commit_the_same_revision(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            initial = await plugin.workspace_bootstrap()
            first, second = deepcopy(initial["settings"]), deepcopy(initial["settings"])
            first["general"]["request_retry_count"] = 1
            second["general"]["request_retry_count"] = 2
            results = await asyncio.gather(
                plugin._workspace_service.save_settings(json.dumps(first), initial["revision"]),
                plugin._workspace_service.save_settings(json.dumps(second), initial["revision"]),
                return_exceptions=True,
            )
            assert sum(isinstance(result, dict) and result["saved"] for result in results) == 1
            assert sum(isinstance(result, ValueError) for result in results) == 1
            saved = json.loads(plugin._platform_store.settings.path.read_text(encoding="utf-8"))
            assert saved["revision"] == initial["revision"] + 1
            assert saved["settings"]["general"]["request_retry_count"] == 1
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("target", ["platforms", "settings"])
@pytest.mark.parametrize("operation", ["settings", "rename"])
def test_live_edits_or_damage_are_not_overwritten(tmp_path, target, operation):
    store, payload = renamed_fixture(tmp_path)
    path = store.path if target == "platforms" else store.settings.path
    path.write_text('{"unrecognized": "preserve this data"}')
    before, revision = snapshot_bytes(store), store.revision
    with pytest.raises(ValueError):
        if operation == "rename":
            store.save_provider(payload, revision)
        else:
            store.save_common(store.settings.values, store.settings.values, revision)
    assert snapshot_bytes(store) == before
    assert store.revision == revision and not store.transaction_path.exists()


@pytest.mark.parametrize("target", ["settings", "platforms", "journal"])
def test_atomic_replace_failure_has_no_committed_side_effect(tmp_path, monkeypatch, target):
    store, payload = renamed_fixture(tmp_path)
    before, revision = snapshot_bytes(store), store.revision
    original_replace = Path.replace
    failed = {"settings": store.settings.path, "platforms": store.path, "journal": store.transaction_path}[target]

    def fail_replace(path, destination):
        if destination == failed:
            raise OSError("mock atomic replace failure")
        return original_replace(path, destination)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError):
        if target == "settings":
            values = deepcopy(store.settings.values)
            values["general"]["request_retry_count"] = 2
            store.save_common(values, values, revision)
        else:
            if target == "platforms":
                payload["name"] = "Original"
                payload["config"]["max_images"] = 2
            store.save_provider(payload, revision)
    assert snapshot_bytes(store) == before
    assert store.revision == revision and store.providers[0]["name"] == "Original"
    assert store.settings.values["general"]["request_retry_count"] == 1


def test_pending_recovery_checks_legacy_conflicts_before_writes(tmp_path, monkeypatch):
    store = pending_transaction(tmp_path, monkeypatch)
    legacy = '[general]\nrequest_retry_count=2\n'
    store.config_path.write_text(legacy)
    before = snapshot_bytes(store)
    with pytest.raises(ValueError, match="冲突"):
        storage.WorkspaceConfigStore(store.path.parent, store.config_path).initialize(tomlkit.parse(legacy))
    assert snapshot_bytes(store) == before
    assert store.config_path.read_text(encoding="utf-8") == legacy
    assert not (store.path.parent / "migration_backups").exists()


def test_valid_external_settings_edit_is_preserved(tmp_path):
    store, rename = renamed_fixture(tmp_path)
    payload = json.loads(store.settings.path.read_text(encoding="utf-8"))
    payload["settings"]["general"]["request_retry_count"] = 2
    store.settings.path.write_text(json.dumps(payload))
    before = snapshot_bytes(store)
    with pytest.raises(ValueError, match="外部修改"):
        store.save_provider(rename, store.revision)
    assert snapshot_bytes(store) == before


@pytest.mark.parametrize("enabled", [True, False])
def test_rename_uses_exact_instance_selectors_not_shared_name_prefixes(tmp_path, enabled):
    store = new_store(tmp_path)
    for name, models in (
        ("Account", ["image", "Model/Detail"]),
        ("Account/Secondary", ["image"]),
    ):
        store.save_provider({"kind": "openai", "name": name, "config": {
            "enabled": enabled, "api_key": "fixture-key", "models": models,
        }}, store.revision)
    values = deepcopy(store.settings.values)
    foreign = "Account/Secondary/image"
    own = ["Account/image", "Account/Model/Detail"]
    values["general"]["default_model"] = foreign
    keys = ("fallback_models", "image_edit_unsupported_models", "text_to_image_unsupported_models")
    for key in keys:
        values["general"][key] = [foreign, *own]
    store.save_common(values, values, store.revision)
    rename = deepcopy(store.providers[0])
    rename["name"] = "Renamed/Account"
    store.save_provider(rename, store.revision)
    general = store.settings.values["general"]
    assert general["default_model"] == foreign
    for key in keys:
        assert general[key] == [foreign, "Renamed/Account/image", "Renamed/Account/Model/Detail"]
    restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
    restarted.initialize({})
    assert restarted.settings.values == store.settings.values
