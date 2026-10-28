"""Agnes 官方图像协议，复用有界响应读取、结果解析和诊断脱敏。"""

from typing import Any, Dict, List, Optional
import asyncio

from .openai import OpenaiImage
from ..http import HttpProxySettings
from ...domain.models.agnes_profiles import build_agnes_payload


class AgnesImage(OpenaiImage):
    """通过官方生成端点执行 Agnes 文生图与多参考图编辑。"""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://apihub.agnes-ai.com/v1",
        default_size: str = "1024x1024",
        ratio: str = "1:1",
        response_format: str = "b64_json",
        model_size_overrides: Optional[Dict[str, str]] = None,
        extra_parameters: Optional[Dict[str, Any]] = None,
        request_timeout_seconds: int = 150,
        logger: Any = None,
        proxy_settings: Optional[HttpProxySettings] = None,
        skip_image_url_ip_check: bool = False,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_size=default_size,
            model_size_overrides=model_size_overrides,
            extra_parameters=extra_parameters,
            request_timeout_seconds=request_timeout_seconds,
            logger=logger,
            proxy_settings=proxy_settings,
            skip_image_url_ip_check=skip_image_url_ip_check,
        )
        self.ratio = ratio
        self.agnes_response_format = response_format

    async def _generate(self, prompt: str, model: str, n: int, images: Optional[List[str]] = None) -> List[bytes]:
        payload = build_agnes_payload(
            prompt,
            model,
            size=self._resolve_size(model),
            ratio=self.ratio,
            response_format=self.agnes_response_format,
            extra_parameters=self.extra_parameters,
            images=images,
            n=n,
        )
        response = await self._post_json(self._build_api_url("images/generations"), payload)
        return await self._extract_images(response)

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> List[bytes]:
        return await self._generate(prompt, model, n)

    async def edit_images(self, prompt: str, model: str, image_bytes_list: List[bytes], n: int = 1) -> List[bytes]:
        # 图片验证与 Base64 编码可能较大，在线程中完成并保留全部参考图。
        images = await asyncio.to_thread(lambda: [self._source_image_data_url(image) for image in image_bytes_list])
        return await self._generate(prompt, model, n, images)
