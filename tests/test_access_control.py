"""联动开关和会话黑白名单的入口边界，不调用真实平台或发送聊天消息。"""

from contextlib import asynccontextmanager
from hashlib import sha256
from importlib import import_module
from inspect import Parameter, signature
from maibot_sdk.components import collect_components
from test_workspace import image_bytes, make_plugin as make_plugin
from unittest.mock import AsyncMock, Mock
import asyncio
import json
import pytest

access = import_module("drawpic_workspace_test.src.maimai_drawpic.application.access")
GeneralConfig = import_module("drawpic_workspace_test.src.maimai_drawpic.domain.configuration.common").GeneralConfig


def provide_streams(plugin, monkeypatch, *, group_id="123456", user_id="654321"):
    async def streams(platform="all_platforms"):
        return {"success": True, "streams": [{
            "session_id": "actual-stream", "platform": "qq", "group_id": group_id, "user_id": user_id,
        }]}
    monkeypatch.setattr(plugin.ctx.chat, "get_all_streams", streams)


@pytest.mark.parametrize("mode,entries,group,user,allowed", [
    ("blacklist", [], "123456", "654321", True),
    ("blacklist", ["123456"], "123456", "654321", False),
    ("blacklist", ["654321"], "123456", "654321", True),
    ("whitelist", [], "123456", "654321", False),
    ("whitelist", ["123456"], "123456", "654321", True),
    ("whitelist", ["654321"], "123456", "654321", False),
    ("blacklist", ["A" * 32], "", "A" * 32, False),
    ("whitelist", ["A" * 32], "", "A" * 32, True),
    ("whitelist", ["A" * 32], "", "a" * 32, False),
    ("whitelist", [], "", "", False),
])
def test_blacklist_whitelist_match_target_not_member_or_hash(mode, entries, group, user, allowed):
    config = GeneralConfig(
        group_access_mode=mode, private_access_mode=mode,
        group_access_ids=entries, private_access_ids=entries,
    )
    context = {"stream_id": "unrelated-hash", "group_id": group, "user_id": user, "platform": "qq"}
    if allowed:
        access.require_chat_access(config, context, Mock())
    else:
        with pytest.raises(access.ChatAccessDenied):
            access.require_chat_access(config, context, Mock())


def test_private_chat_is_independent_of_group_whitelist():
    config = GeneralConfig(group_access_mode="whitelist", group_access_ids=[])
    access.require_chat_access(config, {"stream_id": "private-hash", "user_id": "A" * 32}, Mock())


def test_switch_blocks_every_public_api_and_preserves_private_workspace(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            revision = plugin._platform_store.revision
            result = await plugin.workspace_settings_save(
                json.dumps({"general": {"integration_api_enabled": False}}), revision,
            )
            assert result["saved"] and not plugin.config.general.integration_api_enabled
            tested = []
            for declaration in collect_components(plugin):
                if not declaration["metadata"].get("public"):
                    continue
                name = declaration["name"]
                handler = getattr(plugin, name)
                values = {
                    key: {"prompt": "sample", "preference_json": "{}"}.get(key, "fixture")
                    for key, param in signature(handler).parameters.items()
                    if param.default is Parameter.empty
                }
                if name.endswith("_v2"):
                    response = await handler(**values)
                    assert response["error"]["code"] == "PERMISSION_DENIED", name
                    assert not response["error"]["retry_submit"], name
                    if name == "drawpic_submit_v2":
                        assert response["accepted"] is False and response["task_id"] is None
                else:
                    with pytest.raises(PermissionError, match="联动 API 已关闭"):
                        await handler(**values)
                tested.append(name)
            assert len(tested) == 16
            assert (await plugin.workspace_bootstrap())["settings"]["general"]["integration_api_enabled"] is False
            assert (await plugin.handle_draw_styles())["success"]
            result = await plugin.workspace_settings_save(
                json.dumps({"general": {"integration_api_enabled": True}}), plugin._platform_store.revision,
            )
            assert result["saved"] and (await plugin.drawpic_models())["models"]
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_blocked_real_group_stops_commands_tools_and_direct_submission(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            provide_streams(plugin, monkeypatch)
            plugin.config.general.group_access_ids = ["123456"]
            reserve = Mock(side_effect=AssertionError("blocked request must not reserve quota"))
            monkeypatch.setattr(plugin, "_reserve_draw_quota", reserve)
            for name, values in [
                ("handle_draw", {"prompt": "sample"}),
                ("handle_edit_image", {"prompt": "sample"}),
                ("handle_styled_draw", {"style": "default", "prompt": "sample"}),
                ("handle_draw_styles", {}),
                ("handle_draw_status", {}),
            ]:
                response = await getattr(plugin, name)(
                    **values, stream_id="actual-stream", group_id="999999", user_id="888888",
                )
                assert response["success"] is False and "黑名单" in response["message"], name
            command = await plugin.handle_draw_command(
                "actual-stream", matched_groups={"content": "模型"}, group_id="999999",
            )
            assert command[0] is False and "黑名单" in command[1]
            with pytest.raises(access.ChatAccessDenied):
                await plugin._start_background_image_request(prompt="sample", stream_id="actual-stream")
            reserve.assert_not_called()
            assert not plugin._task_store.snapshot()
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_workspace_and_api_cannot_submit_to_denied_chat_or_mutate_preferences(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            provide_streams(plugin, monkeypatch, group_id="", user_id="A" * 32)
            plugin.config.general.private_access_mode = "whitelist"
            plugin.config.general.private_access_ids = ["B" * 32]
            sources = Mock(side_effect=AssertionError("denied sources must not be processed"))
            monkeypatch.setattr(plugin._workspace().tasks, "_sources", sources)
            response = await plugin.drawpic_submit_v2(prompt="sample", stream_id="actual-stream")
            assert response["accepted"] is False and response["error"]["code"] == "PERMISSION_DENIED"
            preference = await plugin.drawpic_preferences_set_v2("actual-stream", '{"novelai_mode":"anime"}')
            assert preference["error"]["code"] == "PERMISSION_DENIED"
            with pytest.raises(PermissionError):
                await plugin.drawpic_submit(prompt="sample", stream_id="actual-stream")
            response = await plugin.workspace_submit(
                json.dumps({"prompt": "sample", "stream_id": "actual-stream"}),
            )
            assert "白名单" in response["__workspace_error__"]
            sources.assert_not_called()
            assert not plugin._require_session_store().preferences
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_unrestricted_replay_preserves_task_when_stream_disappears(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            async def streams(platform="all_platforms"):
                return {"success": True, "streams": []}
            monkeypatch.setattr(plugin.ctx.chat, "get_all_streams", streams)
            request_id = "retained-request-01"
            values = ["sample", "", "", "", "draw", "gone-stream", None, None]
            signature_value = sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()
            record = plugin._task_store.create_task(
                session_key="qq:group:123456", stream_id="gone-stream", task_type="draw",
                prompt="sample", model="sample-image", provider="openai", message="fixture",
                submission={"origin": "plugin", "request_id": request_id, "signature": signature_value},
            )
            plugin._task_store.update_task(record.task_id, status="completed", message="fixture completed")
            response = await plugin.drawpic_submit_v2("sample", stream_id="gone-stream", request_id=request_id)
            assert response["accepted"] and response["reused"] and response["task_id"] == record.task_id
            assert len(plugin._task_store.snapshot()) == 1
        finally:
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("private,mode", [(False, "blacklist"), (False, "whitelist"), (True, "blacklist"), (True, "whitelist")])
def test_blocked_chat_entry_matrix(make_plugin, monkeypatch, private, mode):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            target = "A" * 32 if private else "123456"
            provide_streams(plugin, monkeypatch, group_id="" if private else target, user_id=target if private else "654321")
            if private:
                plugin.config.general.private_access_mode = mode
                plugin.config.general.private_access_ids = [target] if mode == "blacklist" else []
            else:
                plugin.config.general.group_access_mode = mode
                plugin.config.general.group_access_ids = [target] if mode == "blacklist" else []
            sources = AsyncMock(side_effect=AssertionError("denied request must not load source images"))
            monkeypatch.setattr(plugin._workspace().tasks, "_sources", sources)
            preference_before = dict(plugin._require_session_store().preferences)
            for content in ("帮助", "状态", "模型", "模型 1", "兼容模式 images_api", "NAI mode anime", "NAI cat", "风格 default cat", "文生图 cat", "图生图 cat", "次数"):
                response = await plugin.handle_draw_command(
                    "actual-stream", matched_groups={"content": content}, group_id="spoofed-group", user_id="spoofed-user",
                )
                assert response[0] is False and "名单" in response[1], content
            for name, values in (
                ("handle_draw", {"prompt": "cat"}), ("handle_edit_image", {"prompt": "cat"}),
                ("handle_styled_draw", {"prompt": "cat", "style": "default"}),
                ("handle_draw_styles", {}), ("handle_draw_status", {}),
            ):
                response = await getattr(plugin, name)(**values, stream_id="actual-stream")
                assert response["success"] is False and "名单" in response["message"], name
            response = await plugin.workspace_submit(json.dumps({"prompt": "cat", "stream_id": "actual-stream"}))
            assert "名单" in response["__workspace_error__"]
            with pytest.raises(PermissionError):
                await plugin.drawpic_submit("cat", stream_id="actual-stream")
            response = await plugin.drawpic_submit_v2("cat", stream_id="actual-stream")
            assert response["accepted"] is False and response["error"]["code"] == "PERMISSION_DENIED"
            for name, values in (("drawpic_preferences_v2", {}), ("drawpic_preferences_set_v2", {"preference_json": '{"novelai_mode":"anime"}'})):
                response = await getattr(plugin, name)(stream_id="actual-stream", **values)
                assert response["error"]["code"] == "PERMISSION_DENIED"
            message = {
                "session_id": "actual-stream", "platform": "qq", "processed_plain_text": "prefixed text",
                "message_info": {"group_info": {"group_id": "" if private else target}, "user_info": {"user_id": target if private else "654321"}},
                "raw_message": [{"type": "text", "data": "/绘图 文生图 cat"}],
            }
            fallback = await plugin.handle_prefixed_draw_command_fallback(message=message)
            assert not fallback["custom_result"]["success"] and "名单" in fallback["custom_result"]["response"]
            hooks = import_module("drawpic_workspace_test.src.maimai_drawpic.interfaces.hooks")
            cache = Mock(side_effect=AssertionError("blocked messages must not be cached"))
            monkeypatch.setattr(hooks, "cache_source_image_from_message", cache)
            await plugin.handle_source_image_cache(message=message)
            cache.assert_not_called()
            sources.assert_not_called()
            assert not plugin._task_store.snapshot()
            assert plugin._require_session_store().preferences == preference_before
        finally:
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("stage", ["lock", "sources"])
@pytest.mark.parametrize("revocation", ["api", "list"])
def test_pending_api_submission_rechecks_permissions_before_accepting(make_plugin, monkeypatch, stage, revocation):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        pending = None
        entered, release = asyncio.Event(), asyncio.Event()
        held = asyncio.Lock()
        try:
            tasks = plugin._workspace().tasks
            provide_streams(plugin, monkeypatch)
            if revocation == "list":
                plugin.config.general.group_access_ids = ["999999"]
            async def sources(*args):
                entered.set()
                await release.wait()
                return []
            monkeypatch.setattr(tasks, "_sources", sources)
            if stage == "lock":
                await held.acquire()
                @asynccontextmanager
                async def waiting_lock():
                    entered.set()
                    async with held:
                        yield
                monkeypatch.setattr(tasks, "lock", waiting_lock())
                def snapshot():
                    raise AssertionError("disabled request must not enter acceptance")
                monkeypatch.setattr(tasks.task_store, "retained_task_ids", snapshot)
            pending = asyncio.create_task(plugin.drawpic_submit_v2(
                "cat", stream_id="actual-stream" if revocation == "list" else "", request_id="pending-switch-01",
            ))
            await asyncio.wait_for(entered.wait(), 2)
            if revocation == "api":
                plugin.config.general.integration_api_enabled = False
            else:
                plugin.config.general.group_access_ids = ["123456"]
            release.set()
            if stage == "lock":
                held.release()
            response = await asyncio.wait_for(pending, 2)
            assert response["accepted"] is False and response["error"]["code"] == "PERMISSION_DENIED"
            assert not plugin._task_store.snapshot()
        finally:
            release.set()
            if held.locked():
                held.release()
            if pending is not None and not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("revocation", ["list", "api"])
def test_revocation_while_reserving_quota_refunds_without_creating_task(make_plugin, monkeypatch, revocation):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            provide_streams(plugin, monkeypatch)
            reserve = plugin._reserve_draw_quota
            tokens = []
            def revoke_after_reservation(*args, **kwargs):
                result = reserve(*args, **kwargs)
                assert result[0] and result[2] is not None
                tokens.append(result[2])
                if revocation == "list":
                    plugin.config.general.group_access_ids = ["123456"]
                else:
                    plugin.config.general.integration_api_enabled = False
                return result
            monkeypatch.setattr(plugin, "_reserve_draw_quota", revoke_after_reservation)
            with pytest.raises(PermissionError):
                await plugin._start_background_image_request(
                    prompt="cat", stream_id="actual-stream", user_id="654321", group_id="123456",
                    submission={"origin": "plugin"}, defer_prompt_review=True,
                )
            assert len(tokens) == 1
            token = tokens[0]
            assert plugin._usage_store.get_remaining(
                token.quota_key, period=token.period, default_quota=token.default_quota,
            ) == token.default_quota
            assert not plugin._task_store.snapshot()
        finally:
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("private", [False, True])
def test_allowed_chat_and_workspace_still_work_with_integration_disabled(make_plugin, monkeypatch, private):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            target = "A" * 32 if private else "123456"
            provide_streams(plugin, monkeypatch, group_id="" if private else target, user_id=target if private else "654321")
            plugin.config.general.integration_api_enabled = False
            plugin.config.general.group_access_mode = plugin.config.general.private_access_mode = "whitelist"
            plugin.config.general.group_access_ids = [] if private else [target]
            plugin.config.general.private_access_ids = [target] if private else []
            generated = AsyncMock(return_value=[image_bytes()])
            monkeypatch.setattr(plugin._require_draw_service(), "_run_image_request_attempt", generated)
            sent = AsyncMock(return_value=1)
            monkeypatch.setattr(plugin._require_stream_service(), "send_generated_images_with_fallback", sent)
            assert (await plugin.handle_draw_styles(stream_id="actual-stream"))["success"]
            result = await plugin.handle_draw("cat", stream_id="actual-stream", user_id=target if private else "654321")
            assert result["success"] and result["task_id"]
            await asyncio.gather(*tuple(plugin._require_draw_service().background_tasks))
            assert generated.call_count == sent.call_count == 1
            receipt = await plugin.workspace_submit(json.dumps({"prompt": "cat"}))
            assert receipt["task_id"]
            await asyncio.gather(*tuple(plugin._require_draw_service().background_tasks))
            assert generated.call_count == 2 and sent.call_count == 1
        finally:
            await plugin.on_unload()
    asyncio.run(run())


def test_saved_switch_and_openid_lists_survive_reload(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        general = plugin.config.general.model_dump(mode="json")
        general.update(integration_api_enabled=False, group_access_mode="whitelist", group_access_ids=["B" * 32],
                       private_access_mode="blacklist", private_access_ids=["A" * 32])
        try:
            result = await plugin.workspace_settings_save(json.dumps({"general": general}), plugin._platform_store.revision)
            assert result["saved"]
        finally:
            await plugin.on_unload()
        restored = make_plugin(False)
        await restored.on_load()
        try:
            config = restored.config.general
            assert not config.integration_api_enabled
            assert config.group_access_mode == "whitelist" and config.group_access_ids == ["B" * 32]
            assert config.private_access_mode == "blacklist" and config.private_access_ids == ["A" * 32]
            with pytest.raises(PermissionError):
                await restored.drawpic_models()
            provide_streams(restored, monkeypatch, group_id="", user_id="A" * 32)
            response = await restored.handle_draw_styles(stream_id="actual-stream")
            assert response["success"] is False
        finally:
            await restored.on_unload()
    asyncio.run(run())


def test_late_chat_denial_is_not_reported_as_failure_or_quota_exhaustion(make_plugin, monkeypatch, caplog):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            provide_streams(plugin, monkeypatch)
            start = AsyncMock(side_effect=access.ChatAccessDenied("当前群聊已被黑名单限制"))
            monkeypatch.setattr(plugin, "_start_background_image_request", start)
            monkeypatch.setattr(plugin, "_collect_optional_command_source_images", AsyncMock(return_value=([], [], "")))
            invocation_notice, failure_notice, command_reply = AsyncMock(), AsyncMock(), AsyncMock()
            monkeypatch.setattr(plugin, "_send_invocation_failure_notice", invocation_notice)
            monkeypatch.setattr(plugin, "_send_draw_failure_notice", failure_notice)
            monkeypatch.setattr(plugin, "_send_command_reply", command_reply)
            for name, values in (
                ("handle_draw", {"prompt": "cat"}),
                ("handle_styled_draw", {"prompt": "cat", "style": "default"}),
            ):
                response = await getattr(plugin, name)(**values, stream_id="actual-stream", user_id="654321", group_id="123456")
                assert response["success"] is False and "黑名单" in response["message"]
            response = await plugin.handle_draw_command(
                "actual-stream", matched_groups={"content": "风格 default cat"}, user_id="654321", group_id="123456",
            )
            assert response[0] is False and "黑名单" in response[1]
            assert start.await_count == 3
            invocation_notice.assert_not_called()
            failure_notice.assert_not_called()
            command_reply.assert_not_called()
            assert not [record for record in caplog.records if record.levelname in {"ERROR", "CRITICAL"}]
        finally:
            await plugin.on_unload()
    asyncio.run(run())
