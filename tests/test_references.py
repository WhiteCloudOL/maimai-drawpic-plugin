"""持久参考资产、实际任务模式与显式开关；不调用真实模型。"""

from types import SimpleNamespace
import asyncio
import base64
import importlib
import json
import logging

import pytest

from test_workspace import _PACKAGE, image_bytes, make_plugin as make_plugin


def module(name):
    return importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.{name}")


@pytest.mark.parametrize("supplied,expected", [
    ("off", "off"), (" AUTO ", "auto"), ("required", "required"),
    ("self", "auto"), ("", "auto"), (None, "auto"), (True, "auto"),
    (1, "auto"), ([], "auto"), ({"value": "required"}, "auto"),
])
def test_tool_self_reference_recovers_to_auto_after_host_schema_validation(supplied, expected):
    from jsonschema import validate

    schema = module("interfaces.tools.schemas").DRAW_TOOL_PARAMETERS_SCHEMA
    request = {"prompt": "海边的麦麦", "reference_options": {"self_reference": supplied}}
    validate(request, schema)
    options = module("interfaces.tools.drawing").DrawingToolMixin._drawing_reference_options(
        {"message": {"processed_plain_text": "画你在海边的样子"}}, request["reference_options"],
    )
    parsed = module("domain.references").ReferenceOptions.model_validate(options)
    assert parsed.self_reference == expected and parsed.user_request == "画你在海边的样子"
    if supplied != expected:
        with pytest.raises(ValueError):
            module("domain.references").ReferenceOptions.model_validate({"self_reference": supplied, "user_request": "原话"})


def test_auto_recognition_uses_custom_hints_without_turning_them_into_actions(monkeypatch):
    async def run():
        recognition = module("application.references.recognition")
        captured = []

        async def response(self, prompt, image=None):
            captured.append(prompt)
            return {"subject": "other"}

        monkeypatch.setattr(recognition.ReferenceRecognizer, "_json", response)
        classifier = recognition.ReferenceRecognizer(SimpleNamespace())
        assert await classifier.self_subject("不要画你的自拍，画我的照片", ["麦麦", "小麦"], ["你的自拍"]) == "other"
        assert "不要画你的自拍，画我的照片" in captured[0] and "不能命中即认定" in captured[0]
        for prompts in module("application.references.prompts").PROMPTS.values():
            assert "麦麦" in prompts["self"].format(request="用户原话", names="麦麦", keywords="你的自拍")

    asyncio.run(run())


@pytest.mark.parametrize("user_text,followup,named,sources,expected", [
    ("画一只猫", False, False, ["chat", "web"], (0, 0, "draw")),
    ("画甘雨", False, True, ["chat", "web"], (0, 1, "edit_image")),
    ("画甘雨", False, True, ["chat"], (0, 0, "draw")),
    ("继续改刚才那张图", True, False, ["chat", "web"], (1, 0, "edit_image")),
    ("不要使用以前的图，画一只猫", False, False, ["chat", "web"], (0, 0, "draw")),
])
def test_material_triggers_only_fetch_sources_needed_for_this_request(tmp_path, monkeypatch, user_text, followup, named, sources, expected):
    async def run():
        recognition = module("application.references.recognition")
        service = module("application.references.service")
        references = module("domain.references")
        config = module("domain.configuration.models").DrawpicConfig()
        config.general.references.allow_chat_material_search = True
        config.general.references.allow_web_material_search = True
        counts = {"chat": 0, "web": 0}

        async def needs(self, original, *, source_count=0):
            assert original == user_text and source_count == 0
            return recognition.MaterialNeeds(chat_followup=followup, needs=[
                recognition.MaterialNeed(subject="甘雨", mention="甘雨", web_search=True, role="identity", query="甘雨 官方"),
            ] if named else [])

        async def chat(*args, **kwargs):
            counts["chat"] += 1
            return [references.ReferenceImage(image_bytes(), "chat", description="刚才的图片")]

        async def web(*args, **kwargs):
            counts["web"] += 1
            return [references.ReferenceImage(image_bytes(), "web")]

        async def matches(*args):
            return True

        async def context(stream_id):
            return {"stream_id": stream_id, "user_id": "1001", "group_id": "", "platform": "qq"}

        monkeypatch.setattr(recognition.ReferenceRecognizer, "needs", needs)
        monkeypatch.setattr(recognition.ReferenceRecognizer, "matches", matches)
        monkeypatch.setattr(service, "read_chat_materials", chat)
        monkeypatch.setattr(module("infrastructure.references.materials").MaterialSource, "web", web)
        prepared = await service.freeze_reference_request(
            ctx=SimpleNamespace(logger=logging.getLogger("trigger-test")), config=config,
            store=module("infrastructure.storage.reference_assets").ReferenceAssetStore(tmp_path),
            streams=SimpleNamespace(existing_stream_context=context), prompt=user_text, style="", negative="",
            stream_id="real-stream", options=references.ReferenceOptions(user_request=user_text, material_sources=sources),
            images=[], urls=[],
        )
        result = await prepared.prepare("trigger-test")
        assert (counts["chat"], counts["web"], result.task_type) == expected

    asyncio.run(run())


@pytest.mark.parametrize("status,expected,calls", [("match", True, 1), ("mismatch", False, 1), ("uncertain", True, 2)])
def test_cached_chat_description_reuses_text_before_viewing_image(status, expected, calls):
    async def run():
        recognition = module("application.references.recognition")
        prompts = []

        async def generate(prompt, **kwargs):
            assert kwargs["model"] == "fast-multimodal"
            prompts.append(prompt)
            return {"content": json.dumps({"result": status} if len(prompts) == 1 else {"matches": True})}

        classifier = recognition.ReferenceRecognizer(SimpleNamespace(llm=SimpleNamespace(generate=generate)), "fast-multimodal")
        image = module("domain.references").ReferenceImage(image_bytes(), "chat", description="蓝发角色甘雨")
        need = recognition.MaterialNeed(subject="甘雨", mention="甘雨", web_search=True, role="identity", query="甘雨 官方")
        assert await classifier.matches(image, need) is expected
        assert len(prompts) == calls and isinstance(prompts[0], str)
        if calls == 2:
            assert isinstance(prompts[1], list)

    asyncio.run(run())


def test_material_queries_cannot_invent_entities_outside_original_request(monkeypatch):
    async def run():
        recognition = module("application.references.recognition")

        async def response(*args, **kwargs):
            return {"chat_followup": False, "needs": [{"subject": "甘雨", "mention": "甘雨", "role": "identity",
                    "kind": "character", "web_search": True, "query": "甘雨 官方"}]}

        monkeypatch.setattr(recognition.ReferenceRecognizer, "_json", response)
        with pytest.raises(ValueError, match="原始请求"):
            await recognition.ReferenceRecognizer(SimpleNamespace()).needs("画一只猫")
        for prompts in module("application.references.prompts").PROMPTS.values():
            assert "chat_followup" in prompts["needs"].format(request="画猫", source_count=0)

    asyncio.run(run())


def test_gallery_default_tags_revision_and_frozen_content(tmp_path):
    store = module("infrastructure.storage.reference_assets").ReferenceAssetStore(tmp_path)
    raw = image_bytes()
    first = store.update(revision=0, operation="save", name="默认", tags=["居家"], raw=raw, prompt="保留白色长发")
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
    assert frozen.note == "保留白色长发"
    store.update(revision=2, operation="save", asset_id=identifier, name="替换", tags=[], raw=raw + b"version2")
    assert frozen.raw == raw and frozen.version != store.read(identifier, kind="self").version
    assert store.read(identifier, kind="self").note == "保留白色长发"
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


def test_legacy_gallery_gains_empty_prompt_without_rewriting_index(tmp_path):
    store = module("infrastructure.storage.reference_assets").ReferenceAssetStore(tmp_path)
    snapshot = store.update(revision=0, operation="save", name="旧图片", tags=[], raw=image_bytes())
    identifier = snapshot["assets"][0]["id"]
    del snapshot["assets"][0]["prompt"]
    original = json.dumps(snapshot).encode()
    store.index.write_bytes(original)
    assert store.read(identifier, kind="self").note == ""
    assert store.index.read_bytes() == original
    with pytest.raises(ValueError, match="提示词"):
        store.update(revision=1, operation="save", asset_id=identifier, name="旧图片", tags=[], prompt="a" * 501)
    assert store.index.read_bytes() == original


@pytest.mark.parametrize("kind", ["self", "preset"])
def test_reference_image_prompt_is_frozen_and_used_in_generation(tmp_path, kind):
    async def run():
        config_module = module("domain.configuration.models")
        config = config_module.DrawpicConfig()
        store = module("infrastructure.storage.reference_assets").ReferenceAssetStore(tmp_path)
        snapshot = store.update(revision=0, operation="save", name="水彩参考", tags=[], kind=kind,
                                raw=image_bytes(), prompt="保留水彩笔触")
        identifier = snapshot["assets"][0]["id"]
        if kind == "self":
            config.general.references.self_reference_enabled = True
            options = module("domain.references").ReferenceOptions(self_reference="required")
            style = ""
        else:
            config.style.image_edit_presets_enabled = True
            config.style.presets = [config_module.StylePresetConfig(
                name="水彩", preset_type="image_to_image", reference_bindings=[{"asset_id": identifier}],
            )]
            options = module("domain.references").ReferenceOptions()
            style = "水彩"
        prepared = await module("application.references.service").freeze_reference_request(
            ctx=SimpleNamespace(logger=logging.getLogger("reference-test")), config=config, store=store,
            streams=None, prompt="画一只猫", style=style, negative="", stream_id="", options=options,
            images=[], urls=[], required_mode="edit_image",
        )
        store.update(revision=1, operation="save", asset_id=identifier, kind=kind,
                     name="水彩参考", tags=[], prompt="新的参考提示词")
        result = await prepared.prepare("frozen-prompt")
        assert result.prompt.count("保留水彩笔触") == 1
        assert "新的参考提示词" not in result.prompt
        assert result.images == [image_bytes()]

    asyncio.run(run())


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


def test_public_self_reference_opt_in_and_idempotent_frozen_asset(make_plugin, monkeypatch):
    from test_drawing_client import DrawingClient, LocalAPI

    async def run():
        plugin = make_plugin()
        values = plugin.get_plugin_config_data()
        values["general"]["references"]["self_reference_enabled"] = True
        plugin.set_plugin_config(values)
        await plugin.on_load()
        try:
            store = plugin._workspace().tasks.references
            first = await asyncio.to_thread(store.update, revision=0, operation="save", name="默认", tags=[], raw=image_bytes())
            selected = await asyncio.to_thread(store.update, revision=1, operation="save", name="冬装", tags=["冬装"], raw=image_bytes() + b"winter", prompt="保留白色长发")
            calls = []

            async def no_recognition(*args, **kwargs):
                raise AssertionError("未选择自动识别时不能调用 LLM")

            async def generate(**kwargs):
                calls.append(kwargs)
                return [image_bytes()]

            monkeypatch.setattr(plugin.ctx.llm, "generate", no_recognition)
            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            client = DrawingClient(LocalAPI(plugin), poll_interval=0.001)
            assert (await client.generate("cat", request_id="plain-refs-001", wait_seconds=5)).status == "completed"
            assert calls[-1]["task_type"] == "draw"
            options = {"self_reference": "required", "self_reference_tags": ["冬装"]}
            result = await client.generate("麦麦", task_type="edit_image", request_id="self-refs-001", reference_options=options, wait_seconds=5)
            assert result.status == "completed" and calls[-1]["source_image_bytes_list"] == [image_bytes() + b"winter"]
            assert "identity: bot" in calls[-1]["prompt"]
            assert "保留白色长发" in calls[-1]["prompt"]
            identifier = selected["assets"][1]["id"]
            await asyncio.to_thread(store.update, revision=2, operation="save", asset_id=identifier, name="新版", tags=[], raw=image_bytes() + b"changed")
            repeat = await client.submit("麦麦", task_type="edit_image", request_id="self-refs-001", reference_options=options)
            assert repeat.task_id == result.task_id and repeat.reused and len(calls) == 2
            directory = await client.references()
            assert directory["total"] == 2
            assert directory["chat_material_search_limit"] == 50
            assert set(directory["assets"][0]) == {"id", "name", "tags", "default"}
            assert directory["assets"][0]["default"]
            conflict = await plugin.drawpic_submit_v2("麦麦", reference_options_json=json.dumps(options))
            assert conflict["accepted"] is False and conflict["error"]["code"] == "TASK_MODE_CONFLICT"
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_source_flags_and_missing_chat_do_not_create_tasks(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            result = await plugin.drawpic_submit_v2("甘雨", task_type="edit_image", reference_options_json=json.dumps(
                {"user_request": "画甘雨", "material_sources": ["web"]}))
            assert not result["accepted"] and result["error"]["code"] == "MATERIAL_SOURCE_DISABLED"
            assert not plugin._task_store.snapshot()
            result = await plugin.drawpic_submit_v2("麦麦", task_type="edit_image", reference_options_json='{"self_reference":"required"}')
            assert not result["accepted"] and result["error"]["code"] == "SELF_REFERENCE_DISABLED"
            assert not plugin._task_store.snapshot()
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_search_verifies_each_subject_and_reuse_does_not_search_again(make_plugin, monkeypatch):
    from test_drawing_client import DrawingClient, LocalAPI

    async def run():
        plugin = make_plugin()
        values = plugin.get_plugin_config_data()
        values["general"]["references"]["allow_web_material_search"] = True
        plugin.set_plugin_config(values)
        await plugin.on_load()
        try:
            counts = {"needs": 0, "web": 0, "generation": 0}
            recognizer = module("application.references.recognition")
            images = module("domain.references")

            async def needs(self, request, *, source_count=0):
                counts["needs"] += 1
                return recognizer.MaterialNeeds(chat_followup=False, needs=[recognizer.MaterialNeed(subject="甘雨", mention="甘雨", web_search=True, role="identity", query="原神 甘雨 官方")])

            async def matches(self, image, need):
                return image.raw.endswith(b"ganyu")

            async def web(self, query):
                counts["web"] += 1
                return [images.ReferenceImage(image_bytes() + b"ganyu", "web", url="https://example.org/ganyu.png")]

            async def generate(**kwargs):
                counts["generation"] += 1
                assert len(kwargs["source_image_bytes_list"]) == 2
                assert kwargs["source_image_urls"] == ["", "https://example.org/ganyu.png"]
                assert "identity: 甘雨" in kwargs["prompt"]
                return [image_bytes()]

            monkeypatch.setattr(recognizer.ReferenceRecognizer, "needs", needs)
            monkeypatch.setattr(recognizer.ReferenceRecognizer, "matches", matches)
            monkeypatch.setattr(module("infrastructure.references.materials").MaterialSource, "web", web)
            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            client = DrawingClient(LocalAPI(plugin), poll_interval=0.001)
            options = {"user_request": "让图中的人物与甘雨合照", "material_sources": ["web"]}
            result = await client.generate("人物与甘雨合照", task_type="edit_image", source_images=[image_bytes()],
                                           reference_options=options, request_id="search-refs-001", wait_seconds=5)
            assert result.status == "completed"
            receipt = await client.submit("人物与甘雨合照", task_type="edit_image", source_images=[image_bytes()],
                                          reference_options=options, request_id="search-refs-001")
            assert receipt.reused and counts == {"needs": 1, "web": 1, "generation": 1}
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_multi_preset_public_write_requires_dialog_and_legacy_preserves_fields(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            bootstrap = await plugin.workspace_bootstrap()
            binding_schema = bootstrap["schema"]["sections"]["style"]["fields"]["presets"]["item_fields"]["reference_bindings"]
            assert binding_schema["item_type"] == "object"
            assert set(binding_schema["item_fields"]) == {"asset_id", "role", "subject_id", "note"}
            result = await plugin.drawpic_presets_v2("save", "多图", json.dumps({"name": "多图", "preset_type": "image_to_image",
                "reference_bindings": [{"asset_id": "a"}, {"asset_id": "b"}], "multi_reference_confirmed": True}))
            assert result["error"]["code"] == "MULTI_REFERENCE_CONFIRMATION_REQUIRED"
            await plugin.drawpic_presets_v2("save", "水彩", json.dumps({"name": "水彩", "tags": ["海边"], "apply_to_image_edit": True}))
            await plugin.drawpic_presets("save", "水彩", json.dumps({"name": "水彩", "description": "新版说明"}))
            current = await plugin.drawpic_presets_v2("get", "水彩")
            assert current["preset"]["tags"] == ["海边"] and current["preset"]["apply_to_image_edit"]
            legacy = await plugin.drawpic_presets("get", "水彩")
            assert "preset_type" not in legacy["preset"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_gallery_write_failure_keeps_previous_index_and_owned_file(tmp_path, monkeypatch):
    storage = module("infrastructure.storage.reference_assets")
    store = storage.ReferenceAssetStore(tmp_path)
    first = store.update(revision=0, operation="save", name="默认", tags=[], raw=image_bytes())
    before = store.index.read_bytes()

    def fail(*args):
        raise OSError("simulated index write failure")

    monkeypatch.setattr(storage, "write_json_atomically", fail)
    with pytest.raises(OSError):
        store.update(revision=1, operation="save", asset_id=first["assets"][0]["id"], name="替换", tags=[], raw=image_bytes() + b"new")
    assert store.index.read_bytes() == before
    assert len(list(store.root.glob("*.image"))) == 1
    assert store.read(first["assets"][0]["id"], kind="self").raw == image_bytes()
    store.index.unlink()
    with pytest.raises(ValueError, match="索引缺失"):
        store.snapshot()
    assert len(list(store.root.glob("*.image"))) == 1


@pytest.mark.parametrize("chat_fails", [False, True])
@pytest.mark.parametrize("live_limit", [20, 100])
def test_chat_material_order_and_errors_do_not_silently_enable_web(tmp_path, monkeypatch, chat_fails, live_limit):
    async def run():
        service = module("application.references.service")
        recognition = module("application.references.recognition")
        references = module("domain.references")
        config = module("domain.configuration.models").DrawpicConfig()
        config.general.references.allow_chat_material_search = True
        config.general.references.allow_web_material_search = True
        config.general.references.chat_material_search_limit = 70
        live = config.model_copy(deep=True)
        live.general.references.chat_material_search_limit = live_limit
        counts = {"chat": 0, "web": 0}

        async def context(stream_id):
            assert stream_id == "real-stream"
            return {"stream_id": stream_id, "user_id": "1001", "group_id": "", "platform": "qq"}

        async def chat(ctx, stream_id, *, message_limit):
            counts["chat"] += 1
            assert message_limit == min(70, live_limit)
            if chat_fails:
                raise RuntimeError("chat service unavailable")
            return [references.ReferenceImage(image_bytes(), "chat")]

        async def web(self, query):
            counts["web"] += 1
            return [references.ReferenceImage(image_bytes(), "web", url="https://example.org/ganyu.png")]

        async def needs(self, request, *, source_count=0):
            return recognition.MaterialNeeds(chat_followup=True, needs=[recognition.MaterialNeed(subject="甘雨", mention="甘雨", web_search=True, role="identity", query="甘雨 官方")])

        async def matches(self, image, need):
            return True

        monkeypatch.setattr(service, "read_chat_materials", chat)
        monkeypatch.setattr(recognition.ReferenceRecognizer, "needs", needs)
        monkeypatch.setattr(recognition.ReferenceRecognizer, "matches", matches)
        monkeypatch.setattr(module("infrastructure.references.materials").MaterialSource, "web", web)
        prepared = await service.freeze_reference_request(
            ctx=SimpleNamespace(logger=logging.getLogger("reference-test")), config=config,
            store=module("infrastructure.storage.reference_assets").ReferenceAssetStore(tmp_path),
            streams=SimpleNamespace(existing_stream_context=context), prompt="甘雨", style="", negative="",
            stream_id="real-stream", options=references.ReferenceOptions(user_request="画甘雨", material_sources=["chat", "web"]),
            images=[], urls=[], required_mode="edit_image", get_config=lambda: live,
        )
        if chat_fails:
            with pytest.raises(ValueError) as failure:
                await prepared.prepare("fixture")
            assert failure.value.code == "CHAT_MATERIAL_UNAVAILABLE" and counts == {"chat": 1, "web": 0}
        else:
            result = await prepared.prepare("fixture")
            assert result.task_type == "edit_image" and result.images == [image_bytes()]
            assert counts == {"chat": 1, "web": 0}

    asyncio.run(run())


@pytest.mark.parametrize("message_limit", [1, 50, 200])
def test_sdk_chat_materials_read_once_with_configured_limit_and_real_images(message_limit):
    from maibot_sdk import PluginContext

    async def run():
        calls = []
        encoded = base64.b64encode(image_bytes()).decode("ascii")

        async def rpc(method, plugin_id, payload):
            assert method == "cap.call" and plugin_id == "chat-material-test"
            calls.append(payload)
            return {"success": True, "messages": [
                {"message_id": str(index), "is_self": index == message_limit - 1, "message_segments": [
                    {"type": "image", "base64": encoded, "url": f"https://example.org/{index}.png", "data": f"MaiBot 已识别图片 {index}"},
                ]} for index in range(message_limit)
            ]}

        images = await module("application.references.chat").read_chat_materials(
            PluginContext("chat-material-test", rpc_call=rpc), "real-stream", message_limit=message_limit,
        )
        assert calls == [{"capability": "message.get_recent", "args": {
            "chat_id": "real-stream", "limit": message_limit, "hours": 24,
            "limit_mode": "latest", "include_binary_data": True,
        }}]
        assert [image.url for image in images] == [
            f"https://example.org/{index}.png" for index in reversed(range(message_limit))
        ][:6]
        assert all(image.raw == image_bytes() and image.source == "chat" for image in images)
        assert images[0].description == f"MaiBot 已识别图片 {message_limit - 1}"

    asyncio.run(run())


def test_chat_materials_reject_host_response_exceeding_search_limit():
    async def recent(*args, **kwargs):
        return [{}, {}]

    async def run():
        with pytest.raises(ValueError, match="搜索上限"):
            await module("application.references.chat").read_chat_materials(
                SimpleNamespace(call_capability=recent), "real-stream", message_limit=1,
            )

    asyncio.run(run())


def test_multi_reference_rejection_never_switches_to_fallback_model(make_plugin, monkeypatch):
    from test_drawing_client import DrawingClient, LocalAPI

    async def run():
        plugin = make_plugin()
        config = plugin.get_plugin_config_data()
        config["openai"]["models"] = ["sample-image", "backup-image"]
        config["general"]["fallback_models"] = ["backup-image"]
        plugin.set_plugin_config(config)
        await plugin.on_load()
        try:
            store = plugin._workspace().tasks.references
            await asyncio.to_thread(store.update, revision=0, operation="save", name="正面", tags=[], raw=image_bytes())
            snapshot = await asyncio.to_thread(store.update, revision=1, operation="save", name="侧面", tags=[], raw=image_bytes() + b"side")
            workspace = await plugin.workspace_bootstrap()
            workspace["settings"]["general"]["references"].update(self_reference_enabled=True,
                self_reference_ids=[item["id"] for item in snapshot["assets"]], multi_reference_confirmed=True)
            await plugin.workspace_settings_save(json.dumps(workspace["settings"]), workspace["revision"])
            models = []

            async def reject(**kwargs):
                models.append(kwargs["attempt"].model)
                raise module("domain.errors").ProviderRequestError(400, "unsupported_reference_count", "model rejects multiple references")

            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", reject)
            client = DrawingClient(LocalAPI(plugin), poll_interval=0.001)
            result = await client.generate("麦麦", task_type="edit_image", request_id="multi-reject-001",
                                           reference_options={"self_reference": "required"}, wait_seconds=5)
            assert result.status == "failed" and len(models) == 1
            assert "sample-image" in models[0] and result.error.code == "UPSTREAM_REJECTED"
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("operation,payload", [
    ("self_subject", {"subject": ["self"]}),
    ("needs", {"needs": [{"subject": "甘雨", "role": "invented", "query": "甘雨"}]}),
    ("needs", {"needs": [], "unexpected": True}),
    ("matches", {"matches": "true"}),
])
def test_invalid_recognition_has_stable_error(monkeypatch, operation, payload):
    async def run():
        recognition = module("application.references.recognition")

        async def response(self, prompt, image=None):
            return payload

        monkeypatch.setattr(recognition.ReferenceRecognizer, "_json", response)
        recognizer = recognition.ReferenceRecognizer(SimpleNamespace())
        with pytest.raises(ValueError) as failure:
            if operation == "self_subject":
                await recognizer.self_subject("画麦麦", ["麦麦"])
            elif operation == "needs":
                await recognizer.needs("画甘雨")
            else:
                await recognizer.matches(module("domain.references").ReferenceImage(image_bytes(), "input"),
                    recognition.MaterialNeed(subject="甘雨", mention="甘雨", web_search=True, role="identity", query="甘雨"))
        assert failure.value.code == "REFERENCE_RECOGNITION_FAILED"

    asyncio.run(run())


@pytest.mark.parametrize("markup_in_fetch", [False, True])
def test_sdk_web_pages_produce_real_image_inputs_with_original_urls(monkeypatch, markup_in_fetch):
    from maibot_sdk import PluginContext

    async def run():
        materials = module("infrastructure.references.materials")
        config = module("domain.configuration.models").DrawpicConfig()
        calls, downloads = [], []
        page_url = "https://example.org/character/"
        markup = '<meta property="og:image" content="/images/ganyu.png"><img src="/images/ganyu.png">'

        async def rpc(method, plugin_id, payload, *, timeout_ms):
            assert method == "cap.call" and plugin_id == "material-sdk-test"
            assert timeout_ms == 310000
            calls.append((payload["capability"], payload["args"]))
            if payload["capability"] == "web.search":
                return {"results": [{"title": "甘雨", "url": page_url, "snippet": "character"}]}
            assert payload["capability"] == "web.fetch"
            return {"url": page_url, "content": markup if markup_in_fetch else "角色资料正文，无图片链接"}

        async def document(url, *, image_content, **options):
            assert url == page_url and image_content is False
            assert options["proxy_settings"].enabled is False
            assert options["skip_ip_check"] is False
            return markup.encode("utf-8")

        async def download(url, **options):
            downloads.append(url)
            return image_bytes()

        monkeypatch.setattr(materials, "_download_image", document)
        monkeypatch.setattr(materials, "download_image", download)
        result = await materials.MaterialSource(PluginContext("material-sdk-test", rpc_call=rpc), config).web("甘雨 官方")
        assert calls == [("web.search", {"query": "甘雨 官方", "max_results": 3}),
                         ("web.fetch", {"url": page_url})]
        assert downloads == ["https://example.org/images/ganyu.png"]
        assert len(result) == 1 and result[0].raw == image_bytes()
        assert result[0].source == "web" and result[0].url == downloads[0]

    asyncio.run(run())
