from __future__ import annotations

from typing import Any

import aiohttp
import base64
import time

from ..core.image_utils import detect_mime_type
from ..core.http_proxy import HttpProxySettings


class VolcengineImage:
    """火山引擎方舟图片接口封装。"""

    _DEFAULT_ENDPOINT_URL = "https://ark.cn-beijing.volces.com/api/v3/images/generations"

    def __init__(
        self,
        api_key: str,
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
        default_size: str = "2048*2048",
        model_size_overrides: dict[str, str] | None = None,
        model_endpoint_overrides: dict[str, str] | None = None,
        response_format: str = "url",
        guidance_scale: float = 0.0,
        seed: int = -1,
        watermark: bool = False,
        max_images: int = 1,
        extra_parameters: dict[str, Any] | None = None,
        proxy_settings: HttpProxySettings | None = None,
    ) -> None:
        self.api_key = api_key
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
        self.guidance_scale = float(guidance_scale)
        self.seed = int(seed)
        self.watermark = watermark
        self.max_images = max(int(max_images), 1)
        self.extra_parameters = dict(extra_parameters or {})
        self.proxy_settings = proxy_settings or HttpProxySettings.disabled()

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """调用火山引擎方舟文生图接口。"""

        response = await self._post_json(
            url=self._resolve_endpoint_url(model),
            payload=self._build_payload(prompt=prompt, model=model, n=n),
        )
        return await self._extract_images(response)

    async def edit_images(self, prompt: str, model: str, image_bytes_list: list[bytes], n: int = 1) -> list[bytes]:
        """调用火山引擎方舟图生图接口，支持多张源图。"""

        if not image_bytes_list:
            raise RuntimeError("没有可用于图生图的源图片")

        response = await self._post_json_with_image_format_fallback(
            prompt=prompt,
            model=model,
            image_bytes_list=image_bytes_list,
            n=n,
        )
        return await self._extract_images(response)

    def _resolve_endpoint_url(self, model: str) -> str:
        """按模型解析火山接口地址，不要求用户配置全局 BaseURL。"""

        configured_endpoint = self.model_endpoint_overrides.get(model.strip(), "")
        if not configured_endpoint:
            return self._DEFAULT_ENDPOINT_URL
        if configured_endpoint.startswith(("http://", "https://")):
            return configured_endpoint.rstrip("/")
        return f"https://ark.cn-beijing.volces.com/{configured_endpoint.strip('/')}"

    def _resolve_size(self, model: str) -> str:
        """按模型名解析图片尺寸。"""

        return self.model_size_overrides.get(model.strip(), self.default_size)

    def _resolve_n(self, n: int) -> int:
        """解析最终请求图片数量。"""

        return min(max(int(n), 1), self.max_images)

    def _build_payload(self, prompt: str, model: str, n: int) -> dict[str, Any]:
        """构建火山图片请求体。"""

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "n": self._resolve_n(n),
            "watermark": self.watermark,
        }
        size = self._resolve_size(model)
        if size:
            payload["size"] = size
        if self.response_format:
            payload["response_format"] = self.response_format
        if self.guidance_scale > 0:
            payload["guidance_scale"] = self.guidance_scale
        if self.seed >= 0:
            payload["seed"] = self.seed
        payload.update(self.extra_parameters)
        return payload

    async def _post_json_with_image_format_fallback(
        self,
        *,
        prompt: str,
        model: str,
        image_bytes_list: list[bytes],
        n: int,
    ) -> dict[str, Any]:
        """图生图自动尝试多种火山/兼容网关常见图片字段形态。"""

        image_data_urls = [self._build_image_data_url(image_bytes) for image_bytes in image_bytes_list]
        image_content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": image_data_url,
                },
            }
            for image_data_url in image_data_urls
        ]
        base_payload = self._build_payload(prompt=prompt, model=model, n=n)
        payload_candidates = [
            ("single_image", {**base_payload, "image": image_data_urls[0]}),
            ("single_image_url", {**base_payload, "image_url": image_data_urls[0]}),
            ("image_urls", {**base_payload, "image_urls": image_data_urls}),
            ("images", {**base_payload, "images": image_data_urls}),
            (
                "multimodal_messages",
                {
                    **base_payload,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": prompt,
                                },
                                *image_content,
                            ],
                        }
                    ],
                },
            ),
        ]
        attempt_errors: list[str] = []
        for mode, payload in payload_candidates:
            try:
                self._log_info(
                    "火山引擎图生图字段尝试: model=%s mode=%s image_count=%s",
                    model,
                    mode,
                    len(image_bytes_list),
                )
                return await self._post_json(url=self._resolve_endpoint_url(model), payload=payload)
            except Exception as exc:
                attempt_errors.append(f"{mode}: {exc}")
        raise RuntimeError("火山引擎图生图请求失败: " + " | ".join(attempt_errors))

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

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON POST 请求。"""

        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(
            timeout=timeout, **self.proxy_settings.aiohttp_session_kwargs()
        ) as session:
            async with session.post(
                url,
                headers=self._build_headers(),
                json=payload,
                **self.proxy_settings.aiohttp_request_kwargs(),
            ) as response:
                duration = time.time() - start_time
                response_text = await response.text()
                if response.status != 200:
                    self._log_error(
                        "火山引擎图片接口失败: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        response_text[:1200],
                    )
                    raise RuntimeError(
                        f"火山引擎图片接口错误 ({response.status}, 耗时: {duration:.2f}s): {response_text}"
                    )

                response_json = await response.json()
                error_object = response_json.get("error")
                error_code = response_json.get("code") or response_json.get("error_code")
                if not error_code and isinstance(error_object, dict):
                    error_code = error_object.get("code") or error_object.get("type")
                if error_code:
                    error_message = response_json.get("message") or "未知错误"
                    if isinstance(error_object, dict):
                        error_message = error_object.get("message") or error_object.get("param") or error_message
                    elif isinstance(error_object, str):
                        error_message = error_object
                    self._log_error(
                        "火山引擎图片接口业务失败: code=%s duration=%.2fs url=%s message=%s",
                        error_code,
                        duration,
                        url,
                        error_message,
                    )
                    raise RuntimeError(f"火山引擎图片接口返回错误：{error_code} - {error_message}")

                self._log_info("火山引擎接口成功: status=%s duration=%.2fs", response.status, duration)
                return response_json

    async def _extract_images(self, response: dict[str, Any]) -> list[bytes]:
        """从火山引擎响应中提取图片。"""

        data = self._extract_response_items(response)
        image_bytes_list: list[bytes] = []
        for item in data:
            extracted = await self._extract_image_bytes_from_item(item)
            if extracted is not None:
                image_bytes_list.append(extracted)

        if not image_bytes_list:
            self._log_error("火山引擎响应解析失败: 响应存在但没有可用图片数据")
            raise RuntimeError("火山引擎响应中没有可用图片数据")
        return image_bytes_list

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

        response_preview = str(response)[:1200]
        self._log_error("火山引擎响应解析失败: 未找到图片列表，response_preview=%s", response_preview)
        raise RuntimeError(f"火山引擎响应中未找到图片列表，response_preview={response_preview}")

    async def _extract_image_bytes_from_item(self, item: Any) -> bytes | None:
        """从单个响应条目中提取图片。"""

        if isinstance(item, str):
            return await self._extract_image_bytes_from_string(item)

        if not isinstance(item, dict):
            return None

        image_base64 = item.get("b64_json") or item.get("base64") or item.get("image_base64")
        if isinstance(image_base64, str) and image_base64:
            return base64.b64decode(image_base64)

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

    async def _extract_image_bytes_from_string(self, value: str) -> bytes | None:
        """从字符串中提取图片数据。"""

        if value.startswith("data:image/") and ";base64," in value:
            _prefix, image_base64 = value.split(";base64,", maxsplit=1)
            if image_base64:
                return base64.b64decode(image_base64)
            return None

        if value.startswith("http://") or value.startswith("https://"):
            return await self._download_image(value)

        return None

    async def _download_image(self, url: str) -> bytes:
        """下载 URL 形式返回的图片。"""

        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(
            timeout=timeout, **self.proxy_settings.aiohttp_session_kwargs()
        ) as session:
            async with session.get(url, **self.proxy_settings.aiohttp_request_kwargs()) as response:
                if response.status != 200:
                    self._log_error("下载火山引擎生成图片失败: status=%s url=%s", response.status, url)
                    raise RuntimeError(f"下载火山引擎生成图片失败: status={response.status}")
                return await response.read()

    def _log_info(self, message: str, *args: Any) -> None:
        """记录信息日志。"""

        if self.logger is not None:
            self.logger.info(message, *args)

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""

        if self.logger is not None:
            self.logger.error(message, *args)
