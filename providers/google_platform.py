from io import BytesIO
from typing import Any

from google import genai
from google.genai import errors, types
from PIL import Image as PILImage


class GoogleImage:
    """Google 图片平台封装。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
    ):
        client_kwargs: dict[str, Any] = {"api_key": api_key}
        http_options: dict[str, Any] = {"timeout": request_timeout_seconds * 1000}
        normalized_base_url = base_url.strip()
        self.base_url = normalized_base_url or "https://generativelanguage.googleapis.com"
        self.logger = logger
        if normalized_base_url and normalized_base_url != "https://api.openai.com/v1":
            http_options["base_url"] = normalized_base_url
        client_kwargs["http_options"] = http_options
        self.client = genai.Client(**client_kwargs)

    @staticmethod
    def _uses_generate_content_api(model: str) -> bool:
        """判断当前模型是否应走 Gemini generateContent 图片接口。"""

        normalized_model = model.strip().lower()
        return "image-preview" in normalized_model or "flash-image" in normalized_model

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
    def _extract_images_from_generate_content_response(response: Any) -> list[bytes]:
        """从 generate_content 响应中提取图片字节。"""

        image_bytes_list: list[bytes] = []
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                inline_data = getattr(part, "inline_data", None)
                if inline_data is None:
                    continue
                data = getattr(inline_data, "data", None)
                if data:
                    image_bytes_list.append(data)
        return image_bytes_list

    def _wrap_google_error(self, exc: Exception, model: str, operation: str) -> RuntimeError:
        """将 Google SDK 异常整理为更容易排查的中文错误。"""

        if isinstance(exc, errors.ServerError):
            self._log_error(
                "Google API错误: operation=%s model=%s base_url=%s status=%s error=%s",
                operation,
                model,
                self.base_url,
                exc.code,
                exc,
            )
            return RuntimeError(
                f"Google 图片服务暂时不可用（{operation}，模型: {model}，网关: {self.base_url}，"
                f"状态码: {exc.code}）。这通常是上游网关或模型服务异常，请稍后重试或切换模型。"
            )
        if isinstance(exc, errors.ClientError):
            self._log_error(
                "Google API错误: operation=%s model=%s base_url=%s status=%s error=%s",
                operation,
                model,
                self.base_url,
                exc.code,
                exc,
            )
            return RuntimeError(
                f"Google 图片请求失败（{operation}，模型: {model}，网关: {self.base_url}，"
                f"状态码: {exc.code}）：{exc}"
            )
        self._log_error(
            "Google API错误: operation=%s model=%s base_url=%s error=%s",
            operation,
            model,
            self.base_url,
            exc,
        )
        return RuntimeError(
            f"Google 图片请求失败（{operation}，模型: {model}，网关: {self.base_url}）：{exc}"
        )

    def _log_error(self, message: str, *args: Any) -> None:
        """记录错误日志。"""

        if self.logger is not None:
            self.logger.error(message, *args)

    def _generate_images_with_generate_content(self, prompt: str, model: str) -> list[bytes]:
        """使用 Gemini generateContent 接口执行文生图。"""
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )
        except Exception as exc:
            raise self._wrap_google_error(exc, model, "文生图") from exc
        return self._extract_images_from_generate_content_response(response)

    def _edit_images_with_generate_content(
        self,
        prompt: str,
        model: str,
        image_bytes: bytes,
    ) -> list[bytes]:
        """使用 Gemini generateContent 接口执行图生图。"""
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=self._detect_mime_type(image_bytes),
                    ),
                    prompt,
                ],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )
        except Exception as exc:
            raise self._wrap_google_error(exc, model, "图生图") from exc
        return self._extract_images_from_generate_content_response(response)

    def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """调用 Google 文生图接口。"""

        if self._uses_generate_content_api(model):
            return self._generate_images_with_generate_content(prompt, model)

        try:
            response = self.client.models.generate_images(
                model=model,
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=n,
                    output_mime_type="image/png",
                ),
            )
        except Exception as exc:
            raise self._wrap_google_error(exc, model, "文生图") from exc

        image_bytes_list: list[bytes] = []
        for generated_image in response.generated_images or []:
            image = getattr(generated_image, "image", None)
            image_bytes = getattr(image, "image_bytes", None)
            if image_bytes:
                image_bytes_list.append(image_bytes)
        return image_bytes_list

    def edit_images(self, prompt: str, model: str, image_bytes: bytes, n: int = 1) -> list[bytes]:
        """调用 Google 图生图接口。"""

        if self._uses_generate_content_api(model):
            return self._edit_images_with_generate_content(prompt, model, image_bytes)

        reference_image = types.RawReferenceImage(
            reference_id=1,
            reference_image=types.Image(
                image_bytes=image_bytes,
                mime_type=self._detect_mime_type(image_bytes),
            ),
        )
        try:
            response = self.client.models.edit_image(
                model=model,
                prompt=prompt,
                reference_images=[reference_image],
                config=types.EditImageConfig(
                    number_of_images=n,
                    output_mime_type="image/png",
                ),
            )
        except Exception as exc:
            raise self._wrap_google_error(exc, model, "图生图") from exc

        image_bytes_list: list[bytes] = []
        for generated_image in response.generated_images or []:
            image = getattr(generated_image, "image", None)
            generated_bytes = getattr(image, "image_bytes", None)
            if generated_bytes:
                image_bytes_list.append(generated_bytes)
        return image_bytes_list
