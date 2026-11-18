"""命令设置落盘不占用事件循环，强制 NAI 文生图不丢弃源图。"""

from importlib import import_module
from threading import get_ident
from unittest.mock import AsyncMock
from test_api_settings import provide_streams
from test_workspace import _PACKAGE, image_bytes, make_plugin as make_plugin
import asyncio
import base64
import pytest


@pytest.mark.parametrize("command,quota", [
    ("兼容模式 images_api", False), ("nai 模式 furry", False), ("nai 画师 artist:fixture", False),
    ("设置 群聊 12345 10", True),
])
def test_command_settings_persist_off_event_loop(make_plugin, monkeypatch, command, quota):
    async def run():
        plugin = make_plugin()
        values = plugin.get_plugin_config_data()
        values["general"]["permission_enabled"] = False
        plugin.set_plugin_config(values)
        await plugin.on_load()
        try:
            provide_streams(plugin, monkeypatch)
            monkeypatch.setattr(plugin, "_send_command_reply", AsyncMock(return_value=True))
            owner = plugin._usage_store if quota else plugin
            method = "adjust_remaining" if quota else "_set_session_preference"
            original, loop_thread, writes = getattr(owner, method), get_ident(), []

            def write(*args, **kwargs):
                assert get_ident() != loop_thread, "设置落盘不能阻塞事件循环"
                result = original(*args, **kwargs)
                writes.append(result)
                return result

            monkeypatch.setattr(owner, method, write)
            result = await plugin.handle_draw_command(
                stream_id="actual-stream", user_id="A" * 32, group_id="B" * 32, platform="qq",
                matched_groups={"content": command},
            )
            assert result[0] and len(writes) == 1
            if quota:
                assert writes[0] == 10
            else:
                expected_field = "openai_compatibility_mode" if command.startswith("兼容模式") else (
                    "novelai_mode" if "模式" in command else "novelai_artist_tags"
                )
                assert writes[0][expected_field] == command.rsplit(" ", 1)[1]
        finally:
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("invocation", ["tool", "文生图", "图生图", "风格 none", "nai 文生图"])
@pytest.mark.parametrize("stage", ["submit", "background"])
@pytest.mark.parametrize("notify", [False, True])
def test_failure_notification_setting_exempts_only_commands(make_plugin, monkeypatch, invocation, stage, notify):
    """工具失败受开关控制；各类命令在受理前和后台失败时都通知一次。"""
    async def run():
        plugin = make_plugin()
        values = plugin.get_plugin_config_data()
        values["general"].update(failure_reason_enabled=notify, command_reply_mode="文本")
        values["novelai"].update(api_key="fixture-nai-key", models=["nai-diffusion-4-5-full"])
        plugin.set_plugin_config(values)
        await plugin.on_load()
        try:
            provide_streams(plugin, monkeypatch)
            service = plugin._require_draw_service()
            send = AsyncMock(return_value=True)
            monkeypatch.setattr(plugin._require_stream_service(), "send_text_with_fallback", send)
            source_type = import_module(f"{_PACKAGE}.src.maimai_drawpic.interfaces.chat.message_images").SourceImageInput
            sources = [source_type(base64.b64encode(image_bytes()).decode("ascii"))] if invocation == "图生图" else []
            monkeypatch.setattr(plugin, "_collect_forced_command_source_images", AsyncMock(return_value=(sources, [], "")))
            monkeypatch.setattr(plugin, "_collect_optional_command_source_images", AsyncMock(return_value=([], [], "")))
            if stage == "submit":
                monkeypatch.setattr(plugin, "_start_background_image_request", AsyncMock(side_effect=ValueError("fixture failure")))
            else:
                monkeypatch.setattr(service, "_run_image_request_attempt", AsyncMock(side_effect=ValueError("fixture failure")))
            context = dict(stream_id="actual-stream", user_id="A" * 32, group_id="B" * 32, platform="qq")
            if invocation == "tool":
                result = await plugin.handle_draw(prompt="cat", **context)
                accepted = result["success"]
            else:
                result = await plugin.handle_draw_command(matched_groups={"content": f"{invocation} cat"}, **context)
                accepted = result[0]
            assert accepted == (stage == "background")
            if stage == "background":
                await asyncio.gather(*tuple(service.background_tasks))
                record = plugin._task_store.snapshot()[0]
                assert record["status"] == "failed" and "fixture failure" in record["message"]
            else:
                assert plugin._task_store.get_task_count() == 0
            assert send.await_count == int(invocation != "tool" or notify)
        finally:
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("has_source", [False, True])
def test_forced_novelai_draw_rejects_sources_before_admission(make_plugin, monkeypatch, has_source):
    async def run():
        plugin = make_plugin()
        values = plugin.get_plugin_config_data()
        values["novelai"].update(api_key="fixture-nai-key", models=["nai-diffusion-4-5-full"])
        plugin.set_plugin_config(values)
        await plugin.on_load()
        try:
            monkeypatch.setattr(plugin, "_collect_optional_command_source_images", AsyncMock(
                return_value=([image_bytes()] if has_source else [], [""] if has_source else [], "fixture-message")
            ))
            start = AsyncMock(return_value={"task_id": "abcdef123456"})
            notice = AsyncMock()
            monkeypatch.setattr(plugin, "_start_background_image_request", start)
            monkeypatch.setattr(plugin, "_send_draw_failure_notice", notice)
            result = await plugin._handle_novelai_command(
                rest_payload="文生图 一只猫", message={},
                session_preference={"model": "", "novelai_mode": "", "novelai_artist_tags": ""},
                stream_id="actual-stream", user_id="A" * 32, group_id="B" * 32, platform="qq",
            )
            if has_source:
                assert not result[0] and "不能附带或引用图片" in notice.call_args.kwargs["reason"]
                start.assert_not_awaited()
            else:
                assert result[0] and start.await_count == 1
                assert start.call_args.kwargs["source_image_bytes_list"] == []
            assert plugin._task_store.get_task_count() == 0
        finally:
            await plugin.on_unload()
    asyncio.run(run())
