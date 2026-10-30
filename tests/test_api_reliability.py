"""v2 与独立客户端的隔离回归：全部使用模拟生成器、发送器与 RPC。"""

import asyncio
from copy import deepcopy

import pytest

from test_drawing_client import DrawingClient, DrawingError, DrawingTransportError, LocalAPI, module
from test_workspace import image_bytes, make_plugin as make_plugin


TASK_ID = "abcdef123456"
REQUEST_ID = "reliability-request-01"


def snapshot(**changes):
    result = {
        "task_id": TASK_ID,
        "request_id": REQUEST_ID,
        "status": "completed",
        "images": [],
        "generation_completed": True,
        "results_readable": False,
        "delivery": {"requested": False, "status": "not_requested", "sent_count": 0},
        "retry_after_ms": 0,
        "error": None,
    }
    result.update(changes)
    return result


class ReplyAPI:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    async def call(self, api_name, **kwargs):
        self.calls.append((api_name, kwargs))
        return {"success": True, "result": deepcopy(self.reply)}


@pytest.mark.parametrize("limit", ["total", "single"])
def test_client_capacity_failure_preserves_accepted_result(make_plugin, monkeypatch, limit):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        generated = []
        try:
            async def generate(**kwargs):
                generated.append(kwargs)
                return [image_bytes()]

            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            api = LocalAPI(plugin)
            limits = {"max_result_bytes": 1} if limit == "total" else {"max_image_bytes": 1}
            client = DrawingClient(api, poll_interval=0.001, **limits)
            # 自动 request_id 也必须能取回，才能继续原任务而不是重画。
            result = await client.generate("cat", wait_seconds=5)
            assert result.status == "completed" and result.generation_completed and result.results_readable
            assert result.task_id and result.request_id and result.image_references and not result.images
            assert result.error.code == "RESULT_TOO_LARGE" and not result.error.retry_submit
            assert (result.error.task_id, result.error.request_id) == (result.task_id, result.request_id)
            if limit == "total":
                assert not any(name.endswith("drawpic_image_v2") for name, _, _ in api.calls)
            recovered = await client.wait(result.task_id, wait_seconds=1, read_images=False)
            assert recovered.status == "completed" and recovered.error is None
            assert recovered.request_id == result.request_id and recovered.image_references
            assert len(generated) == 1
            assert sum(name.endswith("drawpic_submit_v2") for name, _, _ in api.calls) == 1
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("sent_before_unknown", [0, 1])
def test_v2_delivery_unknown_overrides_confirmed_partial_count(make_plugin, monkeypatch, sent_before_unknown):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            service = plugin._require_draw_service()
            sends = []

            async def generate(**kwargs):
                return [image_bytes()] * (sent_before_unknown + 1)

            async def target(**kwargs):
                return "fixture-stream"

            async def send(*args, **kwargs):
                sends.append(args)
                return len(sends) <= sent_before_unknown

            monkeypatch.setattr(service, "_run_image_request_attempt", generate)
            monkeypatch.setattr(service.stream_service, "resolve_live_stream_id", target)
            monkeypatch.setattr(plugin.ctx.send, "image", send)
            receipt = await service.start_background_image_request(
                prompt="cat", stream_id="fixture-stream", resolved_model=service.resolve_model_name(),
                resolved_openai_mode="", provider_name="openai",
            )
            await asyncio.gather(*tuple(service.background_tasks))
            state = await plugin.drawpic_task_v2(receipt["task_id"])
            assert state["generation_completed"] and state["results_readable"]
            assert state["delivery"] == {
                "requested": True, "status": "unconfirmed", "sent_count": sent_before_unknown,
            }
            assert len(sends) == sent_before_unknown + 1
            expected_v1_status = "completed" if sent_before_unknown else "failed"
            assert (await plugin.drawpic_task(receipt["task_id"]))["status"] == expected_v1_status
            client_result = await DrawingClient(LocalAPI(plugin)).wait(
                receipt["task_id"], wait_seconds=0.5, read_images=False,
            )
            assert not client_result.wait_expired and client_result.status == expected_v1_status
            assert client_result.delivery["status"] == "unconfirmed"
            assert client_result.error.code == "DELIVERY_UNCONFIRMED"
            saved = module("infrastructure.storage.tasks").DrawTaskStore(plugin._task_store.path)
            saved.load()
            record = saved.get_task(receipt["task_id"])
            assert record.delivery_unconfirmed and record.sent_count == sent_before_unknown
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("cache_available", [True, False])
def test_all_approved_images_delivered_are_sent_even_if_cache_fails(make_plugin, monkeypatch, cache_available):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            service = plugin._require_draw_service()
            delivered = []

            async def generate(**kwargs):
                return [image_bytes(), image_bytes()]

            async def review(prompt, images, *, task_id):
                assert task_id
                return images[:1], ["second image rejected"]

            async def deliver(**kwargs):
                delivered.extend(kwargs["image_bytes_list"])
                return len(kwargs["image_bytes_list"])

            monkeypatch.setattr(service, "_run_image_request_attempt", generate)
            monkeypatch.setattr(service, "filter_reviewed_images", review)
            monkeypatch.setattr(service.stream_service, "send_generated_images_with_fallback", deliver)
            if not cache_available:
                plugin._result_store.retention.RESULT_MAX_BYTES = 1
            receipt = await service.start_background_image_request(
                prompt="cat", stream_id="fixture-stream", resolved_model=service.resolve_model_name(),
                resolved_openai_mode="", provider_name="openai",
            )
            await asyncio.gather(*tuple(service.background_tasks))
            state = await plugin.drawpic_task_v2(receipt["task_id"])
            assert state["status"] == "completed" and state["generated_count"] == 2
            assert state["result_count"] == int(cache_available) and len(delivered) == 1
            assert state["delivery"] == {"requested": True, "status": "sent", "sent_count": 1}
            saved = module("infrastructure.storage.tasks").DrawTaskStore(plugin._task_store.path)
            saved.load()
            assert saved.get_task(receipt["task_id"]).expected_delivery_count == 1
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_known_invalid_stream_is_rejected_before_admission(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            async def no_streams(**kwargs):
                return []

            monkeypatch.setattr(plugin.ctx.chat, "get_all_streams", no_streams)
            result = await plugin.drawpic_submit_v2(
                "cat", stream_id="no-such-stream", request_id=REQUEST_ID,
            )
            assert result["accepted"] is False and result["task_id"] is None
            assert result["status"] == "not_accepted" and result["request_id"] == REQUEST_ID
            assert result["error"]["code"] == "STREAM_UNAVAILABLE" and not result["error"]["retry_submit"]
            with pytest.raises(DrawingError) as raised:
                await DrawingClient(LocalAPI(plugin)).generate(
                    "cat", stream_id="no-such-stream", request_id=REQUEST_ID, wait_seconds=1,
                )
            assert raised.value.code == "STREAM_UNAVAILABLE" and raised.value.request_id == REQUEST_ID
            assert not plugin._task_store.get_task_count()
            assert not plugin._require_draw_service().background_tasks
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("changes", [
    {"status": None}, {"status": []}, {"generation_completed": 1}, {"results_readable": "yes"},
    {"retry_after_ms": -1}, {"retry_after_ms": True}, {"images": None}, {"images": [None]},
    {"images": [{"index": 0, "size": True}]}, {"images": [{"index": True, "size": 1}]},
    {"images": [{"index": 0, "size": 1}, {"index": 0, "size": 1}]},
    {"task_id": "another-task"}, {"delivery": {}}, {"delivery": {"status": []}},
    {"error": {}}, {"error": {"code": "FAILED", "message": 1}},
    {"error": {"code": "FAILED", "message": "failure", "retry_query": "false"}},
])
def test_malformed_task_reply_is_transport_error_with_handle(changes):
    async def run():
        with pytest.raises(DrawingTransportError) as raised:
            await DrawingClient(ReplyAPI(snapshot(**changes))).task(TASK_ID)
        assert raised.value.task_id == TASK_ID

    asyncio.run(run())


def test_incomplete_task_response_retries_only_queries_within_budget():
    async def run():
        api = ReplyAPI({"task_id": TASK_ID})
        result = await DrawingClient(api, poll_interval=0.001).wait(
            TASK_ID, request_id=REQUEST_ID, wait_seconds=0.02,
        )
        assert result.wait_expired and (result.task_id, result.request_id) == (TASK_ID, REQUEST_ID)
        assert api.calls and all(name.endswith("drawpic_task_v2") for name, _ in api.calls)

    asyncio.run(run())


@pytest.mark.parametrize("error", [{}, {"code": "FAILED"}, {"code": 1, "message": "bad"}, []])
def test_malformed_rejection_is_submission_unknown_without_raw_keyerror(error):
    async def run():
        api = ReplyAPI({"accepted": False, "error": error})
        result = await DrawingClient(api).generate("cat", request_id=REQUEST_ID)
        assert result.status == "submission_unknown" and result.error.code == "SUBMISSION_UNKNOWN"
        assert result.request_id == result.error.request_id == REQUEST_ID and len(api.calls) == 1

    asyncio.run(run())


def test_incomplete_accepted_receipt_keeps_known_task_id():
    async def run():
        api = ReplyAPI({"accepted": True, "task_id": TASK_ID})
        handle = await DrawingClient(api).submit("cat", request_id=REQUEST_ID)
        assert (handle.task_id, handle.request_id) == (TASK_ID, REQUEST_ID)
        assert (handle.error.task_id, handle.error.request_id) == (TASK_ID, REQUEST_ID)
        assert handle.error.code == "SUBMISSION_UNKNOWN" and len(api.calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize("status", ["completed", "failed", "rejected", "cancelled", "unconfirmed"])
def test_legitimate_terminal_snapshots_are_not_rejected(status):
    async def run():
        error = None if status == "completed" else {
            "code": "EXAMPLE_ERROR", "message": "", "retry_submit": False, "retry_query": False,
        }
        api = ReplyAPI(snapshot(status=status, error=error))
        result = await DrawingClient(api).wait(TASK_ID, wait_seconds=0.1)
        assert result.status == status and not result.wait_expired
        assert result.request_id == REQUEST_ID and len(api.calls) == 1
        if error:
            assert (result.error.task_id, result.error.request_id) == (TASK_ID, REQUEST_ID)

    asyncio.run(run())


def test_query_business_error_keeps_wait_request_id():
    async def run():
        api = ReplyAPI({"task_id": None, "error": {"code": "TASK_NOT_FOUND", "message": "expired"}})
        with pytest.raises(DrawingError) as raised:
            await DrawingClient(api).wait(TASK_ID, request_id=REQUEST_ID)
        assert (raised.value.task_id, raised.value.request_id) == (TASK_ID, REQUEST_ID)

    asyncio.run(run())


def test_image_error_retains_server_and_client_handles(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            async def generate(**kwargs):
                return [image_bytes()]

            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generate)
            client = DrawingClient(LocalAPI(plugin), poll_interval=0.001)
            result = await client.generate("cat", request_id=REQUEST_ID, read_images=False, wait_seconds=5)
            error = await plugin.drawpic_image_v2(result.task_id, index=-1)
            assert (error["task_id"], error["request_id"]) == (result.task_id, REQUEST_ID)
            assert error["error"]["code"] == "INVALID_REQUEST"
            with pytest.raises(DrawingError) as raised:
                await client.read_image(result.task_id, index=-1)
            assert (raised.value.task_id, raised.value.request_id) == (result.task_id, REQUEST_ID)
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("expected,status", [(2, "partial"), (1, "sent"), (0, "unconfirmed")])
def test_delivery_uses_approved_count_and_treats_legacy_counts_conservatively(make_plugin, expected, status):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            record = plugin._task_store.create_task(
                session_key="", stream_id="fixture-stream", task_type="draw", prompt="",
                model="sample-image", provider="openai", message="fixture",
            )
            plugin._task_store.update_task(
                record.task_id, status="completed", generated_count=3, sent_count=1,
                expected_delivery_count=expected, message="fixture completed",
            )
            state = await plugin.drawpic_task_v2(record.task_id)
            assert state["delivery"] == {"requested": True, "status": status, "sent_count": 1}
            assert state["generation_completed"] and not state["results_readable"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("reply", [{"error": {}}, {"error": {"code": "INVALID_REQUEST"}}])
def test_malformed_image_error_is_transport_error(reply):
    async def run():
        with pytest.raises(DrawingTransportError) as raised:
            await DrawingClient(ReplyAPI(reply)).read_image(TASK_ID)
        assert raised.value.task_id == TASK_ID

    asyncio.run(run())


def test_image_reference_size_mismatch_is_unavailable_with_handles(monkeypatch):
    async def run():
        client = DrawingClient(ReplyAPI(snapshot(
            results_readable=True, images=[{"index": 0, "size": 1}],
        )), max_result_bytes=1)

        async def wrong_image(*args):
            return b"larger-than-the-reference"

        monkeypatch.setattr(client, "read_image", wrong_image)
        result = await client.wait(TASK_ID, wait_seconds=0.5)
        assert result.status == "completed" and result.generation_completed and not result.images
        assert result.error.code == "RESULT_UNAVAILABLE" and not result.error.retry_submit
        assert (result.error.task_id, result.error.request_id) == (TASK_ID, REQUEST_ID)

    asyncio.run(run())
