from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urljoin, urlsplit
import aiohttp
import asyncio
import base64
import time

from ..media.collection import bounded_results, decode_result_base64
from ..media.images import detect_mime_type
from .requests import generation_submission
from ..http import provider_response_error, sanitized_log_args
from ..media.downloads import download_image
from ..http import (
    HttpProxySettings,
    read_response_json,
    read_response_text,
    sanitize_provider_text,
)


VolcengineModelFamily = Literal[
    "seedream_5_pro",
    "seedream_5_flash",
    "seedream_5_lite",
    "seedream_4_5",
    "seedream_4_0",
    "legacy_3",
    "unknown",
]


class VolcengineImage:
    """火山引擎方舟图片接口封装。"""

    _DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
    _GENERATION_PATH = "images/generations"

    def __init__(
        self,
        api_key: str,
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
        default_size: str = "2048*2048",
        model_size_overrides: dict[str, str] | None = None,
        model_endpoint_overrides: dict[str, str] | None = None,
        response_format: str = "url",
        output_format: str = "",
        sequential_image_generation: str = "disabled",
        optimize_prompt_mode: str = "",
        web_search_enabled: bool = False,
        background: str = "",
        layer_decomposition: bool = False,
        guidance_scale: float = 0.0,
        seed: int = -1,
        watermark: bool = False,
        max_images: int = 1,
        extra_parameters: dict[str, Any] | None = None,
        proxy_settings: HttpProxySettings | None = None,
        base_url: str = _DEFAULT_BASE_URL,
        skip_image_url_ip_check: bool = False,
    ) -> None:
        self.api_key = api_key
        self.base_url = self._normalize_base_url(base_url)
        self.logger = logger
        self.request_timeout_seconds = request_timeout_seconds
        self.default_size = default_size.strip()
        self.model_size_overrides = {
            str(model).strip(): str(size).strip()
            for model, size in (model_size_overrides or {}).items()
            if str(model).strip() and str(size).strip()
        }
        self.model_endpoint_overrides = {
            str(model).strip(): str(endpoint).strip()
            for model, endpoint in (model_endpoint_overrides or {}).items()
            if str(model).strip() and str(endpoint).strip()
        }
        self.response_format = response_format.strip()
        self.output_format = output_format.strip().lower()
        self.sequential_image_generation = sequential_image_generation.strip().lower()
        self.optimize_prompt_mode = optimize_prompt_mode.strip().lower()
        self.web_search_enabled = web_search_enabled
        self.background = background.strip().lower()
        self.layer_decomposition = layer_decomposition
        self.guidance_scale = float(guidance_scale)
        self.seed = int(seed)
        self.watermark = watermark
        self.max_images = max(int(max_images), 1)
        self.extra_parameters = dict(extra_parameters or {})
        self.proxy_settings = proxy_settings or HttpProxySettings.disabled()
        self.skip_image_url_ip_check = skip_image_url_ip_check

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """调用火山引擎方舟文生图接口。"""

        response = await self._post_json(
            url=self._resolve_endpoint_url(model),
            payload=self._build_payload(
                prompt=prompt,
                model=model,
                n=n,
                source_image_count=0,
            ),
        )
        return await self._extract_images(response)

    async def edit_images(self, prompt: str, model: str, image_bytes_list: list[bytes], n: int = 1) -> list[bytes]:
        """调用火山引擎方舟图生图接口，支持多张源图。"""

        if not image_bytes_list:
            raise RuntimeError("没有可用于图生图的源图片")

        image_data_urls = [
            await asyncio.to_thread(self._build_image_data_url, image_bytes) for image_bytes in image_bytes_list
        ]
        payload = self._build_payload(
            prompt=prompt,
            model=model,
            n=n,
            source_image_count=len(image_data_urls),
        )
        payload["image"] = image_data_urls[0] if len(image_data_urls) == 1 else image_data_urls
        response = await self._post_json(
            url=self._resolve_endpoint_url(model),
            payload=payload,
        )
        return await self._extract_images(response)

    def _resolve_endpoint_url(self, model: str) -> str:
        """按基础地址和模型覆盖项解析图片生成接口地址。"""

        configured_endpoint = self.model_endpoint_overrides.get(model.strip(), "")
        if not configured_endpoint:
            return self._append_generation_path(self.base_url)
        if configured_endpoint.startswith(("http://", "https://")):
            return configured_endpoint.rstrip("/")
        if configured_endpoint.startswith("/") or configured_endpoint.startswith("api/"):
            parsed_base_url = urlsplit(self.base_url)
            origin = f"{parsed_base_url.scheme}://{parsed_base_url.netloc}/"
            return urljoin(origin, configured_endpoint.lstrip("/"))
        return urljoin(f"{self.base_url}/", configured_endpoint)

    @classmethod
    def _normalize_base_url(cls, base_url: str) -> str:
        normalized_url = base_url.strip().rstrip("/")
        if not normalized_url:
            return cls._DEFAULT_BASE_URL
        if not normalized_url.startswith(("http://", "https://")):
            raise ValueError("火山引擎 base_url 必须以 http:// 或 https:// 开头")
        return normalized_url

    @classmethod
    def _append_generation_path(cls, base_url: str) -> str:
        if base_url.casefold().endswith(f"/{cls._GENERATION_PATH}"):
            return base_url
        return f"{base_url}/{cls._GENERATION_PATH}"

    def _resolve_size(self, model: str) -> str:
        """按模型名解析图片尺寸。"""

        configured_size = self.model_size_overrides.get(model.strip(), self.default_size)
        return configured_size.replace("*", "x").replace("×", "x")

    def _resolve_n(self, n: int) -> int:
        """解析最终请求图片数量。"""

        return min(max(int(n), 1), self.max_images)

    @staticmethod
    def _resolve_model_family(model: str) -> VolcengineModelFamily:
        """按官方模型 ID 识别参数能力；Endpoint ID 保持可配置透传。"""

        normalized_model = model.strip().casefold()
        if "seedream-5-0-pro" in normalized_model:
            return "seedream_5_pro"
        if "seedream-5-0-flash" in normalized_model:
            return "seedream_5_flash"
        if "seedream-5-0" in normalized_model:
            return "seedream_5_lite"
        if "seedream-4-5" in normalized_model:
            return "seedream_4_5"
        if "seedream-4-0" in normalized_model:
            return "seedream_4_0"
        if "seedream-3-0-t2i" in normalized_model or "seededit-3-0-i2i" in normalized_model:
            return "legacy_3"
        return "unknown"

    @staticmethod
    def _supports_sequential_generation(model_family: VolcengineModelFamily) -> bool:
        return model_family in {"seedream_5_lite", "seedream_4_5", "seedream_4_0", "unknown"}

    @staticmethod
    def _supports_output_format(model_family: VolcengineModelFamily) -> bool:
        return model_family in {"seedream_5_pro", "seedream_5_flash", "seedream_5_lite", "unknown"}

    @staticmethod
    def _supports_prompt_optimization(model_family: VolcengineModelFamily) -> bool:
        return model_family in {
            "seedream_5_pro",
            "seedream_5_flash",
            "seedream_5_lite",
            "seedream_4_5",
            "seedream_4_0",
            "unknown",
        }

    @staticmethod
    def _max_reference_images(model_family: VolcengineModelFamily) -> int | None:
        if model_family == "legacy_3":
            return 1
        if model_family in {"seedream_5_pro", "seedream_5_flash"}:
            return 10
        if model_family in {"seedream_5_lite", "seedream_4_5", "seedream_4_0"}:
            return 14
        return None

    def _build_payload(
        self,
        prompt: str,
        model: str,
        n: int,
        *,
        source_image_count: int,
    ) -> dict[str, Any]:
        """构建火山图片请求体。"""

        model_family = self._resolve_model_family(model)
        max_reference_images = self._max_reference_images(model_family)
        if max_reference_images is not None and source_image_count > max_reference_images:
            raise ValueError(f"当前火山引擎模型最多支持 {max_reference_images} 张参考图：{model}")
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "watermark": self.watermark,
        }
        size = self._resolve_size(model)
        if size:
            payload["size"] = size
        if self.response_format:
            payload["response_format"] = self.response_format
        if self.output_format and self._supports_output_format(model_family):
            payload["output_format"] = self.output_format
        if self.guidance_scale > 0 and model_family in {"legacy_3", "unknown"}:
            payload["guidance_scale"] = self.guidance_scale
        if self.seed >= 0 and model_family in {"legacy_3", "unknown"}:
            payload["seed"] = self.seed

        requested_image_count = self._resolve_n(n)
        sequential_mode = self.sequential_image_generation
        if requested_image_count > 1:
            sequential_mode = "auto"
        if sequential_mode == "auto" and self._supports_sequential_generation(model_family):
            remaining_image_count = 15 - source_image_count
            if remaining_image_count < 1:
                raise ValueError("火山引擎组图要求参考图与输出图总数不超过 15 张")
            max_generated_images = min(self.max_images, remaining_image_count)
            if requested_image_count > 1:
                max_generated_images = min(max_generated_images, requested_image_count)
            payload["sequential_image_generation"] = "auto"
            payload["sequential_image_generation_options"] = {
                "max_images": max_generated_images,
            }
        elif requested_image_count > 1:
            raise ValueError(f"当前火山引擎模型不支持组图生成：{model}")

        if self.optimize_prompt_mode and self._supports_prompt_optimization(model_family):
            optimize_mode = self.optimize_prompt_mode
            if optimize_mode == "fast" and model_family in {
                "seedream_5_flash",
                "seedream_5_lite",
                "seedream_4_5",
            }:
                optimize_mode = "standard"
                self._log_warning(
                    "火山引擎模型不支持 fast 提示词优化，已使用 standard: model=%s",
                    model,
                )
            payload["optimize_prompt_options"] = {"mode": optimize_mode}

        if self.web_search_enabled and model_family in {"seedream_5_lite", "unknown"}:
            payload["tools"] = [{"type": "web_search"}]

        is_image_edit = source_image_count > 0
        supports_advanced_edit = model_family in {
            "seedream_5_pro",
            "seedream_5_flash",
            "unknown",
        }
        if is_image_edit and self.background and supports_advanced_edit:
            payload["background"] = self.background
        if is_image_edit and self.layer_decomposition and supports_advanced_edit:
            payload["layer_decomposition"] = True

        payload.update(
            {key: value for key, value in self.extra_parameters.items() if key not in {"model", "prompt", "image"}}
        )
        if model_family not in {"legacy_3", "unknown"}:
            payload.pop("guidance_scale", None)
            payload.pop("seed", None)
        if not self._supports_sequential_generation(model_family):
            payload.pop("sequential_image_generation", None)
            payload.pop("sequential_image_generation_options", None)
        if not self._supports_output_format(model_family):
            payload.pop("output_format", None)
        if not self._supports_prompt_optimization(model_family):
            payload.pop("optimize_prompt_options", None)
        if model_family not in {"seedream_5_lite", "unknown"}:
            payload.pop("tools", None)
        if not is_image_edit or not supports_advanced_edit:
            payload.pop("background", None)
            payload.pop("layer_decomposition", None)

        optimize_options = payload.get("optimize_prompt_options")
        if (
            isinstance(optimize_options, dict)
            and optimize_options.get("mode") == "fast"
            and model_family in {"seedream_5_flash", "seedream_5_lite", "seedream_4_5"}
        ):
            optimize_options["mode"] = "standard"
            self._log_warning(
                "火山引擎模型不支持 fast 提示词优化，已使用 standard: model=%s",
                model,
            )

        # 方舟图片生成 Body 不支持 OpenAI Images API 的 n 字段；插件也不处理流式响应。
        payload.pop("n", None)
        stream_enabled = payload.pop("stream", False)
        if stream_enabled:
            raise ValueError("插件当前仅支持火山引擎非流式图片响应，请移除 stream=true")
        if payload.get("sequential_image_generation") == "disabled":
            payload.pop("sequential_image_generation", None)
            payload.pop("sequential_image_generation_options", None)
        if payload.get("sequential_image_generation") == "auto":
            remaining_count = 15 - source_image_count
            if remaining_count < 1:
                raise ValueError("火山引擎组图要求参考图与输出图总数不超过 15 张")
            options = payload.get("sequential_image_generation_options", {})
            if not isinstance(options, dict):
                raise ValueError("火山引擎组图参数必须是 JSON 对象")
            requested_maximum = options.get("max_images", self.max_images)
            if not isinstance(requested_maximum, int) or isinstance(requested_maximum, bool) or requested_maximum < 1:
                raise ValueError("火山引擎组图 max_images 必须是正整数")
            payload["sequential_image_generation_options"] = {
                **options,
                "max_images": min(requested_maximum, self.max_images, remaining_count),
            }
        if payload.get("background") == "transparent":
            if payload.get("output_format") == "jpeg":
                raise ValueError("火山引擎透明背景模式不能与 jpeg 输出格式同时使用")
            if source_image_count != 1:
                raise ValueError("火山引擎透明背景模式仅支持输入一张图片")
        if payload.get("layer_decomposition") and source_image_count != 1:
            raise ValueError("火山引擎图层拆分仅支持输入一张图片")
        return payload

    def _build_headers(self) -> dict[str, str]:
        """构建请求头。"""

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @classmethod
    def _build_image_data_url(cls, image_bytes: bytes) -> str:
        """把源图片转换为 data URL。"""

        mime_type = cls._detect_mime_type(image_bytes)
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        return f"data:{mime_type};base64,{image_base64}"

    @staticmethod
    def _detect_mime_type(image_bytes: bytes) -> str:
        """尽量根据图片内容推断 MIME 类型。"""

        return detect_mime_type(image_bytes)

    @generation_submission
    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON POST 请求。"""

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
                if response.status != 200:
                    raw_error = await read_response_text(response, max_bytes=64 * 1024)
                    response_text = sanitize_provider_text(raw_error, self.api_key)
                    self._log_error(
                        "火山引擎图片接口失败: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        response_text[:1200],
                    )
                    raise provider_response_error(response.status, raw_error, self.api_key, "volcengine 图片接口拒绝")

                response_json = await read_response_json(response)
                response_error = self._extract_response_error(response_json)
                if response_error is not None:
                    error_code, error_message = (
                        sanitize_provider_text(value, self.api_key) for value in response_error
                    )
                    self._log_error(
                        "火山引擎图片接口业务失败: code=%s duration=%.2fs url=%s message=%s",
                        error_code,
                        duration,
                        url,
                        error_message,
                    )
                    raise provider_response_error(
                        400, {"code": error_code, "message": error_message}, self.api_key, "火山引擎图片接口返回错误"
                    )

                self._log_info("火山引擎接口成功: status=%s duration=%.2fs", response.status, duration)
                return response_json

    @staticmethod
    def _extract_response_error(response: dict[str, Any]) -> tuple[str, str] | None:
        """提取顶层业务错误；兼容成功响应中存在空 error 的网关。"""

        error_object = response.get("error")
        error_code = response.get("code") or response.get("error_code")
        if not error_code and isinstance(error_object, dict):
            error_code = error_object.get("code") or error_object.get("type")
        has_error_object = (isinstance(error_object, dict) and bool(error_object)) or (
            isinstance(error_object, str) and bool(error_object.strip())
        )
        if not error_code and not has_error_object:
            return None

        error_message = response.get("message") or "未知错误"
        if isinstance(error_object, dict):
            error_message = error_object.get("message") or error_object.get("param") or error_message
        elif isinstance(error_object, str):
            error_message = error_object
        return str(error_code or "unknown_error"), str(error_message)

    @bounded_results
    async def _extract_images(self, response: dict[str, Any]) -> list[bytes]:
        """从火山引擎响应中提取图片。"""

        data = self._extract_response_items(response)
        image_bytes_list: list[bytes] = []
        item_errors: list[str] = []
        for item in data:
            item_error = self._extract_item_error(item)
            if item_error:
                item_errors.append(sanitize_provider_text(item_error, self.api_key))
                continue
            extracted = await self._extract_image_bytes_from_item(item)
            if extracted is not None:
                image_bytes_list.append(extracted)

        if not image_bytes_list:
            error_suffix = f"：{'；'.join(item_errors)}" if item_errors else ""
            self._log_error("火山引擎响应解析失败: 响应存在但没有可用图片数据%s", error_suffix)
            raise RuntimeError(f"火山引擎响应中没有可用图片数据{error_suffix}")
        if item_errors:
            self._log_warning(
                "火山引擎组图部分生成失败: success_count=%s errors=%s",
                len(image_bytes_list),
                "；".join(item_errors),
            )
        return image_bytes_list

    @staticmethod
    def _extract_item_error(item: Any) -> str:
        """提取组图响应中单张图片的错误信息。"""

        if not isinstance(item, dict):
            return ""
        error_object = item.get("error")
        if isinstance(error_object, dict):
            code = str(error_object.get("code") or "unknown_error")
            message = str(error_object.get("message") or "未知错误")
            return f"{code} - {message}"
        if isinstance(error_object, str) and error_object.strip():
            return error_object.strip()
        return ""

    def _extract_response_items(self, response: dict[str, Any]) -> list[Any]:
        """提取响应中可能承载图片的条目列表。"""

        for key in ("data", "images", "result"):
            value = response.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                nested_items = value.get("data") or value.get("images")
                if isinstance(nested_items, list):
                    return nested_items

        choices = response.get("choices")
        if isinstance(choices, list):
            return choices

        response_preview = sanitize_provider_text(response, self.api_key)
        self._log_error("火山引擎响应解析失败: 未找到图片列表，response_preview=%s", response_preview)
        raise RuntimeError(f"火山引擎响应中未找到图片列表，response_preview={response_preview}")

    @bounded_results
    async def _extract_image_bytes_from_item(self, item: Any) -> bytes | None:
        """从单个响应条目中提取图片。"""

        if isinstance(item, str):
            return await self._extract_image_bytes_from_string(item)

        if not isinstance(item, dict):
            return None

        image_base64 = item.get("b64_json") or item.get("base64") or item.get("image_base64")
        if isinstance(image_base64, str) and image_base64:
            return await asyncio.to_thread(decode_result_base64, image_base64)

        for key in ("url", "image_url", "image", "content"):
            value = item.get(key)
            if isinstance(value, str) and value:
                extracted = await self._extract_image_bytes_from_string(value)
                if extracted is not None:
                    return extracted
            if isinstance(value, dict):
                extracted = await self._extract_image_bytes_from_item(value)
                if extracted is not None:
                    return extracted

        message = item.get("message")
        if isinstance(message, dict):
            extracted = await self._extract_image_bytes_from_item(message)
            if extracted is not None:
                return extracted

        for key in ("content", "images", "data"):
            nested_items = item.get(key)
            if not isinstance(nested_items, list):
                continue
            for nested_item in nested_items:
                extracted = await self._extract_image_bytes_from_item(nested_item)
                if extracted is not None:
                    return extracted

        return None

    @bounded_results
    async def _extract_image_bytes_from_string(self, value: str) -> bytes | None:
        """从字符串中提取图片数据。"""

        if value.startswith("data:image/") and ";base64," in value:
            _prefix, image_base64 = value.split(";base64,", maxsplit=1)
            if image_base64:
                return await asyncio.to_thread(decode_result_base64, image_base64)
            return None

        if value.startswith("http://") or value.startswith("https://"):
            return await self._download_image(value)

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

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""
        if self.logger is not None:
            self.logger.error(message, *sanitized_log_args(args, self.api_key))

    def _log_warning(self, message: str, *args: Any) -> None:
        """记录警告日志。"""
        if self.logger is not None:
            self.logger.warning(message, *sanitized_log_args(args, self.api_key))
