from dataclasses import dataclass
from typing import Any, Literal, Protocol

from ...domain.configuration.platforms.common import NegativePromptConfig
from ...infrastructure.providers.openai import OpenaiImage

ProviderName = Literal["agnes", "aliyun", "openai", "google", "zhipu", "minimax", "volcengine", "siliconflow", "novelai", "comfyui"]


_DOMESTIC_PROXY_BYPASS_PROVIDERS = {"aliyun", "volcengine", "siliconflow", "minimax"}


@dataclass(frozen=True, slots=True)
class ModelTaskCapability:
    """模型对指定绘图任务的判断结果。"""

    allowed: bool
    reason: str
    source: str


@dataclass(frozen=True, slots=True)
class OpenAIModelRoute:
    """OpenAI 兼容模型到具体实例的路由。"""

    display_model: str
    upstream_model: str
    instance_name: str
    api_key: str
    base_url: str
    compatibility_mode: str
    default_size: str
    model_size_overrides: dict[str, str]
    quality: str
    response_format: str
    output_format: str
    background: str
    moderation: str
    max_images: int
    extra_parameters: dict[str, Any]
    rewrite_prompt_to_english: bool
    negative_prompt_config: NegativePromptConfig


class ImageProvider(Protocol):
    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """根据文本提示生成图片。"""

    async def edit_images(self, prompt: str, model: str, image_bytes_list: list[bytes], n: int = 1) -> list[bytes]:
        """基于一张或多张输入图片执行编辑。"""


class RoutedOpenAIImage:
    """把用户可见模型名映射到 OpenAI 兼容实例的上游模型名。"""

    def __init__(self, provider: OpenaiImage, upstream_model: str) -> None:
        self.provider = provider
        self.upstream_model = upstream_model

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """使用上游模型名执行文生图。"""

        del model
        return await self.provider.generate_images(prompt, self.upstream_model, n)

    async def edit_images(self, prompt: str, model: str, image_bytes_list: list[bytes], n: int = 1) -> list[bytes]:
        """使用上游模型名执行图生图。"""

        del model
        return await self.provider.edit_images(prompt, self.upstream_model, image_bytes_list, n)
