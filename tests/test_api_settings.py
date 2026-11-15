"""公开绘图设置与请求恢复：真实组件收集、本地持久化及模拟 RPC。"""

from hashlib import sha256
from test_drawing_client import DrawingClient, DrawingError, LocalAPI
from test_workspace import image_bytes, make_plugin as make_plugin
import asyncio
import base64
import json
import pytest


def provide_streams(plugin, monkeypatch):
    calls = []

    async def streams(platform="qq"):
        calls.append(platform)
        return {"success": True, "streams": [{
            "session_id": "actual-stream", "platform": "qq", "user_id": "A" * 32,
            "group_id": "B" * 32, "account_id": "shared-account",
        }]}

    monkeypatch.setattr(plugin.ctx.chat, "get_all_streams", streams)
    return calls


@pytest.mark.parametrize("method,arguments", [
    ("drawpic_submit", {"prompt": "cat", "reference_options": '{"self_reference":"off"}'}),
    ("drawpic_submit", {"prompt": "cat", "reference_options": []}),
    ("drawpic_submit", {"prompt": "cat", "reference_options": {"material_sources": {"web"}}}),
    ("drawpic_submit", {"prompt": "cat", "reference_options": {"user_request": "汉" * 22000}}),
    ("drawpic_submit", {"prompt": "cat", "unexpected": True}),
    ("drawpic_submit", {}),
    ("drawpic_preferences_set", {"stream_id": "actual-stream", "preferences": '{"model":"x"}'}),
    ("drawpic_presets", {"operation": "save", "preset": '{"name":"x"}'}),
])
def test_native_object_validation_rejects_before_acceptance(make_plugin, method, arguments):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            result = await getattr(plugin, method)(**arguments)
            assert result["error"]["code"] == "INVALID_REQUEST"
            assert not result["error"]["retry_submit"]
            if method == "drawpic_submit":
                assert result["accepted"] is False and result["task_id"] is None
            assert plugin._task_store.get_task_count() == 0
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_client_preferences_partial_update_clear_and_reload(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            calls = provide_streams(plugin, monkeypatch)
            client = DrawingClient(LocalAPI(plugin))
            models = await client.models()
            model = models["models"][0]["name"]
            assert {"draw_reason", "api_edit_image", "api_edit_reason", "max_source_images"} <= models["models"][0].keys()
            original = plugin._platform_store.path.read_bytes()
            set_result = await client.set_preferences(
                "actual-stream", model=model, openai_compatibility_mode="images_api", novelai_artist_tags="artist:test"
            )
            assert set_result["preferences"]["model"] == model
            changed = await client.set_preferences("actual-stream", novelai_mode="furry")
            assert changed["preferences"]["model"] == model
            assert changed["preferences"]["novelai_artist_tags"] == "artist:test"
            assert (await client.preferences("actual-stream"))["preferences"] == changed["preferences"]
            store = plugin._require_session_store()
            await asyncio.to_thread(store.load)
            assert store.preferences["qq:group:" + "B" * 32] == changed["preferences"]
            cleared = await client.set_preferences("actual-stream", model="", novelai_artist_tags="")
            assert cleared["preferences"]["model"] == cleared["preferences"]["novelai_artist_tags"] == ""
            assert cleared["preferences"]["novelai_mode"] == "furry"
            assert plugin._platform_store.path.read_bytes() == original
            assert set(calls) == {"all_platforms"}
        finally:
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("patch", [
    {"api_key": "secret"}, {"general": {}}, {"model": "sample-image"}, {"model": "absent/model"},
    {"novelai_mode": "invalid"}, {"openai_compatibility_mode": "invalid"}, {"novelai_artist_tags": "x" * 16001},
    {"model": None}, {"style": "preset"},
])
def test_preferences_reject_invalid_or_admin_fields(make_plugin, monkeypatch, patch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            provide_streams(plugin, monkeypatch)
            before = dict(plugin._require_session_store().preferences)
            result = await plugin.drawpic_preferences_set("actual-stream", patch)
            assert result["error"]["code"] == "INVALID_REQUEST"
            assert not result["error"]["retry_submit"]
            assert plugin._require_session_store().preferences == before
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_preferences_requires_existing_session_and_failed_write_does_not_publish(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            provide_streams(plugin, monkeypatch)
            client = DrawingClient(LocalAPI(plugin))
            # 不能把 OpenID 当成 stream_id，再经 open_session 创建会话。
            with pytest.raises(DrawingError, match="聊天流"):
                await client.set_preferences("A" * 32, novelai_mode="anime")
            store = plugin._require_session_store()
            before = dict(store.preferences)

            def fail(values):
                raise OSError("fixture disk unavailable")

            with monkeypatch.context() as scoped:
                scoped.setattr(store, "_persist", fail)
                with pytest.raises(OSError, match="disk"):
                    await plugin.drawpic_preferences_set("actual-stream", {'novelai_mode': 'anime'})
            assert store.preferences == before
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_client_preset_crud_rename_updates_default(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            client = DrawingClient(LocalAPI(plugin))
            await client.save_preset({"name": "fixture", "positive_prompt_template": "watercolor {prompt}"})
            current = plugin.config.model_dump(mode="json")
            current["style"]["default_style"] = "fixture"
            await plugin.workspace_settings_save(json.dumps({"style": current["style"]}), plugin._platform_store.revision)
            await client.save_preset({"name": "renamed", "positive_prompt_template": "ink {prompt}"}, name="fixture")
            assert (await client.presets())["default_style"] == "renamed"
            assert (await client.preset("renamed"))["preset"]["positive_prompt_template"] == "ink {prompt}"
            await client.delete_preset("renamed")
            assert (await client.presets())["default_style"] == ""
            with pytest.raises(DrawingError, match="不存在"):
                await client.preset("renamed")
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_task_overrides_bytes_and_readonly_request_recovery(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            generated = []

            async def generate(**kwargs):
                generated.append(kwargs)
                return [image_bytes()]

            service = plugin._require_draw_service()
            monkeypatch.setattr(service, "_run_image_request_attempt", generate)
            api = LocalAPI(plugin)
            client = DrawingClient(api, poll_interval=0.001)
            params = {"request_id": "overrides-request-01", "task_type": "edit_image", "source_images": [image_bytes()],
                      "openai_compatibility_mode": "images_api", "novelai_mode": "anime", "novelai_artist_tags": ""}
            result = await client.generate("cat", wait_seconds=3, **params)
            assert result.status == "completed" and len(generated) == 1
            assert generated[0]["attempt"].openai_compatibility_mode == "images_api"
            recovered = await client.recover(params["request_id"], wait_seconds=3)
            assert recovered.task_id == result.task_id and recovered.images
            reused = await client.submit("cat", **params)
            assert reused.task_id == result.task_id and reused.reused
            with pytest.raises(DrawingError) as error:
                await client.submit("cat", **{**params, "novelai_artist_tags": "artist:new"})
            assert error.value.code == "REQUEST_ID_CONFLICT"
            missing = await client.recover("request-not-retained", wait_seconds=3)
            assert missing.error.code == "REQUEST_NOT_FOUND" and not missing.error.retry_submit
            assert len(generated) == 1
            page = await client.tasks(status="completed")
            assert page["total"] == 1 and page["items"][0]["task_id"] == result.task_id
            encoded = next(args for name, _, args in api.calls if name.endswith("drawpic_submit"))["source_images"][0]
            assert base64.b64decode(encoded) == image_bytes()
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_default_options_preserve_old_idempotency_signature(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            async def generate(**kwargs):
                return [image_bytes()]

            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            receipt = await plugin.drawpic_submit("cat", request_id="old-signature-request")
            record = plugin._task_store.get_task(receipt["task_id"])
            expected = sha256(json.dumps(["cat", "", "", "", "draw", "", None, None], ensure_ascii=False).encode()).hexdigest()
            assert record.submission["signature"] == expected
            await asyncio.gather(*tuple(plugin._require_draw_service().background_tasks))
            reused = await plugin.drawpic_submit("cat", request_id="old-signature-request")
            assert reused["reused"] and reused["task_id"] == receipt["task_id"]
            rejected = await plugin.drawpic_submit("cat", novelai_mode="bad")
            assert rejected["error"]["code"] == "INVALID_REQUEST" and not rejected["accepted"]
        finally:
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("tags,expected", [(None, "artist:session"), ("", "artist:default"), ("artist:task", "artist:task")])
def test_novelai_task_overrides_inherit_without_mutating_preferences(make_plugin, monkeypatch, tags, expected):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            await plugin.workspace_provider_save(json.dumps({
                "kind": "novelai", "name": "NAI", "config": {
                    "api_key": "fixture-nai-key", "models": ["nai-diffusion-4-5-full"], "default_artist_tags": "artist:default",
                },
            }), plugin._platform_store.revision)
            provide_streams(plugin, monkeypatch)
            async def send(*args, **kwargs):
                return True

            monkeypatch.setattr(plugin.ctx.send, "image", send)
            generated = []

            async def generate(**kwargs):
                generated.append(kwargs["attempt"])
                return [image_bytes()]

            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            client = DrawingClient(LocalAPI(plugin), poll_interval=0.001)
            original = await client.set_preferences("actual-stream", novelai_mode="background", novelai_artist_tags="artist:session")
            models = (await client.models())["models"]
            model = next(item for item in models if item["provider"] == "novelai")
            assert model["api_edit_image"] and model["max_source_images"] == 1
            result = await client.generate(
                "cat", model=model["name"], stream_id="actual-stream", novelai_mode="furry",
                novelai_artist_tags=tags, wait_seconds=3,
            )
            assert result.status == "completed" and len(generated) == 1
            assert generated[0].novelai_mode == "furry" and generated[0].novelai_artist_tags == expected
            assert (await client.preferences("actual-stream"))["preferences"] == original["preferences"]
            with pytest.raises(DrawingError, match="最多支持 1"):
                await client.submit("cat", model=model["name"], task_type="edit_image",
                                    source_images=[image_bytes(), image_bytes() + b"second-source"])
            assert len(generated) == 1
        finally:
            await plugin.on_unload()
    asyncio.run(run())
