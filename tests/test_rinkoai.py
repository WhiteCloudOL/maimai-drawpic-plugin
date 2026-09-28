"""RinkoAI NAI 专用协议、能力拒绝与安全诊断测试（不调用网络）。"""

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
    provider = _Transport({}, compatibility_mode="chat_completions")
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
        default_openai_compatibility_mode="chat_completions",
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
    config = _config.OpenAIModelConfig(default_openai_compatibility_mode="chat_completions")
    assert config.default_openai_compatibility_mode == "rinkoai"
    modes = config.model_json_schema()["properties"]["default_openai_compatibility_mode"]["enum"]
    assert "rinkoai" in modes and "chat_completions" not in modes
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"qq:group:1": {"openai_compatibility_mode": "chat_completions"}}))
    store = _preferences.SessionPreferenceStore(path, _aliased_router(), None)
    store.load()
    assert store.get_preference("stream", group_id="1")["openai_compatibility_mode"] == "rinkoai"
    store.set_preference("stream", group_id="1", openai_compatibility_mode="RinkoAI兼容")
    assert "chat_completions" not in path.read_text()
    assert "RinkoAI 兼容" in _texts.build_compatible_mode_text("chat_completions")
