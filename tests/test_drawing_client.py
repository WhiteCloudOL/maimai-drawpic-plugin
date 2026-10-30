"""正式客户端通过实际 SDK 组件声明连接隔离插件；不调用真实模型或聊天。"""

from pathlib import Path
from functools import partial
from threading import Event
from maibot_sdk.components import collect_components
from test_workspace import _PACKAGE, image_bytes, make_plugin as make_plugin
import asyncio
import ast
import base64
import importlib
import json
import re
import shutil
import subprocess
import sys
import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "clients"))
from maimai_drawing_client import DrawingClient, DrawingError, DrawingTransportError  # noqa: E402


def module(name):
    return importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.{name}")


class LocalAPI:
    def __init__(self, plugin):
        self.plugin, self.calls = plugin, []
        self.handlers = {
            (item["name"], item["metadata"]["version"]): item["metadata"]["handler_name"]
            for item in collect_components(plugin)
            if item["type"] == "API"
        }

    async def call(self, api_name, version="1", **kwargs):
        self.calls.append((api_name, version, kwargs))
        handler = self.handlers[(api_name.rsplit(".", 1)[1], version)]
        result = await getattr(self.plugin, handler)(**kwargs)
        if api_name.endswith("drawpic_task_v2") and version == "2":
            result["retry_after_ms"] = 1  # 加速模拟轮询，不改变产品接口。
        return {"success": True, "result": result}


def test_incomplete_submission_receipt_preserves_key_and_rejects_invalid_key():
    async def run():
        class IncompleteAPI:
            def __init__(self):
                self.calls = 0

            async def call(self, *args, **kwargs):
                self.calls += 1
                return {"success": True, "result": {"accepted": True}}

        api = IncompleteAPI()
        client = DrawingClient(api)
        result = await client.generate("cat", request_id="incomplete-receipt-01")
        assert result.request_id == "incomplete-receipt-01" and result.task_id is None
        assert result.error.code == "SUBMISSION_UNKNOWN" and not result.error.retry_submit
        assert result.error.request_id == result.request_id and api.calls == 1
        with pytest.raises(ValueError, match="request_id"):
            await client.submit("cat", request_id="invalid key")
        assert api.calls == 1

    asyncio.run(run())


def test_documented_background_llm_edit_and_recovery_examples(make_plugin, monkeypatch, tmp_path):
    async def run():
        namespace = {"DrawingClient": partial(DrawingClient, poll_interval=0.001), "DrawingError": DrawingError}
        document = (Path(__file__).parents[1] / "docs/integration.md").read_text(encoding="utf-8")
        for code in re.findall(r"```python\n(.*?)\n```", document, re.S):
            tree = ast.parse(code)
            body = [
                node
                for node in tree.body
                if isinstance(node, (ast.AsyncFunctionDef, ast.Import))
                or isinstance(node, ast.ImportFrom)
                and not node.level
            ]
            exec(compile(ast.Module(body=body, type_ignores=[]), "docs/integration.md", "exec"), namespace)
        plugin = make_plugin()
        await plugin.on_load()
        try:
            generations = []

            async def generate(**kwargs):
                generations.append(kwargs)
                return [image_bytes()]

            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            plugin.ctx.api = LocalAPI(plugin)
            output = tmp_path / "result.png"
            background = await namespace["background_draw"](plugin.ctx, "cat", "docs-background-01", output)
            assert background.status == "completed" and output.read_bytes() == image_bytes()
            receipt = await namespace["llm_submit"](plugin.ctx, "cat", "docs-llm-01", 10)
            await asyncio.gather(*tuple(plugin._require_draw_service().background_tasks))
            queried = await namespace["llm_query"](plugin.ctx, receipt["task_id"])
            assert queried["status"] == "completed" and "data" not in queried["images"][0]
            model = (await plugin.drawpic_models())["models"][0]["name"]
            edited = await namespace["edit_picture"](plugin.ctx, image_bytes(), model, "docs-edit-01")
            assert edited.status == "completed" and generations[-1]["task_type"] == "edit_image"
            saved = {"task_id": receipt["task_id"], "request_id": receipt["request_id"], "request": {"prompt": "cat"}}
            resumed = await namespace["resume_drawing"](plugin.ctx, saved, 5)
            assert resumed.task_id == receipt["task_id"] and resumed.images
            saved["task_id"] = None  # 模拟回执丢失，仍用原键找回。
            recovered = await namespace["resume_drawing"](plugin.ctx, saved, 5)
            assert recovered.task_id == receipt["task_id"] and len(generations) == 3
            assert (await namespace["call_v2"](plugin.ctx, "task", task_id=receipt["task_id"]))["status"] == "completed"
            assert "presets" in await namespace["call_drawpic"](plugin, "drawpic_presets", operation="list")
            assert all(not kwargs["stream_id"] for _, _, kwargs in plugin.ctx.api.calls if "stream_id" in kwargs)
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_generate_uses_real_v2_and_returns_images_without_sending(make_plugin, monkeypatch, tmp_path):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            generated = []

            async def generate(**kwargs):
                # 执行开始前，磁盘上已存在任务及同文件幂等映射。
                disk = json.loads(plugin._task_store.path.read_text(encoding="utf-8"))
                record = disk["tasks"][kwargs["task_id"]]
                assert record["submission"]["request_id"] == "client-request-01"
                generated.append(kwargs)
                return [image_bytes()]

            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            api = LocalAPI(plugin)
            client = DrawingClient(api, poll_interval=0.001)
            result = await client.generate("watercolor", request_id="client-request-01", wait_seconds=5)
            assert result.status == "completed" and not result.wait_expired
            assert result.images[0].data == image_bytes()
            assert result.generation_completed and result.results_readable
            assert result.delivery == {"requested": False, "status": "not_requested", "sent_count": 0}
            assert "expires_at" in result.image_references[0]
            assert not any(key in result.image_references[0] for key in ["data", "data_url", "file"])
            target = tmp_path / "calling-plugin/output.png"
            assert await client.save_image(result.task_id, target) == target
            assert target.read_bytes() == image_bytes()
            with pytest.raises(FileExistsError):
                await client.save_image(result.task_id, target)
            assert len(generated) == 1
            again = await client.submit("watercolor", request_id="client-request-01")
            assert again.task_id == result.task_id and again.reused
            with pytest.raises(DrawingError) as conflict:
                await client.submit("changed prompt", request_id="client-request-01")
            assert conflict.value.code == "REQUEST_ID_CONFLICT"
            task = await client.task(result.task_id)
            assert "submission" not in task and "prompt" not in task and "signature" not in json.dumps(task)
            assert len({(item[0], item[1]) for item in api.calls}) >= 3
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_generated_but_review_rejected_is_distinct_from_prompt_rejection(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:

            async def generate(**kwargs):
                return [image_bytes()]

            async def reject_images(prompt, images, *, task_id):
                assert task_id
                return [], ["fixture image review rejected"]

            service = plugin._require_draw_service()
            monkeypatch.setattr(service, "_run_image_request_attempt", generate)
            monkeypatch.setattr(service, "filter_reviewed_images", reject_images)
            result = await DrawingClient(LocalAPI(plugin), poll_interval=0.001).generate("cat", wait_seconds=5)
            assert result.status == "rejected" and result.generation_completed
            assert result.error.code == "MODERATION_REJECTED" and not result.results_readable
            assert not result.images and not result.image_references
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_wait_timeout_then_resume_same_task_and_expiry(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            ready, generated = asyncio.Event(), []

            async def generate(**kwargs):
                generated.append(kwargs)
                await ready.wait()
                return [image_bytes()]

            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            client = DrawingClient(LocalAPI(plugin), poll_interval=0.001)
            first = await client.generate("cat", request_id="resume-request-01", wait_seconds=0.08)
            assert first.wait_expired and first.task_id and first.status in {"pending", "running"}
            ready.set()
            result = await client.wait(first.task_id, request_id=first.request_id, wait_seconds=5)
            assert result.status == "completed" and len(generated) == 1
            await asyncio.to_thread(shutil.rmtree, plugin._result_store.root / first.task_id)
            expired = await client.wait(first.task_id, wait_seconds=1)
            assert expired.generation_completed and not expired.results_readable
            assert expired.error.code == "RESULT_EXPIRED" and not expired.error.retry_submit
            with pytest.raises(DrawingError, match="过期"):
                await client.read_image(first.task_id)
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["timeout", "host_error", "sdk_error", "budget"])
def test_submission_unknown_always_keeps_request_id_and_never_resubmits(mode):
    async def run():
        calls = []

        class API:
            async def call(self, *args, **kwargs):
                calls.append(kwargs)
                if mode in {"timeout", "budget"}:
                    await asyncio.sleep(2)
                if mode == "sdk_error":
                    raise ConnectionError("IPC closed")
                return {"success": False, "error": "Host lost response"}

        client = DrawingClient(API(), rpc_timeout=0.02)
        result = await client.generate(
            "cat", request_id="uncertain-id-01", wait_seconds=0.005 if mode == "budget" else 1
        )
        assert result.task_id is None and result.request_id == "uncertain-id-01"
        assert result.status == "submission_unknown" and result.error.code == "SUBMISSION_UNKNOWN"
        assert not result.error.retry_submit and len(calls) == 1

    asyncio.run(run())


def test_v2_failures_unknown_cancellation_and_concurrency(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            service = plugin._require_draw_service()

            async def fail(**kwargs):
                raise module("domain.errors").ProviderOutcomeUnknown("远端受理状态未知")

            monkeypatch.setattr(service, "_run_image_request_attempt", fail)
            client = DrawingClient(LocalAPI(plugin), poll_interval=0.001)
            result = await client.generate("cat", wait_seconds=5)
            assert result.status == "unconfirmed" and result.error.code == "UPSTREAM_UNCONFIRMED"
            assert not result.error.retry_submit
            assert (await plugin.drawpic_task(result.task_id))["status"] == "failed"  # v1 保持原终态。

            async def block(**kwargs):
                await asyncio.Event().wait()

            monkeypatch.setattr(service, "_run_image_request_attempt", block)
            handles = [await client.submit("cat", request_id=f"concurrent-id-{index}") for index in range(4)]
            with pytest.raises(DrawingError) as full:
                await client.submit("fifth")
            assert full.value.code == "CONCURRENCY_LIMIT" and full.value.retry_submit
            cancelled = await client.cancel(handles[0].task_id)
            assert cancelled["status"] == "cancelled" and cancelled["upstream_cancelled"] is None
            assert (await plugin.drawpic_task(handles[0].task_id))["status"] == "failed"
            again = await client.cancel(handles[0].task_id)
            assert not again["cancel_requested"] and again["status"] == "cancelled"
            listing = await plugin.drawpic_tasks_v2(status="cancelled")
            assert listing["total"] == 1 and "thumbnail" not in listing["items"][0]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_failed_persistence_does_not_execute_or_leave_phantom_dedup(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            service, generated = plugin._require_draw_service(), []

            async def generate(**kwargs):
                generated.append(kwargs)
                return [image_bytes()]

            monkeypatch.setattr(service, "_run_image_request_attempt", generate)
            store_module = module("infrastructure.storage.tasks")
            with monkeypatch.context() as patch:

                def fail(*args):
                    raise OSError("simulated disk failure")

                patch.setattr(store_module, "write_json_atomically", fail)
                with pytest.raises(OSError):
                    await plugin.drawpic_submit("cat", request_id="disk-failure-id")
                assert not generated and not service.background_tasks
                assert plugin._task_store.find_request("disk-failure-id") is None
            await plugin.drawpic_submit("cat", request_id="disk-failure-id")
            await asyncio.gather(*tuple(service.background_tasks))
            assert len(generated) == 1
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_idempotency_is_loaded_from_task_file_after_restart(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()

        async def generate(**kwargs):
            return [image_bytes()]

        monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
        first = await plugin.drawpic_submit("cat", request_id="restart-id-01")
        await asyncio.gather(*tuple(plugin._require_draw_service().background_tasks))
        metadata_path = plugin._workspace_service.tasks.metadata_path
        await plugin.on_unload()
        # 删除辅助元数据，主任务文件本身必须足以恢复 request_id 映射。
        metadata_path.unlink(missing_ok=True)
        restarted = make_plugin()
        await restarted.on_load()
        try:
            result = await restarted.drawpic_submit_v2("cat", request_id="restart-id-01")
            assert result["task_id"] == first["task_id"] and result["reused"]
            assert not restarted._require_draw_service().background_tasks
        finally:
            await restarted.on_unload()

    asyncio.run(run())


def test_client_copy_imports_without_plugin_or_sdk(tmp_path):
    source = Path(__file__).parents[1] / "clients/maimai_drawing_client"
    shutil.copytree(source, tmp_path / "maimai_drawing_client", ignore=shutil.ignore_patterns("__pycache__"))
    script = "import sys;sys.path.insert(0,'.');from maimai_drawing_client import DrawingClient;assert 'maibot_sdk' not in sys.modules;print(DrawingClient.__name__)"
    result = subprocess.run([sys.executable, "-I", "-c", script], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_cancellation_during_persistence_keeps_intent_and_does_not_execute(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            store = plugin._task_store
            original, persisted, release = store.create_task, Event(), Event()

            def slow_create(**kwargs):
                result = original(**kwargs)
                persisted.set()
                assert release.wait(5)
                return result

            monkeypatch.setattr(store, "create_task", slow_create)
            pending = asyncio.create_task(plugin.drawpic_submit("cat", request_id="cancel-admission-01"))
            assert await asyncio.to_thread(persisted.wait, 5)
            pending.cancel()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await pending
            saved = store.find_request("cancel-admission-01")
            assert saved["error"]["code"] == "SUBMISSION_INTERRUPTED"
            assert not plugin._require_draw_service().background_tasks
            reused = await plugin.drawpic_submit("cat", request_id="cancel-admission-01")
            assert reused == {"task_id": saved["task_id"], "reused": True}
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_restart_intent_is_unconfirmed_and_never_replayed(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        saved = plugin._task_store.create_task(
            session_key="",
            stream_id="",
            task_type="draw",
            prompt="",
            model="sample-image",
            provider="openai",
            message="admitted",
            submission={"request_id": "orphaned-intent-01", "signature": "saved", "origin": "plugin"},
        )
        await plugin.on_unload()
        restarted = make_plugin()
        await restarted.on_load()
        try:
            state = await restarted.drawpic_task_v2(saved.task_id)
            assert state["status"] == "unconfirmed" and state["error"]["code"] == "RESTART_UNCONFIRMED"
            assert state["request_id"] == "orphaned-intent-01"
            assert not restarted._require_draw_service().background_tasks
        finally:
            await restarted.on_unload()

    asyncio.run(run())


def test_corrupt_task_file_is_preserved_instead_of_clearing_idempotency(tmp_path):
    store_class = module("infrastructure.storage.tasks").DrawTaskStore
    path = tmp_path / "tasks.json"
    for value in ["invalid json", "[]", '{"tasks": []}', '{"tasks":{"bad-id":{}}}']:
        path.write_text(value, encoding="utf-8")
        with pytest.raises(ValueError):
            store_class(path).load()
        assert path.read_text(encoding="utf-8") == value


@pytest.mark.parametrize("change", ["offset", "size", "done", "data", "next_offset"])
def test_client_rejects_invalid_chunk_protocol_without_looping(change):
    async def run():
        class API:
            async def call(self, *args, **kwargs):
                data = {
                    "error": None,
                    "size": 1,
                    "mime": "image/png",
                    "filename": "a.png",
                    "data": base64.b64encode(b"x").decode(),
                    "offset": 0,
                    "next_offset": 1,
                    "done": True,
                }
                data[change] = {"offset": 1, "size": 0, "done": False, "data": "!", "next_offset": 0}[change]
                return {"success": True, "result": data}

        with pytest.raises(DrawingTransportError):
            await DrawingClient(API()).read_image("abcdef123456")

    asyncio.run(run())
