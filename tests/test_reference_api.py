"""经真实 SDK、插件事务、图片文件和本机 HTTP 绘图服务验证全部公开接口。"""

from aiohttp import web
from aiohttp.web import FileField
from maibot_sdk.components import collect_components
from pathlib import Path
import ast
import asyncio
import base64
import json
import re

import pytest

from test_api_settings import provide_streams
from test_drawing_client import DrawingClient, DrawingError, LocalAPI
from test_workspace import image_bytes, make_plugin as make_plugin


PUBLIC_APIS = {"drawpic_models", "drawpic_draw", "drawpic_submit", "drawpic_task", "drawpic_request",
               "drawpic_tasks", "drawpic_image", "drawpic_cancel", "drawpic_preferences", "drawpic_preferences_set",
               "drawpic_presets", "drawpic_references", "drawpic_reference", "drawpic_reference_update",
               "drawpic_reference_image", "drawpic_reference_settings", "drawpic_reference_settings_set"}


def test_every_public_api_through_sdk_and_real_local_http(make_plugin, monkeypatch, tmp_path):
    async def run():
        requests = []

        async def respond(request):
            if request.method == "GET":
                return web.json_response({"data": [{"id": "gpt-image-1"}]})
            if request.content_type == "multipart/form-data":
                form = await request.post()
                uploaded = [await asyncio.to_thread(item.file.read) for key in ("image", "image[]")
                            for item in form.getall(key, []) if isinstance(item, FileField)]
            else:
                await request.read()
                uploaded = []
            requests.append((request.path, uploaded))
            return web.json_response({"data": [{"b64_json": base64.b64encode(image_bytes()).decode("ascii")}]})

        app = web.Application(client_max_size=10 * 1024 * 1024)
        app.router.add_route("*", "/{path:.*}", respond)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        port = runner.addresses[0][1]
        plugin = make_plugin()
        config = plugin.get_plugin_config_data()
        config["openai"].update(base_url=f"http://127.0.0.1:{port}/v1", models=["gpt-image-1"], rewrite_prompt_to_english=False)
        config["general"]["default_model"] = "gpt-image-1"
        plugin.set_plugin_config(config)
        await plugin.on_load()
        try:
            provide_streams(plugin, monkeypatch)
            api = LocalAPI(plugin)
            client = DrawingClient(api, poll_interval=0.001)
            model = (await client.models())["models"][0]["name"]
            await client.set_preferences("actual-stream", model=model)
            assert (await client.preferences("actual-stream"))["preferences"]["model"] == model
            own = await client.save_reference({"name": "自己的形象", "tags": ["日常"], "prompt": "保留长发"}, revision=0, image=image_bytes())
            raw = image_bytes() + b"\x00" * 300000
            scene = await client.save_reference({"name": "海边", "kind": "preset", "tags": ["海边"]}, revision=own["revision"], image=raw)
            own_id, scene_id = own["asset_id"], scene["asset_id"]
            assert (await client.reference(own_id))["asset"]["prompt"] == "保留长发"
            catalog = await client.references(kind="self", search="日常")
            assert catalog["total"] == 1 and catalog["assets"][0]["id"] == own_id
            selected = await client.set_default_reference(own_id, revision=scene["revision"])
            moved = await client.move_reference(scene_id, 0, revision=selected["revision"])
            await client.save_reference({"asset_id": own_id, "prompt": "白色长发"}, revision=moved["revision"])
            assert (await client.reference_preview(scene_id))["data_url"].startswith("data:image/webp;base64,")
            destination = await client.save_reference_image(scene_id, tmp_path / "scene.png")
            assert destination.read_bytes() == raw
            chunks = [args for name, _, args in api.calls if name.endswith("drawpic_reference_image") and args.get("kind") == "original"]
            assert len(chunks) == 2 and chunks[0]["offset"] == 0 and chunks[1]["offset"] == 192 * 1024
            settings = await client.reference_settings()
            await client.set_reference_settings(revision=settings["revision"], self_reference_enabled=True,
                self_names=["小麦"], self_keywords=["自拍", "画"], image_edit_presets_enabled=True)
            await client.save_preset({"name": "海边预设", "preset_type": "image_to_image",
                                      "reference_bindings": [{"asset_id": scene_id}]})
            assert (await client.preset("海边预设"))["preset"]["reference_bindings"][0]["asset_id"] == scene_id
            assert (await client.presets())["presets"]
            settings = await client.reference_settings()
            await client.set_reference_settings(revision=settings["revision"], default_image_edit_preset="海边预设")
            handle = await client.draw("画海边", reference_id=scene_id, style="none", request_id="simple-http-api-01")
            simple = await client.wait(handle, wait_seconds=10)
            assert simple.status == "completed" and simple.images[0].data == image_bytes()
            advanced = await client.generate("画麦麦在海边", task_type="edit_image", style="none", request_id="advanced-http-api-01",
                reference_options={"self_reference": "required", "self_reference_ids": [own_id],
                                   "reference_ids": [scene_id], "multi_reference_confirmed": True}, wait_seconds=10)
            assert advanced.status == "completed" and advanced.images[0].data == image_bytes()
            plain = await client.draw("画猫", request_id="plain-http-api-001")
            assert (await client.wait(plain, wait_seconds=10)).status == "completed"
            preset_only = await client.draw("画海边", style="海边预设", request_id="preset-http-api-01")
            assert (await client.wait(preset_only, wait_seconds=10)).status == "completed"
            assert (await client.request(handle.request_id))["task_id"] == handle.task_id
            assert (await client.task(handle.task_id))["generation_completed"]
            assert (await client.tasks())["total"] == 4
            assert not (await client.cancel(handle.task_id))["cancel_requested"]
            await client.delete_preset("海边预设")
            revision = (await client.references())["revision"]
            deleted = await client.delete_reference(scene_id, revision=revision)
            recovered = await client.draw("画海边", reference_id=scene_id, style="none", request_id=handle.request_id)
            assert recovered.task_id == handle.task_id and recovered.reused
            with pytest.raises(DrawingError) as conflict:
                await client.draw("换了请求", reference_id=scene_id, style="none", request_id=handle.request_id)
            assert conflict.value.code == "REQUEST_ID_CONFLICT"
            await client.delete_reference(own_id, revision=deleted["revision"])
            assert (await client.references())["total"] == 0
            assert requests == [("/v1/images/edits", [raw]), ("/v1/images/edits", [raw, image_bytes()]),
                                ("/v1/images/generations", []), ("/v1/images/edits", [raw])]
            assert {name.rsplit(".", 1)[1] for name, _, _ in api.calls} == PUBLIC_APIS
            assert {item["name"] for item in collect_components(plugin)
                    if item["type"] == "API" and item["metadata"]["public"]} == PUBLIC_APIS
            assert all(version == "" for _, version, _ in api.calls)
        finally:
            await plugin.on_unload()
            await runner.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize("endpoint,args", [
    ("drawpic_draw", {"prompt": "cat", "self_reference": "true"}),
    ("drawpic_reference", {"asset_id": "../outside"}),
    ("drawpic_references", {"page": True}),
    ("drawpic_reference_update", {"operation": "save", "revision": 0, "reference": {"path": "/outside"}}),
    ("drawpic_reference_update", {"operation": "save", "revision": True, "reference": {"name": "cat"}}),
    ("drawpic_reference_image", {"asset_id": "../outside", "kind": "original", "asset_version": "0" * 64}),
    ("drawpic_reference_settings_set", {"revision": 0, "settings": {"deepseek_api_key": "forbidden"}}),
    ("drawpic_reference_settings_set", {"revision": 0, "settings": {"self_reference_enabled": "true"}}),
    ("drawpic_reference_settings_set", {"revision": 0, "settings": {"self_names": []}, "confirm_multi_reference": 1}),
])
def test_new_api_input_errors_are_structured_and_do_not_write(make_plugin, endpoint, args):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            before = plugin._platform_store.revision
            reply = await LocalAPI(plugin).call(f"maimai-drawpic-plugin.{endpoint}", **args)
            assert reply["error"] is not None and isinstance(reply["error"]["message"], str)
            assert plugin._platform_store.revision == before
            assert not plugin._workspace().tasks.references.snapshot()["assets"]
            assert plugin._task_store.get_task_count() == 0
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_reference_conflicts_and_replacement_are_not_retried(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            client = DrawingClient(LocalAPI(plugin))
            first = await client.save_reference({"name": "原图"}, revision=0, image=image_bytes())
            with pytest.raises(DrawingError) as stale:
                await client.save_reference({"asset_id": first["asset_id"], "name": "旧草稿"}, revision=0)
            assert stale.value.code == "REFERENCE_REVISION_CONFLICT"
            await client.save_reference({"asset_id": first["asset_id"]}, revision=first["revision"], image=image_bytes() + b"new")
            with pytest.raises(DrawingError) as changed:
                await client.read_reference_image(first["asset_id"], asset_version=first["asset"]["version"])
            assert changed.value.code == "REFERENCE_VERSION_CONFLICT"
            current = await client.reference_settings()
            await client.set_reference_settings(revision=current["revision"], self_names=["新称呼"])
            with pytest.raises(DrawingError) as settings_stale:
                await client.set_reference_settings(revision=current["revision"], self_names=["旧草稿"])
            assert settings_stale.value.code == "CONFIG_REVISION_CONFLICT"
            assert (await client.reference_settings())["settings"]["self_names"] == ["新称呼"]
            latest = await client.reference(first["asset_id"])
            await client.delete_reference(first["asset_id"], revision=latest["revision"])
            with pytest.raises(DrawingError) as missing:
                await client.read_reference_image(first["asset_id"], asset_version=latest["asset"]["version"])
            assert missing.value.code == "REFERENCE_NOT_FOUND"
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_saved_reference_is_protected_when_runtime_refresh_fails(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            workspace = await plugin.workspace_bootstrap()
            workspace["settings"]["general"]["references"]["deepseek_api_key"] = "fixture-private-search-key"
            await plugin.workspace_settings_save(json.dumps(workspace["settings"]), workspace["revision"])
            client = DrawingClient(LocalAPI(plugin))
            image = await client.save_reference({"name": "人设"}, revision=0, image=image_bytes())
            settings = await client.reference_settings()

            async def fail_refresh(values):
                raise RuntimeError("fixture refresh failure")

            monkeypatch.setattr(plugin._workspace(), "apply_settings", fail_refresh)
            saved = await client.set_reference_settings(revision=settings["revision"], self_reference_ids=[image["asset_id"]])
            assert saved["saved"] and saved["runtime_refresh_pending"]
            assert (await client.reference_settings())["settings"]["self_reference_ids"] == [image["asset_id"]]
            with pytest.raises(DrawingError):
                await client.delete_reference(image["asset_id"], revision=image["revision"])
            assert plugin._platform_store.settings.values["general"]["references"]["deepseek_api_key"] == "fixture-private-search-key"
            assert "fixture-private-search-key" not in json.dumps(saved)
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_drawing_client_never_combines_replaced_reference_chunks(make_plugin, tmp_path):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            api = LocalAPI(plugin)
            writer = DrawingClient(api)
            image = await writer.save_reference({"name": "原图"}, revision=0,
                                                image=image_bytes() + b"\x00" * 300000)

            class ReplacingAPI:
                replaced = False

                async def call(self, api_name, **arguments):
                    reply = await api.call(api_name, **arguments)
                    if api_name.endswith("drawpic_reference_image") and arguments.get("offset") == 0 and not self.replaced:
                        self.replaced = True
                        await writer.save_reference({"asset_id": image["asset_id"]}, revision=image["revision"],
                                                    image=image_bytes() + b"replaced-after-first-chunk")
                    return reply

            destination = tmp_path / "incomplete-reference.png"
            with pytest.raises(DrawingError) as changed:
                await DrawingClient(ReplacingAPI()).save_reference_image(image["asset_id"], destination)
            assert changed.value.code == "REFERENCE_VERSION_CONFLICT"
            assert not destination.exists()
            reads = [args for name, _, args in api.calls if name.endswith("drawpic_reference_image")]
            assert [args["offset"] for args in reads] == [0, 192 * 1024]
            assert all(args["asset_version"] == image["asset"]["version"] for args in reads)
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_multi_reference_confirmation_is_explicit_and_not_an_llm_field(make_plugin):
    from test_references import module

    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            client = DrawingClient(LocalAPI(plugin))
            first = await client.save_reference({"name": "正面"}, revision=0, image=image_bytes())
            second = await client.save_reference({"name": "侧面"}, revision=first["revision"], image=image_bytes() + b"side")
            settings = await client.reference_settings()
            ids = [first["asset_id"], second["asset_id"]]
            staged = await client.set_reference_settings(revision=settings["revision"], self_reference_ids=ids)
            assert not staged["settings"]["self_reference_enabled"]
            assert not staged["settings"]["multi_reference_confirmed"]
            with pytest.raises(DrawingError) as required:
                await client.set_reference_settings(revision=staged["revision"], self_reference_enabled=True)
            assert required.value.code == "MULTI_REFERENCE_CONFIRMATION_REQUIRED"
            confirmed = await client.set_reference_settings(revision=staged["revision"],
                self_reference_enabled=True, confirm_multi_reference=True)
            assert confirmed["settings"]["multi_reference_confirmed"]
            schema = module("interfaces.tools.schemas").DRAW_TOOL_PARAMETERS_SCHEMA
            assert "multi_reference_confirmed" not in schema["properties"]["reference_options"]["properties"]
            with pytest.raises(ValueError, match="不能由聊天模型"):
                plugin._drawing_reference_options({}, {"multi_reference_confirmed": True})
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_documented_reference_configuration_example_runs(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            plugin.ctx.api = LocalAPI(plugin)
            namespace = {"DrawingClient": DrawingClient}
            document = (Path(__file__).parents[1] / "docs/integration.md").read_text(encoding="utf-8")
            assert set(re.findall(r"^\| `(drawpic_[a-z_]+)` \|", document, re.M)) == PUBLIC_APIS
            for code in re.findall(r"```python\n(.*?)\n```", document, re.S):
                tree = ast.parse(code)
                functions = [item for item in tree.body if isinstance(item, ast.AsyncFunctionDef)
                             and item.name == "configure_self_reference"]
                if functions:
                    exec(compile(ast.Module(body=functions, type_ignores=[]), "docs/integration.md", "exec"), namespace)
            identifier = await namespace["configure_self_reference"](plugin.ctx, image_bytes())
            info = await DrawingClient(plugin.ctx.api).reference(identifier)
            assert info["asset"]["default"] and info["asset"]["prompt"] == "保留白色长发"
            assert plugin.config.general.references.self_reference_enabled
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_external_plugin_can_confirm_and_save_multi_image_preset(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            client = DrawingClient(LocalAPI(plugin))
            first = await client.save_reference({"name": "场景", "kind": "preset"}, revision=0, image=image_bytes())
            second = await client.save_reference({"name": "光线", "kind": "preset"}, revision=first["revision"], image=image_bytes() + b"light")
            preset = {"name": "组合", "preset_type": "image_to_image", "reference_bindings": [
                {"asset_id": first["asset_id"]}, {"asset_id": second["asset_id"]}]}
            with pytest.raises(DrawingError) as needed:
                await client.save_preset(preset)
            assert needed.value.code == "MULTI_REFERENCE_CONFIRMATION_REQUIRED"
            await client.save_preset(preset, confirm_multi_reference=True)
            assert (await client.preset("组合"))["preset"]["multi_reference_confirmed"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("endpoint", sorted(PUBLIC_APIS))
def test_every_public_api_obeys_integration_switch(make_plugin, endpoint):
    async def run():
        plugin = make_plugin()
        config = plugin.get_plugin_config_data()
        config["general"]["integration_api_enabled"] = False
        plugin.set_plugin_config(config)
        await plugin.on_load()
        try:
            arguments = {
                "drawpic_draw": {"prompt": "cat"}, "drawpic_submit": {"prompt": "cat"},
                "drawpic_task": {"task_id": "a" * 12}, "drawpic_request": {"request_id": "valid-request-id"},
                "drawpic_image": {"task_id": "a" * 12}, "drawpic_cancel": {"task_id": "a" * 12},
                "drawpic_preferences": {"stream_id": "stream"},
                "drawpic_preferences_set": {"stream_id": "stream", "preferences": {}},
                "drawpic_reference": {"asset_id": "a" * 32}, "drawpic_reference_image": {"asset_id": "a" * 32},
                "drawpic_reference_update": {"operation": "delete", "revision": 0, "reference": {"asset_id": "a" * 32}},
                "drawpic_reference_settings_set": {"settings": {"self_names": ["麦麦"]}, "revision": 0},
            }
            response = await LocalAPI(plugin).call(f"maimai-drawpic-plugin.{endpoint}", **arguments.get(endpoint, {}))
            assert response["error"]["code"] == "PERMISSION_DENIED"
            assert plugin._task_store.get_task_count() == 0
        finally:
            await plugin.on_unload()

    asyncio.run(run())
