from __future__ import annotations

from typing import Any
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


class SiliconFlowImage:
    """硅基流动图片生成接口封装。"""

    _BASE_URL = "https://api.siliconflow.cn"

    def __init__(
        self,
        api_key: str,
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
        image_size: str = "1024x1024",
        model_size_overrides: dict[str, str] | None = None,
        seed: int = -1,
        num_inference_steps: int = 20,
        guidance_scale: float = 7.5,
        negative_prompt: str = "",
        cfg: float = 0.0,
        extra_parameters: dict[str, Any] | None = None,
        proxy_settings: HttpProxySettings | None = None,
        skip_image_url_ip_check: bool = False,
    ) -> None:
        self.api_key = api_key
        self.logger = logger
        self.request_timeout_seconds = request_timeout_seconds
        self.image_size = image_size.strip()
        self.model_size_overrides = {
            str(model).strip(): str(size).strip()
            for model, size in (model_size_overrides or {}).items()
            if str(model).strip() and str(size).strip()
        }
        self.seed = int(seed)
        self.num_inference_steps = int(num_inference_steps)
        self.guidance_scale = float(guidance_scale)
        self.negative_prompt = negative_prompt.strip()
        self.cfg = float(cfg)
        self.extra_parameters = dict(extra_parameters or {})
        self.proxy_settings = proxy_settings or HttpProxySettings.disabled()
        self.skip_image_url_ip_check = skip_image_url_ip_check

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """调用硅基流动文生图接口。"""

        response = await self._post_json(
            url=f"{self._BASE_URL}/v1/images/generations",
            payload=self._build_payload(prompt=prompt, model=model, n=n),
        )
        return await self._extract_images(response)

    async def edit_images(self, prompt: str, model: str, image_bytes_list: list[bytes], n: int = 1) -> list[bytes]:
        """使用官方 image/image2/image3 字段提交模型支持的所有源图。"""

        if not image_bytes_list:
            raise RuntimeError("没有可用于图生图的源图片")
        maximum = self.max_reference_images(model)
        if len(image_bytes_list) > maximum:
            raise ValueError(f"当前硅基流动模型最多支持 {maximum} 张源图片：{model}")
        payload = self._build_payload(prompt=prompt, model=model, n=n)
        for index, data in enumerate(image_bytes_list):
            mime_type = detect_mime_type(data)
            encoded = await asyncio.to_thread(base64.b64encode, data)
            key = "image" if index == 0 else f"image{index + 1}"
            payload[key] = f"data:{mime_type};base64,{encoded.decode('ascii')}"
        response = await self._post_json(
            url=f"{self._BASE_URL}/v1/images/generations",
            payload=payload,
        )
        return await self._extract_images(response)

    def _resolve_size(self, model: str) -> str:
        """按模型名解析图片尺寸。"""

        return self.model_size_overrides.get(model.strip(), self.image_size)

    @staticmethod
    def max_reference_images(model: str) -> int:
        """当前官方接口仅 Qwen Image Edit 2509 支持三张源图。"""

        return 3 if model.strip().lower() == "qwen/qwen-image-edit-2509" else 1

    def _build_payload(self, prompt: str, model: str, n: int, image_size_override: str | None = None) -> dict[str, Any]:
        """构建硅基流动图片生成请求体。"""

        if n != 1:
            raise ValueError("硅基流动已移除 batch_size，每次请求只生成一张图片，请分别提交任务")
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
        }
        image_size = image_size_override if image_size_override is not None else self._resolve_size(model)
        if image_size:
            payload["image_size"] = image_size
        if self.seed >= 0:
            payload["seed"] = self.seed
        if self.num_inference_steps > 0:
            payload["num_inference_steps"] = self.num_inference_steps
        normalized_model = model.strip().lower()
        if self.guidance_scale > 0 and normalized_model == "kwai-kolors/kolors":
            payload["guidance_scale"] = self.guidance_scale
        if self.cfg > 0 and normalized_model.startswith("qwen/qwen-image"):
            payload["cfg"] = self.cfg
        if self.negative_prompt:
            payload["negative_prompt"] = self.negative_prompt
        payload.update(self.extra_parameters)
        payload.update({"model": model, "prompt": prompt})
        # 已下线字段不能通过旧配置或扩展参数重新写回请求。
        payload.pop("batch_size", None)
        payload.pop("output_format", None)
        payload.pop("n", None)
        if normalized_model.startswith("qwen/qwen-image-edit"):
            payload.pop("image_size", None)
        if normalized_model != "kwai-kolors/kolors":
            payload.pop("guidance_scale", None)
        if not normalized_model.startswith("qwen/qwen-image"):
            payload.pop("cfg", None)
        return payload

    def _build_headers(self) -> dict[str, str]:
        """构建请求头。"""

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

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
                    error_text = sanitize_provider_text(raw_error, self.api_key)
                    self._log_error(
                        "硅基流动图片接口失败: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        error_text[:1200],
                    )
                    raise provider_response_error(response.status, raw_error, self.api_key, "siliconflow 图片接口拒绝")
                response_json = await read_response_json(response)
                self._log_info("硅基流动接口成功: status=%s duration=%.2fs", response.status, duration)
                return response_json

    @bounded_results
    async def _extract_images(self, response: dict[str, Any]) -> list[bytes]:
        """从硅基流动响应中提取图片。"""

        data = response.get("images") or response.get("data")
        if not isinstance(data, list):
            response_preview = sanitize_provider_text(response, self.api_key)
            self._log_error("硅基流动响应解析失败: 未找到 images/data 列表，response_preview=%s", response_preview)
            raise RuntimeError(f"硅基流动响应中未找到 images/data 字段，response_preview={response_preview}")

        image_bytes_list: list[bytes] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            image_base64 = item.get("b64_json")
            if isinstance(image_base64, str) and image_base64:
                image_bytes_list.append(await asyncio.to_thread(decode_result_base64, image_base64))
                continue

            image_url = item.get("url") or item.get("image_url") or item.get("image")
            if isinstance(image_url, str) and image_url:
                image_bytes_list.append(await self._download_image(image_url))

        if not image_bytes_list:
            self._log_error("硅基流动响应解析失败: images/data 存在但没有可用图片数据")
            raise RuntimeError("硅基流动响应中没有可用图片数据")
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

    def _log_warning(self, message: str, *args: Any) -> None:
        """记录警告日志。"""
        if self.logger is not None:
            self.logger.warning(message, *sanitized_log_args(args, self.api_key))

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""
        if self.logger is not None:
            self.logger.error(message, *sanitized_log_args(args, self.api_key))
