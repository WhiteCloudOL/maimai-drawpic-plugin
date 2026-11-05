"""实例路由与异步错误契约回归；临时配置、内存传输，不调用平台或聊天。"""

import asyncio
import base64
import importlib
import json

import pytest

from test_workspace import _PACKAGE, image_bytes, make_plugin as make_plugin, storage


def module(name):
    return importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.{name}")


async def add_provider(plugin, kind, name, **values):
    config = storage.WorkspaceConfigStore.platform_model(kind)().model_dump(mode="json")
    config.update(api_key="fixture-key", rewrite_prompt_to_english=False)
    config.update(values)
    return await plugin.workspace_provider_save(
        json.dumps({"kind": kind, "name": name, "config": config}), plugin._platform_store.revision
    )


async def set_settings(plugin, **values):
    settings = storage.common_config(plugin.config.model_dump(mode="json"))
    settings["general"].update(private_quota_enabled=False, **values)
    await plugin.workspace_settings_save(json.dumps(settings), plugin._platform_store.revision)


@pytest.mark.parametrize("kind", ["openai", "siliconflow", "novelai"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("style_template", [None, "", "{negative_prompt}", "水印，{negative_prompt}"])
def test_negative_prompts_apply_instance_policy_before_style_and_translation(
    make_plugin, monkeypatch, kind, enabled, style_template,
):
    """从公开提交入口验证过滤、独立风格、默认词去重和最终请求的英文内容。"""

    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            model = "nai-diffusion-3" if kind == "novelai" else "fixture-image"
            await add_provider(
                plugin, kind, "Drawing", models=[model], negative_prompt_enabled=enabled,
                negative_prompt="水印，文字", rewrite_prompt_to_english=True,
            )
            await plugin.workspace_settings_save(json.dumps({"style": {"presets": [{
                "name": "fixture", "positive_prompt_template": "{prompt}",
                "negative_prompt_template": style_template if style_template is not None else "{negative_prompt}",
            }]}}), plugin._platform_store.revision)
            service = plugin._require_draw_service()
            rewrites, requests = [], []
            translations = {"猫": "a cat", "水印": "watermark", "模糊": "blurry", "文字": "text"}

            async def rewrite(prompt, provider, selected_model):
                assert service.router.should_rewrite_prompt_to_english(provider, selected_model)
                rewrites.append(prompt)
                return ", ".join(translations[term.strip()] for term in prompt.split(","))

            async def generate(provider, prompt, model, n=1):
                negative = "" if kind == "openai" else provider.negative_prompt
                requests.append((prompt, negative))
                return [image_bytes()]

            provider_class = {
                "openai": ("openai", "OpenaiImage"),
                "siliconflow": ("siliconflow", "SiliconFlowImage"),
                "novelai": ("novelai", "NovelAIImage"),
            }[kind]
            provider_module = module(f"infrastructure.providers.{provider_class[0]}")
            monkeypatch.setattr(provider_module.__dict__[provider_class[1]], "generate_images", generate)
            monkeypatch.setattr(service, "rewrite_prompt_to_english_if_needed", rewrite)
            receipt = await plugin.drawpic_submit(
                "猫", negative_prompt="模糊，水印", style="fixture" if style_template is not None else "none",
            )
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert result["status"] == "completed", result["message"]
            expected_terms = ["watermark"] if style_template == "水印，{negative_prompt}" else []
            if enabled:
                expected_terms.extend(["blurry", "watermark", "text"])
            expected_negative = ", ".join(dict.fromkeys(expected_terms))
            assert len(rewrites) == (2 if expected_negative else 1)
            assert requests == [(
                "a cat" + (f", Negative prompt: {expected_negative}" if kind == "openai" and expected_negative else ""),
                "" if kind == "openai" else expected_negative,
            )]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("task_type", ["draw", "edit_image"])
@pytest.mark.parametrize("prompt_mode", ["single_prompt", "positive_negative"])
@pytest.mark.parametrize("enabled", [False, True])
def test_comfyui_negative_prompts_keep_task_defaults_and_style_separate(
    make_plugin, monkeypatch, task_type, prompt_mode, enabled,
):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            config = storage.WorkspaceConfigStore.platform_model("comfyui")().model_dump(mode="json")
            config.update(
                enabled=True, negative_prompt_enabled=enabled,
                negative_prompt="watermark", rewrite_prompt_to_english=False,
                t2i_prompt_mode=prompt_mode, i2i_prompt_mode=prompt_mode,
                t2i_negative_prompt="text", i2i_negative_prompt="signature",
            )
            saved = await plugin.workspace_provider_save(json.dumps({
                "kind": "comfyui", "name": "Workflow", "config": config,
            }), plugin._platform_store.revision)
            assert saved["saved"], saved
            requests = []

            async def generate(provider, prompt, model, *args):
                negative = provider.i2i_negative_prompt if task_type == "edit_image" else provider.t2i_negative_prompt
                requests.append((prompt, negative))
                return [image_bytes()]

            provider_class = module("infrastructure.providers.comfyui").ComfyUIImage
            monkeypatch.setattr(provider_class, "generate_images", generate)
            monkeypatch.setattr(provider_class, "edit_images", generate)
            monkeypatch.setattr(provider_class, "validate_task_configuration", lambda *args: None)
            service = plugin._require_draw_service()
            await service._run_image_request_attempt(
                attempt=module("application.drawing").ImageRequestAttempt(
                    model="Workflow/comfyui", provider_name="comfyui", openai_compatibility_mode="",
                ),
                prompt="a cat", task_id="fixture-task", task_type=task_type,
                source_image_bytes_list=[image_bytes()] if task_type == "edit_image" else [],
                source_image_urls=[""] if task_type == "edit_image" else [], matched_message_id="",
                request_negative_prompt="blurry", style_negative_prompt_template="watermark, {negative_prompt}",
            )
            negative = "watermark" + (", blurry" if enabled else "")
            if prompt_mode == "positive_negative" and enabled:
                negative += ", signature" if task_type == "edit_image" else ", text"
            assert requests == [(
                "a cat" + (f", Negative prompt: {negative}" if prompt_mode == "single_prompt" else ""),
                "" if prompt_mode == "single_prompt" else negative,
            )]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_negative_prompt_fallback_uses_each_instance_settings(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            await add_provider(plugin, "openai", "Primary", models=["first"], negative_prompt_enabled=False)
            await add_provider(
                plugin, "openai", "Backup", models=["second"],
                negative_prompt_enabled=True, negative_prompt="watermark, text",
            )
            await set_settings(plugin, fallback_models=["Backup/second"], request_retry_count=0)
            requests = []

            async def post(provider, url, payload):
                requests.append(payload["prompt"])
                if payload["model"] == "first":
                    raise module("domain.errors").ProviderConnectionError("connection not established")
                return {"data": [{"b64_json": base64.b64encode(image_bytes()).decode("ascii")}]}

            monkeypatch.setattr(module("infrastructure.providers.openai").OpenaiImage, "_post_json", post)
            service = plugin._require_draw_service()
            receipt = await plugin.drawpic_submit("a cat", negative_prompt="blurry, watermark")
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert result["status"] == "completed", result["message"]
            assert requests == ["a cat", "a cat, Negative prompt: blurry, watermark, text"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_negative_prompt_rewrite_failure_stops_submission_and_redacts_errors(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            await add_provider(
                plugin, "openai", "Drawing", models=["image"],
                negative_prompt_enabled=True, negative_prompt="secret negative terms", rewrite_prompt_to_english=True,
            )
            service = plugin._require_draw_service()

            async def rewrite(prompt, **kwargs):
                if "secret negative terms" in prompt:
                    raise ValueError("fixture-key translation failure")
                return {"success": True, "response": "a cat"}

            async def unexpected_post(*args, **kwargs):
                pytest.fail("Rewriting failed before any generation request was sent")

            monkeypatch.setattr(plugin.ctx.llm, "generate", rewrite)
            monkeypatch.setattr(module("infrastructure.providers.openai").OpenaiImage, "_post_json", unexpected_post)
            receipt = await plugin.drawpic_submit("a cat")
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert result["status"] == "failed"
            assert "反向提示词英文改写失败" in result["message"]
            assert "fixture-key" not in result["message"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def mock_chat(plugin, monkeypatch):
    async def context(**kwargs):
        return {"stream_id": "fixture-stream", "user_id": "12345", "group_id": "", "platform": "qq"}

    async def send(**kwargs):
        return len(kwargs["image_bytes_list"])

    stream = plugin._require_stream_service()
    monkeypatch.setattr(stream, "resolve_live_stream_context", context)
    monkeypatch.setattr(stream, "send_generated_images_with_fallback", send)


@pytest.mark.parametrize(
    "entry,session_mode,request_mode,expected_modes",
    [
        ("workspace", "", "", ["images_api", "chat_completions"]),
        ("chat", "", "", ["images_api", "chat_completions"]),
        ("chat", "images_api", "", ["images_api", "images_api"]),
        ("chat", "images_api", "chat_completions", ["chat_completions", "chat_completions"]),
    ],
)
def test_openai_fallback_keeps_instance_defaults_and_explicit_overrides(
    make_plugin, monkeypatch, entry, session_mode, request_mode, expected_modes
):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            await add_provider(
                plugin, "openai", "Primary", models=["primary-image"],
                base_url="https://primary.invalid/v1", default_openai_compatibility_mode="images_api",
            )
            await add_provider(
                plugin, "openai", "Backup", models=["backup-image"],
                base_url="https://backup.invalid/v1", default_openai_compatibility_mode="chat_completions",
            )
            await set_settings(plugin, fallback_models=["Backup/backup-image"], request_retry_count=0)
            calls = []
            errors = module("domain.errors")
            encoded = base64.b64encode(image_bytes()).decode("ascii")

            async def post(self, url, payload):
                calls.append((self.compatibility_mode, url, payload["model"]))
                if "primary.invalid" in url:
                    raise errors.ProviderConnectionError("connection not established")
                if url.endswith("/chat/completions"):
                    return {"choices": [{"message": {"content": "data:image/png;base64," + encoded}}]}
                return {"data": [{"b64_json": encoded}]}

            monkeypatch.setattr(module("infrastructure.providers.openai").OpenaiImage, "_post_json", post)
            service = plugin._require_draw_service()
            if entry == "workspace":
                receipt = await plugin.drawpic_submit("a cat")
            else:
                mock_chat(plugin, monkeypatch)
                plugin._set_session_preference(
                    "fixture-stream", "12345", openai_compatibility_mode=session_mode
                )
                receipt = await plugin._start_background_image_request(
                    prompt="a cat", stream_id="fixture-stream", user_id="12345",
                    requested_openai_compatibility_mode=request_mode,
                )
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert result["status"] == "completed", result["message"]
            assert [item[0] for item in calls] == expected_modes
            assert [item[2] for item in calls] == ["primary-image", "backup-image"]
            assert [item[1].rsplit("/v1", 1)[1] for item in calls] == [
                "/chat/completions" if mode == "chat_completions" else "/images/generations"
                for mode in expected_modes
            ]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("explicit", [False, True])
def test_novelai_fallback_keeps_each_instances_mode_and_artist_tags(make_plugin, monkeypatch, explicit):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            for name, mode in [("Primary", "anime"), ("Backup", "furry")]:
                await add_provider(
                    plugin, "novelai", name, models=["nai-diffusion-3", "nai-diffusion-furry-3"],
                    base_url=f"https://{name.lower()}.invalid", default_mode=mode,
                    default_artist_tags=f"artist:{name.lower()}",
                )
            await set_settings(plugin, fallback_models=["Backup/nai-diffusion-3"], request_retry_count=0)
            calls = []
            errors = module("domain.errors")

            async def post(self, url, payload):
                calls.append((self.mode, self.artist_tags, payload["model"], payload["input"]))
                if "primary.invalid" in url:
                    raise errors.ProviderConnectionError("connection not established")
                return image_bytes(), "image/png"

            monkeypatch.setattr(module("infrastructure.providers.novelai").NovelAIImage, "_post_generation", post)
            mock_chat(plugin, monkeypatch)
            if explicit:
                plugin._set_session_preference(
                    "fixture-stream", "12345", novelai_mode="anime", novelai_artist_tags="artist:session"
                )
            service = plugin._require_draw_service()
            receipt = await plugin._start_background_image_request(
                prompt="a cat", stream_id="fixture-stream", user_id="12345",
            )
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert result["status"] == "completed", result["message"]
            assert [item[:3] for item in calls] == (
                [("anime", "artist:session", "nai-diffusion-3")] * 2 if explicit else [
                    ("anime", "artist:primary", "nai-diffusion-3"),
                    ("furry", "artist:backup", "nai-diffusion-furry-3"),
                ]
            )
            for _, artist, _, prompt in calls:
                assert artist in prompt
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("default", ["sample-image", "missing-image"])
def test_nonempty_invalid_default_rejects_submit_but_discovery_remains_usable(make_plugin, default):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            await add_provider(plugin, "openai", "Second", models=["sample-image"])
            await set_settings(plugin, default_model=default)
            await plugin.on_unload()
            plugin = make_plugin()
            await plugin.on_load()
            router = plugin._require_router()
            with pytest.raises(ValueError, match="平台"):
                router.resolve_model_name()
            with pytest.raises(ValueError, match="平台"):
                await plugin.drawpic_submit("a cat")
            assert plugin._task_store.get_task_count() == 0
            assert router.resolve_model_name("Second/sample-image") == "Second/sample-image"
            for result in [await plugin.drawpic_models(), await plugin.workspace_bootstrap()]:
                assert len(result["models"]) == 2
                assert result["default_model"] == ""
                assert result["default_model_error"]
            await set_settings(plugin, default_model="Second/sample-image")
            assert plugin._require_router().resolve_default_model() == "Second/sample-image"
            await set_settings(plugin, default_model="")
            assert plugin._require_router().resolve_default_model() == plugin._require_router().get_all_models()[0]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_unique_legacy_default_short_name_remains_supported(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            router = plugin._require_router()
            assert router.resolve_default_model() == router.resolve_model_name("sample-image")
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_model_discovery_reports_real_upstream(make_plugin):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            await add_provider(plugin, "openai", "Alias", models=["gpt-image-2.5", "plain-image"])
            await add_provider(plugin, "novelai", "Novel", models=["nai-diffusion-3"])
            result = await plugin.drawpic_models()
            models = {item["name"]: item for item in result["models"]}
            assert models["Alias/gpt-image-2.5"]["upstream_model"] == "gpt-image-2.5"
            assert models["Alias/gpt-image-2.5"]["platform_name"] == "Alias"
            assert models["Alias/plain-image"]["upstream_model"] == "plain-image"
            assert models["Novel/nai-diffusion-3"]["upstream_model"] == "nai-diffusion-3"
            route = plugin._require_router().resolve_openai_model_route("Alias/gpt-image-2.5")
            assert route.upstream_model == models["Alias/gpt-image-2.5"]["upstream_model"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("nested", [True, False])
@pytest.mark.parametrize("code", ["DataInspectionFailed", "InvalidParameter", "server_busy"])
def test_vidu_terminal_error_keeps_details_and_never_resubmits(make_plugin, monkeypatch, nested, code):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            model = "vidu/vidu-image_reference2image"
            await add_provider(plugin, "aliyun", "Vidu", models=[model])
            await add_provider(plugin, "openai", "Backup", models=["backup-image"])
            await set_settings(plugin, fallback_models=["Backup/backup-image"], request_retry_count=2)
            calls = []

            async def request(self, method, url, **kwargs):
                calls.append(method)
                if method == "POST":
                    return {"output": {"task_id": "accepted-123"}, "request_id": "submit-123"}
                error = {"code": code, "message": "fixture terminal failure"}
                response = {
                    "request_id": "query-123",
                    "output": {"task_id": "accepted-123", "task_status": "FAILED"},
                }
                if nested:
                    response["output"].update(error)
                    response.update(code="OuterError", message="less specific outer message")
                else:
                    response.update(error)
                return response

            async def unexpected_post(*args, **kwargs):
                pytest.fail("An accepted Vidu task must never submit to a fallback")

            monkeypatch.setattr(module("infrastructure.providers.aliyun").AliyunImage, "_request_json", request)
            monkeypatch.setattr(module("infrastructure.providers.openai").OpenaiImage, "_post_json", unexpected_post)
            service = plugin._require_draw_service()
            receipt = await service.start_background_image_request(
                prompt="a cat", stream_id="", resolved_model=f"Vidu/{model}",
                resolved_openai_mode="", provider_name="aliyun",
                source_image_bytes_list=[image_bytes()], source_image_urls=["https://source.invalid/image.png"],
            )
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert calls == ["POST", "GET"]
            assert result["status"] == ("rejected" if code == "DataInspectionFailed" else "failed")
            for detail in (code, "fixture terminal failure", "accepted-123", "query-123"):
                assert detail in result["message"]
            record = plugin._task_store.get_task(receipt["task_id"])
            assert not record.error["retry_submit"]
            assert record.error["code"] == (
                "MODERATION_REJECTED" if code == "DataInspectionFailed" else "RESULT_UNAVAILABLE"
            )
        finally:
            await plugin.on_unload()

    asyncio.run(run())
