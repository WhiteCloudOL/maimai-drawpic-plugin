"""ComfyUI 官方 HTTP 契约与工作台保存回归；仅使用临时文件和本地模拟服务。"""

from aiohttp import web
from contextlib import asynccontextmanager
import asyncio
import json
import pytest
import time

from test_provider_request_phases import comfy_provider, module
from test_workspace import image_bytes, make_plugin as make_plugin

errors = module("domain.errors")


def workflow():
    return {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "original"}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "negative"}},
        "3": {"class_type": "KSampler", "inputs": {"seed": 1}},
        "10": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
    }


def configured(tmp_path):
    provider = comfy_provider(tmp_path)
    path = tmp_path / "workflow.json"
    path.write_text(json.dumps(workflow()), encoding="utf-8")
    provider.t2i_workflow_path = provider.i2i_workflow_path = str(path)
    provider.t2i_positive_prompt_node_id = provider.i2i_positive_prompt_node_id = "6"
    provider.t2i_negative_prompt_node_id = provider.i2i_negative_prompt_node_id = "7"
    provider.i2i_image_node_id = "10"
    provider.seed = 18446744073709551615
    return provider


@asynccontextmanager
async def server(handler, port):
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


@pytest.mark.parametrize("edit", [False, True])
def test_local_official_upload_prompt_history_and_view_contract(tmp_path, unused_tcp_port, edit):
    async def run():
        calls, posted, queries = [], [], []
        raw = image_bytes()

        async def handler(request):
            calls.append((request.method, request.path))
            if request.path == "/upload/image":
                form = await request.post()
                assert form["type"] == "input" and form["image"].file.read() == raw
                return web.json_response({"name": "renamed.png", "subfolder": "uploads", "type": "input"})
            if request.path == "/prompt":
                body = await request.json()
                assert set(body) == {"prompt", "client_id"}
                posted.append(body["prompt"])
                return web.json_response({"prompt_id": "fixture-id", "number": 0, "node_errors": {}})
            if request.path == "/history/fixture-id":
                queries.append(request.path)
                return web.json_response({} if len(queries) == 1 else {"fixture-id": {
                    "status": {"status_str": "success", "completed": True, "messages": []},
                    "outputs": {"8": {"images": [{"filename": "preview.png", "type": "temp"}]},
                                "9": {"images": [{"filename": "result 1.png", "subfolder": "run folder", "type": "output"}]}},
                }})
            assert request.path == "/view"
            assert dict(request.query) == {"filename": "result 1.png", "subfolder": "run folder", "type": "output"}
            return web.Response(body=raw, content_type="image/png")

        async with server(handler, unused_tcp_port) as endpoint:
            provider = configured(tmp_path)
            provider.base_url = endpoint
            actual = await provider.edit_images("changed", "comfyui", [raw]) if edit else await provider.generate_images("changed", "comfyui")
            assert actual == [raw]
        assert len(posted) == 1 and posted[0]["6"]["inputs"]["text"] == "changed"
        assert posted[0]["3"]["inputs"]["seed"] == 18446744073709551615
        assert posted[0]["10"]["inputs"]["image"] == ("uploads/renamed.png" if edit else "old.png")
        assert calls.count(("POST", "/upload/image")) == int(edit)
        assert len(queries) == 2

    asyncio.run(run())


def test_http_validation_error_retains_node_details_and_omits_inputs(tmp_path, unused_tcp_port):
    async def run():
        async def handler(request):
            return web.json_response({"error": {"type": "prompt_outputs_failed_validation", "message": "invalid outputs"},
                "node_errors": {"6": {"class_type": "CLIPTextEncode", "errors": [
                    {"type": "required_input_missing", "message": "Required input missing", "details": "clip", "extra_info": {"private": "hidden-workflow-input"}}
                ]}}}, status=400)
        async with server(handler, unused_tcp_port) as endpoint:
            provider = configured(tmp_path)
            provider.base_url = endpoint
            with pytest.raises(errors.ProviderRequestError) as raised:
                await provider.generate_images("not logged", "comfyui")
        failure = raised.value
        assert failure.status == 400 and failure.code == "prompt_outputs_failed_validation"
        assert "node=6" in str(failure) and "clip" in str(failure)
        assert "hidden-workflow-input" not in str(failure)
        assert not failure.retryable and not failure.allow_fallback
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["slow_query", "execution_error", "incomplete"])
def test_accepted_workflow_failure_keeps_id_and_never_requeues(tmp_path, monkeypatch, failure):
    async def run():
        provider = configured(tmp_path)
        provider.request_timeout_seconds = 0.04
        calls = []
        async def request(method, path, **kwargs):
            calls.append((method, path))
            if method == "POST":
                return {"prompt_id": "fixture-id"}
            if failure == "slow_query":
                await asyncio.sleep(1)
            return {"fixture-id": {"status": {
                "status_str": "error" if failure == "execution_error" else "success", "completed": False,
                "messages": [["execution_error", {"node_id": "3", "exception_message": "bad model", "current_inputs": {"text": "private prompt"}}]],
            }, "outputs": {}}}
        monkeypatch.setattr(provider, "_request_json", request)
        start = time.monotonic()
        with pytest.raises(errors.ProviderSubmittedError) as raised:
            await provider._execute_workflow(workflow(), "文生图")
        assert time.monotonic() - start < 0.5
        assert raised.value.remote_task_id == "fixture-id" and not raised.value.retryable
        assert "private prompt" not in str(raised.value)
        assert [method for method, _ in calls].count("POST") == 1
        if failure == "execution_error":
            assert "bad model" in str(raised.value)
    asyncio.run(run())


def test_invalid_image_target_fails_before_upload(tmp_path, monkeypatch):
    provider = configured(tmp_path)
    provider.i2i_image_node_id = "missing"
    async def unexpected(*args):
        pytest.fail("invalid workflow must not upload or submit")
    monkeypatch.setattr(provider, "_upload_image", unexpected)
    with pytest.raises(ValueError, match="missing"):
        asyncio.run(provider.edit_images("test", "comfyui", [image_bytes()]))


def test_prompt_targets_cannot_overwrite_each_other_or_links(tmp_path):
    provider = configured(tmp_path)
    provider.t2i_negative_prompt_node_id = "6"
    with pytest.raises(ValueError, match="不同节点"):
        provider.validate_task_configuration("draw")
    linked = workflow()
    linked["6"]["inputs"]["text"] = ["11", 0]
    with pytest.raises(ValueError, match="连线"):
        provider._get_node_inputs(linked, "6", "text", "提示词")


@pytest.mark.parametrize("invalid", [{"nodes": []}, {"6": {"inputs": {"text": "test"}}}, {"6": {"class_type": "CLIPTextEncode", "inputs": []}}])
def test_non_api_node_definitions_fail_before_network(tmp_path, invalid):
    provider = configured(tmp_path)
    (tmp_path / "workflow.json").write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(ValueError, match="API"):
        provider.validate_task_configuration("draw")


def test_workspace_uint64_seed_round_trip_is_exact(make_plugin):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            result = await plugin.workspace_provider_save(json.dumps({"kind": "comfyui", "name": "Local", "config": {"seed": "18446744073709551615"}}), plugin._platform_store.revision)
            assert result["saved"]
            snapshot = await plugin.workspace_bootstrap()
            record = next(item for item in snapshot["providers"] if item["kind"] == "comfyui")
            assert record["config"]["seed"] == "18446744073709551615"
            assert plugin._platform_store.providers[0]["config"]["seed"] == 18446744073709551615
            again = await plugin.workspace_provider_save(json.dumps({key: record[key] for key in ("id", "kind", "name", "config")}), snapshot["revision"])
            assert again["saved"] and plugin._platform_store.providers[0]["config"]["seed"] == 18446744073709551615
        finally:
            await plugin.on_unload()
    asyncio.run(run())
