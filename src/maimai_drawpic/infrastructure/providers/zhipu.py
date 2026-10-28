from __future__ import annotations

from typing import Any
import aiohttp
import asyncio
import time

from .requests import generation_submission
from ..media.collection import bounded_results, decode_result_base64
from ..http import provider_response_error, sanitized_log_args
from ..media.downloads import download_image
from ..http import (
    HttpProxySettings,
    read_response_json,
    read_response_text,
    sanitize_provider_text,
)


class ZhipuImage:
    """智谱图像生成接口封装。"""

    _BASE_URL = "https://open.bigmodel.cn"

    def __init__(
        self,
        api_key: str,
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
        quality: str = "",
        size: str = "1280x1280",
        watermark_enabled: bool = True,
        user_id: str = "",
        extra_parameters: dict[str, Any] | None = None,
        proxy_settings: HttpProxySettings | None = None,
        skip_image_url_ip_check: bool = False,
    ) -> None:
        self.api_key = api_key
        self.logger = logger
        self.request_timeout_seconds = request_timeout_seconds
        self.quality = quality.strip()
        self.size = size.strip()
        self.watermark_enabled = watermark_enabled
        self.user_id = user_id.strip()
        self.extra_parameters = dict(extra_parameters or {})
        self.proxy_settings = proxy_settings or HttpProxySettings.disabled()
        self.skip_image_url_ip_check = skip_image_url_ip_check

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """调用智谱文生图接口。"""

        if n != 1:
            raise RuntimeError("智谱图像生成接口当前仅按单张图片流程接入")

        response = await self._post_json(
            url=f"{self._BASE_URL}/api/paas/v4/images/generations",
            payload=self._build_payload(prompt=prompt, model=model),
        )
        return await self._extract_images(response)

    async def edit_images(self, prompt: str, model: str, image_bytes_list: list[bytes], n: int = 1) -> list[bytes]:
        """智谱当前未接入图生图编辑接口。"""

        del prompt, model, image_bytes_list, n
        raise RuntimeError("智谱图片模型当前仅支持文生图，不支持图生图编辑")

    def _build_payload(self, prompt: str, model: str) -> dict[str, Any]:
        """构建智谱图像生成请求体。"""

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
        }
        if self.quality:
            payload["quality"] = self.quality
        if self.size:
            payload["size"] = self.size
        payload["watermark_enabled"] = self.watermark_enabled
        if self.user_id:
            payload["user_id"] = self.user_id
        payload.update(self.extra_parameters)
        return payload

    def _build_headers(self) -> dict[str, str]:
        """构建请求头。"""

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

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
                    error_text = sanitize_provider_text(raw_error, self.api_key)
                    self._log_error(
                        "智谱图片生成接口失败: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        error_text[:1200],
                    )
                    raise provider_response_error(response.status, raw_error, self.api_key, "zhipu 图片接口拒绝")
                response_json = await read_response_json(response)
                data_count = len(response_json.get("data", [])) if isinstance(response_json.get("data"), list) else 0
                self._log_info(
                    "智谱接口成功: status=%s duration=%.2fs data_count=%s", response.status, duration, data_count
                )
                return response_json

    @bounded_results
    async def _extract_images(self, response: dict[str, Any]) -> list[bytes]:
        """从接口响应中提取图片。"""

        data = response.get("data")
        if not isinstance(data, list):
            response_preview = sanitize_provider_text(response, self.api_key)
            self._log_error("智谱响应解析失败: 未找到 data 列表，response_preview=%s", response_preview)
            raise RuntimeError(f"智谱响应中未找到 data 字段，response_preview={response_preview}")

        image_bytes_list: list[bytes] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            image_base64 = item.get("b64_json")
            if isinstance(image_base64, str) and image_base64:
                image_bytes_list.append(await asyncio.to_thread(decode_result_base64, image_base64))
                continue

            image_url = item.get("url")
            if isinstance(image_url, str) and image_url:
                image_bytes_list.append(await self._download_image(image_url))

        if not image_bytes_list:
            self._log_error("智谱响应解析失败: data 存在但没有可用图片数据")
            raise RuntimeError("智谱响应中没有可用图片数据")
        return image_bytes_list

    async def _download_image(self, url: str) -> bytes:
        """下载 URL 形式返回的图片。"""

        return await download_image(
            url,
            base_url=self._BASE_URL,
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
