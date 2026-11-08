"""生成图历史同步的 SDK 参数、投递边界和诊断；不连接真实平台。"""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
import asyncio
import base64
import json
import logging

import pytest

from test_routing_review_fixes import module, set_settings
from test_workspace import image_bytes, make_plugin as make_plugin


ChatStreamService = module("application.chat.service").ChatStreamService
Unconfirmed = module("application.chat.types").ImageDeliveryUnconfirmedError


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("outcome", [True, False, None, {"sent": False}, TimeoutError("adapter timeout")])
def test_batch_sync_is_requested_once_per_image_and_unknown_delivery_stops(
    caplog: Any, enabled: bool, outcome: Any,
) -> None:
    async def run() -> None:
        sender = AsyncMock(side_effect=[True, outcome, True])
        service = ChatStreamService(SimpleNamespace(
            send=SimpleNamespace(image=sender), logger=logging.getLogger("drawpic.history_sync"),
        ))
        service.resolve_live_stream_id = AsyncMock(side_effect=["actual-session", "other-session"])
        with caplog.at_level(logging.DEBUG):
            if outcome is True:
                assert await service.send_generated_images_with_fallback(
                    "requested-session", [b"first", b"second", b"third"],
                    task_id="history-task", task_type="draw", provider="openai", model="sample-image",
                    sync_to_maisaka_history=enabled,
                ) == 3
            else:
                with pytest.raises(Unconfirmed) as raised:
                    await service.send_generated_images_with_fallback(
                        "requested-session", [b"first", b"second", b"third"],
                        task_id="history-task", sync_to_maisaka_history=enabled,
                    )
                assert raised.value.sent_count == 1
        expected_images = [b"first", b"second", b"third"] if outcome is True else [b"first", b"second"]
        assert sender.await_count == len(expected_images)
        assert service.resolve_live_stream_id.await_count == 1
        for call, raw in zip(sender.await_args_list, expected_images):
            assert call.args == (base64.b64encode(raw).decode("ascii"), "actual-session")
            assert call.kwargs == ({"sync_to_maisaka_history": True} if enabled else {})
        assert f"history_sync_requested={enabled}" in caplog.text
        assert "task_id=history-task" in caplog.text
        assert "历史同步成功" not in caplog.text
        if outcome is True:
            assert "发送绘图结果成功" in caplog.text
        else:
            assert "发送绘图结果成功" not in caplog.text
            assert "投递结果未知" in caplog.text or "发送图片异常" in caplog.text
        for raw in expected_images:
            assert base64.b64encode(raw).decode("ascii") not in caplog.text

    asyncio.run(run())


def test_reply_cards_and_unavailable_sessions_do_not_request_history_sync() -> None:
    async def run() -> None:
        sender = AsyncMock(return_value=True)
        service = ChatStreamService(SimpleNamespace(
            send=SimpleNamespace(image=sender), logger=logging.getLogger("drawpic.history_sync"),
        ))
        service.resolve_live_stream_id = AsyncMock(return_value="actual-session")
        assert await service.send_image_bytes_with_fallback(b"command card", "requested-session")
        assert sender.await_args.kwargs == {}
        sender.reset_mock()
        service.resolve_live_stream_id.return_value = ""
        with pytest.raises(module("application.chat.types").ChatStreamUnavailableError):
            await service.send_generated_images_with_fallback(
                "missing-session", [b"generated"], sync_to_maisaka_history=True,
            )
        sender.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("enabled", [False, True])
def test_cancelled_delivery_is_not_repeated(enabled: bool) -> None:
    async def run() -> None:
        sender = AsyncMock(side_effect=[True, asyncio.CancelledError()])
        service = ChatStreamService(SimpleNamespace(
            send=SimpleNamespace(image=sender), logger=logging.getLogger("drawpic.history_sync"),
        ))
        with pytest.raises(asyncio.CancelledError):
            await service.send_generated_images(
                "actual-session", [b"first", b"second", b"third"], sync_to_maisaka_history=enabled,
            )
        assert sender.await_count == 2

    asyncio.run(run())


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("stream_id", ["", "actual-session"])
@pytest.mark.parametrize("task_type", ["draw", "edit_image"])
def test_workspace_setting_controls_real_sdk_submission(
    make_plugin: Any, monkeypatch: Any, caplog: Any, enabled: bool, stream_id: str, task_type: str,
) -> None:
    async def run() -> None:
        plugin = make_plugin()
        await plugin.on_load()
        try:
            assert plugin.config.general.sync_generated_images_to_history is False
            with caplog.at_level(logging.DEBUG):
                await set_settings(plugin, sync_generated_images_to_history=enabled)
                service = plugin._require_draw_service()
                requests = []

                async def capability(name: str, **kwargs: Any) -> bool:
                    assert name == "send.image"
                    requests.append(kwargs)
                    return True

                async def generate(**kwargs: Any):
                    return [image_bytes(), image_bytes()]

                monkeypatch.setattr(plugin.ctx, "call_capability", capability)
                monkeypatch.setattr(plugin.ctx.chat, "get_all_streams", AsyncMock(return_value={
                    "success": True, "streams": [{"session_id": "actual-session", "platform": "qq", "user_id": "user"}],
                }))
                monkeypatch.setattr(service, "_run_image_request_attempt", generate)
                receipt = await plugin.drawpic_submit(
                    "a cat", stream_id=stream_id, task_type=task_type,
                    source_images=[base64.b64encode(image_bytes()).decode("ascii")] if task_type == "edit_image" else None,
                )
                await asyncio.gather(*tuple(service.background_tasks))
                result = await plugin.drawpic_task_v2(receipt["task_id"])
            assert result["status"] == "completed", result["message"]
            assert len(requests) == (2 if stream_id else 0)
            assert result["delivery"]["status"] == ("sent" if stream_id else "not_requested")
            for request in requests:
                assert request.get("sync_to_maisaka_history", False) is enabled
                assert request["stream_id"] == stream_id
            if not stream_id and enabled:
                assert "生成结果未投递，跳过会话历史同步" in caplog.text
            if enabled:
                assert "生成图片历史同步设置已保存" in caplog.text
            assert "历史同步成功" not in caplog.text
            assert base64.b64encode(image_bytes()).decode("ascii") not in caplog.text
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_unknown_delivery_keeps_task_unconfirmed_and_redacts_diagnostics(
    make_plugin: Any, monkeypatch: Any, caplog: Any,
) -> None:
    async def run() -> None:
        plugin = make_plugin()
        await plugin.on_load()
        try:
            await set_settings(plugin, sync_generated_images_to_history=True)
            service = plugin._require_draw_service()
            sender = AsyncMock(side_effect=[True, TimeoutError(
                "secret-fixture-key https://example.invalid/image?signature=PRIVATE_SIGNATURE "
                + "data:image/png;base64," + base64.b64encode(image_bytes()).decode("ascii")
            )])
            generator = AsyncMock(return_value=[image_bytes()] * 3)
            monkeypatch.setattr(plugin.ctx.send, "image", sender)
            monkeypatch.setattr(service, "_run_image_request_attempt", generator)
            monkeypatch.setattr(service.stream_service, "resolve_live_stream_id", AsyncMock(return_value="actual-session"))
            with caplog.at_level(logging.DEBUG):
                receipt = await service.start_background_image_request(
                    prompt="cat", stream_id="actual-session", resolved_model=service.resolve_model_name(),
                    resolved_openai_mode="", provider_name="openai",
                )
                await asyncio.gather(*tuple(service.background_tasks))
                result = await plugin.drawpic_task_v2(receipt["task_id"])
            assert result["generation_completed"]
            assert result["error"]["code"] == "DELIVERY_UNCONFIRMED"
            assert result["delivery"] == {"requested": True, "status": "unconfirmed", "sent_count": 1}
            assert sender.await_count == 2 and generator.await_count == 1
            assert all(call.kwargs == {"sync_to_maisaka_history": True} for call in sender.await_args_list)
            for private in ("secret-fixture-key", "PRIVATE_SIGNATURE", base64.b64encode(image_bytes()).decode("ascii")):
                assert private not in caplog.text
                assert private not in json.dumps(result)
            assert "历史同步成功" not in caplog.text
        finally:
            await plugin.on_unload()

    asyncio.run(run())
