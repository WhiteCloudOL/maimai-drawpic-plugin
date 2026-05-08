from typing import Any, Literal, Protocol

from ..providers.google_platform import GoogleImage
from ..providers.openai_platform import OpenaiImage
from .config import DrawpicConfig, OpenAICompatibilityMode


class ImageProvider(Protocol):
    def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """根据文本提示生成图片。"""

    def edit_images(self, prompt: str, model: str, image_bytes: bytes, n: int = 1) -> list[bytes]:
        """基于输入图片执行编辑。"""


class ProviderRouter:
    """负责模型归属判断与 Provider 创建。"""

    def __init__(self, config: DrawpicConfig):
        self.config = config

    def get_openai_models(self) -> list[str]:
        """获取 OpenAI 模型列表。"""

        return [model.strip() for model in self.config.openai.models if model.strip()]

    def get_google_models(self) -> list[str]:
        """获取 Google 模型列表。"""

        return [model.strip() for model in self.config.google.models if model.strip()]

    def get_all_models(self) -> list[str]:
        """获取全部可用模型列表。"""

        return self.get_openai_models() + self.get_google_models()

    def get_model_provider(self, model: str) -> Literal["openai", "google", ""]:
        """根据模型名称判断其所属提供商。"""

        normalized_model = model.strip()
        if normalized_model in self.get_openai_models():
            return "openai"
        if normalized_model in self.get_google_models():
            return "google"
        return ""

    def resolve_default_model(self) -> str:
        """解析当前有效的默认模型。"""

        configured_default = self.config.general.default_model.strip()
        if self.get_model_provider(configured_default):
            return configured_default

        all_models = self.get_all_models()
        if all_models:
            return all_models[0]
        raise ValueError("当前未配置任何可用图片模型")

    def resolve_openai_compatibility_mode(self, mode: str = "") -> OpenAICompatibilityMode:
        """解析最终使用的 OpenAI 兼容模式。"""

        normalized_mode = mode.strip()
        if normalized_mode in {"auto", "images_api", "chat_completions", "novelai_images_api"}:
            return normalized_mode  # type: ignore[return-value]

        default_mode = self.config.general.default_openai_compatibility_mode
        if default_mode in {"auto", "images_api", "chat_completions", "novelai_images_api"}:
            return default_mode
        return "auto"

    def resolve_request_timeout_seconds(self) -> int:
        """解析最终使用的请求超时时间。"""

        timeout_seconds = int(self.config.general.request_timeout_seconds)
        if timeout_seconds < 5:
            return 5
        if timeout_seconds > 600:
            return 600
        return timeout_seconds

    def resolve_model_name(self, model: str = "", allow_unknown_model: bool = False) -> str:
        """解析最终使用的模型名。"""

        normalized_model = model.strip()
        if normalized_model and self.get_model_provider(normalized_model):
            return normalized_model
        if normalized_model and allow_unknown_model:
            return normalized_model
        return self.resolve_default_model()

    def create_openai_provider(self, compatibility_mode: OpenAICompatibilityMode) -> OpenaiImage:
        """创建 OpenAI 图片提供商实例。"""

        return OpenaiImage(
            api_key=self.config.openai.api_key,
            base_url=self.config.openai.base_url,
            compatibility_mode=compatibility_mode,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
        )

    def create_google_provider(self) -> GoogleImage:
        """创建 Google 图片提供商实例。"""

        return GoogleImage(
            api_key=self.config.google.api_key,
            base_url=self.config.google.base_url,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
        )

    def require_platform_for_model(
        self,
        model: str,
        openai_compatibility_mode: str = "",
    ) -> tuple[ImageProvider, Literal["openai", "google"]]:
        """根据模型解析并创建对应的平台实例。"""

        provider_type = self.get_model_provider(model)
        if provider_type == "google":
            return self.create_google_provider(), "google"
        if provider_type == "openai":
            return self.create_openai_provider(
                self.resolve_openai_compatibility_mode(openai_compatibility_mode)
            ), "openai"
        raise RuntimeError(f"模型未归属于任何已配置提供商：{model}")
