"""RinkoAI / New API 协议、自动兼容与安全诊断测试（不调用网络）。"""

from importlib import import_module
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image

import asyncio
import base64
import json
import pytest
import sys
import types


_PKG_NAME = "maimai_drawpic_pkg"
if _PKG_NAME not in sys.modules:
    package = types.ModuleType(_PKG_NAME)
    package.__path__ = [str(Path(__file__).resolve().parent.parent)]
    sys.modules[_PKG_NAME] = package

_models = import_module(f"{_PKG_NAME}.models.rinkoai_models")
_config = import_module(f"{_PKG_NAME}.core.config")
_router = import_module(f"{_PKG_NAME}.core.provider_router")
_preferences = import_module(f"{_PKG_NAME}.core.session_preferences")
_texts = import_module(f"{_PKG_NAME}.core.texts")
_OpenaiImage = import_module(f"{_PKG_NAME}.providers.openai_platform").OpenaiImage
_OpenAIRequestError = import_module(f"{_PKG_NAME}.providers.openai_platform").OpenAIRequestError
_openai_models = import_module(f"{_PKG_NAME}.models.openai_models")
_MODEL = "nai-diffusion-5-full"


def _png() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(buffer, format="PNG")
    return buffer.getvalue()


class _Transport(_OpenaiImage):
    """替换传输层，计数以确保失败不会再次发起付费生成。"""

    def __init__(self, response: Dict[str, Any], **options: Any) -> None:
        values = {
            "api_key": "test-secret",
            "base_url": "https://api.rinko.ai/v1",
            "compatibility_mode": "auto",
        }
        values.update(options)
        super().__init__(**values)
        self.response = response
        self.calls: List[Dict[str, Any]] = []
        self.downloads: List[str] = []
        self.metadata_calls = 0
        self.metadata: Dict[str, List[str]] = {}

    async def _fetch_model_endpoint_types(self) -> Dict[str, List[str]]:
        self.metadata_calls += 1
        return self.metadata

    async def _post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"url": url, "payload": payload})
        return self.response

    async def _download_image(self, url: str) -> bytes:
        self.downloads.append(url)
        return _png()


def _response(content: Any, **message_fields: Any) -> Dict[str, Any]:
    return {"id": "request-1", "choices": [{"message": {"content": content, **message_fields}}]}


@pytest.mark.parametrize("base_url,model,expected", [
    ("https://api.rinko.ai/v1", _MODEL, True),
    ("https://API.RINKO.AI", "nai-diffusion-4-5-full", True),
    ("https://api.rinko.ai/v1", "gpt-image-2", False),
    ("https://api.rinko.ai/v1", "stable-diffusion-xl", False),
    ("https://api.rinko.ai.example/v1", _MODEL, False),
    ("https://other.example/v1", _MODEL, False),
])
def test_special_protocol_is_scoped(base_url: str, model: str, expected: bool) -> None:
    assert _models.is_rinkoai_nai_model(base_url, model) is expected


def test_generation_uses_verified_chat_payload_and_real_png() -> None:
    image = _png()
    content = f"![image](data:image/png;base64,{base64.b64encode(image).decode()})"
    provider = _Transport(_response(content), extra_parameters={"stream": True, "model": "wrong"})
    assert asyncio.run(provider.generate_images("blue sky", _MODEL)) == [image]
    assert provider.calls == [{
        "url": "https://api.rinko.ai/v1/chat/completions",
        "payload": {
            "model": _MODEL,
            "messages": [{"role": "user", "content": "blue sky"}],
            "stream": False,
        },
    }]


def test_multi_markdown_and_structured_images_are_not_lost() -> None:
    provider = _Transport({})
    content = "![one](https://images.example/one.png) ![two](https://images.example/two.png)"
    response = _response([{"type": "text", "text": content}])
    assert len(asyncio.run(provider._extract_chat_completion_images(response))) == 2
    assert len(provider.downloads) == 2
    # 空字符串 content 不能跳过 message.images。
    response = _response("", images=[{"image_url": {"url": "https://images.example/three.png"}}])
    assert asyncio.run(provider._extract_chat_completion_images(response)) == [_png()]


@pytest.mark.parametrize("response", [
    _response("no image"),
    {"error": {"code": "denied", "message": "test-secret data:image/png;base64," + "A" * 300}},
    _response("![image](data:image/png;base64,invalid!)"),
])
def test_errors_never_retry_or_disclose_image_data(response: Dict[str, Any]) -> None:
    provider = _Transport(response)
    with pytest.raises(RuntimeError) as error:
        asyncio.run(provider.generate_images("sky", _MODEL))
    assert len(provider.calls) == 1
    assert "test-secret" not in str(error.value)
    assert "A" * 80 not in str(error.value)


def test_business_error_preserves_safe_diagnostics() -> None:
    provider = _Transport({})
    with pytest.raises(RuntimeError) as error:
        provider._raise_response_error({
            "id": "req-123",
            "error": {"code": "quota_exceeded", "message": "https://images.example/a?secret=value"},
        })
    assert "quota_exceeded" in str(error.value)
    assert "req-123" in str(error.value)
    assert "secret=value" not in str(error.value)
    assert provider._sanitize_text("Authorization: Bearer other-secret") == "Authorization: Bearer [REDACTED]"


def test_explicit_legacy_mode_is_scoped_and_multi_image_is_rejected() -> None:
    provider = _Transport({}, compatibility_mode="novelai_images_api")
    assert provider._resolve_generation_modes(_MODEL) == ["rinkoai"]
    assert provider._resolve_generation_modes("gpt-image-2")[0] == "images_api"
    provider.base_url = "https://other.example"
    with pytest.raises(ValueError, match="仅适用于"):
        provider._resolve_generation_modes(_MODEL)
    with pytest.raises(ValueError, match="一张"):
        _models.build_rinkoai_payload("sky", _MODEL, 2, {})


def test_other_rinkoai_models_keep_images_api_default() -> None:
    provider = _Transport({"data": [{"b64_json": base64.b64encode(_png()).decode()}]})
    assert asyncio.run(provider.generate_images("sky", "gpt-image-2")) == [_png()]
    assert provider.calls[0]["url"].endswith("/v1/images/generations")
    assert provider._resolve_edit_modes("gpt-image-2") == ["images_api"]
    assert "rinkoai" not in provider._resolve_generation_modes("gemini-3.1-flash-image-preview")


def _aliased_router() -> Any:
    config = _config.DrawpicConfig()
    config.openai.enabled = False
    config.openai.instances = [_config.OpenAICompatibleInstanceConfig(
        name="RinkoAI",
        api_key="test-key",
        base_url="https://api.rinko.ai/v1",
        models=f"rinko-nai={_MODEL}, rinko-gpt=gpt-image-2",
        default_openai_compatibility_mode="novelai_images_api",
    )]
    return _router.ProviderRouter(config)


def test_edit_is_rejected_before_paid_request_and_aliases_use_upstream_name() -> None:
    router = _aliased_router()
    capability = router.evaluate_model_task_capability("rinko-nai", "edit_image")
    assert not capability.allowed
    assert capability.source == "rinkoai_nai_protocol"
    assert router.evaluate_model_task_capability("rinko-nai", "draw").allowed
    assert router.evaluate_model_task_capability("rinko-gpt", "edit_image").allowed
    assert router.resolve_openai_compatibility_mode(model="rinko-nai") == "rinkoai"
    routed, _ = router.require_platform_for_model("rinko-nai")
    assert routed.upstream_model == _MODEL
    routed_gpt, _ = router.require_platform_for_model("rinko-gpt")
    assert routed_gpt.provider._resolve_edit_modes("gpt-image-2") == ["images_api"]
    provider = _Transport({})
    with pytest.raises(ValueError, match="未验证支持图生图"):
        asyncio.run(provider.edit_images("red hat", _MODEL, [_png()]))
    assert not provider.calls


def test_legacy_config_and_session_preferences_are_normalized(tmp_path: Path) -> None:
    config = _config.OpenAIModelConfig(default_openai_compatibility_mode="novelai_images_api")
    assert config.default_openai_compatibility_mode == "rinkoai"
    modes = config.model_json_schema()["properties"]["default_openai_compatibility_mode"]["enum"]
    assert "rinkoai" in modes and "chat_completions" in modes and "novelai_images_api" not in modes
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"qq:group:1": {"openai_compatibility_mode": "novelai_images_api"}}))
    store = _preferences.SessionPreferenceStore(path, _aliased_router(), None)
    store.load()
    assert store.get_preference("stream", group_id="1")["openai_compatibility_mode"] == "rinkoai"
    store.set_preference("stream", group_id="1", openai_compatibility_mode="RinkoAI兼容")
    assert "novelai_images_api" not in path.read_text()
    assert "RinkoAI 兼容" in _texts.build_compatible_mode_text("novelai_images_api")
    store.set_preference("stream", group_id="1", openai_compatibility_mode="chat_completions")
    assert store.get_preference("stream", group_id="1")["openai_compatibility_mode"] == "chat_completions"


class _AutoTransport(_Transport):
    """按序注入端点响应，同时记录表单提交而不访问网络。"""

    def __init__(self, results: List[Any], **options: Any) -> None:
        super().__init__({}, base_url="https://newapi.example/v1", **options)
        self.results = list(results)

    def _next(self) -> Dict[str, Any]:
        assert self.results, "发生未预期的重复请求"
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def _post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"url": url, "payload": payload})
        return self._next()

    async def _post_form(self, url: str, form: Any) -> Dict[str, Any]:
        images = [value for _name, _headers, value in form._fields if isinstance(value, bytes)]
        self.calls.append({"url": url, "images": images})
        return self._next()


def _both_response() -> Dict[str, Any]:
    encoded = base64.b64encode(_png()).decode()
    response = _response(f"![image](data:image/png;base64,{encoded})")
    response["data"] = [{"b64_json": encoded}]
    return response


def test_newapi_chat_generation_and_multi_source_edit_protocol() -> None:
    extra = {"extra_body": {"google": {"image_config": {"aspect_ratio": "16:9"}}}, "stream": True}
    provider = _AutoTransport([_both_response(), _both_response()],
                              compatibility_mode="chat_completions", extra_parameters=extra)
    assert asyncio.run(provider.generate_images("sky", "custom-image-model")) == [_png()]
    jpeg_buffer = BytesIO()
    Image.new("RGB", (8, 8)).save(jpeg_buffer, format="JPEG")
    sources = [jpeg_buffer.getvalue(), _png()]
    assert asyncio.run(provider.edit_images("red hat", "custom-image-model", sources)) == [_png()]
    assert provider.metadata_calls == 0
    payload = provider.calls[1]["payload"]
    assert payload["stream"] is False
    assert payload["extra_body"] == extra["extra_body"]
    assert "contents" not in payload and "size" not in payload
    content = payload["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "red hat"}
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert content[2]["image_url"]["url"].startswith("data:image/png;base64,")
    for item, source in zip(content[1:], sources):
        assert base64.b64decode(item["image_url"]["url"].split(",", 1)[1]) == source


@pytest.mark.parametrize("model,metadata,endpoint", [
    ("gpt-image-2", {}, "images/generations"),
    ("gemini-3.1-flash-image-preview", {}, "chat/completions"),
    ("custom-image-model", {"custom-image-model": ["openai"]}, "chat/completions"),
    ("gemini-3.1-flash-image-preview", {"gemini-3.1-flash-image-preview": ["image-generation"]},
     "images/generations"),
])
def test_auto_uses_metadata_before_model_rules(model: str, metadata: Dict[str, List[str]], endpoint: str) -> None:
    provider = _AutoTransport([_both_response(), _both_response()])
    provider.metadata = metadata
    assert asyncio.run(provider.generate_images("sky", model)) == [_png()]
    assert asyncio.run(provider.generate_images("sky", model)) == [_png()]
    assert all(call["url"].endswith(endpoint) for call in provider.calls)
    assert provider.metadata_calls == 1


def test_auto_route_switch_is_bounded_and_success_is_cached_by_task() -> None:
    provider = _AutoTransport([
        _OpenAIRequestError(404, "", "", "404 page not found"),
        _both_response(), _both_response(), _both_response(),
    ])
    assert asyncio.run(provider.generate_images("sky", "custom-image-model")) == [_png()]
    assert asyncio.run(provider.generate_images("sky", "custom-image-model")) == [_png()]
    assert asyncio.run(provider.edit_images("sky", "custom-image-model", [_png()])) == [_png()]
    assert [call["url"].rsplit("/v1/", 1)[1] for call in provider.calls] == [
        "images/generations", "chat/completions", "chat/completions", "images/edits",
    ]
    assert provider.metadata_calls == 1


def test_auto_edit_switch_keeps_all_sources_and_does_not_retry_forms() -> None:
    provider = _AutoTransport([
        _OpenAIRequestError(405, "", "", "Method Not Allowed"), _both_response(),
    ])
    assert asyncio.run(provider.edit_images("sky", "custom-image-model", [_png(), _png()])) == [_png()]
    assert len(provider.calls) == 2
    assert len(provider.calls[0]["images"]) == 2
    assert len(provider.calls[1]["payload"]["messages"][0]["content"]) == 3


@pytest.mark.parametrize("failure", [
    _OpenAIRequestError(401, "", "", "Unauthorized"),
    _OpenAIRequestError(403, "permission_denied", "", "Denied"),
    _OpenAIRequestError(402, "insufficient_quota", "", "Quota exceeded"),
    _OpenAIRequestError(429, "rate_limit_exceeded", "", "Rate limited"),
    _OpenAIRequestError(404, "model_not_found", "model", "Model not found"),
    _OpenAIRequestError(500, "", "", "Server error"),
    TimeoutError("request timed out"),
    _response("no image"),
    {"error": {"code": "content_filter", "message": "blocked"}},
])
@pytest.mark.parametrize("task", ["draw", "edit_image"])
def test_auto_does_not_repeat_paid_or_business_failures(failure: Any, task: str) -> None:
    provider = _AutoTransport([failure])
    with pytest.raises(RuntimeError):
        if task == "draw":
            asyncio.run(provider.generate_images("sky", "custom-image-model"))
        else:
            asyncio.run(provider.edit_images("sky", "custom-image-model", [_png()]))
    assert len(provider.calls) == 1


def test_declared_or_manual_endpoint_never_probes_other_endpoints() -> None:
    error = _OpenAIRequestError(405, "", "", "Method Not Allowed")
    provider = _AutoTransport([error], compatibility_mode="chat_completions")
    with pytest.raises(_OpenAIRequestError):
        asyncio.run(provider.generate_images("sky", "custom-image-model"))
    assert len(provider.calls) == 1 and provider.metadata_calls == 0
    provider = _AutoTransport([error])
    provider.metadata = {"custom-image-model": ["openai"]}
    with pytest.raises(_OpenAIRequestError):
        asyncio.run(provider.generate_images("sky", "custom-image-model"))
    assert len(provider.calls) == 1
    provider = _AutoTransport([])
    provider.metadata = {"native-only": ["gemini"]}
    with pytest.raises(ValueError, match="公布的端点不支持"):
        asyncio.run(provider.generate_images("sky", "native-only"))
    assert not provider.calls


def test_form_validation_retry_never_drops_sources() -> None:
    provider = _AutoTransport([
        _OpenAIRequestError(400, "invalid_parameter", "image", "Wrong image field"), _both_response(),
    ])
    asyncio.run(provider.edit_images("sky", "custom-image-model", [_png(), _png()]))
    assert len(provider.calls) == 2
    assert all(len(call["images"]) == 2 for call in provider.calls)


@pytest.mark.parametrize("status,code,message,allowed", [
    (404, "", "404 page not found", True),
    (405, "", "Method Not Allowed", True),
    (400, "unsupported_endpoint", "Unsupported endpoint", True),
    (404, "model_not_found", "Model not found", False),
    (404, "", "Model missing", False),
    (403, "unsupported_endpoint", "Access denied", False),
    (500, "unsupported_endpoint", "Server error", False),
])
def test_endpoint_error_classification_is_conservative(status: int, code: str, message: str, allowed: bool) -> None:
    assert _openai_models.is_endpoint_unsupported(status, code, message) is allowed


def test_http_error_keeps_classification_and_redacts_logs() -> None:
    class _Content:
        def __init__(self, value: bytes) -> None:
            self.value = value

        async def iter_chunked(self, size: int) -> Any:
            del size
            yield self.value

    logs: List[str] = []
    provider = _Transport({}, logger=types.SimpleNamespace(error=lambda msg, *args: logs.append(msg % args)))
    response = types.SimpleNamespace(
        status=404, headers={"x-request-id": "req-safe"}, charset="utf-8",
        content=_Content(b"404 page not found"),
    )
    error = asyncio.run(provider._http_error(response, "https://newapi.example/a?secret=hidden", 1.2))
    assert error.can_retry_endpoint
    assert "req-safe" in str(error) and "duration=1.20s" in str(error)
    response.status = 401
    response.content = _Content(json.dumps({"error": {
        "code": "permission_denied",
        "message": "test-secret https://images.example/a?token=hidden data:image/png;base64," + "A" * 300,
    }}).encode())
    error = asyncio.run(provider._http_error(response, "https://newapi.example/a?secret=hidden", 1.2))
    assert not error.can_retry_endpoint
    diagnostics = str(error) + " ".join(logs)
    assert "test-secret" not in diagnostics
    assert "hidden" not in diagnostics
    assert "A" * 80 not in diagnostics


def test_newapi_model_alias_uses_upstream_name_for_metadata(monkeypatch: Any) -> None:
    config = _config.DrawpicConfig()
    config.openai.enabled = False
    config.openai.instances = [_config.OpenAICompatibleInstanceConfig(
        name="New API", api_key="test-key", base_url="https://newapi.example/v1",
        models="display-image=custom-upstream-image", default_openai_compatibility_mode="auto",
    )]
    routed, _ = _router.ProviderRouter(config).require_platform_for_model("display-image")
    calls: List[Dict[str, Any]] = []

    async def _metadata() -> Dict[str, List[str]]:
        return {"custom-upstream-image": ["openai"]}

    async def _post(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        calls.append({"url": url, "payload": payload})
        return _both_response()

    monkeypatch.setattr(routed.provider, "_fetch_model_endpoint_types", _metadata)
    monkeypatch.setattr(routed.provider, "_post_json", _post)
    assert asyncio.run(routed.generate_images("sky", "display-image")) == [_png()]
    assert calls[0]["url"].endswith("chat/completions")
    assert calls[0]["payload"]["model"] == "custom-upstream-image"
