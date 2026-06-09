from typing import Any, Literal, Protocol

from ..providers.aliyun_platform import AliyunImage
from ..providers.google_platform import GoogleImage
from ..providers.novelai_platform import NovelAIImage
from ..providers.openai_platform import OpenaiImage
from ..providers.siliconflow_platform import SiliconFlowImage
from ..providers.zhipu_platform import ZhipuImage
from .config import DrawpicConfig, OpenAICompatibilityMode
from .provider_options import parse_key_value_options, parse_model_value_overrides

ProviderName = Literal["aliyun", "openai", "google", "zhipu", "siliconflow", "novelai"]


class ImageProvider(Protocol):
    def generate_images(self, prompt: str, model: str, n: int = 1) -> list[bytes]:
        """根据文本提示生成图片。"""

    def edit_images(self, prompt: str, model: str, image_bytes: bytes, n: int = 1) -> list[bytes]:
        """基于输入图片执行编辑。"""


class ProviderRouter:
    """负责模型归属判断与 Provider 创建。"""

    def __init__(self, config: DrawpicConfig, logger: Any | None = None):
        self.config = config
        self.logger = logger

    def get_openai_models(self) -> list[str]:
        """获取 OpenAI 模型列表。"""

        return [model.strip() for model in self.config.openai.models if model.strip()]

    def get_aliyun_models(self) -> list[str]:
        """获取阿里百炼模型列表。"""

        return [model.strip() for model in self.config.aliyun.models if model.strip()]

    def get_google_models(self) -> list[str]:
        """获取 Google 模型列表。"""

        return [model.strip() for model in self.config.google.models if model.strip()]

    def get_zhipu_models(self) -> list[str]:
        """获取智谱模型列表。"""

        return [model.strip() for model in self.config.zhipu.models if model.strip()]

    def get_siliconflow_models(self) -> list[str]:
        """获取硅基流动模型列表。"""

        return [model.strip() for model in self.config.siliconflow.models if model.strip()]

    def get_novelai_models(self) -> list[str]:
        """获取 NovelAI / NovelAPI 模型列表。"""

        return [model.strip() for model in self.config.novelai.models if model.strip()]

    def get_all_models(self) -> list[str]:
        """获取全部可用模型列表。"""

        return (
            self.get_aliyun_models()
            + self.get_openai_models()
            + self.get_google_models()
            + self.get_zhipu_models()
            + self.get_siliconflow_models()
            + self.get_novelai_models()
        )

    def get_model_provider(self, model: str) -> ProviderName | Literal[""]:
        """根据模型名称判断其所属提供商。"""

        normalized_model = model.strip()
        if normalized_model in self.get_aliyun_models():
            return "aliyun"
        if normalized_model in self.get_openai_models():
            return "openai"
        if normalized_model in self.get_google_models():
            return "google"
        if normalized_model in self.get_zhipu_models():
            return "zhipu"
        if normalized_model in self.get_siliconflow_models():
            return "siliconflow"
        if normalized_model in self.get_novelai_models():
            return "novelai"
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

        default_mode = self.config.openai.default_openai_compatibility_mode
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

    def should_rewrite_prompt_to_english(self, provider_name: str) -> bool:
        """判断指定提供商是否需要先把提示词改写为英文。"""

        normalized_provider = provider_name.strip().lower()
        if normalized_provider == "aliyun":
            return self.config.aliyun.rewrite_prompt_to_english
        if normalized_provider == "openai":
            return self.config.openai.rewrite_prompt_to_english
        if normalized_provider == "google":
            return self.config.google.rewrite_prompt_to_english
        if normalized_provider == "zhipu":
            return self.config.zhipu.rewrite_prompt_to_english
        if normalized_provider == "siliconflow":
            return self.config.siliconflow.rewrite_prompt_to_english
        if normalized_provider == "novelai":
            return self.config.novelai.rewrite_prompt_to_english
        return False

    def resolve_model_name(self, model: str = "", allow_unknown_model: bool = False) -> str:
        """解析最终使用的模型名。"""

        normalized_model = model.strip()
        if normalized_model and self.get_model_provider(normalized_model):
            return normalized_model
        if normalized_model and allow_unknown_model:
            return normalized_model
        return self.resolve_default_model()

    def create_aliyun_provider(self) -> AliyunImage:
        """创建阿里百炼图片提供商实例。"""

        return AliyunImage(
            api_key=self.config.aliyun.api_key,
            base_url=self.config.aliyun.base_url,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            default_size=self.config.aliyun.default_size,
            model_size_overrides=parse_model_value_overrides(self.config.aliyun.model_size_overrides),
            negative_prompt=self.config.aliyun.negative_prompt,
            prompt_extend=self.config.aliyun.prompt_extend,
            watermark=self.config.aliyun.watermark,
            max_images=self.config.aliyun.max_images,
            extra_parameters=parse_key_value_options(self.config.aliyun.extra_parameters),
        )

    def create_openai_provider(self, compatibility_mode: OpenAICompatibilityMode) -> OpenaiImage:
        """创建 OpenAI 图片提供商实例。"""

        return OpenaiImage(
            api_key=self.config.openai.api_key,
            base_url=self.config.openai.base_url,
            compatibility_mode=compatibility_mode,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            default_size=self.config.openai.default_size,
            model_size_overrides=parse_model_value_overrides(self.config.openai.model_size_overrides),
            quality=self.config.openai.quality,
            response_format=self.config.openai.response_format,
            output_format=self.config.openai.output_format,
            background=self.config.openai.background,
            moderation=self.config.openai.moderation,
            max_images=self.config.openai.max_images,
            extra_parameters=parse_key_value_options(self.config.openai.extra_parameters),
        )

    def create_google_provider(self) -> GoogleImage:
        """创建 Google 图片提供商实例。"""

        return GoogleImage(
            api_key=self.config.google.api_key,
            base_url=self.config.google.base_url,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            number_of_images=self.config.google.number_of_images,
            aspect_ratio=self.config.google.aspect_ratio,
            output_mime_type=self.config.google.output_mime_type,
            person_generation=self.config.google.person_generation,
            negative_prompt=self.config.google.negative_prompt,
            seed=self.config.google.seed,
            guidance_scale=self.config.google.guidance_scale,
            add_watermark=self.config.google.add_watermark,
            extra_parameters=parse_key_value_options(self.config.google.extra_parameters),
        )

    def create_zhipu_provider(self) -> ZhipuImage:
        """创建智谱图片提供商实例。"""

        return ZhipuImage(
            api_key=self.config.zhipu.api_key,
            base_url=self.config.zhipu.base_url,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            size=self.config.zhipu.size,
            response_format=self.config.zhipu.response_format,
            user=self.config.zhipu.user,
            extra_parameters=parse_key_value_options(self.config.zhipu.extra_parameters),
        )

    def create_siliconflow_provider(self) -> SiliconFlowImage:
        """创建硅基流动图片提供商实例。"""

        return SiliconFlowImage(
            api_key=self.config.siliconflow.api_key,
            base_url=self.config.siliconflow.base_url,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            image_size=self.config.siliconflow.image_size,
            model_size_overrides=parse_model_value_overrides(self.config.siliconflow.model_size_overrides),
            batch_size=self.config.siliconflow.batch_size,
            seed=self.config.siliconflow.seed,
            num_inference_steps=self.config.siliconflow.num_inference_steps,
            guidance_scale=self.config.siliconflow.guidance_scale,
            negative_prompt=self.config.siliconflow.negative_prompt,
            output_format=self.config.siliconflow.output_format,
            extra_parameters=parse_key_value_options(self.config.siliconflow.extra_parameters),
        )

    def create_novelai_provider(self) -> NovelAIImage:
        """创建 NovelAI / NovelAPI 图片提供商实例。"""

        return NovelAIImage(
            api_key=self.config.novelai.api_key,
            base_url=self.config.novelai.base_url,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            width=self.config.novelai.width,
            height=self.config.novelai.height,
            model_size_overrides=parse_model_value_overrides(self.config.novelai.model_size_overrides),
            sampler=self.config.novelai.sampler,
            steps=self.config.novelai.steps,
            scale=self.config.novelai.scale,
            seed=self.config.novelai.seed,
            negative_prompt=self.config.novelai.negative_prompt,
            uc_preset=self.config.novelai.uc_preset,
            quality_toggle=self.config.novelai.quality_toggle,
            sm=self.config.novelai.sm,
            sm_dyn=self.config.novelai.sm_dyn,
            noise_schedule=self.config.novelai.noise_schedule,
            img2img_strength=self.config.novelai.img2img_strength,
            img2img_noise=self.config.novelai.img2img_noise,
            max_images=self.config.novelai.max_images,
            extra_parameters=parse_key_value_options(self.config.novelai.extra_parameters),
        )

    def supports_image_edit(self, model: str) -> bool:
        """判断模型是否支持图生图编辑。"""

        return self.get_model_provider(model) != "zhipu"

    def require_platform_for_model(
        self,
        model: str,
        openai_compatibility_mode: str = "",
    ) -> tuple[ImageProvider, ProviderName]:
        """根据模型解析并创建对应的平台实例。"""

        provider_type = self.get_model_provider(model)
        if provider_type == "aliyun":
            return self.create_aliyun_provider(), "aliyun"
        if provider_type == "google":
            return self.create_google_provider(), "google"
        if provider_type == "zhipu":
            return self.create_zhipu_provider(), "zhipu"
        if provider_type == "siliconflow":
            return self.create_siliconflow_provider(), "siliconflow"
        if provider_type == "novelai":
            return self.create_novelai_provider(), "novelai"
        if provider_type == "openai":
            return self.create_openai_provider(
                self.resolve_openai_compatibility_mode(openai_compatibility_mode)
            ), "openai"
        raise RuntimeError(f"模型未归属于任何已配置提供商：{model}")
