"""统一公开接口的原生对象参数、无版本调用和完整联动路径。"""

import asyncio
import pytest

from test_access_control import provide_streams
from test_drawing_client import DrawingClient, LocalAPI, module
from test_workspace import image_bytes, make_plugin


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


def test_all_unified_endpoints_work_through_sdk_without_version_selection(make_plugin, monkeypatch, tmp_path):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            provide_streams(plugin, monkeypatch, group_id="", user_id="10001")
            calls = []
            async def generate(**kwargs):
                calls.append(kwargs)
                return [image_bytes()]
            def deny_external_generation(*args, **kwargs):
                raise AssertionError("External generation is forbidden in this test")
            provider = module("infrastructure.providers.openai").OpenaiImage
            monkeypatch.setattr(provider, "generate_images", deny_external_generation)
            monkeypatch.setattr(provider, "edit_images", deny_external_generation)
            api = LocalAPI(plugin)
            client = DrawingClient(api, poll_interval=0.001)
            model = (await client.models())["models"][0]["name"]
            await client.set_preferences("actual-stream", model=model)
            assert (await client.preferences("actual-stream"))["preferences"]["model"] == model
            preset = {"name": "统一预设", "tags": ["水彩"], "positive_prompt_template": "watercolor, {prompt}"}
            assert (await client.save_preset(preset))["error"] is None
            assert (await client.preset(preset["name"]))["preset"]["tags"] == ["水彩"]
            assert (await client.presets())["presets"]
            assert (await client.references())["error"] is None
            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            result = await client.generate(
                "cat", model=model, task_type="edit_image", source_images=[image_bytes()],
                request_id="unified-native-request", reference_options={"self_reference": "off", "user_request": "画一只猫"},
                wait_seconds=5,
            )
            assert result.status == "completed" and len(calls) == 1
            assert result.images[0].data == image_bytes()
            recovered = await client.request(result.request_id)
            assert recovered["task_id"] == result.task_id and "record" not in recovered
            assert (await client.tasks())["items"][0]["task_id"] == result.task_id
            assert not (await client.cancel(result.task_id))["cancel_requested"]
            destination = tmp_path / "unified.png"
            await client.save_image(result.task_id, destination)
            assert destination.read_bytes() == image_bytes()
            await client.delete_preset(preset["name"])
            assert not (await client.presets())["presets"]
            assert all(version == "" for _, version, _ in api.calls)
            assert {name.rsplit(".", 1)[1] for name, _, _ in api.calls} == {
                "drawpic_models", "drawpic_submit", "drawpic_task", "drawpic_request", "drawpic_tasks",
                "drawpic_image", "drawpic_cancel", "drawpic_preferences", "drawpic_preferences_set",
                "drawpic_presets", "drawpic_references",
            }
            submitted = next(arguments for name, _, arguments in api.calls if name.endswith("drawpic_submit"))
            assert submitted["reference_options"] == {"self_reference": "off", "user_request": "画一只猫"}
            assert "reference_options_json" not in submitted
        finally:
            await plugin.on_unload()
    asyncio.run(run())
