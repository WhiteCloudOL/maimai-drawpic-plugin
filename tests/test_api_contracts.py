"""官方图片协议、资源释放与失败行为的回归验证，无付费网络调用。"""

from io import BytesIO
from threading import get_ident
from typing import Any, Dict, List, Optional

from aiohttp import web
from google.genai import models as google_models
from google.genai import types as google_types
from PIL import Image

import asyncio
import base64
import pytest

from test_config_i18n import _bootstrap_plugin_package

_bootstrap_plugin_package()

from maimai_drawpic_pkg.src.maimai_drawpic.domain.configuration.models import DrawpicConfig  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.application.drawing import DrawService  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.infrastructure.http import sanitize_provider_text  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.application.routing import ProviderRouter  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.infrastructure.providers.aliyun import AliyunImage  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.infrastructure.providers.comfyui import ComfyUIImage  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.infrastructure.providers.gemini import GoogleImage  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.infrastructure.providers.novelai import NovelAIImage  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.infrastructure.providers.openai import OpenaiImage  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.infrastructure.providers.siliconflow import SiliconFlowImage  # noqa: E402
from maimai_drawpic_pkg.src.maimai_drawpic.infrastructure.providers.volcengine import VolcengineImage  # noqa: E402


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+"
    "A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_google_default_config_serializes_through_developer_api_converter() -> None:
    """SDK 字段存在不代表 Gemini API 支持；真实转换器也必须接受默认配置。"""

    config = DrawpicConfig()
    provider = ProviderRouter(config).create_google_provider()
    request_config = provider._build_generate_content_config()
    assert request_config.image_config is None
    configured = GoogleImage(api_key="test-key", image_size="2K", aspect_ratio="16:9", seed=7)
    request = configured._build_generate_content_config()
    converted = google_models._ImageConfig_to_mldev(request.image_config)
    assert converted == {"imageSize": "2K", "aspectRatio": "16:9"}
    assert request.seed == 7


def test_google_client_closed_and_only_final_images_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实 SDK 响应中可能带思考图片；客户端退出与最终图片提取均需正确。"""

    import maimai_drawpic_pkg.src.maimai_drawpic.infrastructure.providers.gemini as module

    response = google_types.GenerateContentResponse(candidates=[google_types.Candidate(
        content=google_types.Content(parts=[
            google_types.Part(thought=True, inline_data=google_types.Blob(data=b"thought", mime_type="image/png")),
            google_types.Part(inline_data=google_types.Blob(data=PNG, mime_type="image/png")),
        ])
    )])
    closed: List[bool] = []
    calls: List[Dict[str, Any]] = []

    class Client:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs
            self.models = self

        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            closed.append(True)

        def generate_content(self, **kwargs: Any):
            calls.append(kwargs)
            return response

    monkeypatch.setattr(module.genai, "Client", Client)
    provider = GoogleImage(api_key="test-key", negative_prompt="blurry")
    assert provider.edit_images("keep subject", "gemini-3-pro-image", [PNG, PNG]) == [PNG]
    assert len(calls[0]["contents"]) == 3
    assert "Negative prompt: blurry" in calls[0]["contents"][-1]
    assert closed == [True]


def test_google_unknown_extra_parameter_is_not_silently_ignored() -> None:
    with pytest.raises(ValueError, match="不支持"):
        GoogleImage(api_key="test", extra_parameters={"output_mime_type": "image/png"})._build_generate_content_config()


@pytest.mark.parametrize("model", ["gpt-image-2", "gpt-image-2-2026-04-21", "gpt-image-2.5-flare"])
def test_gpt_image_unsupported_legacy_fields_are_removed(model: str) -> None:
    provider = OpenaiImage(
        api_key="test", response_format="url", moderation="low", output_format="png",
        extra_parameters={"input_fidelity": "high", "output_compression": 50, "model": "wrong-model"},
    )
    body = provider._build_images_generation_payload("prompt", model, 1)
    assert body["model"] == model
    assert body["moderation"] == "low"
    assert not {"response_format", "input_fidelity", "output_compression"} & set(body)


def test_openai_edit_keeps_moderation_and_serializes_json_values() -> None:
    class Provider(OpenaiImage):
        fields: Dict[str, str]

        async def _post_form(self, url, form):
            del url
            self.fields = {field[0]["name"]: field[2] for field in form._fields if not isinstance(field[2], bytes)}
            return {"data": []}

    provider = Provider(api_key="test", moderation="low", extra_parameters={"custom_bool": False})
    asyncio.run(provider._post_edit_form_with_fallback(
        url="https://example/v1/images/edits", model="gpt-image-2", prompt="edit", image_bytes_list=[PNG], n=1,
    ))
    assert provider.fields["moderation"] == "low"
    assert provider.fields["custom_bool"] == "false"


def test_siliconflow_removes_retired_parameters_and_uses_model_guidance() -> None:
    provider = SiliconFlowImage(api_key="test", cfg=4, extra_parameters={
        "batch_size": 3, "output_format": "png", "cfg": 4, "model": "wrong-model",
    })
    qwen = provider._build_payload("prompt", "Qwen/Qwen-Image-Edit-2509", 1)
    assert qwen["cfg"] == 4
    assert not {"batch_size", "output_format", "image_size", "guidance_scale"} & set(qwen)
    kolors = provider._build_payload("prompt", "Kwai-Kolors/Kolors", 1)
    assert kolors["guidance_scale"] == 7.5
    assert "cfg" not in kolors
    assert kolors["model"] == "Kwai-Kolors/Kolors"


def test_siliconflow_three_references_are_submitted_once() -> None:
    class Provider(SiliconFlowImage):
        calls: List[Dict[str, Any]] = []

        async def _post_json(self, url, payload):
            del url
            self.calls.append(payload)
            return {"images": [{"b64_json": base64.b64encode(PNG).decode("ascii")}]}

    provider = Provider(api_key="test")
    assert asyncio.run(provider.edit_images("edit", "Qwen/Qwen-Image-Edit-2509", [PNG] * 3)) == [PNG]
    assert len(provider.calls) == 1
    assert {"image", "image2", "image3"} <= provider.calls[0].keys()


@pytest.mark.parametrize("watermark_enabled", [None, True, False])
def test_siliconflow_watermark_reaches_generation_and_edit_headers(
    unused_tcp_port: int, monkeypatch: pytest.MonkeyPatch, watermark_enabled: Optional[bool],
) -> None:
    """经过配置与路由构造后，在隔离 HTTP 服务核对两个模式的真实请求头。"""

    async def run() -> None:
        requests: List[Dict[str, Any]] = []

        async def receive(request: web.Request) -> web.Response:
            requests.append({"headers": request.headers, "body": await request.json()})
            return web.json_response({"images": [{"b64_json": base64.b64encode(PNG).decode("ascii")}]})

        app = web.Application()
        app.router.add_post("/v1/images/generations", receive)
        runner = web.AppRunner(app)
        await runner.setup()
        try:
            await web.TCPSite(runner, "127.0.0.1", unused_tcp_port).start()
            monkeypatch.setattr(SiliconFlowImage, "_BASE_URL", f"http://127.0.0.1:{unused_tcp_port}")
            values: Dict[str, Any] = {"api_key": "fixture-siliconflow-key"}
            if watermark_enabled is not None:
                values["watermark_enabled"] = watermark_enabled
            config = DrawpicConfig.model_validate({"siliconflow": values})
            provider = ProviderRouter(config).create_siliconflow_provider()
            assert await provider.generate_images("a cat", "Kwai-Kolors/Kolors") == [PNG]
            assert await provider.edit_images("keep the subject", "Qwen/Qwen-Image-Edit-2509", [PNG]) == [PNG]
            assert len(requests) == 2
            for request in requests:
                assert request["headers"].get("X-Enable-Watermark") == ("0" if watermark_enabled is False else None)
                assert request["headers"]["Authorization"] == "Bearer fixture-siliconflow-key"
                assert request["headers"]["Content-Type"] == "application/json"
                assert not {"watermark_enabled", "X-Enable-Watermark"} & request["body"].keys()
            assert "image" not in requests[0]["body"] and requests[1]["body"]["image"].startswith("data:image/png;base64,")
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_novelai_auth_failure_is_not_retried_with_another_size() -> None:
    class Provider(NovelAIImage):
        calls = 0

        async def _post_generation(self, url, payload):
            del url, payload
            self.calls += 1
            raise RuntimeError("HTTP 401 invalid token")

    provider = Provider(api_key="test")
    with pytest.raises(RuntimeError, match="401"):
        asyncio.run(provider.edit_images("edit", "nai-diffusion-5-full", [PNG]))
    assert provider.calls == 1


def test_novelai_invalid_size_override_is_not_silently_replaced() -> None:
    provider = NovelAIImage(api_key="test", model_size_overrides={"nai-diffusion-5-full": "-64x1024"})
    with pytest.raises(ValueError, match="正整数"):
        provider._resolve_size("nai-diffusion-5-full")


def test_output_image_validation_runs_outside_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    import maimai_drawpic_pkg.src.maimai_drawpic.application.drawing.planning as module

    event_loop_thread = get_ident()
    validation_threads: List[int] = []
    original_validate = module.validate_result_images

    def validate(data: List[bytes]) -> List[bytes]:
        validation_threads.append(get_ident())
        return original_validate(data)

    async def generate() -> List[bytes]:
        return [PNG]

    monkeypatch.setattr(module, "validate_result_images", validate)
    monkeypatch.setattr(DrawService, "resolve_request_timeout_seconds", lambda _self: 5)
    service = DrawService.__new__(DrawService)
    assert asyncio.run(service.run_provider_call(generate)) == [PNG]
    assert validation_threads and all(thread != event_loop_thread for thread in validation_threads)


@pytest.mark.parametrize("provider_name,model,count", [
    ("novelai", "nai-diffusion-5-full", 2),
    ("comfyui", "comfyui", 2),
    ("google", "gemini-2.5-flash-image", 4),
    ("siliconflow", "Kwai-Kolors/Kolors", 2),
    ("siliconflow", "Qwen/Qwen-Image-Edit-2509", 4),
])
def test_router_rejects_excess_references(provider_name: str, model: str, count: int) -> None:
    config = DrawpicConfig()
    if provider_name == "comfyui":
        config.comfyui.enabled = True
    else:
        config.__dict__[provider_name].models = [model]
    router = ProviderRouter(config)
    with pytest.raises(ValueError, match="参考图片"):
        router.validate_source_image_count(model, count)


def test_aliyun_model_without_negative_field_retains_negative_content() -> None:
    provider = AliyunImage(api_key="test", negative_prompt="blurry")
    body = provider._build_payload("subject", "kling/kling-v3-image-generation", "draw", [], 1)
    assert "Negative prompt: blurry" in body["input"]["messages"][0]["content"][0]["text"]
    assert "negative_prompt" not in body["parameters"]


def test_ark_extra_parameters_cannot_bypass_group_limit() -> None:
    provider = VolcengineImage(api_key="test", max_images=4, extra_parameters={
        "sequential_image_generation": "auto", "sequential_image_generation_options": {"max_images": 100},
    })
    body = provider._build_payload("prompt", "doubao-seedream-4-5-251128", 1, source_image_count=14)
    assert body["sequential_image_generation_options"]["max_images"] == 1


def test_comfy_upload_uses_actual_jpeg_mime_and_extension() -> None:
    provider = ComfyUIImage.__new__(ComfyUIImage)
    provider.logger = None
    fields: Dict[str, Any] = {}

    async def post_form(path, form):
        del path
        field = form._fields[0]
        fields.update({"filename": field[0]["filename"], "mime": field[1]["Content-Type"]})
        return {"name": field[0]["filename"], "type": "input", "subfolder": ""}

    provider._post_form = post_form
    jpeg = BytesIO()
    Image.new("RGB", (8, 8)).save(jpeg, format="JPEG")
    result = asyncio.run(provider._upload_image(jpeg.getvalue()))
    assert result.endswith(".jpg")
    assert fields["mime"] == "image/jpeg"


def test_provider_diagnostics_remove_secrets_and_signed_urls() -> None:
    text = sanitize_provider_text(
        "bad test-token Bearer hidden https://user:password@example.com/img.png?Signature=secret "
        + "data:image/png;base64," + "A" * 120,
        "test-token",
    )
    for secret in ["test-token", "hidden", "password", "Signature", "secret", "A" * 80]:
        assert secret not in text
