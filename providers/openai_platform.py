from __future__ import annotations

import base64
import mimetypes
import re
import time
from io import BytesIO
from typing import Any

import aiohttp
from PIL import Image as PILImage


class OpenaiImage:
    """OpenAI 兼容图片接口封装。"""

    _MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com",
        compatibility_mode: str = "images_api",
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.compatibility_mode = compatibility_mode
        self.logger = logger
        self.request_timeout_seconds = request_timeout_seconds

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """手动调用 OpenAI 兼容文生图接口。"""

        attempt_errors: list[str] = []
        for mode in self._resolve_generation_modes(model):
            try:
                if mode == "chat_completions":
                    response = await self._post_json(
                        url=f"{self.base_url}/v1/chat/completions",
                        payload=self._build_chat_completions_payload(prompt=prompt, model=model, n=n),
                    )
                    return await self._extract_chat_completion_images(response)

                payload: dict[str, Any] = {
                    "model": model,
                    "prompt": prompt,
                    "n": n,
                    "size": "1024x1024",
                }
                if mode == "images_api" and not self._is_gpt_image_model(model):
                    payload["response_format"] = "b64_json"

                response = await self._post_json(
                    url=f"{self.base_url}/v1/images/generations",
                    payload=payload,
                )
                return await self._extract_images_auto(response)
            except Exception as exc:
                attempt_errors.append(f"{mode}: {exc}")

        raise RuntimeError("自动兼容模式全部尝试失败: " + " | ".join(attempt_errors))

    async def edit_images(self, prompt: str, model: str, image_bytes: bytes, n: int = 1) -> list[bytes]:
        """手动调用 OpenAI 兼容图生图接口。"""

        attempt_errors: list[str] = []
        mime_type = self._detect_mime_type(image_bytes)
        for mode in self._resolve_edit_modes(model):
            try:
                if mode == "chat_completions":
                    response = await self._post_json(
                        url=f"{self.base_url}/v1/chat/completions",
                        payload=self._build_chat_completions_edit_payload(
                            prompt=prompt,
                            model=model,
                            image_bytes=image_bytes,
                            n=n,
                        ),
                    )
                    return await self._extract_chat_completion_images(response)

                response = await self._post_edit_form_with_fallback(
                    url=f"{self.base_url}/v1/images/edits",
                    model=model,
                    prompt=prompt,
                    image_bytes=image_bytes,
                    mime_type=mime_type,
                    n=n,
                )
                return await self._extract_images_auto(response)
            except Exception as exc:
                attempt_errors.append(f"{mode}: {exc}")

        raise RuntimeError("自动兼容模式全部尝试失败: " + " | ".join(attempt_errors))

    @staticmethod
    def _is_gpt_image_model(model: str) -> bool:
        """判断是否为 GPT Image 系列模型。"""

        return "gpt-image" in model

    @staticmethod
    def _is_novelai_model(model: str) -> bool:
        """判断是否为 NovelAI 风格模型。"""

        normalized_model = model.strip().lower()
        return normalized_model.startswith("nai-") or "diffusion" in normalized_model

    @staticmethod
    def _uses_google_image_chat_format(model: str) -> bool:
        """判断当前模型是否更适合走 Gemini 风格的 chat 图片格式。"""

        normalized_model = model.strip().lower()
        return (
            normalized_model.startswith("gemini-")
            or "image-preview" in normalized_model
            or "flash-image" in normalized_model
            or "pro-image" in normalized_model
        )

    @staticmethod
    def _guess_mime_type(filename: str) -> str:
        """根据文件名猜测 MIME 类型。"""

        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or "image/png"

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

    @staticmethod
    def _guess_filename_by_mime_type(mime_type: str) -> str:
        """根据 MIME 类型生成上传文件名。"""

        extension_map = {
            "image/jpeg": "jpg",
            "image/png": "png",
            "image/webp": "webp",
        }
        extension = extension_map.get(mime_type, "png")
        return f"source.{extension}"

    def _build_headers(self, with_json_content_type: bool = False) -> dict[str, str]:
        """构建请求头。"""

        headers = {"Authorization": f"Bearer {self.api_key}"}
        if with_json_content_type:
            headers["Content-Type"] = "application/json"
        return headers

    def _resolve_generation_modes(self, model: str) -> list[str]:
        """解析文生图的自动兼容尝试顺序。"""

        if self.compatibility_mode != "auto":
            return [self.compatibility_mode]
        if self._is_novelai_model(model):
            return ["novelai_images_api", "images_api"]
        if self._is_gpt_image_model(model):
            return ["images_api", "chat_completions", "novelai_images_api"]
        if self._uses_google_image_chat_format(model):
            return ["chat_completions", "images_api", "novelai_images_api"]
        return ["images_api", "novelai_images_api", "chat_completions"]

    def _resolve_edit_modes(self, model: str) -> list[str]:
        """解析图生图的自动兼容尝试顺序。"""

        if self.compatibility_mode != "auto":
            return [self.compatibility_mode]
        if self._is_gpt_image_model(model):
            return ["images_api", "chat_completions"]
        if self._uses_google_image_chat_format(model):
            return ["chat_completions", "images_api"]
        if self._is_novelai_model(model):
            return ["images_api", "novelai_images_api"]
        return ["images_api", "chat_completions"]

    def _build_chat_completions_payload(self, prompt: str, model: str, n: int) -> dict[str, Any]:
        """构建 chat completions 兼容模式的文生图请求体。"""

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "stream": False,
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": prompt,
                        }
                    ],
                }
            ],
        }
        if n > 1:
            payload["n"] = n
        return payload

    def _build_chat_completions_edit_payload(
        self,
        prompt: str,
        model: str,
        image_bytes: bytes,
        n: int,
    ) -> dict[str, Any]:
        """构建 chat completions 兼容模式的图生图请求体。"""

        mime_type = self._detect_mime_type(image_bytes)
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:{mime_type};base64,{image_base64}"
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                            },
                        },
                    ],
                }
            ],
            "stream": False,
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": prompt,
                        },
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": image_base64,
                            }
                        },
                    ],
                }
            ],
        }
        if n > 1:
            payload["n"] = n
        return payload

    async def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """发送 JSON POST 请求。"""

        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                headers=self._build_headers(with_json_content_type=True),
                json=payload,
            ) as response:
                duration = time.time() - start_time
                if response.status != 200:
                    error_text = await response.text()
                    self._log_error(
                        "OpenAI API错误: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        error_text[:1200],
                    )
                    raise RuntimeError(
                        f"OpenAI 图片生成接口错误 ({response.status}, 耗时: {duration:.2f}s): {error_text}"
                    )
                return await response.json()

    async def _post_form(self, url: str, form: aiohttp.FormData) -> dict[str, Any]:
        """发送表单 POST 请求。"""

        start_time = time.time()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                url,
                headers=self._build_headers(),
                data=form,
            ) as response:
                duration = time.time() - start_time
                if response.status != 200:
                    error_text = await response.text()
                    self._log_error(
                        "OpenAI API错误: status=%s duration=%.2fs url=%s response_preview=%s",
                        response.status,
                        duration,
                        url,
                        error_text[:1200],
                    )
                    raise RuntimeError(
                        f"OpenAI 图片编辑接口错误 ({response.status}, 耗时: {duration:.2f}s): {error_text}"
                    )
                return await response.json()

    async def _post_edit_form_with_fallback(
        self,
        *,
        url: str,
        model: str,
        prompt: str,
        image_bytes: bytes,
        mime_type: str,
        n: int,
    ) -> dict[str, Any]:
        """发送图片编辑表单，并自动兼容 image / image[] 两种字段名。"""

        attempt_errors: list[str] = []
        filename = self._guess_filename_by_mime_type(mime_type)
        for field_name in ("image", "image[]"):
            try:
                form = aiohttp.FormData()
                form.add_field("model", model)
                form.add_field("prompt", prompt)
                form.add_field("n", str(n))
                form.add_field("size", "1024x1024")
                form.add_field(
                    field_name,
                    image_bytes,
                    filename=filename,
                    content_type=mime_type,
                )
                return await self._post_form(url=url, form=form)
            except Exception as exc:
                attempt_errors.append(f"{field_name}: {exc}")
        raise RuntimeError("图片编辑表单提交失败: " + " | ".join(attempt_errors))

    async def _extract_images(self, response: dict[str, Any]) -> list[bytes]:
        """从接口响应中提取图片。"""

        data = response.get("data")
        if not isinstance(data, list):
            response_preview = str(response)[:1200]
            raise RuntimeError(f"响应中未找到 data 字段，response_preview={response_preview}")

        image_bytes_list: list[bytes] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            image_base64 = item.get("b64_json")
            if isinstance(image_base64, str) and image_base64:
                image_bytes_list.append(base64.b64decode(image_base64))
                continue

            image_url = item.get("url")
            if isinstance(image_url, str) and image_url:
                image_bytes_list.append(await self._download_image(image_url))

        if not image_bytes_list:
            raise RuntimeError("未找到有效的图片数据")
        return image_bytes_list

    async def _extract_images_auto(self, response: dict[str, Any]) -> list[bytes]:
        """自动尝试多种图片响应格式。"""

        parsers = (
            self._extract_images,
            self._extract_novelai_images,
            self._extract_chat_completion_images,
        )
        errors: list[str] = []
        for parser in parsers:
            try:
                return await parser(response)
            except Exception as exc:
                errors.append(f"{parser.__name__}: {exc}")
        raise RuntimeError("未能从响应中解析图片数据: " + " | ".join(errors))

    async def _extract_novelai_images(self, response: dict[str, Any]) -> list[bytes]:
        """从 NovelAI 风格响应中提取图片。"""

        images = response.get("images")
        if not isinstance(images, list):
            response_preview = str(response)[:1200]
            raise RuntimeError(f"NovelAI 响应中未找到 images 字段，response_preview={response_preview}")

        image_bytes_list: list[bytes] = []
        for item in images:
            if isinstance(item, str) and item:
                image_bytes_list.append(base64.b64decode(item))

        if not image_bytes_list:
            raise RuntimeError("NovelAI 响应中没有可用图片数据")
        return image_bytes_list

    async def _extract_chat_completion_images(self, response: dict[str, Any]) -> list[bytes]:
        """从 chat completions 响应中提取图片。"""

        choices = response.get("choices")
        if not isinstance(choices, list):
            raise RuntimeError("chat completions 响应中未找到 choices 字段")

        image_bytes_list: list[bytes] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue

            content = message.get("content")
            if isinstance(content, str):
                extracted = await self._extract_image_bytes_from_string(content)
                if extracted is not None:
                    image_bytes_list.append(extracted)
                continue

            if isinstance(content, list):
                for item in content:
                    extracted = await self._extract_image_bytes_from_content_item(item)
                    if extracted is not None:
                        image_bytes_list.append(extracted)

            direct_images = message.get("images")
            if isinstance(direct_images, list):
                for item in direct_images:
                    extracted = await self._extract_image_bytes_from_content_item(item)
                    if extracted is not None:
                        image_bytes_list.append(extracted)

        if image_bytes_list:
            return image_bytes_list

        response_output = response.get("output")
        if isinstance(response_output, list):
            for item in response_output:
                extracted = await self._extract_image_bytes_from_content_item(item)
                if extracted is not None:
                    image_bytes_list.append(extracted)

        top_level_image = response.get("image") or response.get("image_url") or response.get("b64_json")
        extracted = await self._extract_image_bytes_from_content_item(top_level_image)
        if extracted is not None:
            image_bytes_list.append(extracted)

        if image_bytes_list:
            return image_bytes_list

        choices_preview = str(choices)[:1200]
        raise RuntimeError(
            "chat completions 响应中未找到可解析的图片数据，choices_preview="
            f"{choices_preview}"
        )

    async def _extract_image_bytes_from_content_item(self, item: Any) -> bytes | None:
        """从单个内容片段中提取图片。"""

        if isinstance(item, str):
            return await self._extract_image_bytes_from_string(item)

        if not isinstance(item, dict):
            return None

        image_base64 = item.get("b64_json") or item.get("image_base64")
        if isinstance(image_base64, str) and image_base64:
            return base64.b64decode(image_base64)

        image_url = item.get("url")
        if isinstance(image_url, str) and image_url:
            return await self._extract_image_bytes_from_string(image_url)

        image_url_object = item.get("image_url")
        if isinstance(image_url_object, dict):
            image_url = image_url_object.get("url")
        else:
            image_url = image_url_object
        if isinstance(image_url, str) and image_url:
            return await self._extract_image_bytes_from_string(image_url)

        data_field = item.get("data")
        if isinstance(data_field, str) and data_field:
            return await self._extract_image_bytes_from_string(data_field)

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

        markdown_match = self._MARKDOWN_IMAGE_PATTERN.search(value)
        if markdown_match is not None:
            return await self._extract_image_bytes_from_string(markdown_match.group(1))

        return None

    async def _download_image(self, url: str) -> bytes:
        """下载 URL 形式返回的图片。"""

        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    self._log_error("OpenAI API错误: 下载图片失败 status=%s url=%s", response.status, url)
                    raise RuntimeError(f"下载生成图片失败: status={response.status}")
                return await response.read()

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""

        if self.logger is not None:
            self.logger.error(message, *args)
