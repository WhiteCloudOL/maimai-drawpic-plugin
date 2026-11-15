"""已受理任务的查询断线不得重新生成；所有故障均为内存模拟。"""

from inspect import signature
from test_workspace import _PACKAGE, DrawpicConfig, image_bytes, make_plugin as make_plugin, storage
import aiohttp
import asyncio
import importlib
import json
import pytest


def module(name):
    return importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.{name}")


def connector_error():
    return aiohttp.ClientConnectorError(None, OSError("simulated connection failure"))


def comfy_provider(tmp_path):
    provider_class = module("infrastructure.providers.comfyui").ComfyUIImage
    config = DrawpicConfig().comfyui.model_dump()
    kwargs = {name: config[name] for name in signature(provider_class).parameters if name in config}
    kwargs.update(base_url="http://comfy.invalid", plugin_dir=tmp_path, data_dir=tmp_path)
    provider = provider_class(**kwargs)
    provider.poll_interval_seconds = 0
    return provider


@pytest.mark.parametrize("kind", ["comfyui", "aliyun"])
@pytest.mark.parametrize("failure", ["recover", "connector", "timeout", "query_rate_limit"])
def test_accepted_task_query_never_resubmits_or_uses_fallback(make_plugin, monkeypatch, tmp_path, kind, failure):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            record = (await plugin.workspace_bootstrap())["providers"][0]
            record["config"]["models"] = ["sample-image", "backup-image"]
            await plugin.workspace_provider_save(
                json.dumps({key: record[key] for key in ("id", "kind", "name", "config")}),
                plugin._platform_store.revision,
            )
            settings = storage.common_config(plugin.config.model_dump(mode="json"))
            settings["general"].update(request_retry_count=2, fallback_models=[f"{record['name']} / backup-image"])
            await plugin.workspace_settings_save(json.dumps(settings), plugin._platform_store.revision)

            errors = module("domain.errors")
            provider = (
                comfy_provider(tmp_path)
                if kind == "comfyui"
                else module("infrastructure.providers.aliyun").AliyunImage("fake", async_poll_interval_seconds=0)
            )
            accepted, queries, attempts, failures = [], [], [], []

            async def request(method, url, **kwargs):
                if method == "POST":
                    remote_id = f"queued-{len(accepted) + 1}"
                    accepted.append(remote_id)
                    return {"prompt_id": remote_id, "output": {"task_id": remote_id}}
                queries.append(url.rsplit("/", 1)[-1])
                if failure == "query_rate_limit":
                    # 即使查询返回可重试 HTTP 码，也不能把它当成生成请求被拒绝。
                    raise errors.ProviderRequestError(429, "rate_limit_exceeded", "query rate limit")
                if failure != "recover" or len(queries) <= 2:
                    raise TimeoutError("query timeout") if failure == "timeout" else connector_error()
                if kind == "comfyui":
                    return {accepted[0]: {"outputs": {"9": {"images": [{"filename": "result.png"}]}}}}
                return {"output": {"task_status": "SUCCEEDED"}}

            async def download(descriptor):
                return image_bytes()

            async def generate(**kwargs):
                attempts.append(kwargs["attempt"].model)
                try:
                    if kind == "comfyui":
                        return await provider._execute_workflow({}, "文生图")
                    await provider._execute_request("kling/kling-v3-image-generation", {})
                    return [image_bytes()]
                except errors.ProviderSubmittedError as exc:
                    failures.append(exc)
                    raise

            monkeypatch.setattr(provider, "_request_json", request)
            if kind == "comfyui":
                monkeypatch.setattr(provider, "_download_image", download)
            service = plugin._require_draw_service()
            monkeypatch.setattr(service, "_run_image_request_attempt", generate)
            task = await plugin.drawpic_submit("phase regression")
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(task["task_id"])
            assert accepted == ["queued-1"] and len(attempts) == 1
            assert queries == ["queued-1"] * (1 if failure == "query_rate_limit" else 3)
            assert result["status"] == ("completed" if failure == "recover" else "failed" if failure == "query_rate_limit" else "unconfirmed")
            if failure != "recover":
                assert len(failures) == 1 and failures[0].remote_task_id == "queued-1"
                assert not failures[0].retryable and not failures[0].allow_fallback
                assert "queued-1" in result["message"] and "已提交" in result["message"]
                assert "尚未发出" not in result["message"]
                assert "受理状态不确定" not in result["message"]
                assert failures[0].outcome_unknown == (failure != "query_rate_limit")
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize(
    "kind,class_name,method",
    [
        ("openai", "OpenaiImage", "_post_json"),
        ("openai", "OpenaiImage", "_post_form"),
        ("aliyun", "AliyunImage", "_post_json"),
        ("comfyui", "ComfyUIImage", "_post_json"),
        ("comfyui", "ComfyUIImage", "_post_form"),
        ("novelai", "NovelAIImage", "_post_generation"),
        ("siliconflow", "SiliconFlowImage", "_post_json"),
        ("volcengine", "VolcengineImage", "_post_json"),
        ("zhipu", "ZhipuImage", "_post_json"),
    ],
)
def test_post_transport_classifies_only_connection_not_established(monkeypatch, tmp_path, kind, class_name, method):
    async def run():
        errors = module("domain.errors")
        provider_class = getattr(module(f"infrastructure.providers.{kind}"), class_name)
        provider = comfy_provider(tmp_path) if kind == "comfyui" else provider_class("fake")
        hits = []

        async def disconnected(self, http_method, url, **kwargs):
            hits.append((http_method, kwargs["allow_redirects"]))
            raise connector_error()

        monkeypatch.setattr(aiohttp.ClientSession, "_request", disconnected)
        payload = aiohttp.FormData() if method == "_post_form" else {}
        with pytest.raises(errors.ProviderConnectionError) as captured:
            await getattr(provider, method)("http://provider.invalid/generate", payload)
        assert hits == [("POST", False)]
        assert captured.value.retryable and captured.value.allow_fallback

    asyncio.run(run())


def test_unclassified_connection_failure_cannot_infer_submission_state(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            settings = storage.common_config(plugin.config.model_dump(mode="json"))
            settings["general"]["request_retry_count"] = 2
            await plugin.workspace_settings_save(json.dumps(settings), plugin._platform_store.revision)
            service, calls = plugin._require_draw_service(), []

            async def generate(**kwargs):
                calls.append(kwargs)
                raise connector_error()

            monkeypatch.setattr(service, "_run_image_request_attempt", generate)
            task = await plugin.drawpic_submit("unknown phase")
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(task["task_id"])
            assert len(calls) == 1 and "受理状态不确定" in result["message"]
            assert "尚未发出" not in result["message"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_submitted_query_preserves_cancellation_and_moderation():
    async def run():
        requests, errors = module("infrastructure.providers.requests"), module("domain.errors")
        started, calls = asyncio.Event(), []

        async def query():
            calls.append(1)
            started.set()
            await asyncio.Event().wait()

        async def poll():
            async with requests.submitted_task("provider", "remote-id"):
                return await requests.query_submitted_task(query, poll_interval=0)

        task = asyncio.create_task(poll())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 1
        rejection = errors.ProviderRequestError(400, "content_policy_violation", "blocked")
        with pytest.raises(errors.ProviderRequestError) as captured:
            async with requests.submitted_task("provider", "remote-id"):
                raise rejection
        assert captured.value is rejection and captured.value.rejected

    asyncio.run(run())
