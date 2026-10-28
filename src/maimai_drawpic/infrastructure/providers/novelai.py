from __future__ import annotations

from io import BytesIO
from typing import Any
import aiohttp
import asyncio
import base64
import json
import random
import re
import time
import zipfile

from ..media.collection import bounded_results, current_budget, decode_result_base64
from ..media.images import detect_image_dimensions
from ...domain.errors import ProviderResultError
from .requests import generation_submission
from ..http import provider_response_error, sanitized_log_args
from ..media.downloads import download_image
from ..http import HttpProxySettings, MAX_PROVIDER_RESPONSE_BYTES, read_response_bytes, sanitize_provider_text


_QUALITY_SUFFIX_BY_MODEL = {
    "nai-diffusion-5-full": "very aesthetic, masterpiece, no text",
    "nai-diffusion-5-curated": "very aesthetic, masterpiece, no text",
    "nai-diffusion-4-5-full": "location, very aesthetic, masterpiece, no text",
    "nai-diffusion-4-5-curated": "location, masterpiece, no text, -0.8::feet::, rating:general",
    "nai-diffusion-4-full": "no text, best quality, very aesthetic, absurdres",
    "nai-diffusion-4-curated-preview": "rating:general, amazing quality, very aesthetic, absurdres",
    "nai-diffusion-3": "best quality, amazing quality, very aesthetic, absurdres",
    "nai-diffusion-furry-3": "{best quality}, {amazing quality}",
}
_V5_UNSUPPORTED_PARAMETER_KEYS = {
    "director_reference_descriptions",
    "director_reference_images",
    "director_reference_information_extracted",
    "director_reference_secondary_strength_values",
    "director_reference_strength_values",
    "reference_image_multiple",
    "reference_information_extracted_multiple",
    "reference_strength_multiple",
    "skip_cfg_above_sigma",
}


class NovelAIImage:
    """NovelAI 官方图片接口与兼容 NovelAPI 网关封装。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://image.novelai.net",
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
        width: int = 832,
        height: int = 1216,
        model_size_overrides: dict[str, str] | None = None,
        sampler: str = "k_euler_ancestral",
        steps: int = 28,
        scale: float = 5.0,
        seed: int = -1,
        artist_tags: str = "",
        positive_prompt: str = "",
        negative_prompt: str = "",
        mode: str = "anime",
        uc_preset: int = 0,
        quality_toggle: bool = True,
        sm: bool = False,
        sm_dyn: bool = False,
        noise_schedule: str = "native",
        v4_noise_schedule: str = "karras",
        img2img_strength: float = 0.6,
        img2img_noise: float = 0.1,
        max_images: int = 1,
        extra_parameters: dict[str, Any] | None = None,
        proxy_settings: HttpProxySettings | None = None,
        skip_image_url_ip_check: bool = False,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.request_timeout_seconds = request_timeout_seconds
        self.width = int(width)
        self.height = int(height)
        self.model_size_overrides = {
            str(model).strip(): str(size).strip()
            for model, size in (model_size_overrides or {}).items()
            if str(model).strip() and str(size).strip()
        }
        self.sampler = sampler.strip()
        self.steps = int(steps)
        self.scale = float(scale)
        self.seed = int(seed)
        self.artist_tags = artist_tags.strip()
        self.positive_prompt = positive_prompt.strip()
        self.negative_prompt = negative_prompt.strip()
        self.mode = mode.strip().lower() or "anime"
        self.uc_preset = int(uc_preset)
        self.quality_toggle = quality_toggle
        self.sm = sm
        self.sm_dyn = sm_dyn
        self.noise_schedule = noise_schedule.strip()
        self.v4_noise_schedule = v4_noise_schedule.strip()
        self.img2img_strength = float(img2img_strength)
        self.img2img_noise = float(img2img_noise)
        self.max_images = max(int(max_images), 1)
        self.extra_parameters = dict(extra_parameters or {})
        self.proxy_settings = proxy_settings or HttpProxySettings.disabled()
        self.skip_image_url_ip_check = skip_image_url_ip_check

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """调用 NovelAI / NovelAPI 文生图接口。"""

        content, content_type = await self._post_generation(
            url=f"{self.base_url}/ai/generate-image",
            payload=self._build_payload(prompt=prompt, model=model, action="generate", n=n),
        )
        return await self._extract_images(content, content_type)

    async def edit_images(self, prompt: str, model: str, image_bytes_list: list[bytes], n: int = 1) -> list[bytes]:
        """调用 NovelAI / NovelAPI 图生图接口，仅接受一张源图片。"""

        if not image_bytes_list:
            raise RuntimeError("没有可用于图生图的源图片")
        if len(image_bytes_list) > 1:
            raise ValueError("NovelAI 图生图仅支持一张源图片，请选择一张图片后重试")

        image_bytes = image_bytes_list[0]
        content, content_type = await self._post_img2img_with_source_size_fallback(
            prompt=prompt,
            model=model,
            image_bytes=image_bytes,
            n=n,
        )
        return await self._extract_images(content, content_type)

    def _build_payload(
        self,
        prompt: str,
        model: str,
        action: str,
        n: int,
        size_override: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        """构建 NovelAI 图片请求体。"""

        width, height = size_override if size_override is not None else self._resolve_size(model)
        normalized_model = model.strip().lower()
        is_v3_model = self._is_v3_model(normalized_model)
        is_v4_model = self._is_v4_model(normalized_model)
        is_v5_model = self._is_v5_model(normalized_model)
        is_official_model = is_v3_model or is_v4_model or is_v5_model
        merged_prompt = self._merge_prompt_parts(self.artist_tags, self.positive_prompt, prompt)
        mode_prompt = self._apply_mode_prompt(merged_prompt, normalized_model)
        effective_prompt = self._apply_quality_tags(mode_prompt, normalized_model) if is_official_model else mode_prompt
        parameters: dict[str, Any] = {
            "width": width,
            "height": height,
            "scale": self.scale,
            "sampler": self.sampler,
            "steps": self.steps,
            "n_samples": min(max(int(n), 1), self.max_images),
            "seed": self._resolve_seed(),
            "ucPreset": self.uc_preset,
            "qualityToggle": self.quality_toggle,
            "sm": self.sm,
            "sm_dyn": self.sm_dyn,
        }
        if is_official_model:
            parameters.update(
                {
                    "params_version": 4,
                    "cfg_rescale": 0,
                    "dynamic_thresholding": False,
                    "legacy": False,
                    "legacy_v3_extend": False,
                    "negative_prompt": self.negative_prompt,
                }
            )
        if is_v4_model or is_v5_model:
            parameters.update(
                {
                    "legacy_uc": False,
                    "v4_negative_prompt": {
                        "caption": {
                            "base_caption": self.negative_prompt,
                            "char_captions": [],
                        }
                    },
                    "v4_prompt": {
                        "caption": {
                            "base_caption": effective_prompt,
                            "char_captions": [],
                        },
                        "use_coords": False,
                        "use_order": True,
                    },
                }
            )
        elif not is_v3_model and self.negative_prompt:
            parameters["uc"] = self.negative_prompt
        if is_v5_model:
            noise_schedule = "karras"
        else:
            noise_schedule = self.v4_noise_schedule if is_v4_model else self.noise_schedule
        if noise_schedule:
            parameters["noise_schedule"] = noise_schedule
        parameters.update(self.extra_parameters)
        if is_official_model:
            self._sanitize_official_parameters(
                parameters,
                model=normalized_model,
                action=action,
            )
        return {
            "input": effective_prompt,
            "model": model,
            "action": action,
            "parameters": parameters,
        }

    def _apply_mode_prompt(self, prompt: str, model: str) -> str:
        """按 NovelAI 官方数据集模式在提示词开头添加标签。"""

        if self.mode == "anime":
            return prompt
        if self._is_v3_model(model):
            if self.mode == "furry":
                return prompt
            raise ValueError("NovelAI background 模式仅支持 V4.5 或 V5 模型")
        if self.mode == "furry":
            return self._prepend_dataset_tag(prompt, "fur dataset")
        if self.mode == "background":
            if self._is_v4_model(model) and not model.startswith("nai-diffusion-4-5"):
                raise ValueError("NovelAI background 模式仅支持 V4.5 或 V5 模型")
            return self._prepend_dataset_tag(prompt, "background dataset")
        raise ValueError(f"不支持的 NovelAI 模式：{self.mode}")

    @staticmethod
    def _merge_prompt_parts(*parts: str) -> str:
        """合并 NovelAI 默认正向词与本次请求提示词。"""

        return ", ".join(part.strip(" \t\r\n,") for part in parts if part.strip(" \t\r\n,"))

    @staticmethod
    def _prepend_dataset_tag(prompt: str, dataset_tag: str) -> str:
        """确保数据集标签位于基础提示词最前方且不会重复。"""

        normalized_prompt = prompt.strip(" \t\r\n,")
        if normalized_prompt.casefold().startswith(dataset_tag.casefold()):
            return normalized_prompt
        return f"{dataset_tag}, {normalized_prompt}" if normalized_prompt else dataset_tag

    def _apply_quality_tags(self, prompt: str, model: str) -> str:
        """按模型追加 NovelAI 官方质量标签。"""

        suffix = _QUALITY_SUFFIX_BY_MODEL.get(model, "")
        if not self.quality_toggle or not suffix or suffix.lower() in prompt.lower():
            return prompt
        if self._is_v3_model(model):
            return "|".join(self._append_quality_suffix(part, suffix) for part in prompt.split("|"))

        text_block_match = re.search(r"\n(?=\s*Text:)", prompt, flags=re.IGNORECASE)
        if text_block_match is None:
            return self._append_quality_suffix(prompt, suffix)
        prompt_body = prompt[: text_block_match.start()]
        text_block = prompt[text_block_match.start() :]
        return self._append_quality_suffix(prompt_body, suffix) + text_block

    @staticmethod
    def _append_quality_suffix(prompt: str, suffix: str) -> str:
        """在提示词权重后缀之前添加质量标签。"""

        stripped_prompt = prompt.rstrip()
        weight_match = re.search(r"(:-?\d+(?:\.\d+)?)$", stripped_prompt)
        weight_suffix = weight_match.group(1) if weight_match is not None else ""
        prompt_body = stripped_prompt[: weight_match.start()] if weight_match is not None else stripped_prompt
        if not prompt_body:
            return suffix + weight_suffix
        separator = " " if prompt_body.endswith(",") else ", "
        return f"{prompt_body}{separator}{suffix}{weight_suffix}"

    def _sanitize_official_parameters(
        self,
        parameters: dict[str, Any],
        *,
        model: str,
        action: str,
    ) -> None:
        """按 NovelAI 当前模型能力清理并补全请求参数。"""

        is_v3_model = self._is_v3_model(model)
        is_v4_model = self._is_v4_model(model)
        is_v5_model = self._is_v5_model(model)
        parameters.pop("qualityToggle", None)
        parameters.pop("ucPreset", None)
        parameters.pop("uc", None)
        parameters["params_version"] = 4
        parameters["legacy"] = False
        parameters["legacy_v3_extend"] = False
        parameters["dynamic_thresholding"] = False
        parameters.setdefault("cfg_rescale", 0)

        if is_v5_model:
            for key in _V5_UNSUPPORTED_PARAMETER_KEYS:
                parameters.pop(key, None)
            parameters.pop("sm", None)
            parameters.pop("sm_dyn", None)
            parameters["noise_schedule"] = "karras"
        elif is_v4_model:
            parameters.pop("sm", None)
            parameters.pop("sm_dyn", None)
            if parameters.get("noise_schedule") not in {"karras", "exponential", "polyexponential"}:
                parameters["noise_schedule"] = "karras"
        elif is_v3_model and action == "img2img":
            # NovelAI 官方说明 SMEA 与图生图不兼容。
            parameters.pop("sm", None)
            parameters.pop("sm_dyn", None)

        sampler = str(parameters.get("sampler", "")).strip().lower()
        if (is_v4_model or is_v5_model) and sampler in {"ddim", "ddim_v3"}:
            sampler = "k_euler_ancestral"
            parameters["sampler"] = sampler
        elif is_v3_model and sampler == "ddim":
            sampler = "ddim_v3"
            parameters["sampler"] = sampler

        if is_v3_model and (action == "img2img" or sampler == "ddim_v3"):
            parameters.pop("sm", None)
            parameters.pop("sm_dyn", None)
        elif is_v3_model and not parameters.get("sm"):
            parameters["sm_dyn"] = False

        noise_schedule = str(parameters.get("noise_schedule", "")).strip().lower()
        if sampler == "k_euler_ancestral" and noise_schedule != "native":
            parameters["deliberate_euler_ancestral_bug"] = False
            parameters["prefer_brownian"] = True
        else:
            parameters.pop("deliberate_euler_ancestral_bug", None)
            parameters.pop("prefer_brownian", None)

        if action == "img2img":
            parameters["add_original_image"] = True
            parameters["extra_noise_seed"] = parameters["seed"]

    @staticmethod
    def _is_v3_model(model: str) -> bool:
        """判断模型是否属于 NovelAI V3。"""

        return model.strip().lower() in {"nai-diffusion-3", "nai-diffusion-furry-3"}

    @staticmethod
    def _is_v4_model(model: str) -> bool:
        """判断模型是否使用 NovelAI V4 参数结构。"""

        return model.strip().lower().startswith("nai-diffusion-4")

    @staticmethod
    def _is_v5_model(model: str) -> bool:
        """判断模型是否使用 NovelAI V5 参数结构。"""

        return model.strip().lower().startswith("nai-diffusion-5")

    def _resolve_size(self, model: str) -> tuple[int, int]:
        """按模型名解析图片尺寸。"""

        size = self.model_size_overrides.get(model.strip(), "")
        if not size:
            return max(self.width, 1), max(self.height, 1)

        normalized_size = size.replace("*", "x").lower()
        if "x" not in normalized_size:
            raise ValueError(f"NovelAI 模型尺寸必须为 宽x高：{size}")
        width_text, height_text = normalized_size.split("x", maxsplit=1)
        try:
            width, height = int(width_text.strip()), int(height_text.strip())
        except ValueError as exc:
            raise ValueError(f"NovelAI 模型尺寸无效：{size}") from exc
        if width <= 0 or height <= 0:
            raise ValueError(f"NovelAI 模型尺寸必须为正整数：{size}")
        return width, height

    @staticmethod
    def _detect_image_size(image_bytes: bytes) -> tuple[int, int] | None:
        """读取源图尺寸。"""

        return detect_image_dimensions(image_bytes)

    async def _post_img2img_with_source_size_fallback(
        self,
        *,
        prompt: str,
        model: str,
        image_bytes: bytes,
        n: int,
    ) -> tuple[bytes, str]:
        """使用合法源图尺寸或配置尺寸提交一次请求，不因上游错误自动重绘。"""

        default_size = self._resolve_size(model)
        source_size = await asyncio.to_thread(self._detect_image_size, image_bytes)
        # 官方尺寸要求边长为 64 的倍数；不合法的源图尺寸不向上游试错。
        size = source_size if source_size and all(edge % 64 == 0 for edge in source_size) else default_size
        payload = self._build_payload(prompt=prompt, model=model, action="img2img", n=n, size_override=size)
        encoded = await asyncio.to_thread(base64.b64encode, image_bytes)
        payload["parameters"].update(
            {
                "image": encoded.decode("ascii"),
                "strength": self.img2img_strength,
                "noise": self.img2img_noise,
            }
        )
        return await self._post_generation(url=f"{self.base_url}/ai/generate-image", payload=payload)

    def _resolve_seed(self) -> int:
        """解析 NovelAI seed；负数表示每次随机。"""

        if self.seed >= 0:
            return self.seed
        return random.randint(0, 2**32 - 1)

    def _build_headers(self) -> dict[str, str]:
        """构建请求头。"""

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/zip, application/json, image/*",
        }

    @generation_submission
    async def _post_generation(self, url: str, payload: dict[str, Any]) -> tuple[bytes, str]:
        """发送 NovelAI 图片请求并保留二进制响应。"""

        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout, **self.proxy_settings.aiohttp_session_kwargs()) as session:
            async with session.post(
                url,
                headers=self._build_headers(),
                json=payload,
                allow_redirects=False,
                **self.proxy_settings.aiohttp_request_kwargs(),
            ) as response:
                duration = time.time() - start_time
                content = await read_response_bytes(
                    response, max_bytes=MAX_PROVIDER_RESPONSE_BYTES if response.status in {200, 201} else 64 * 1024
                )
                content_type = response.headers.get("Content-Type", "")
                if response.status not in {200, 201}:
                    error_preview = sanitize_provider_text(
                        content[:1200].decode("utf-8", errors="replace"), self.api_key
                    )
                    self._log_error(
                        "NovelAI 图片接口失败: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        error_preview,
                    )
                    raise provider_response_error(
                        response.status, content.decode("utf-8", errors="replace"), self.api_key, "novelai 图片接口拒绝"
                    )
                self._log_info("NovelAI 接口成功: status=%s duration=%.2fs", response.status, duration)
                return content, content_type

    @bounded_results
    async def _extract_images(self, content: bytes, content_type: str) -> list[bytes]:
        """从 NovelAI 官方 zip、兼容 JSON 或直接图片响应中提取图片。"""

        normalized_content_type = content_type.lower()
        if "application/json" in normalized_content_type:
            try:
                response = await asyncio.to_thread(json.loads, content)
            except Exception as exc:
                raise RuntimeError(f"NovelAI JSON 响应解析失败：{exc}") from exc
            return await self._extract_images_from_json(response)

        if zipfile.is_zipfile(BytesIO(content)):
            return await asyncio.to_thread(self._extract_images_from_zip, content)

        if normalized_content_type.startswith("image/"):
            return [current_budget().accept(content)]

        response_preview = sanitize_provider_text(content[:1200].decode("utf-8", errors="replace"), self.api_key)
        raise RuntimeError(f"NovelAI 响应不是可解析的图片、zip 或 JSON，response_preview={response_preview}")

    @bounded_results
    def _extract_images_from_zip(self, content: bytes) -> list[bytes]:
        """从 NovelAI 官方 zip 响应中提取图片文件。"""

        image_bytes_list: list[bytes] = []
        with zipfile.ZipFile(BytesIO(content)) as image_zip:
            for file_info in image_zip.infolist():
                if file_info.is_dir():
                    continue
                filename = file_info.filename.lower()
                if not filename.endswith((".png", ".jpg", ".jpeg", ".webp")):
                    continue
                if file_info.file_size > current_budget().available():
                    raise ProviderResultError("NovelAI zip 图片超过剩余结果预算，未重新生成")
                with image_zip.open(file_info) as member:
                    image_bytes_list.append(current_budget().accept(member.read(current_budget().available() + 1)))

        if not image_bytes_list:
            raise RuntimeError("NovelAI zip 响应中没有可用图片文件")
        return image_bytes_list

    @bounded_results
    async def _extract_images_from_json(self, response: dict[str, Any]) -> list[bytes]:
        """从 NovelAPI 兼容 JSON 响应中提取图片。"""

        image_bytes_list: list[bytes] = []
        for item in self._iter_json_image_items(response):
            if isinstance(item, str):
                extracted = await self._extract_image_from_string(item)
                if extracted is not None:
                    image_bytes_list.append(extracted)
            elif isinstance(item, dict):
                image_base64 = item.get("b64_json") or item.get("image_base64") or item.get("data")
                if isinstance(image_base64, str) and image_base64:
                    extracted = await self._extract_image_from_string(image_base64)
                    if extracted is not None:
                        image_bytes_list.append(extracted)
                        continue
                image_url = item.get("url") or item.get("image") or item.get("image_url")
                if isinstance(image_url, str) and image_url:
                    extracted = await self._extract_image_from_string(image_url)
                    if extracted is not None:
                        image_bytes_list.append(extracted)

        if not image_bytes_list:
            response_preview = sanitize_provider_text(response, self.api_key)
            raise RuntimeError(f"NovelAPI JSON 响应中没有可用图片数据，response_preview={response_preview}")
        return image_bytes_list

    @staticmethod
    def _iter_json_image_items(response: dict[str, Any]) -> list[Any]:
        """兼容常见图片 JSON 响应字段。"""

        for key in ("data", "images", "output"):
            value = response.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested_items = NovelAIImage._iter_json_image_items(value)
                if nested_items:
                    return nested_items
        image = response.get("image") or response.get("url") or response.get("b64_json")
        if image:
            return [image]
        return []

    @bounded_results
    async def _extract_image_from_string(self, value: str) -> bytes | None:
        """从字符串中提取图片字节。"""

        if value.startswith("data:image/") and ";base64," in value:
            _prefix, image_base64 = value.split(";base64,", maxsplit=1)
            return await asyncio.to_thread(decode_result_base64, image_base64)
        if value.startswith("http://") or value.startswith("https://"):
            return await self._download_image(value)
        try:
            return await asyncio.to_thread(decode_result_base64, value)
        except ProviderResultError:
            raise
        except Exception:
            return None

    async def _download_image(self, url: str) -> bytes:
        """下载 URL 形式返回的图片。"""

        return await download_image(
            url,
            base_url=self.base_url,
            proxy_settings=self.proxy_settings,
            skip_ip_check=self.skip_image_url_ip_check,
            timeout_seconds=self.request_timeout_seconds,
        )

    def _log_info(self, message: str, *args: Any) -> None:
        """记录信息日志。"""
        if self.logger is not None:
            self.logger.info(message, *sanitized_log_args(args, self.api_key))

    def _log_warning(self, message: str, *args: Any) -> None:
        """记录警告日志。"""
        if self.logger is not None:
            self.logger.warning(message, *sanitized_log_args(args, self.api_key))

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""
        if self.logger is not None:
            self.logger.error(message, *sanitized_log_args(args, self.api_key))
