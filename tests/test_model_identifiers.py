"""平台名称、真实模型 ID、完整选择器及索引命令的迁移与持久化边界。"""

from copy import deepcopy
from importlib import import_module
import asyncio
import json

import pytest

from test_workspace import _PACKAGE, make_plugin as make_plugin, storage

texts = import_module(f"{_PACKAGE}.src.maimai_drawpic.interfaces.chat.texts")


def legacy_store(tmp_path):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize({})
    records = [
        {"id": "a" * 32, "kind": "openai", "name": "Main API", "config": {
            "enabled": True, "api_key": "fixture-original-key",
            "models": ["主力=gpt-image-2", "gpt-image-2", "备用=gpt-image-1"],
            "model_size_overrides": ["主力=1024x1024"],
        }},
        {"id": "b" * 32, "kind": "google", "name": "Main_API", "config": {
            "enabled": True, "api_key": "fixture-second-key", "models": ["gemini-image"],
        }},
        {"id": "c" * 32, "kind": "aliyun", "name": "空 格", "config": {
            "enabled": False, "api_key": "fixture-disabled-key", "models": ["qwen-image-3.0"],
        }},
    ]
    store.providers = [store._validate_record(record) for record in records]
    store._save()
    settings = deepcopy(store.settings.values)
    settings["general"].update(
        default_model="Main API / 主力", fallback_models=["Main API/备用", "空 格 / qwen-image-3.0"],
        image_edit_unsupported_models=["主力"], text_to_image_unsupported_models=["空 格/qwen-image-3.0"],
    )
    store.settings.save(settings, store.revision)
    preferences = {
        "qq:group:one": {"model": "Main API / 主力", "openai_compatibility_mode": "images_api"},
        "qq:user:two": {"model": "gpt-image-1", "novelai_artist_tags": "keep artists"},
        "qq:user:three": {"model": "空 格/qwen-image-3.0"},
        "qq:user:missing": {"model": "暂时不可用/unknown-model"},
    }
    preference_path = store.path.parent / "session_preferences.json"
    storage.write_json_atomically(preference_path, preferences)
    return store


def restart(store):
    restarted = storage.WorkspaceConfigStore(store.path.parent, store.config_path)
    restarted.initialize({})
    return restarted


def assert_converted(store):
    assert [record["id"] for record in store.providers] == ["a" * 32, "b" * 32, "c" * 32]
    assert [record["name"] for record in store.providers] == ["Main_API_2", "Main_API", "空_格"]
    first = store.providers[0]["config"]
    assert first["models"] == ["gpt-image-2", "gpt-image-1"]
    assert first["api_key"] == "fixture-original-key"
    assert first["model_size_overrides"] == ["gpt-image-2=1024x1024"]
    assert store.providers[2]["config"]["enabled"] is False
    assert store.providers[1]["config"]["api_key"] == "fixture-second-key"
    assert store.providers[2]["config"]["api_key"] == "fixture-disabled-key"
    general = store.settings.values["general"]
    assert general["default_model"] == "Main_API_2/gpt-image-2"
    assert general["fallback_models"] == ["Main_API_2/gpt-image-1", "空_格/qwen-image-3.0"]
    assert general["image_edit_unsupported_models"] == ["Main_API_2/gpt-image-2"]
    assert general["text_to_image_unsupported_models"] == ["空_格/qwen-image-3.0"]
    preferences = json.loads((store.path.parent / "session_preferences.json").read_text(encoding="utf-8"))
    assert preferences["qq:group:one"]["model"] == "Main_API_2/gpt-image-2"
    assert preferences["qq:group:one"]["openai_compatibility_mode"] == "images_api"
    assert preferences["qq:user:two"]["model"] == "Main_API_2/gpt-image-1"
    assert preferences["qq:user:two"]["novelai_artist_tags"] == "keep artists"
    assert preferences["qq:user:three"]["model"] == "空_格/qwen-image-3.0"
    assert preferences["qq:user:missing"]["model"] == "暂时不可用/unknown-model"


def test_old_names_aliases_settings_and_preferences_migrate_together(tmp_path):
    store = legacy_store(tmp_path)
    paths = [store.path, store.settings.path, store.path.parent / "session_preferences.json"]
    originals = [path.read_bytes() for path in paths]
    converted = restart(store)
    assert_converted(converted)
    backups = [path.read_bytes() for path in (store.path.parent / "migration_backups").glob("identifiers-*.json")]
    assert all(original in backups for original in originals)
    first_load = [path.read_bytes() for path in paths]
    again = restart(converted)
    assert_converted(again)
    assert again.revision == converted.revision
    assert [path.read_bytes() for path in paths] == first_load


@pytest.mark.parametrize("target", ["journal", "platforms", "settings", "preferences"])
def test_identifier_migration_recovers_after_each_committed_write(tmp_path, monkeypatch, target):
    store = legacy_store(tmp_path)
    paths = {"journal": store.transaction_path, "platforms": store.path, "settings": store.settings.path,
             "preferences": store.path.parent / "session_preferences.json"}
    original = storage.write_json_atomically

    class Interrupted(BaseException):
        pass

    def interrupt(path, value):
        original(path, value)
        if path == paths[target]:
            raise Interrupted()

    with monkeypatch.context() as patch:
        patch.setattr(storage, "write_json_atomically", interrupt)
        with pytest.raises(Interrupted):
            restart(store)
    assert store.transaction_path.exists()
    recovered = restart(store)
    assert_converted(recovered)
    assert not store.transaction_path.exists()


def test_identifier_recovery_preserves_external_preference_edit(tmp_path, monkeypatch):
    store = legacy_store(tmp_path)

    class Interrupted(BaseException):
        pass

    with monkeypatch.context() as patch:
        patch.setattr(storage.WorkspaceConfigStore, "_materialize_transaction", lambda *_: (_ for _ in ()).throw(Interrupted()))
        with pytest.raises(Interrupted):
            restart(store)
    preference_path = store.path.parent / "session_preferences.json"
    preference_path.write_bytes(b'{"external":{"model":"keep-this"}}\n')
    paths = [store.path, store.settings.path, preference_path, store.transaction_path]
    before = [path.read_bytes() for path in paths]
    with pytest.raises(ValueError, match="冲突"):
        restart(store)
    assert [path.read_bytes() for path in paths] == before


@pytest.mark.parametrize("explicit_first", [True, False])
def test_conflicts_keep_all_models_old_route_and_direct_overrides(tmp_path, explicit_first):
    store = legacy_store(tmp_path)
    config = store.providers[0]["config"]
    config["models"].append("主力=additional-model")
    config["model_size_overrides"].insert(0 if explicit_first else 1, "gpt-image-2=1024x1536")
    config["model_size_overrides"].append("gpt-image-2=1536x1024")
    store._save()
    before = store.path.read_bytes()
    converted = restart(store)
    assert converted.providers[0]["config"]["models"] == ["gpt-image-2", "gpt-image-1", "additional-model"]
    assert converted.providers[0]["config"]["model_size_overrides"] == ["gpt-image-2=1536x1024"]
    assert converted.settings.values["general"]["default_model"] == "Main_API_2/gpt-image-2"
    assert any("覆盖值冲突" in message for message in converted.identifier_repairs)
    assert any("重复定义别名" in message for message in converted.identifier_repairs)
    assert before in [p.read_bytes() for p in (store.path.parent / "migration_backups").glob("*.json")]
    assert not restart(converted).identifier_repairs


@pytest.mark.parametrize("platforms_exist", [False, True])
def test_incomplete_alias_is_backed_up_and_skipped_on_reload(tmp_path, platforms_exist):
    data_dir = tmp_path / "data"
    config_path = tmp_path / "config.toml"
    store = storage.WorkspaceConfigStore(data_dir, config_path)
    values = {"models": ["gpt-image-2", "portrait= "], "api_key": "fixture-key"}
    if platforms_exist:
        store.initialize({})
        store.providers = [store._new_record("openai", "Local", values)]
        store._save()
        legacy = {}
    else:
        config_path.write_bytes(b'[openai]\nmodels=["gpt-image-2", "portrait= "]\napi_key="fixture-key"\n')
        legacy = {"openai": values}

    before = (store.path if platforms_exist else config_path).read_bytes()
    store.initialize(legacy)
    assert store.providers[0]["config"]["models"] == ["gpt-image-2"]
    assert store.providers[0]["config"]["api_key"] == "fixture-key"
    assert len(store.identifier_repairs) == 1 and "models 第 2 项" in store.identifier_repairs[0]
    assert "fixture-key" not in store.identifier_repairs[0]
    assert before in [p.read_bytes() for p in (data_dir / "migration_backups").iterdir()]
    assert not restart(store).identifier_repairs


def test_old_toml_conflicting_only_in_models_keeps_workspace_and_backs_up_toml(tmp_path):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize({})
    store.save_provider({"kind": "openai", "name": "Local", "config": {
        "api_key": "fixture-key", "models": ["image"],
    }}, store.revision)
    original = b'[openai]\napi_key="fixture-key"\nmodels=["portrait="]\n'
    store.config_path.write_bytes(original)
    active = store.path.read_bytes()
    converted = restart(store)
    assert store.path.read_bytes() == active
    assert any("已采用工作台 JSON" in message for message in converted.identifier_repairs)
    assert original in [p.read_bytes() for p in (store.path.parent / "migration_backups").glob("*.toml")]
    assert not restart(converted).identifier_repairs


def test_new_platform_save_omits_blank_model_rows(tmp_path):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize({})
    store.save_provider({"kind": "openai", "name": "Local", "config": {
        "api_key": "fixture-key", "models": ["gpt-image-2", "", "  ", " gpt-image-2 "],
    }}, store.revision)
    assert store.providers[0]["config"]["models"] == ["gpt-image-2"]
    saved = store.path.read_bytes()
    assert restart(store).providers == store.providers
    assert store.path.read_bytes() == saved


def test_only_unusable_models_still_allow_load_and_reload(tmp_path, make_plugin):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "plugin/config.toml")
    store.initialize({})
    store.providers = [store._new_record("openai", "Local", {
        "api_key": "fixture-private-key", "models": ["portrait=", "  "],
        "model_size_overrides": ["portrait=1024x1024"],
    })]
    store._save()
    async def run():
        for iteration in range(2):
            plugin = make_plugin(False)
            await plugin.on_load()
            try:
                assert not plugin._require_router().get_all_models()
                assert bool(plugin._platform_store.identifier_repairs) == (iteration == 0)
                assert plugin._platform_store.providers[0]["config"]["model_size_overrides"] == []
            finally:
                await plugin.on_unload()
    asyncio.run(run())
    logs = (store.path.parent / "logs/drawpic.log").read_text(encoding="utf-8")
    assert logs.count("models 第 1 项") == 1 and "WARNING" in logs and "migration_backups" in logs
    assert "fixture-private-key" not in logs


@pytest.mark.parametrize("name", ["My API", "平台　名称", "名称\tAPI", " 名称", "名称 "])
def test_new_platform_names_reject_whitespace(tmp_path, name):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize({})
    original = store.path.read_bytes()
    with pytest.raises(ValueError, match="空格"):
        store.save_provider({"kind": "openai", "name": name, "config": {}}, store.revision)
    assert store.path.read_bytes() == original


@pytest.mark.parametrize("kind", ["openai", "google", "aliyun"])
def test_new_platform_models_reject_aliases_without_writing(tmp_path, kind):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize({})
    before = store.path.read_bytes()
    with pytest.raises(ValueError, match="别名"):
        store.save_provider({"kind": kind, "name": "中英文_API", "config": {
            "models": ["显示名称=real-model-id"],
        }}, store.revision)
    assert store.path.read_bytes() == before


@pytest.mark.parametrize("old_name,new_name", [
    (" Main API ", "_Main_API_"), ("中文　API", "中文_API"), ("Two  Spaces", "Two__Spaces"),
])
def test_legacy_name_conversion_preserves_every_space(tmp_path, old_name, new_name):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize({})
    store.providers = [store._validate_record({"id": "a" * 32, "kind": "openai", "name": old_name,
                                              "config": {"models": ["image"], "api_key": "fixture-key"}})]
    store._save()
    converted = restart(store)
    assert converted.providers[0]["name"] == new_name
    assert converted.providers[0]["config"]["api_key"] == "fixture-key"


@pytest.mark.parametrize("kind,old_name,new_name", [
    ("openai", "OpenAI / 兼容服务", "OpenAI_Compatible"),
    ("openai", "OpenAI_/_兼容服务", "OpenAI_Compatible"),
    ("openai", "OpenAI / 兼容服务 2", "OpenAI_Compatible_2"),
    ("openai", "OpenAI_/_兼容服务_2", "OpenAI_Compatible_2"),
    ("openai", "openai", "openai"),
    ("google", "Google Gemini", "google"),
    ("google", "Google_Gemini_2", "google_2"),
    ("agnes", "Agnes AI", "agnes"),
    ("agnes", "Agnes_AI", "agnes"),
    ("novelai", "NovelAI / NovelAPI", "novelai"),
    ("novelai", "NovelAI_/_NovelAPI", "novelai"),
    ("openai", "我的中转_API", "我的中转_API"),
    ("openai", "OpenAI_/_兼容服务_自定义", "OpenAI_/_兼容服务_自定义"),
    ("aliyun", "阿里百炼", "阿里百炼"),
])
def test_default_name_repair_updates_settings_and_preferences(tmp_path, kind, old_name, new_name):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize({})
    record = store._validate_record({"id": "a" * 32, "kind": kind, "name": old_name,
                                     "config": {"enabled": True, "api_key": "fixture-preserved-key"}})
    store.providers = [record]
    store._save()
    router = storage.ProviderRouter(store.effective_config({}, [record]))
    model = router.get_all_models()[0]
    before = deepcopy(record["config"])
    old_selector = f"{old_name}/{model}"
    new_selector = f"{new_name}/{model}"
    settings = deepcopy(store.settings.values)
    settings["general"].update(default_model=old_selector, fallback_models=[old_selector],
                               image_edit_unsupported_models=[old_selector], text_to_image_unsupported_models=[old_selector])
    store.settings.save(settings, store.revision)
    preference_path = store.path.parent / "session_preferences.json"
    storage.write_json_atomically(preference_path, {"qq:group:one": {"model": old_selector}})
    converted = restart(store)
    assert converted.providers[0]["name"] == new_name
    assert converted.providers[0]["id"] == record["id"] and converted.providers[0]["config"] == before
    general = converted.settings.values["general"]
    assert general["default_model"] == new_selector
    for field in ("fallback_models", "image_edit_unsupported_models", "text_to_image_unsupported_models"):
        assert general[field] == [new_selector]
    assert json.loads(preference_path.read_text(encoding="utf-8"))["qq:group:one"]["model"] == new_selector
    again = restart(converted)
    assert again.providers == converted.providers and again.revision == converted.revision


def test_default_name_repair_respects_existing_custom_names_and_numbers(tmp_path):
    store = storage.WorkspaceConfigStore(tmp_path / "data", tmp_path / "config.toml")
    store.initialize({})
    names = ["OpenAI_/_兼容服务_2", "OpenAI_Compatible", "OpenAI_Compatible_2", "OpenAI / 兼容服务", "自定义中转"]
    store.providers = [store._validate_record({"id": f"{index:032x}", "kind": "openai", "name": name,
                                               "config": {"api_key": f"fixture-key-{index}"}})
                       for index, name in enumerate(names, 1)]
    store._save()
    converted = restart(store)
    assert [record["name"] for record in converted.providers] == [
        "OpenAI_Compatible_3", "OpenAI_Compatible", "OpenAI_Compatible_2", "OpenAI_Compatible_4", "自定义中转",
    ]
    assert [record["config"]["api_key"] for record in converted.providers] == [f"fixture-key-{i}" for i in range(1, 6)]


def test_toggle_changes_only_selected_state_and_rejects_stale_revision(tmp_path, monkeypatch):
    store = restart(legacy_store(tmp_path))
    before = deepcopy(store.providers)
    revision = store.revision
    store.set_provider_enabled(before[0]["id"], False, revision)
    before[0]["config"]["enabled"] = False
    assert store.providers == before
    with pytest.raises(ValueError, match="更新"):
        store.set_provider_enabled(before[0]["id"], True, revision)
    assert restart(store).providers == before
    original = store.path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(store, "_save", lambda *_: (_ for _ in ()).throw(OSError("fixture failed write")))
        with pytest.raises(OSError):
            store.set_provider_enabled(before[0]["id"], True, store.revision)
    assert store.providers == before and store.path.read_bytes() == original


@pytest.mark.parametrize("selection,expected", [
    ("1", 0), ("2", 1), ("备用/sample-image", 1), ("sample-image", None),
    ("0", None), ("-1", None), ("3", None), ("1.5", None), ("9" * 100, None),
])
def test_command_selection_requires_complete_name_or_valid_index(make_plugin, monkeypatch, selection, expected):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            await plugin.workspace_provider_save(json.dumps({"kind": "openai", "name": "备用", "config": {
                "enabled": True, "api_key": "fixture-backup-key", "models": ["sample-image"],
            }}), plugin._platform_store.revision)
            context = {"stream_id": "fixture-stream", "user_id": "fixture-user", "group_id": "", "platform": "qq"}
            replies = []

            async def resolve(**kwargs):
                return context

            async def reply(**kwargs):
                replies.append(kwargs)

            monkeypatch.setattr(plugin, "_extract_runtime_context", lambda **kwargs: context)
            monkeypatch.setattr(plugin, "_merge_resolved_runtime_context", lambda *args, **kwargs: context)
            monkeypatch.setattr(plugin._require_stream_service(), "resolve_live_stream_context", resolve)
            monkeypatch.setattr(plugin, "_send_command_reply", reply)
            monkeypatch.setattr(plugin, "_can_manage_session", lambda *_: True)
            models = plugin._require_router().get_all_models()
            await plugin.handle_draw_command(matched_groups={"content": "模型"})
            lines = replies[-1]["body"].splitlines()
            assert [line for line in lines if line[:1].isdigit()] == [f"{i}. {model}" for i, model in enumerate(models, 1)]
            outcome = await plugin.handle_draw_command(matched_groups={"content": f"模型 {selection}"})
            preference = plugin._get_session_preference(**context)["model"]
            if expected is None:
                assert outcome[0] is False and preference == ""
            else:
                assert outcome[0] is True and preference == models[expected]
                saved = json.loads(plugin._session_preferences_path.read_text(encoding="utf-8"))
                assert next(iter(saved.values()))["model"] == models[expected]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_plugin_startup_migrates_saved_preferences_and_survives_reload(tmp_path, make_plugin):
    store = legacy_store(tmp_path)
    store.providers[0]["config"]["models"].extend(["", "  "])
    store.providers[1]["config"]["models"].append("\t")
    store._save()
    original_platforms = store.path.read_bytes()

    async def run():
        for _ in range(2):
            plugin = make_plugin(False)
            await plugin.on_load()
            try:
                assert_converted(plugin._platform_store)
                assert plugin._platform_store.providers[1]["config"]["models"] == ["gemini-image"]
                assert plugin.config.general.default_model == "Main_API_2/gpt-image-2"
                assert plugin._session_store.preferences["qq:group:one"]["model"] == "Main_API_2/gpt-image-2"
                assert plugin._session_store.preferences["qq:user:three"]["model"] == "空_格/qwen-image-3.0"
                assert plugin._require_router().resolve_default_model() == "Main_API_2/gpt-image-2"
            finally:
                await plugin.on_unload()
        backups = (store.path.parent / "migration_backups").glob("identifiers-platforms-*.json")
        assert original_platforms in [path.read_bytes() for path in backups]

    asyncio.run(run())


def test_runtime_rename_updates_disabled_platform_preferences_on_disk_and_in_memory(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            store = plugin._platform_store
            record = deepcopy(store.providers[0])
            old_model = plugin._require_router().get_all_models()[0]
            plugin._set_session_preference("fixture-stream", model=old_model)
            await plugin.workspace_provider_enabled(record["id"], False, store.revision)
            record["name"] = "新名称"
            record["config"]["enabled"] = False
            await plugin.workspace_provider_save(json.dumps(record), store.revision)
            expected = "新名称/sample-image"
            assert plugin._session_store.get_preference("fixture-stream")["model"] == expected
            saved = json.loads(plugin._session_preferences_path.read_text(encoding="utf-8"))
            assert next(iter(saved.values()))["model"] == expected
            assert store.providers[0]["config"]["api_key"] == "secret-fixture-key"
        finally:
            await plugin.on_unload()
        saved = json.loads(plugin._session_preferences_path.read_text(encoding="utf-8"))
        assert next(iter(saved.values()))["model"] == expected

    asyncio.run(run())


def test_pending_rename_prevents_preference_writes_until_recovery(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            store = plugin._platform_store
            session_store = plugin._session_store
            model = plugin._require_router().get_all_models()[0]
            plugin._set_session_preference("fixture-stream", model=model)
            payload = deepcopy(store.providers[0])
            payload["name"] = "Renamed"

            def fail(*args):
                raise OSError("fixture pending transaction")

            with monkeypatch.context() as patch:
                patch.setattr(store, "_materialize_transaction", fail)
                result = await plugin._workspace_service.save_provider(json.dumps(payload), store.revision)
                assert result["saved"] and result["recovery_pending"]
                paths = [store.path, store.settings.path, store.transaction_path, plugin._session_preferences_path]
                before = [path.read_bytes() for path in paths]
                with pytest.raises(OSError):
                    session_store.set_preference("fixture-stream", novelai_artist_tags="must not overwrite journal")
                assert [path.read_bytes() for path in paths] == before
                assert session_store.get_preference("fixture-stream")["novelai_artist_tags"] == ""
            session_store.set_preference("fixture-stream", novelai_artist_tags="after recovery")
            assert not store.transaction_path.exists()
        finally:
            await plugin.on_unload()
        saved = json.loads(plugin._session_preferences_path.read_text(encoding="utf-8"))
        assert next(iter(saved.values()))["model"] == "Renamed/sample-image"
        assert next(iter(saved.values()))["novelai_artist_tags"] == "after recovery"
        assert restart(store).providers[0]["name"] == "Renamed"

    asyncio.run(run())


def test_model_list_includes_agnes_comfyui_and_empty_state(make_plugin):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            body = texts.build_model_text(plugin._require_router(), {"model": ""})
            assert "暂无可用模型" in body
            for kind, name in (("agnes", "Agnes_AI"), ("comfyui", "本地绘图")):
                await plugin.workspace_provider_save(json.dumps({"kind": kind, "name": name, "config": {
                    "enabled": True,
                }}), plugin._platform_store.revision)
            models = plugin._require_router().get_all_models()
            assert any(model.startswith("Agnes_AI/") for model in models)
            assert "本地绘图/comfyui" in models
            body = texts.build_model_text(plugin._require_router(), {"model": ""})
            assert [line for line in body.splitlines() if line[:1].isdigit()] == [
                f"{index}. {model}" for index, model in enumerate(models, 1)
            ]
        finally:
            await plugin.on_unload()

    asyncio.run(run())
