"""MiniMax 官方协议测试：仅本地 HTTP 与内存图片，不使用真实密钥。"""

from importlib import import_module
from test_model_discovery import server
from test_workspace import _PACKAGE, DrawpicConfig, image_bytes, make_plugin as make_plugin
from unittest.mock import AsyncMock, Mock
from aiohttp import web
import asyncio
import base64
import json
import pytest

profiles = import_module(f"{_PACKAGE}.src.maimai_drawpic.domain.models.minimax_profiles")
minimax = import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.providers.minimax")
config_type = import_module(f"{_PACKAGE}.src.maimai_drawpic.domain.configuration.models").MiniMaxModelConfig
router_type = import_module(f"{_PACKAGE}.src.maimai_drawpic.application.routing").ProviderRouter
errors = import_module(f"{_PACKAGE}.src.maimai_drawpic.domain.errors")


def client(**overrides):
    values = config_type(**overrides).model_dump(mode="json")
    values.update(model_size_overrides={}, extra_parameters={})
    return minimax.MiniMaxImage("fixture-minimax-key", values, logger=Mock())


def build(model="MiniMax-H3-Image", *, edit=False, **overrides):
    return profiles.build_minimax_payload(client(**overrides).values, "test prompt", model, edit=edit)


def test_defaults_and_h3_parameters_are_not_legacy_parameters():
    assert config_type().models == ["MiniMax-H3-Image"]
    assert config_type().request_timeout_seconds == 600
    assert not config_type().negative_prompt_enabled
    payload = build(area="2K", aspect_ratio="16:9", n=3, output_format="webp", output_compression=82,
                    aigc_watermark=True, disable_prompt_enhanced=True)
    assert payload == {
        "model": "MiniMax-H3-Image", "prompt": "test prompt", "size": "auto", "area": "2K",
        "aspect_ratio": "16:9", "n": 3, "output_format": "webp", "output_compression": 82,
        "aigc_watermark": True, "disable_prompt_enhanced": True, "response_format": "url", "stream": False,
    }
    assert "disable_prompt_enhanced" not in build(edit=True)


def test_legacy_parameters_and_zero_seed():
    payload = build("image-01", size="1024x1536", seed=0, prompt_optimizer=True, n=9, response_format="b64_json")
    assert payload["width"] == 1024 and payload["height"] == 1536
    assert payload["seed"] == 0 and payload["prompt_optimizer"] is True
    assert payload["response_format"] == "base64" and payload["n"] == 9
    assert not payload.keys() & {"size", "area", "stream", "output_format", "disable_prompt_enhanced"}
    live = build("image-01-live", style_type="水彩", style_weight=0.4)
    assert live["style"] == {"style_type": "水彩", "style_weight": 0.4}


@pytest.mark.parametrize("model,overrides", [
    ("MiniMax-H3-Image", {"size": "200x200"}),
    ("MiniMax-H3-Image", {"size": "5000x4001"}),
    ("MiniMax-H3-Image", {"size": "2048x2048", "area": "2K"}),
    ("MiniMax-H3-Image", {"size": "2048x2048", "aspect_ratio": "auto"}),
    ("MiniMax-H3-Image", {"aspect_ratio": "4:1"}),
    ("MiniMax-H3-Image", {"aspect_ratio": "0:1"}),
    ("MiniMax-H3-Image", {"area": "8K"}),
    ("MiniMax-H3-Image", {"disable_prompt_enhanced": True}),
    ("MiniMax-H3-Image", {"stream": True, "response_format": "b64_json"}),
    ("MiniMax-H3-Image", {"n": 10}),
    ("MiniMax-H3-Image", {"n": 2, "response_format": "b64_json", "output_format": "png"}),
    ("image-01", {"n": 10}),
    ("image-01", {"size": "1025x1024"}),
    ("image-01", {"size": "1024x1024", "aspect_ratio": "1:1"}),
    ("image-01-live", {"size": "1024x1024"}),
    ("image-01-live", {"aspect_ratio": "21:9"}),
    ("image-01-live", {"style_type": "unknown"}),
    ("image-01", {"stream": True}),
])
def test_invalid_parameters_fail_before_post(model, overrides):
    with pytest.raises(ValueError):
        build(model, **overrides)


def test_extension_parameters_cannot_replace_task_identity_or_cross_protocols():
    for extra in ({"prompt": "override"}, {"images": []}, {"seed": 42}, {"negative_prompt": "bypass"}):
        provider = client()
        provider.values["extra_parameters"] = extra
        with pytest.raises(ValueError):
            profiles.build_minimax_payload(provider.values, "test", "MiniMax-H3-Image", edit=False)


@pytest.mark.parametrize("model,path", [("MiniMax-H3-Image", "/v1/images/edits"), ("image-01", "/v1/image_generation")])
def test_official_endpoints_reference_shapes_and_base64_results(unused_tcp_port, model, path):
    async def run():
        calls = []
        raw = image_bytes()
        async def handler(request):
            payload = await request.json()
            calls.append(payload)
            assert request.path == path
            assert request.headers["Authorization"] == "Bearer fixture-minimax-key"
            data = [{"b64_json": base64.b64encode(raw).decode()}] if model in profiles.H3_MODELS else {"image_base64": [base64.b64encode(raw).decode()]}
            return web.json_response({"data": data, "base_resp": {"status_code": 0}, "request_id": "fixture-id"})
        async with server(handler, unused_tcp_port) as endpoint:
            provider = client(base_url=endpoint + "/v1")
            images = [raw, raw] if model in profiles.H3_MODELS else [raw]
            assert await provider.edit_images("test", model, images) == [raw]
        assert len(calls) == 1
        payload = calls[0]
        if model in profiles.H3_MODELS:
            assert len(payload["images"]) == 2 and payload["images"][0]["image_url"].startswith("data:image/png;base64,")
            assert "disable_prompt_enhanced" not in payload and "subject_reference" not in payload
        else:
            assert payload["subject_reference"][0]["type"] == "character"
            assert "images" not in payload
    asyncio.run(run())


@pytest.mark.parametrize("status,code,rejected,retryable", [(200,1004,False,False),(200,1008,False,False),(200,1026,True,False),(200,1002,False,True),(422,1027,True,False),(500,1000,False,False)])
def test_business_and_http_errors_never_become_empty_success(unused_tcp_port, status, code, rejected, retryable):
    async def run():
        calls = []
        async def handler(request):
            calls.append(request.path)
            body = {"base_resp": {"status_code": code, "status_msg": "fixture failed"}} if status == 200 else {"error": {"code": str(code), "message": "fixture failed"}}
            return web.json_response(body, status=status)
        async with server(handler, unused_tcp_port) as endpoint:
            provider = client(base_url=endpoint + "/v1")
            with pytest.raises(errors.ProviderRequestError) as raised:
                await provider.generate_images("test", "image-01")
            assert raised.value.code == str(code)
            assert raised.value.rejected == rejected and raised.value.retryable == retryable
        assert len(calls) == 1
    asyncio.run(run())


def test_real_h3_balance_error_shape_and_diagnostics_redaction():
    provider = client()
    data = {"type":"error","error":{"type":"insufficient_balance_error","message":"insufficient balance (1008) fixture-minimax-key https://example.test/a?sig=fixture","http_code":"402"},"request_id":"fixture-id"}
    failure = provider._error(402, data)
    assert failure.code == "insufficient_balance_error" and not failure.retryable and not failure.allow_fallback
    assert "fixture-minimax-key" not in str(failure) and "sig=fixture" not in str(failure)
    assert "fixture-id" in str(failure)


def test_partial_failure_preserves_success_and_invalid_base64_is_not_retried():
    async def run():
        provider = client()
        raw = image_bytes()
        data = {"data":[{"error":{"code":"1027","message":"blocked"}},{"b64_json":base64.b64encode(raw).decode()}]}
        assert await provider._extract_images(data, h3=True) == [raw]
        with pytest.raises(errors.ProviderResultError):
            await provider._extract_images({"data":[{"b64_json":"not-base64!"}]}, h3=True)
        with pytest.raises(errors.ProviderRequestError) as raised:
            await provider._extract_images({"data":[{"error":{"code":"1027","message":"blocked"}}]}, h3=True)
        assert raised.value.rejected
    asyncio.run(run())


@pytest.mark.parametrize("mode", ["complete", "interrupted", "quota", "duplicate"])
def test_sse_order_failures_and_terminal_errors(unused_tcp_port, monkeypatch, mode):
    async def run():
        calls = []
        async def handler(request):
            calls.append(request.path)
            if mode == "quota":
                events = [{"type":"error","error":{"type":"insufficient_balance_error","http_code":"402","message":"balance (1008)"}}]
            else:
                events = [{"type":"image_generation.partial_succeeded","image_index":1,"url":"https://example.test/second"},
                          {"type":"image_generation.partial_succeeded","image_index":0,"url":"https://example.test/first"}]
                if mode == "duplicate":
                    events.append(events[0])
                if mode != "interrupted":
                    events.append({"type":"image_generation.completed","request_id":"fixture-id","usage":{"generated_images":2}})
            raw = (": keepalive\r\n\r\n" + "".join("event: " + event["type"] + "\r\ndata: " + json.dumps(event) + "\r\n\r\n" for event in events)).encode()
            response = web.StreamResponse(headers={"Content-Type":"text/event-stream"})
            await response.prepare(request)
            for start in range(0, len(raw), 7):
                await response.write(raw[start:start+7])
            await response.write_eof()
            return response
        downloaded = []
        async def download(url, **kwargs):
            downloaded.append(url)
            return image_bytes()
        monkeypatch.setattr(minimax, "download_image", download)
        async with server(handler, unused_tcp_port) as endpoint:
            provider = client(base_url=endpoint+"/v1", stream=True, n=2, area="1K")
            if mode == "complete":
                assert len(await provider.generate_images("test", "MiniMax-H3-Image")) == 2
                assert downloaded == ["https://example.test/first", "https://example.test/second"]
            else:
                expected = {"interrupted":errors.ProviderOutcomeUnknown,"quota":errors.ProviderRequestError,"duplicate":errors.ProviderResultError}[mode]
                with pytest.raises(expected):
                    await provider.generate_images("test", "MiniMax-H3-Image")
                assert not downloaded
        assert len(calls) == 1
    asyncio.run(run())


def test_workspace_instance_isolation_registry_and_proxy_rules(make_plugin):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            entry = next(item for item in (await plugin.workspace_bootstrap())["catalog"] if item["kind"] == "minimax")
            assert entry["defaults"]["models"] == ["MiniMax-H3-Image"]
            assert not entry["model_discovery"] and entry["model_presets"] == list(profiles.MINIMAX_MODELS)
            assert "不是在线模型目录" in entry["model_presets_hint"]
            for name, n in (("MiniMax_A",1),("MiniMax_B",2)):
                result = await plugin.workspace_provider_save(json.dumps({"kind":"minimax","name":name,"config":{"api_key":"fixture-"+name,"n":n,"area":"1K"}}), plugin._platform_store.revision)
                assert result["saved"]
            router = plugin._require_router()
            assert router.get_model_provider("MiniMax_A/MiniMax-H3-Image") == "minimax"
            a, _ = router.require_platform_for_model("MiniMax_A/MiniMax-H3-Image")
            b, _ = router.require_platform_for_model("MiniMax_B/MiniMax-H3-Image")
            assert a.provider is not b.provider and a.provider.values["n"] == 1 and b.provider.values["n"] == 2
            assert router.get_max_source_images("MiniMax_A/MiniMax-H3-Image") == 16
        finally:
            await plugin.on_unload()
    asyncio.run(run())
    config = DrawpicConfig()
    config.proxy.enabled = True
    domestic = router_type(config).create_minimax_provider()
    assert not domestic.proxy_settings.enabled
    config.minimax.base_url = "https://api.minimax.io/v1"
    assert router_type(config).create_minimax_provider().proxy_settings.enabled


@pytest.mark.parametrize("failure", ["timeout", "download", "invalid_json"])
def test_uncertain_or_post_success_failures_do_not_resubmit(unused_tcp_port, monkeypatch, failure):
    async def run():
        calls = []
        async def handler(request):
            calls.append(request.path)
            if failure == "timeout":
                await asyncio.sleep(0.3)
            if failure == "invalid_json":
                return web.Response(text="not-json")
            return web.json_response({"data":[{"url":"https://example.test/image"}]})
        async def download(*args, **kwargs):
            raise errors.ProviderResultError("fixture download failure")
        monkeypatch.setattr(minimax, "download_image", download)
        async with server(handler, unused_tcp_port) as endpoint:
            provider = client(base_url=endpoint + "/v1")
            if failure == "timeout":
                provider.values["request_timeout_seconds"] = 0.05
            expected = errors.ProviderOutcomeUnknown if failure == "timeout" else errors.ProviderResultError
            with pytest.raises(expected):
                await provider.generate_images("test", "MiniMax-H3-Image")
        assert len(calls) == 1
    asyncio.run(run())
