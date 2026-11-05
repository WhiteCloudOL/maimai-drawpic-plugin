"""NAI 多角色反向词的归属、实例开关和改写失败边界，不访问真实平台。"""

from copy import deepcopy
import asyncio
import base64
import json

import pytest

from test_routing_review_fixes import add_provider, module, set_settings
from test_workspace import image_bytes, make_plugin as make_plugin


@pytest.mark.parametrize("model", ["nai-diffusion-4-full", "nai-diffusion-4-5-full", "nai-diffusion-5-full"])
@pytest.mark.parametrize("task_type", ["draw", "edit_image"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("rewrite_enabled", [False, True])
def test_novelai_character_negatives_keep_binding_in_actual_payload(
    make_plugin, monkeypatch, model, task_type, enabled, rewrite_enabled,
):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            negative = {
                "caption": {
                    "base_caption": "全图，水印",
                    "char_captions": [
                        {"char_caption": "眼镜，水印，眼镜", "centers": [{"x": 0.2, "y": 0.4}]},
                        {"char_caption": "", "centers": [{"x": 0.4, "y": 0.4}]},
                        {"centers": [{"x": 0.5, "y": 0.4}]},
                        {"char_caption": "帽衫，水印，帽衫", "centers": [{"x": 0.8, "y": 0.4}]},
                        {"char_caption": "眼镜，水印", "centers": [{"x": 0.9, "y": 0.4}]},
                    ],
                },
                "use_coords": True,
                "use_order": False,
                "legacy_uc": False,
            }
            positive = {
                "caption": {
                    "base_caption": "a scene with five characters",
                    "char_captions": [
                        {"char_caption": f"character {index}", "centers": deepcopy(character["centers"])}
                        for index, character in enumerate(negative["caption"]["char_captions"], start=1)
                    ],
                },
                "use_coords": True,
                "use_order": False,
            }
            await add_provider(
                plugin, "novelai", "NAI", models=[model], negative_prompt_enabled=enabled,
                negative_prompt="默认，水印", rewrite_prompt_to_english=rewrite_enabled,
                extra_parameters=[
                    f"v4_negative_prompt={json.dumps(negative, ensure_ascii=False)}",
                    f"v4_prompt={json.dumps(positive)}", "custom_flag=false",
                ],
            )
            await plugin.workspace_settings_save(json.dumps({"style": {"presets": [{
                "name": "fixture", "positive_prompt_template": "{prompt}",
                "negative_prompt_template": "风格，{negative_prompt}",
            }]}}), plugin._platform_store.revision)
            original_disk = plugin._platform_store.path.read_bytes()
            original_records = deepcopy(plugin._platform_store.providers)
            prompts, payloads = [], []
            translations = {
                "猫": "a cat", "风格": "style", "请求": "request", "水印": "watermark",
                "默认": "default", "全图": "global", "眼镜": "glasses", "帽衫": "hoodie",
            }

            async def rewrite(rendered, **kwargs):
                text = rendered.rsplit("用户提示词：\n", 1)[1]
                prompts.append(text)
                return {"success": True, "response": ", ".join(
                    translations[part.strip()] for part in text.split(",")
                )}

            async def generate(provider, prompt, selected_model, *args):
                payloads.append(provider._build_payload(
                    prompt=prompt, model=selected_model, action="img2img" if task_type == "edit_image" else "generate", n=1,
                ))
                return [image_bytes()]

            monkeypatch.setattr(plugin.ctx.llm, "generate", rewrite)
            provider_class = module("infrastructure.providers.novelai").NovelAIImage
            monkeypatch.setattr(provider_class, "generate_images", generate)
            monkeypatch.setattr(provider_class, "edit_images", generate)
            service = plugin._require_draw_service()
            receipt = await plugin.drawpic_submit(
                "猫", negative_prompt="请求，水印", style="fixture", task_type=task_type,
                source_images=[base64.b64encode(image_bytes()).decode("ascii")] if task_type == "edit_image" else None,
            )
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert result["status"] == "completed", result["message"]
            parameters = payloads[0]["parameters"]
            assert parameters["v4_prompt"] == positive
            assert parameters["custom_flag"] is False
            base = "风格, 请求, 水印, 默认, 全图" if enabled else "风格"
            if rewrite_enabled:
                base = ", ".join(translations[part.strip()] for part in base.split(","))
            assert parameters["negative_prompt"] == base
            if enabled:
                expected = deepcopy(negative)
                expected["caption"]["base_caption"] = base
                characters = expected["caption"]["char_captions"]
                characters[0]["char_caption"] = "glasses, watermark" if rewrite_enabled else "眼镜, 水印"
                characters[3]["char_caption"] = "hoodie, watermark" if rewrite_enabled else "帽衫, 水印"
                characters[4]["char_caption"] = "glasses, watermark" if rewrite_enabled else "眼镜, 水印"
                assert parameters["v4_negative_prompt"] == expected
            else:
                assert parameters["v4_negative_prompt"] == {"caption": {"base_caption": base, "char_captions": []}}
            expected_calls = 5 if enabled else 2
            assert len(prompts) == (expected_calls if rewrite_enabled else 0)
            if enabled and rewrite_enabled:
                assert prompts[-3:] == ["眼镜, 水印", "帽衫, 水印", "眼镜, 水印"]
            assert plugin._platform_store.providers == original_records
            assert plugin._platform_store.path.read_bytes() == original_disk
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_novelai_character_rewrite_failure_reports_index_and_stops_generation(make_plugin, monkeypatch, caplog):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            negative = {"caption": {"char_captions": [
                {"char_caption": "眼镜", "centers": [{"x": 0.2, "y": 0.5}]},
                {"char_caption": "帽衫", "centers": [{"x": 0.8, "y": 0.5}]},
            ]}}
            await add_provider(
                plugin, "novelai", "NAI", models=["nai-diffusion-5-full"],
                negative_prompt_enabled=True, negative_prompt="", rewrite_prompt_to_english=True,
                extra_parameters=[f"v4_negative_prompt={json.dumps(negative, ensure_ascii=False)}"],
            )
            original_disk = plugin._platform_store.path.read_bytes()

            async def rewrite(rendered, **kwargs):
                text = rendered.rsplit("用户提示词：\n", 1)[1]
                if text == "帽衫":
                    raise ValueError("fixture-key role rewrite failed")
                return {"success": True, "response": "glasses" if text == "眼镜" else "a scene"}

            async def unexpected_generate(*args, **kwargs):
                pytest.fail("A role rewrite failure must stop before generation")

            monkeypatch.setattr(plugin.ctx.llm, "generate", rewrite)
            monkeypatch.setattr(module("infrastructure.providers.novelai").NovelAIImage, "generate_images", unexpected_generate)
            service = plugin._require_draw_service()
            receipt = await plugin.drawpic_submit("a scene")
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert result["status"] == "failed"
            assert "第 2 个角色反向提示词英文改写失败" in result["message"]
            assert "fixture-key" not in result["message"]
            assert "role_index=2" in caplog.text
            assert "fixture-key" not in caplog.text
            assert plugin._platform_store.path.read_bytes() == original_disk
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_novelai_base_only_extension_keeps_empty_character_array(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            await add_provider(
                plugin, "novelai", "NAI", models=["nai-diffusion-5-full"], negative_prompt="",
                extra_parameters=['v4_negative_prompt={"caption":{"base_caption":"blurry"},"use_order":true}'],
            )
            requests = []

            async def generate(provider, prompt, selected_model, n=1):
                requests.append(provider._build_payload(prompt=prompt, model=selected_model, action="generate", n=n))
                return [image_bytes()]

            monkeypatch.setattr(module("infrastructure.providers.novelai").NovelAIImage, "generate_images", generate)
            service = plugin._require_draw_service()
            receipt = await plugin.drawpic_submit("a scene")
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert result["status"] == "completed", result["message"]
            assert requests[0]["parameters"]["v4_negative_prompt"] == {
                "caption": {"base_caption": "blurry", "char_captions": []}, "use_order": True,
            }
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("primary_enabled", [False, True])
def test_novelai_fallback_reads_character_negatives_from_its_own_instance(make_plugin, monkeypatch, primary_enabled):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            for name, enabled, text in (("Primary", primary_enabled, "first"), ("Backup", not primary_enabled, "second")):
                negative = {"caption": {"char_captions": [{"char_caption": text, "centers": [{"x": 0.3, "y": 0.5}]}]}}
                await add_provider(
                    plugin, "novelai", name, models=["nai-diffusion-5-full"], negative_prompt_enabled=enabled,
                    negative_prompt="", extra_parameters=[f"v4_negative_prompt={json.dumps(negative)}"],
                )
            await set_settings(plugin, request_retry_count=0, fallback_models=["Backup/nai-diffusion-5-full"])
            requests = []

            async def generate(provider, prompt, selected_model, n=1):
                payload = provider._build_payload(prompt=prompt, model=selected_model, action="generate", n=n)
                requests.append(payload["parameters"]["v4_negative_prompt"]["caption"]["char_captions"])
                if len(requests) == 1:
                    raise module("domain.errors").ProviderConnectionError("connection not established")
                return [image_bytes()]

            monkeypatch.setattr(module("infrastructure.providers.novelai").NovelAIImage, "generate_images", generate)
            service = plugin._require_draw_service()
            receipt = await plugin.drawpic_submit("a scene")
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert result["status"] == "completed", result["message"]
            expected_first = [{"char_caption": "first", "centers": [{"x": 0.3, "y": 0.5}]}]
            expected_second = [{"char_caption": "second", "centers": [{"x": 0.3, "y": 0.5}]}]
            assert requests == [expected_first if primary_enabled else [], [] if primary_enabled else expected_second]
        finally:
            await plugin.on_unload()

    asyncio.run(run())


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("characters", [None, {}, ["wrong"], [{"char_caption": 123}]])
def test_novelai_invalid_character_shapes_are_ignored_only_when_disabled(make_plugin, monkeypatch, enabled, characters):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            negative = {"caption": {"char_captions": characters}}
            await add_provider(
                plugin, "novelai", "NAI", models=["nai-diffusion-5-full"], negative_prompt_enabled=enabled,
                negative_prompt="", extra_parameters=[f"v4_negative_prompt={json.dumps(negative)}"],
            )
            requests = []

            async def generate(provider, prompt, selected_model, n=1):
                requests.append(provider._build_payload(prompt=prompt, model=selected_model, action="generate", n=n))
                return [image_bytes()]

            monkeypatch.setattr(module("infrastructure.providers.novelai").NovelAIImage, "generate_images", generate)
            service = plugin._require_draw_service()
            receipt = await plugin.drawpic_submit("a scene")
            await asyncio.gather(*tuple(service.background_tasks))
            result = await plugin.drawpic_task(receipt["task_id"])
            assert result["status"] == ("failed" if enabled else "completed")
            assert len(requests) == (0 if enabled else 1)
            if enabled:
                assert "扩展参数 v4_negative_prompt" in result["message"]
        finally:
            await plugin.on_unload()

    asyncio.run(run())
