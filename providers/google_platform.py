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
        number_of_images: int = 1,
        aspect_ratio: str = "",
        output_mime_type: str = "image/png",
        person_generation: str = "",
        negative_prompt: str = "",
        seed: int = -1,
        guidance_scale: float = 0.0,
        add_watermark: bool = False,
        extra_parameters: dict[str, Any] | None = None,
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
        self.number_of_images = max(int(number_of_images), 1)
        self.aspect_ratio = aspect_ratio.strip()
        self.output_mime_type = output_mime_type.strip()
        self.person_generation = person_generation.strip()
        self.negative_prompt = negative_prompt.strip()
        self.seed = int(seed)
        self.guidance_scale = float(guidance_scale)
        self.add_watermark = add_watermark
        self.extra_parameters = dict(extra_parameters or {})

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

    @staticmethod
    def _filter_config_kwargs(config_class: type[Any], kwargs: dict[str, Any]) -> dict[str, Any]:
        """只保留当前 google-genai 版本支持的配置字段。"""

        fields = getattr(config_class, "model_fields", None)
        if isinstance(fields, dict):
            return {key: value for key, value in kwargs.items() if key in fields and value is not None}
        return {key: value for key, value in kwargs.items() if value is not None}

    def _build_image_config_kwargs(self, n: int) -> dict[str, Any]:
        """构建 Google 图片生成/编辑配置参数。"""

        kwargs: dict[str, Any] = {
            "number_of_images": min(max(int(n), 1), self.number_of_images),
        }
        if self.output_mime_type:
            kwargs["output_mime_type"] = self.output_mime_type
        if self.aspect_ratio:
            kwargs["aspect_ratio"] = self.aspect_ratio
        if self.person_generation:
            kwargs["person_generation"] = self.person_generation
        if self.negative_prompt:
            kwargs["negative_prompt"] = self.negative_prompt
        if self.seed >= 0:
            kwargs["seed"] = self.seed
        if self.guidance_scale > 0:
            kwargs["guidance_scale"] = self.guidance_scale
        kwargs["add_watermark"] = self.add_watermark
        kwargs.update(self.extra_parameters)
        return kwargs

    def _build_generate_content_config(self) -> types.GenerateContentConfig:
        """构建 Gemini generateContent 图片配置。"""

        config_kwargs: dict[str, Any] = {
            "response_modalities": ["TEXT", "IMAGE"],
        }
        image_config_class = getattr(types, "ImageConfig", None)
        if image_config_class is not None:
            image_config_kwargs = {
                key: value
                for key, value in self._build_image_config_kwargs(1).items()
                if key not in {"number_of_images", "add_watermark"}
            }
            filtered_image_config_kwargs = self._filter_config_kwargs(image_config_class, image_config_kwargs)
            if filtered_image_config_kwargs:
                config_kwargs["image_config"] = image_config_class(**filtered_image_config_kwargs)
        return types.GenerateContentConfig(
            **self._filter_config_kwargs(types.GenerateContentConfig, config_kwargs)
        )

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
                config=self._build_generate_content_config(),
            )
        except Exception as exc:
            raise self._wrap_google_error(exc, model, "文生图") from exc
        return self._extract_images_from_generate_content_response(response)

    def _edit_images_with_generate_content(
        self,
        prompt: str,
        model: str,
        image_bytes_list: list[bytes],
    ) -> list[bytes]:
        """使用 Gemini generateContent 接口执行图生图，支持多张源图片。"""
        contents: list[Any] = [
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=self._detect_mime_type(image_bytes),
            )
            for image_bytes in image_bytes_list
        ]
        contents.append(prompt)
        try:
            response = self.client.models.generate_content(
                model=model,
                contents=contents,
                config=self._build_generate_content_config(),
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
                    **self._filter_config_kwargs(
                        types.GenerateImagesConfig,
                        self._build_image_config_kwargs(n),
                    )
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

    def edit_images(self, prompt: str, model: str, image_bytes_list: list[bytes], n: int = 1) -> list[bytes]:
        """调用 Google 图生图接口，支持一张或多张源图片。"""

        if not image_bytes_list:
            raise RuntimeError("没有可用于图生图的源图片")

        if self._uses_generate_content_api(model):
            return self._edit_images_with_generate_content(prompt, model, image_bytes_list)

        reference_images = [
            types.RawReferenceImage(
                reference_id=index,
                reference_image=types.Image(
                    image_bytes=image_bytes,
                    mime_type=self._detect_mime_type(image_bytes),
                ),
            )
            for index, image_bytes in enumerate(image_bytes_list, start=1)
        ]
        try:
            response = self.client.models.edit_image(
                model=model,
                prompt=prompt,
                reference_images=reference_images,
                config=types.EditImageConfig(
                    **self._filter_config_kwargs(
                        types.EditImageConfig,
                        self._build_image_config_kwargs(n),
                    )
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
