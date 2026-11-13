"""Lifecycle and settlement regressions, using only temporary storage and mocks."""

import asyncio
import importlib
import json
from threading import Event

import pytest

from test_workspace import _PACKAGE, image_bytes, make_plugin


def module(name):
    return importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.{name}")


async def configured_plugin(make_plugin, monkeypatch):
    plugin = make_plugin()
    config = plugin.get_plugin_config_data()
    config["general"].update(private_quota_enabled=True, private_quota_period="daily", private_default_quota=1)
    plugin.set_plugin_config(config)
    await plugin.on_load()

    async def context(**kwargs):
        return {"stream_id": "mock-stream", "user_id": "12345678", "group_id": "", "platform": "qq"}

    async def notice(**kwargs):
        return None

    async def streams(**kwargs):
        return {"success": True, "streams": [await context()]}

    monkeypatch.setattr(plugin._require_stream_service(), "resolve_live_stream_context", context)
    monkeypatch.setattr(plugin.ctx.chat, "get_all_streams", streams)
    monkeypatch.setattr(plugin, "_send_draw_failure_notice", notice)
    return plugin


def remaining(plugin):
    return plugin._usage_store.get_remaining("qq:user:12345678", period="daily", default_quota=1)


def block_stage(plugin, service, monkeypatch, stage):
    entered, release = Event(), Event()
    if stage == "persist":
        create = plugin._task_store.create_task

        def persist(**kwargs):
            record = create(**kwargs)
            entered.set()
            assert release.wait(5)
            return record

        monkeypatch.setattr(plugin._task_store, "create_task", persist)
    else:
        async def block(*args, **kwargs):
            entered.set()
            await asyncio.to_thread(release.wait, 5)
            if stage == "stream":
                return {"stream_id": "mock-stream", "user_id": "12345678", "group_id": "", "platform": "qq"}

        if stage == "stream":
            monkeypatch.setattr(service.stream_service, "resolve_live_stream_context", block)
        else:
            monkeypatch.setattr(service, "review_prompt_or_raise", block)
    return entered, release


@pytest.mark.parametrize("stage", ["stream", "review", "persist"])
def test_refresh_preserves_submitting_service_for_cancel(make_plugin, monkeypatch, stage):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        old = plugin._require_draw_service()
        entered, release = block_stage(plugin, old, monkeypatch, stage)
        generating = asyncio.Event()

        async def generate(**kwargs):
            generating.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(old, "_run_image_request_attempt", generate)
        incoming = asyncio.create_task(plugin._start_background_image_request(prompt="cat", stream_id="mock-stream"))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            await plugin._workspace_service.refresh()
            assert plugin._draw_service is not old
            assert old in module("application.workspace.lifecycle").active_services(plugin)
            release.set()
            receipt = await incoming
            await asyncio.wait_for(generating.wait(), 5)
            await plugin._workspace_service.tasks.cancel(receipt["task_id"])
            assert not old.background_tasks
            assert remaining(plugin) == 1
            assert plugin._task_store.get_task(receipt["task_id"]).error["code"] == "CANCELLED"
        finally:
            release.set()
            if not incoming.done():
                incoming.cancel()
            await asyncio.gather(incoming, return_exceptions=True)
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("stage", ["stream", "review", "persist"])
def test_unload_drains_inflight_submission_before_return(make_plugin, monkeypatch, stage):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        old = plugin._require_draw_service()
        entered, release = block_stage(plugin, old, monkeypatch, stage)
        calls = []

        async def generate(**kwargs):
            calls.append(kwargs)
            return [image_bytes()]

        monkeypatch.setattr(old, "_run_image_request_attempt", generate)
        incoming = asyncio.create_task(plugin._start_background_image_request(prompt="cat", stream_id="mock-stream"))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            await plugin._workspace_service.refresh()
            closing = asyncio.create_task(plugin.on_unload())
            await asyncio.sleep(0)
            release.set()
            await closing
            assert incoming.done() and incoming.cancelled()
            assert not calls and not old.has_active_work and remaining(plugin) == 1
            with pytest.raises(RuntimeError, match="卸载"):
                await old.start_background_image_request(
                    prompt="late", stream_id="", resolved_model="sample-image", resolved_openai_mode="", provider_name="openai"
                )
            with pytest.raises(RuntimeError, match="卸载"):
                await plugin._start_background_image_request(prompt="late", stream_id="mock-stream")
            if stage == "persist":
                record = plugin._task_store.snapshot()[0]
                assert record["status"] == "failed"
                assert record["error"]["code"] == "SUBMISSION_INTERRUPTED"
        finally:
            release.set()
            await asyncio.gather(incoming, return_exceptions=True)
    asyncio.run(run())


def test_cancel_during_quota_io_waits_and_refunds_once(make_plugin, monkeypatch):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        entered, release = Event(), Event()
        original = plugin._reserve_draw_quota

        def reserve(*args, **kwargs):
            result = original(*args, **kwargs)
            entered.set()
            assert release.wait(5)
            return result

        monkeypatch.setattr(plugin, "_reserve_draw_quota", reserve)
        pending = asyncio.create_task(plugin._start_background_image_request(prompt="cat", stream_id="mock-stream"))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            pending.cancel()
            await asyncio.sleep(0)
            pending.cancel()
            await asyncio.sleep(0)
            assert not pending.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert remaining(plugin) == 1
            assert not plugin._task_store.snapshot()
            assert not plugin._require_draw_service().background_tasks
        finally:
            release.set()
            await plugin.on_unload()
    asyncio.run(run())


def test_cancel_before_first_execution_settles_quota(make_plugin, monkeypatch):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        service = plugin._require_draw_service()
        calls = []

        async def generate(**kwargs):
            calls.append(kwargs)
            return [image_bytes()]

        monkeypatch.setattr(service, "_run_image_request_attempt", generate)
        try:
            receipt = await plugin._start_background_image_request(prompt="cat", stream_id="mock-stream")
            await service.cancel_background_tasks()
            await service.cancel_background_tasks()
            record = plugin._task_store.get_task(receipt["task_id"])
            assert not calls and record.status == "failed" and record.error["code"] == "CANCELLED"
            assert remaining(plugin) == 1 and not service.has_active_work
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_task_write_failure_cannot_skip_refund(make_plugin, monkeypatch):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        store, service = plugin._task_store, plugin._require_draw_service()
        original_create, original_save = store.create_task, store.save
        calls = []

        async def generate(**kwargs):
            calls.append(kwargs)
            return [image_bytes()]

        def fail_save():
            raise OSError("mock disk failure")

        def create_then_fail(**kwargs):
            record = original_create(**kwargs)
            monkeypatch.setattr(store, "save", fail_save)
            return record

        monkeypatch.setattr(service, "_run_image_request_attempt", generate)
        monkeypatch.setattr(store, "create_task", create_then_fail)
        try:
            receipt = await plugin._start_background_image_request(prompt="cat", stream_id="mock-stream")
            await asyncio.gather(*tuple(service.background_tasks))
            assert remaining(plugin) == 1 and not calls
            assert store.get_task(receipt["task_id"]).status == "failed"
            assert store.get_task(receipt["task_id"]).persistence_pending
            assert json.loads(store.path.read_text(encoding="utf-8"))["tasks"][receipt["task_id"]]["status"] == "pending"
        finally:
            monkeypatch.setattr(store, "save", original_save)
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("mutation", [
    lambda value: value.pop("tasks"),
    lambda value: value.update(tasks=[]),
    lambda value: value.update(latest_task_id_by_session=[]),
    lambda value: next(iter(value["tasks"].values())).update(submission=[]),
    lambda value: next(iter(value["tasks"].values())).update(submission={"request_id": "request"}),
    lambda value: next(iter(value["tasks"].values())).update(submission={"request_id": 12, "signature": "hash"}),
    lambda value: next(iter(value["tasks"].values())).update(sent_count=-1),
    lambda value: next(iter(value["tasks"].values())).update(delivery_unconfirmed="false"),
    lambda value: next(iter(value["tasks"].values())).update(status=[]),
    lambda value: next(iter(value["tasks"].values())).update(task_type=[]),
    lambda value: next(iter(value["tasks"].values())).update(created_at=20261015),
])
def test_corrupt_task_schema_preserves_bytes_and_current_records(tmp_path, mutation):
    cls = module("infrastructure.storage.tasks").DrawTaskStore
    store = cls(tmp_path / "tasks.json")
    record = store.create_task(session_key="session", stream_id="", task_type="draw", prompt="", model="model", provider="test", message="")
    value = json.loads(store.path.read_text(encoding="utf-8"))
    mutation(value)
    store.path.write_text(json.dumps(value))
    original = store.path.read_bytes()
    with pytest.raises(ValueError, match="未清空幂等记录"):
        store.load()
    assert store.path.read_bytes() == original
    assert store.get_task(record.task_id) is record
    with pytest.raises(ValueError, match="拒绝覆盖"):
        store.save()
    with pytest.raises(ValueError, match="拒绝覆盖"):
        store.create_task(session_key="new", stream_id="", task_type="draw", prompt="", model="model", provider="test", message="")
    assert store.path.read_bytes() == original
    assert store.get_task_count() == 1


def test_legacy_task_schema_and_new_delivery_fields_roundtrip(tmp_path):
    cls = module("infrastructure.storage.tasks").DrawTaskStore
    store = cls(tmp_path / "tasks.json")
    record = store.create_task(session_key="session", stream_id="", task_type="draw", prompt="", model="model", provider="test", message="")
    store.update_task(record.task_id, status="failed", message="unknown", expected_delivery_count=2, delivery_unconfirmed=True, sent_count=1)
    restarted = cls(store.path)
    restarted.load()
    current = restarted.get_task(record.task_id)
    assert current.expected_delivery_count == 2 and current.delivery_unconfirmed and current.sent_count == 1
    payload = json.loads(store.path.read_text(encoding="utf-8"))
    for key in ("submission", "expected_delivery_count", "delivery_unconfirmed", "generated_count", "error"):
        payload["tasks"][record.task_id].pop(key)
    store.path.write_text(json.dumps(payload))
    restarted.load()
    current = restarted.get_task(record.task_id)
    assert current.expected_delivery_count == 0 and not current.delivery_unconfirmed and current.submission == {}


def test_success_commits_quota_and_clears_reservation(make_plugin, monkeypatch):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        service = plugin._require_draw_service()

        async def generate(**kwargs):
            return [image_bytes()]

        async def send(**kwargs):
            return len(kwargs["image_bytes_list"])

        monkeypatch.setattr(service, "_run_image_request_attempt", generate)
        monkeypatch.setattr(service.stream_service, "send_generated_images_with_fallback", send)
        try:
            receipt = await plugin._start_background_image_request(prompt="cat", stream_id="mock-stream")
            await asyncio.gather(*tuple(service.background_tasks))
            assert plugin._task_store.get_task(receipt["task_id"]).status == "completed"
            assert remaining(plugin) == 0
            saved = json.loads(plugin._usage_store.path.read_text(encoding="utf-8"))["qq:user:12345678"]
            assert saved["used"] == 1 and saved["reservation_ids"] == []
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_cancel_during_delivery_preserves_unknown_outcome(make_plugin, monkeypatch):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        service = plugin._require_draw_service()
        sending = asyncio.Event()

        async def generate(**kwargs):
            return [image_bytes()]

        async def send(**kwargs):
            sending.set()
            await asyncio.Event().wait()

        monkeypatch.setattr(service, "_run_image_request_attempt", generate)
        monkeypatch.setattr(service.stream_service, "send_generated_images_with_fallback", send)
        try:
            receipt = await plugin._start_background_image_request(prompt="cat", stream_id="mock-stream")
            await asyncio.wait_for(sending.wait(), 5)
            await plugin._workspace_service.tasks.cancel(receipt["task_id"])
            record = plugin._task_store.get_task(receipt["task_id"])
            assert record.status == "failed" and record.delivery_unconfirmed
            assert record.generated_count == 1 and record.expected_delivery_count == 1
            assert remaining(plugin) == 1
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_duplicate_request_keys_block_loading_until_original_is_restored(tmp_path):
    cls = module("infrastructure.storage.tasks").DrawTaskStore
    store = cls(tmp_path / "tasks.json")
    record = store.create_task(
        session_key="session", stream_id="", task_type="draw", prompt="", model="model", provider="test", message="",
        submission={"request_id": "stable-key", "signature": "hash", "origin": "plugin"},
    )
    original = store.path.read_bytes()
    payload = json.loads(original)
    duplicate_id = "f" * 12 if record.task_id != "f" * 12 else "a" * 12
    payload["tasks"][duplicate_id] = {**payload["tasks"][record.task_id], "task_id": duplicate_id}
    store.path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="请求键重复"):
        store.load()
    store.path.write_bytes(original)
    store.load()
    store.save()
    assert store.find_request("stable-key")["task_id"] == record.task_id


@pytest.mark.parametrize("success", [False, True])
def test_transient_quota_settlement_io_retries_same_reservation(make_plugin, monkeypatch, success):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        service, store = plugin._require_draw_service(), plugin._usage_store
        original_save = store.save
        writes, provider_calls = [], []

        def fail_once():
            writes.append(1)
            if len(writes) == 1:
                raise OSError("transient settlement write failure")
            original_save()

        async def generate(**kwargs):
            provider_calls.append(1)
            monkeypatch.setattr(store, "save", fail_once)
            if not success:
                raise module("domain.errors").ProviderError("mock provider rejection")
            return [image_bytes()]

        async def send(**kwargs):
            return len(kwargs["image_bytes_list"])

        monkeypatch.setattr(service, "_run_image_request_attempt", generate)
        monkeypatch.setattr(service.stream_service, "send_generated_images_with_fallback", send)
        try:
            receipt = await plugin._start_background_image_request(prompt="cat", stream_id="mock-stream")
            await asyncio.gather(*tuple(service.background_tasks))
            assert plugin._task_store.get_task(receipt["task_id"]).status == ("completed" if success else "failed")
            assert len(provider_calls) == 1 and len(writes) == 2
            assert remaining(plugin) == (0 if success else 1)
            assert json.loads(store.path.read_text(encoding="utf-8"))["qq:user:12345678"]["reservation_ids"] == []
        finally:
            monkeypatch.setattr(store, "save", original_save)
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("version", [1, 2])
def test_cancel_during_completion_preserves_actual_success(make_plugin, monkeypatch, version):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        service = plugin._require_draw_service()
        entered, release = Event(), Event()
        original_update = plugin._task_store.update_task
        sends, provider_calls = [], []

        async def generate(**kwargs):
            provider_calls.append(1)
            return [image_bytes()]

        async def send(**kwargs):
            sends.append(1)
            return 1

        def update(*args, **kwargs):
            if kwargs.get("status") == "completed":
                entered.set()
                assert release.wait(5)
            return original_update(*args, **kwargs)

        monkeypatch.setattr(service, "_run_image_request_attempt", generate)
        monkeypatch.setattr(service.stream_service, "send_generated_images_with_fallback", send)
        monkeypatch.setattr(plugin._task_store, "update_task", update)
        try:
            receipt = await plugin.drawpic_submit_v2("cat", stream_id="mock-stream", request_id="cancel-completed")
            assert await asyncio.to_thread(entered.wait, 5)
            cancel = plugin.drawpic_cancel_v2 if version == 2 else plugin.drawpic_cancel
            cancelling = asyncio.create_task(cancel(receipt["task_id"]))
            await asyncio.sleep(0.02)
            assert not cancelling.done()
            release.set()
            if version == 2:
                result = await cancelling
                assert result["status"] == "completed" and result["cancel_requested"]
                assert result["error"] is None and result["delivery"]["status"] == "sent"
            else:
                with pytest.raises(ValueError, match="已经结束"):
                    await cancelling
            assert plugin._task_store.get_task(receipt["task_id"]).status == "completed"
            assert len(sends) == len(provider_calls) == 1 and remaining(plugin) == 0
            assert plugin._usage_store.records["qq:user:12345678"].reservation_ids == []
        finally:
            release.set()
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("stage", ["initial", "attempt", "generated", "failed"])
def test_cancellation_waits_for_owned_status_io(make_plugin, monkeypatch, stage):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        service, store = plugin._require_draw_service(), plugin._task_store
        entered, release = Event(), Event()
        original_update = store.update_task
        provider_calls = []

        async def generate(**kwargs):
            provider_calls.append(1)
            if stage == "failed":
                raise module("domain.errors").ProviderError("mock provider rejection")
            return [image_bytes()]

        def update(*args, **kwargs):
            message = kwargs.get("message", "")
            block = (
                stage == "initial" and message == "图片正在生成中"
                or stage == "attempt" and message.startswith("首选模型 ")
                or stage == "generated" and message == "图片已生成，正在审核结果"
                or stage == "failed" and kwargs.get("status") == "failed"
            )
            if block and not entered.is_set():
                entered.set()
                assert release.wait(5)
            return original_update(*args, **kwargs)

        monkeypatch.setattr(service, "_run_image_request_attempt", generate)
        monkeypatch.setattr(store, "update_task", update)
        try:
            receipt = await plugin.drawpic_submit_v2("cat", stream_id="mock-stream", request_id="cancel-status-io")
            assert await asyncio.to_thread(entered.wait, 5)
            cancelling = asyncio.create_task(plugin.drawpic_cancel_v2(receipt["task_id"]))
            await asyncio.sleep(0.02)
            assert not cancelling.done()
            release.set()
            result = await cancelling
            record = store.get_task(receipt["task_id"])
            assert record.status == "failed" and not service.has_active_work
            assert result["status"] == ("failed" if stage == "failed" else "cancelled")
            assert record.error["code"] == ("UPSTREAM_REJECTED" if stage == "failed" else "CANCELLED")
            assert len(provider_calls) == (1 if stage in {"generated", "failed"} else 0)
            assert remaining(plugin) == 1
        finally:
            release.set()
            await plugin.on_unload()
    asyncio.run(run())


def test_late_progress_cannot_overwrite_terminal_record(tmp_path):
    store = module("infrastructure.storage.tasks").DrawTaskStore(tmp_path / "tasks.json")
    record = store.create_task(session_key="session", stream_id="", task_type="draw", prompt="", model="model", provider="test", message="")
    terminal = store.update_task(record.task_id, status="failed", message="cancelled", error={"code": "CANCELLED", "message": "cancelled"})
    original = store.path.read_bytes()
    assert store.update_task(record.task_id, status="running", message="late progress") is terminal
    assert store.path.read_bytes() == original and store.get_task(record.task_id).status == "failed"
