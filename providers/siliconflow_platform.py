from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image as PILImage

import aiohttp
import base64
import time



class SiliconFlowImage:
    """硅基流动图片生成接口封装。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.siliconflow.cn",
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
        image_size: str = "1024x1024",
        model_size_overrides: dict[str, str] | None = None,
        batch_size: int = 1,
        seed: int = -1,
        num_inference_steps: int = 20,
        guidance_scale: float = 7.5,
        negative_prompt: str = "",
        output_format: str = "png",
        extra_parameters: dict[str, Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.request_timeout_seconds = request_timeout_seconds
        self.image_size = image_size.strip()
        self.model_size_overrides = {
            str(model).strip(): str(size).strip()
            for model, size in (model_size_overrides or {}).items()
            if str(model).strip() and str(size).strip()
        }
        self.batch_size = max(int(batch_size), 1)
        self.seed = int(seed)
        self.num_inference_steps = int(num_inference_steps)
        self.guidance_scale = float(guidance_scale)
        self.negative_prompt = negative_prompt.strip()
        self.output_format = output_format.strip()
        self.extra_parameters = dict(extra_parameters or {})

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """调用硅基流动文生图接口。"""

        response = await self._post_json(
            url=f"{self.base_url}/v1/images/generations",
            payload=self._build_payload(prompt=prompt, model=model, n=n),
        )
        return await self._extract_images(response)

    async def edit_images(self, prompt: str, model: str, image_bytes: bytes, n: int = 1) -> list[bytes]:
        """调用硅基流动图生图接口。"""

        payload = self._build_payload(prompt=prompt, model=model, n=n)
        mime_type = self._detect_mime_type(image_bytes)
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        payload["image"] = f"data:{mime_type};base64,{image_base64}"
        response = await self._post_json(
            url=f"{self.base_url}/v1/images/generations",
            payload=payload,
        )
        return await self._extract_images(response)

    def _resolve_size(self, model: str) -> str:
        """按模型名解析图片尺寸。"""

        return self.model_size_overrides.get(model.strip(), self.image_size)

    def _build_payload(self, prompt: str, model: str, n: int) -> dict[str, Any]:
        """构建硅基流动图片生成请求体。"""

        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "batch_size": min(max(int(n), 1), self.batch_size),
        }
        image_size = self._resolve_size(model)
        if image_size:
            payload["image_size"] = image_size
        if self.seed >= 0:
            payload["seed"] = self.seed
        if self.num_inference_steps > 0:
            payload["num_inference_steps"] = self.num_inference_steps
        if self.guidance_scale > 0:
            payload["guidance_scale"] = self.guidance_scale
        if self.negative_prompt:
            payload["negative_prompt"] = self.negative_prompt
        if self.output_format:
            payload["output_format"] = self.output_format
        payload.update(self.extra_parameters)
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

        with PILImage.open(BytesIO(image_bytes)) as image:
            format_name = str(image.format or "").upper()

        mime_type_map = {
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "PNG": "image/png",
            "WEBP": "image/webp",
        }
        return mime_type_map.get(format_name, "image/png")

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON POST 请求。"""

        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._build_headers(), json=payload) as response:
                duration = time.time() - start_time
                if response.status != 200:
                    error_text = await response.text()
                    self._log_error(
                        "硅基流动图片接口失败: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        error_text[:1200],
                    )
                    raise RuntimeError(
                        f"硅基流动图片接口错误 ({response.status}, 耗时: {duration:.2f}s): {error_text}"
                    )
                response_json = await response.json()
                self._log_info("硅基流动接口成功: status=%s duration=%.2fs", response.status, duration)
                return response_json

    async def _extract_images(self, response: dict[str, Any]) -> list[bytes]:
        """从硅基流动响应中提取图片。"""

        data = response.get("images") or response.get("data")
        if not isinstance(data, list):
            response_preview = str(response)[:1200]
            self._log_error("硅基流动响应解析失败: 未找到 images/data 列表，response_preview=%s", response_preview)
            raise RuntimeError(f"硅基流动响应中未找到 images/data 字段，response_preview={response_preview}")

        image_bytes_list: list[bytes] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            image_base64 = item.get("b64_json")
            if isinstance(image_base64, str) and image_base64:
                image_bytes_list.append(base64.b64decode(image_base64))
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

        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    self._log_error("下载硅基流动生成图片失败: status=%s url=%s", response.status, url)
                    raise RuntimeError(f"下载硅基流动生成图片失败: status={response.status}")
                return await response.read()

    def _log_info(self, message: str, *args: Any) -> None:
        """记录信息日志。"""

        if self.logger is not None:
            self.logger.info(message, *args)

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""

        if self.logger is not None:
            self.logger.error(message, *args)
