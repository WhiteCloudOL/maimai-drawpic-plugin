"""审核预算、任务路由与取消边界，不调用真实模型或聊天平台。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import asyncio
import base64
import json
import pytest

from test_review_regressions import module
from test_workspace import DrawpicConfig, image_bytes, make_plugin as make_plugin


Moderation = module("application.moderation").DrawpicModerationService
PASS = {"success": True, "response": "结论：PASS\n原因：fixture"}


def review_context(generate):
    return SimpleNamespace(llm=SimpleNamespace(generate=generate), logger=Mock())


@pytest.mark.parametrize("stage", ["prompt", "image"])
@pytest.mark.parametrize("model", ["replyer", "planner", "vlm"])
def test_review_model_and_rpc_budget_are_independent(stage: str, model: str) -> None:
    async def run() -> None:
        config = DrawpicConfig()
        config.general.prompt_review_enabled = config.general.image_review_enabled = True
        assert config.general.prompt_review_model == config.general.image_review_model == "vlm"
        assert config.general.prompt_review_timeout_seconds == config.general.image_review_timeout_seconds == 60
        setattr(config.general, f"{stage}_review_model", model)
        setattr(config.general, f"{stage}_review_timeout_seconds", 75 if stage == "prompt" else 135)
        llm = AsyncMock(return_value=PASS)
        service = Moderation(config, review_context(llm))
        raw = image_bytes()
        if stage == "prompt":
            result = await asyncio.wait_for(service.review_prompt("fixture cat"), 2)
        else:
            result = await asyncio.wait_for(service.review_image("fixture cat", raw), 2)
            payload = llm.await_args.args[0]
            assert isinstance(payload, list)
            assert base64.b64decode(payload[0]["content"][1]["image_base64"]) == raw
        assert result.passed
        assert llm.await_args.kwargs == {
            "model": model, "temperature": 0.0, "max_tokens": 512,
            "rpc_timeout_ms": 75000 if stage == "prompt" else 135000,
        }
        other = "image" if stage == "prompt" else "prompt"
        assert getattr(config.general, f"{other}_review_timeout_seconds") == 60

    asyncio.run(run())


@pytest.mark.parametrize("swallow_cancel", [False, True])
def test_review_deadline_rejects_even_a_late_pass(swallow_cancel: bool) -> None:
    async def run() -> None:
        config = DrawpicConfig()
        config.general.image_review_enabled = True
        # 缩短测试时钟；真实配置仍严格限制为 5～600 秒。
        config.general = config.general.model_copy(update={
            "image_review_timeout_seconds": 0.03, "image_review_retry_count": 0,
        })

        async def slow(*args, **kwargs):
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                if not swallow_cancel:
                    raise
            return PASS

        llm = AsyncMock(side_effect=slow)
        service = Moderation(config, review_context(llm))
        with pytest.raises(RuntimeError, match="图片审核等待超时"):
            await service.review_image("fixture", image_bytes())
        assert llm.await_count == 1

    asyncio.run(run())


@pytest.mark.parametrize("swallow_cancel", [False, True])
def test_review_cancellation_cannot_be_converted_into_pass(swallow_cancel: bool) -> None:
    async def run() -> None:
        config = DrawpicConfig()
        config.general.prompt_review_enabled = True
        entered = asyncio.Event()

        async def slow(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                if not swallow_cancel:
                    raise
            return PASS

        service = Moderation(config, review_context(AsyncMock(side_effect=slow)))
        task = asyncio.create_task(service.review_prompt("fixture"))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["prompt", "image"])
@pytest.mark.parametrize("failure", [
    TimeoutError(), RuntimeError("fixture transport failure"),
    {"success": True, "response": "invalid fixture response"},
])
def test_review_defaults_retry_twice_and_log_each_attempt(stage: str, failure) -> None:
    async def run() -> None:
        config = DrawpicConfig()
        config.general.prompt_review_enabled = config.general.image_review_enabled = True
        assert config.general.prompt_review_retry_count == config.general.image_review_retry_count == 2
        llm = AsyncMock(side_effect=[failure, failure, PASS])
        ctx = review_context(llm)
        service = Moderation(config, ctx)
        if stage == "prompt":
            result = await service.review_prompt("private fixture prompt", task_id="audit-fixture")
        else:
            result = await service.review_image(
                "private fixture prompt", image_bytes(), task_id="audit-fixture", image_index=2,
            )
        assert result.passed
        assert llm.await_count == 3
        assert all(call.kwargs["rpc_timeout_ms"] == 60000 for call in llm.await_args_list)
        logs = [call.args[0] % call.args[1:] for call in ctx.logger.info.call_args_list]
        warnings = [call.args[0] % call.args[1:] for call in ctx.logger.warning.call_args_list]
        assert len(warnings) == 2
        assert all("retrying=True" in line for line in warnings)
        assert any("attempt=3 total_attempts=3 result=PASS duration_ms=" in line for line in logs)
        assert all("task_id=audit-fixture" in line and "model_task=vlm" in line for line in logs + warnings)
        assert "private fixture prompt" not in "\n".join(logs + warnings)

    asyncio.run(run())


@pytest.mark.parametrize("retry_count", [0, 1, 3])
def test_review_retry_count_controls_exhaustion(retry_count: int) -> None:
    async def run() -> None:
        config = DrawpicConfig()
        config.general.prompt_review_enabled = True
        config.general.prompt_review_retry_count = retry_count
        ctx = review_context(AsyncMock(return_value={"success": True, "response": ""}))
        service = Moderation(config, ctx)
        with pytest.raises(RuntimeError, match="空结果"):
            await service.review_prompt("fixture", task_id="audit-exhaustion")
        assert ctx.llm.generate.await_count == retry_count + 1
        last = ctx.logger.warning.call_args
        assert "retrying=False" in last.args[0] % last.args[1:]

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["prompt", "image"])
def test_explicit_rejection_does_not_retry(stage: str) -> None:
    async def run() -> None:
        config = DrawpicConfig()
        config.general.prompt_review_enabled = config.general.image_review_enabled = True
        ctx = review_context(AsyncMock(return_value={"success": True, "response": "结论：REJECT\n原因：fixture"}))
        service = Moderation(config, ctx)
        result = await service.review_prompt("fixture") if stage == "prompt" else await service.review_image("fixture", image_bytes())
        assert not result.passed
        assert ctx.llm.generate.await_count == 1
        ctx.logger.warning.assert_not_called()

    asyncio.run(run())


def test_cancelling_retry_backoff_stops_and_logs_cancellation() -> None:
    async def run() -> None:
        config = DrawpicConfig()
        config.general.prompt_review_enabled = True
        failed = asyncio.Event()
        ctx = review_context(AsyncMock(side_effect=RuntimeError("fixture")))
        ctx.logger.warning.side_effect = lambda *args: failed.set()
        task = asyncio.create_task(Moderation(config, ctx).review_prompt("fixture", task_id="audit-cancel"))
        await asyncio.wait_for(failed.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert ctx.llm.generate.await_count == 1
        last = ctx.logger.info.call_args
        assert "审核已取消: task_id=audit-cancel" in last.args[0] % last.args[1:]

    asyncio.run(run())


def test_malformed_review_never_logs_raw_model_payload() -> None:
    async def run() -> None:
        config = DrawpicConfig()
        config.general.image_review_enabled = True
        config.general.image_review_retry_count = 0
        raw = "private prompt; Authorization: Bearer fixture-secret; " + base64.b64encode(image_bytes()).decode()
        ctx = review_context(AsyncMock(return_value={"success": True, "response": raw}))
        service = Moderation(config, ctx)
        with pytest.raises(RuntimeError) as error:
            await service.review_image("private prompt", image_bytes(), task_id="audit-safe")
        logs = "\n".join(call.args[0] % call.args[1:] for call in ctx.logger.method_calls)
        assert "error_code=INVALID_RESPONSE" in logs
        for secret in ("private prompt", "fixture-secret", raw):
            assert secret not in logs
            assert secret not in str(error.value)

    asyncio.run(run())


async def configured_plugin(make_plugin, monkeypatch, *, prompt: bool = False, image: bool = True):
    plugin = make_plugin()
    await plugin.on_load()
    bootstrap = await plugin.workspace_bootstrap()
    provider = bootstrap["providers"][0]
    provider["config"]["models"] = ["sample-image", "backup-image"]
    await plugin.workspace_provider_save(
        json.dumps({key: provider[key] for key in ("id", "kind", "name", "config")}), bootstrap["revision"],
    )
    bootstrap = await plugin.workspace_bootstrap()
    values = bootstrap["settings"]
    values["general"].update(
        prompt_review_enabled=prompt, image_review_enabled=image,
        request_retry_count=3, fallback_models=[f"{provider['name']}/backup-image"],
        group_quota_enabled=False, private_quota_enabled=False,
    )
    await plugin.workspace_settings_save(json.dumps(values), bootstrap["revision"])
    service = plugin._require_draw_service()
    live = {"stream_id": "review-fixture-stream", "user_id": "12345", "group_id": "67890", "platform": "qq"}
    monkeypatch.setattr(service.stream_service, "resolve_live_stream_context", AsyncMock(return_value=live))
    monkeypatch.setattr(service.stream_service, "send_text_with_fallback", AsyncMock(return_value=True))
    generated = AsyncMock(return_value=[image_bytes()])
    sent = AsyncMock(return_value=1)
    monkeypatch.setattr(service, "_run_image_request_attempt", generated)
    monkeypatch.setattr(service.stream_service, "send_generated_images_with_fallback", sent)
    return plugin, service, generated, sent


def test_review_settings_and_attempts_are_saved_in_safe_task_logs(make_plugin, monkeypatch, caplog) -> None:
    caplog.set_level("INFO", logger="plugin.maimai-drawpic-plugin")

    async def run():
        plugin, service, generated, sent = await configured_plugin(make_plugin, monkeypatch, prompt=True, image=True)
        try:
            llm = AsyncMock(side_effect=[TimeoutError(), PASS, PASS])
            monkeypatch.setattr(service.moderation_service.ctx.llm, "generate", llm)
            result = await plugin.handle_draw(
                prompt="private-audit-input-fixture", stream_id="review-fixture-stream",
                user_id="12345", group_id="67890", platform="qq",
            )
            await asyncio.gather(*tuple(service.background_tasks))
            assert (await plugin.drawpic_task(result["task_id"]))["status"] == "completed"
            assert generated.await_count == sent.await_count == 1
            path = plugin.ctx.paths.data_dir / "logs" / "drawpic.log"
            return path, result["task_id"]
        finally:
            await plugin.on_unload()

    path, task_id = asyncio.run(run())
    text = path.read_text(encoding="utf-8")
    assert "审核配置已保存:" in text
    assert "prompt_timeout_seconds=60 prompt_retry_count=2" in text
    assert "image_timeout_seconds=60 image_retry_count=2" in text
    task_lines = "\n".join(line for line in text.splitlines() if f"task_id={task_id}" in line)
    assert "stage=提示词审核" in task_lines and "stage=图片审核 image_index=1" in task_lines
    assert "error_code=REVIEW_TIMEOUT" in task_lines and "retrying=True" in task_lines
    assert "attempt=2 total_attempts=3 result=PASS duration_ms=" in task_lines
    assert "绘图任务完成:" in task_lines
    for secret in ("private-audit-input-fixture", "secret-fixture-key", base64.b64encode(image_bytes()).decode()):
        assert secret not in text


@pytest.mark.parametrize("failure", ["timeout", "empty", "malformed", "exception", "reject", "vision_unsupported", "late_pass"])
def test_generated_image_cannot_bypass_failed_review(make_plugin, monkeypatch, failure: str) -> None:
    async def run() -> None:
        plugin, service, generated, sent = await configured_plugin(make_plugin, monkeypatch)
        try:
            responses = {
                "empty": {"success": True, "response": ""},
                "malformed": {"success": True, "response": "PASS maybe"},
                "reject": {"success": True, "response": "结论：REJECT\n原因：fixture"},
                "vision_unsupported": {"success": False, "error": "model does not support image input"},
            }

            async def review(*args, **kwargs):
                if failure == "timeout":
                    raise TimeoutError
                if failure == "exception":
                    raise RuntimeError("fixture transport failed")
                if failure == "late_pass":
                    try:
                        await asyncio.sleep(5)
                    except asyncio.CancelledError:
                        return PASS
                return responses[failure]

            if failure == "late_pass":
                service.moderation_service.config.general = service.moderation_service.config.general.model_copy(
                    update={"image_review_timeout_seconds": 0.03},
                )
            monkeypatch.setattr(service.moderation_service.ctx.llm, "generate", AsyncMock(side_effect=review))
            result = await plugin.handle_draw(prompt="fixture cat", stream_id="review-fixture-stream", user_id="12345", group_id="67890", platform="qq")
            assert result["success"]
            await asyncio.gather(*tuple(service.background_tasks))
            task = await plugin.drawpic_task(result["task_id"])
            assert task["status"] == ("rejected" if failure == "reject" else "failed")
            assert generated.await_count == 1
            sent.assert_not_awaited()
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("entry", ["tool", "command"])
def test_chat_submission_returns_before_prompt_review_finishes(make_plugin, monkeypatch, entry: str) -> None:
    async def run() -> None:
        plugin, service, generated, sent = await configured_plugin(make_plugin, monkeypatch, prompt=True, image=False)
        entered, release = asyncio.Event(), asyncio.Event()

        async def review(*args, **kwargs):
            entered.set()
            await release.wait()
            return PASS

        try:
            monkeypatch.setattr(service.moderation_service.ctx.llm, "generate", AsyncMock(side_effect=review))
            if entry == "tool":
                result = await asyncio.wait_for(plugin.handle_draw(
                    prompt="fixture cat", stream_id="review-fixture-stream", user_id="12345", group_id="67890", platform="qq",
                ), 2)
                assert result["success"]
            else:
                monkeypatch.setattr(plugin, "_send_command_reply", AsyncMock())
                monkeypatch.setattr(plugin.ctx.message, "get_recent", AsyncMock(return_value=[]))
                result = await asyncio.wait_for(plugin.handle_draw_command(
                    stream_id="review-fixture-stream", user_id="12345", group_id="67890", platform="qq",
                    matched_groups={"content": "文生图 fixture cat"},
                ), 2)
                assert result[0]
            await asyncio.wait_for(entered.wait(), 2)
            generated.assert_not_awaited()
            release.set()
            await asyncio.gather(*tuple(service.background_tasks))
            assert generated.await_count == sent.await_count == 1
        finally:
            release.set()
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["prompt", "image"])
def test_cancelled_drawing_never_sends_a_late_review_pass(make_plugin, monkeypatch, stage: str) -> None:
    async def run() -> None:
        plugin, service, generated, sent = await configured_plugin(
            make_plugin, monkeypatch, prompt=stage == "prompt", image=stage == "image",
        )
        entered = asyncio.Event()

        async def review(*args, **kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return PASS

        try:
            monkeypatch.setattr(service.moderation_service.ctx.llm, "generate", AsyncMock(side_effect=review))
            result = await plugin.handle_draw(prompt="fixture", stream_id="review-fixture-stream", user_id="12345", group_id="67890", platform="qq")
            await asyncio.wait_for(entered.wait(), 2)
            tasks = tuple(service.background_tasks)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            record = await plugin.drawpic_task(result["task_id"])
            assert record["status"] == "failed"
            assert "取消" in record["message"]
            assert generated.await_count == (0 if stage == "prompt" else 1)
            sent.assert_not_awaited()
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_prompt_rejection_never_starts_generation(make_plugin, monkeypatch) -> None:
    async def run() -> None:
        plugin, service, generated, sent = await configured_plugin(make_plugin, monkeypatch, prompt=True, image=False)
        try:
            monkeypatch.setattr(service.moderation_service.ctx.llm, "generate", AsyncMock(return_value={
                "success": True, "response": "结论：REJECT\n原因：fixture",
            }))
            result = await plugin.handle_draw(prompt="fixture", stream_id="review-fixture-stream", user_id="12345", group_id="67890", platform="qq")
            await asyncio.gather(*tuple(service.background_tasks))
            assert (await plugin.drawpic_task(result["task_id"]))["status"] == "rejected"
            generated.assert_not_awaited()
            sent.assert_not_awaited()
        finally:
            await plugin.on_unload()

    asyncio.run(run())
