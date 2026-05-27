from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image as PILImage
import aiohttp
import base64
import time


class AliyunImage:
    """阿里百炼图片接口封装。"""

    _MULTIMODAL_GENERATION_PATH = "/api/v1/services/aigc/multimodal-generation/generation"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com",
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
        default_size: str = "1024*1024",
        model_size_overrides: dict[str, str] | None = None,
        negative_prompt: str = "",
        prompt_extend: bool = True,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.logger = logger
        self.request_timeout_seconds = request_timeout_seconds
        self.default_size = default_size.strip()
        self.model_size_overrides = {
            str(model).strip(): str(size).strip()
            for model, size in (model_size_overrides or {}).items()
            if str(model).strip() and str(size).strip()
        }
        self.negative_prompt = negative_prompt.strip()
        self.prompt_extend = prompt_extend

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """调用阿里百炼文生图接口。"""

        response = await self._post_json(
            url=f"{self.base_url}{self._MULTIMODAL_GENERATION_PATH}",
            payload={
                "model": model,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "text": prompt,
                                }
                            ],
                        }
                    ]
                },
                "parameters": self._build_parameters(model, n),
            },
        )
        return await self._extract_images(response)

    async def edit_images(self, prompt: str, model: str, image_bytes: bytes, n: int = 1) -> list[bytes]:
        """调用阿里百炼图像编辑接口。"""

        mime_type = self._detect_mime_type(image_bytes)
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        response = await self._post_json(
            url=f"{self.base_url}{self._MULTIMODAL_GENERATION_PATH}",
            payload={
                "model": model,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "image": f"data:{mime_type};base64,{image_base64}",
                                },
                                {
                                    "text": prompt,
                                },
                            ],
                        }
                    ]
                },
                "parameters": self._build_parameters(model, n),
            },
        )
        return await self._extract_images(response)

    def _build_parameters(self, model: str, n: int) -> dict[str, Any]:
        """构建阿里百炼图片处理参数。"""

        parameters: dict[str, Any] = {
            "n": n,
            "watermark": False,
        }
        if self.negative_prompt:
            parameters["negative_prompt"] = self.negative_prompt

        normalized_model = model.strip()
        if normalized_model != "qwen-image-edit":
            parameters["prompt_extend"] = self.prompt_extend
            resolved_size = self._resolve_size(normalized_model)
            if resolved_size:
                parameters["size"] = resolved_size
        return parameters

    def _resolve_size(self, model: str) -> str:
        """按模型名解析分辨率配置。"""

        return self.model_size_overrides.get(model, self.default_size)

    @staticmethod
    def _detect_mime_type(image_bytes: bytes) -> str:
        """尽量根据图片内容推断 MIME 类型。"""

        with PILImage.open(BytesIO(image_bytes)) as image:
            format_name = str(image.format or "").upper()

        mime_type_map = {
            "BMP": "image/bmp",
            "GIF": "image/gif",
            "JPEG": "image/jpeg",
            "JPG": "image/jpeg",
            "PNG": "image/png",
            "TIFF": "image/tiff",
            "WEBP": "image/webp",
        }
        return mime_type_map.get(format_name, "image/png")

    def _build_headers(self) -> dict[str, str]:
        """构建请求头。"""

        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON POST 请求。"""

        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, headers=self._build_headers(), json=payload) as response:
                duration = time.time() - start_time
                response_text = await response.text()
                if response.status != 200:
                    self._log_error(
                        "阿里百炼图片接口失败: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        response_text[:1200],
                    )
                    raise RuntimeError(
                        f"阿里百炼图片接口错误 ({response.status}, 耗时: {duration:.2f}s): {response_text}"
                    )

                response_json = await response.json()
                if response_json.get("code"):
                    error_code = response_json.get("code")
                    error_message = response_json.get("message") or "未知错误"
                    self._log_error(
                        "阿里百炼图片接口业务失败: code=%s duration=%.2fs url=%s message=%s",
                        error_code,
                        duration,
                        url,
                        error_message,
                    )
                    raise RuntimeError(f"阿里百炼图片接口返回错误：{error_code} - {error_message}")

                self._log_info("阿里百炼接口成功: status=%s duration=%.2fs", response.status, duration)
                return response_json

    async def _extract_images(self, response: dict[str, Any]) -> list[bytes]:
        """从接口响应中提取图片。"""

        output = response.get("output")
        if not isinstance(output, dict):
            response_preview = str(response)[:1200]
            self._log_error("阿里百炼响应解析失败: 未找到 output 对象，response_preview=%s", response_preview)
            raise RuntimeError(f"阿里百炼响应中未找到 output 字段，response_preview={response_preview}")

        choices = output.get("choices")
        if not isinstance(choices, list):
            response_preview = str(response)[:1200]
            self._log_error("阿里百炼响应解析失败: 未找到 choices 列表，response_preview=%s", response_preview)
            raise RuntimeError(f"阿里百炼响应中未找到 choices 字段，response_preview={response_preview}")

        image_bytes_list: list[bytes] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content_list = message.get("content")
            if not isinstance(content_list, list):
                continue
            for item in content_list:
                if not isinstance(item, dict):
                    continue
                image_url = item.get("image")
                if isinstance(image_url, str) and image_url:
                    image_bytes_list.append(await self._download_image(image_url))

        if not image_bytes_list:
            self._log_error("阿里百炼响应解析失败: output.choices 存在但没有可用图片数据")
            raise RuntimeError("阿里百炼响应中没有可用图片数据")
        return image_bytes_list

    async def _download_image(self, url: str) -> bytes:
        """下载 URL 形式返回的图片。"""

        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    self._log_error("下载阿里百炼生成图片失败: status=%s url=%s", response.status, url)
                    raise RuntimeError(f"下载阿里百炼生成图片失败: status={response.status}")
                return await response.read()

    def _log_info(self, message: str, *args: Any) -> None:
        """记录信息日志。"""

        if self.logger is not None:
            self.logger.info(message, *args)

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""

        if self.logger is not None:
            self.logger.error(message, *args)
