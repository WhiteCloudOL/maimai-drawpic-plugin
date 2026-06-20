from dataclasses import dataclass
from typing import Any, Literal, Protocol

import re

from ..providers.aliyun_platform import AliyunImage
from ..providers.google_platform import GoogleImage
from ..providers.novelai_platform import NovelAIImage
from ..providers.openai_platform import OpenaiImage
from ..providers.siliconflow_platform import SiliconFlowImage
from ..providers.volcengine_platform import VolcengineImage
from ..providers.zhipu_platform import ZhipuImage
from .config import DrawpicConfig, OpenAICompatibilityMode
from .provider_options import parse_key_value_options, parse_model_value_overrides

ProviderName = Literal["aliyun", "openai", "google", "zhipu", "volcengine", "siliconflow", "novelai"]
OPENAI_COMPATIBILITY_MODES = {"auto", "images_api", "chat_completions", "novelai_images_api"}


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


class ProviderRouter:
    """负责模型归属判断与 Provider 创建。"""

    def __init__(self, config: DrawpicConfig, logger: Any | None = None):
        self.config = config
        self.logger = logger
        # Provider 实例缓存：键为 (provider_type, model, openai_compatibility_mode)，
        # 值为已构造的 ImageProvider 实例。ProviderRouter 每次随 _refresh_services 重建，
        # 因此缓存生命周期与配置版本一致，无需手动失效。
        self._provider_cache: dict[tuple[str, str, str], ImageProvider] = {}
        # OpenAI 路由列表缓存，避免每次 get_openai_models / get_model_provider 都重算
        self._openai_routes_cache: list[OpenAIModelRoute] | None = None

    @staticmethod
    def _split_inline_items(value: str) -> list[str]:
        """按换行、逗号或分号拆分 WebUI 对象列表内的复合字符串字段。"""

        return [item.strip() for item in re.split(r"[\n,;；，]+", str(value or "")) if item.strip()]

    @classmethod
    def _parse_model_routes(cls, value: str) -> list[tuple[str, str]]:
        """解析模型映射，支持 显示名=上游模型名。"""

        routes: list[tuple[str, str]] = []
        for item in cls._split_inline_items(value):
            if "=" in item:
                display_model, upstream_model = item.split("=", maxsplit=1)
                display_model = display_model.strip()
                upstream_model = upstream_model.strip()
            else:
                display_model = item
                upstream_model = item
            if display_model and upstream_model:
                routes.append((display_model, upstream_model))
        return routes

    @classmethod
    def _parse_key_value_text(cls, value: str) -> list[str]:
        """解析对象列表内的 key=value 多行字段为字符串列表。"""

        return cls._split_inline_items(value)

    @staticmethod
    def _normalize_openai_compatibility_mode(mode: str) -> OpenAICompatibilityMode:
        """规范化 OpenAI 兼容模式。"""

        normalized_mode = mode.strip()
        if normalized_mode in OPENAI_COMPATIBILITY_MODES:
            return normalized_mode  # type: ignore[return-value]
        return "auto"

    def _iter_openai_routes(self) -> list[OpenAIModelRoute]:
        """展开主 OpenAI 配置和额外 OpenAI 兼容实例。"""

        # 路由列表在配置不变时是纯函数结果，缓存避免重复解析
        if self._openai_routes_cache is not None:
            return self._openai_routes_cache

        routes: list[OpenAIModelRoute] = []
        if self.config.openai.enabled:
            for model in self.config.openai.models:
                normalized_model = model.strip()
                if not normalized_model:
                    continue
                routes.append(
                    OpenAIModelRoute(
                        display_model=normalized_model,
                        upstream_model=normalized_model,
                        instance_name="OpenAI",
                        api_key=self.config.openai.api_key,
                        base_url=self.config.openai.base_url,
                        compatibility_mode=self.config.openai.default_openai_compatibility_mode,
                        default_size=self.config.openai.default_size,
                        model_size_overrides=parse_model_value_overrides(self.config.openai.model_size_overrides),
                        quality=self.config.openai.quality,
                        response_format=self.config.openai.response_format,
                        output_format=self.config.openai.output_format,
                        background=self.config.openai.background,
                        moderation=self.config.openai.moderation,
                        max_images=self.config.openai.max_images,
                        extra_parameters=parse_key_value_options(self.config.openai.extra_parameters),
                        rewrite_prompt_to_english=self.config.openai.rewrite_prompt_to_english,
                    )
                )

        for instance in self.config.openai.instances:
            if not instance.enabled:
                continue
            instance_name = instance.name.strip() or "OpenAI 兼容实例"
            instance_model_size_overrides = parse_model_value_overrides(
                self._parse_key_value_text(instance.model_size_overrides)
            )
            instance_extra_parameters = parse_key_value_options(self._parse_key_value_text(instance.extra_parameters))
            for display_model, upstream_model in self._parse_model_routes(instance.models):
                model_size_overrides = dict(instance_model_size_overrides)
                if display_model != upstream_model and display_model in model_size_overrides:
                    model_size_overrides.setdefault(upstream_model, model_size_overrides[display_model])
                routes.append(
                    OpenAIModelRoute(
                        display_model=display_model,
                        upstream_model=upstream_model,
                        instance_name=instance_name,
                        api_key=instance.api_key,
                        base_url=instance.base_url,
                        compatibility_mode=self._normalize_openai_compatibility_mode(
                            instance.default_openai_compatibility_mode
                        ),
                        default_size=instance.default_size,
                        model_size_overrides=model_size_overrides,
                        quality=instance.quality,
                        response_format=instance.response_format,
                        output_format=instance.output_format,
                        background=instance.background,
                        moderation=instance.moderation,
                        max_images=instance.max_images,
                        extra_parameters=instance_extra_parameters,
                        rewrite_prompt_to_english=instance.rewrite_prompt_to_english,
                    )
                )
        self._openai_routes_cache = routes
        return routes

    def resolve_openai_model_route(self, model: str) -> OpenAIModelRoute | None:
        """解析 OpenAI 显示模型名对应的具体实例。"""

        normalized_model = model.strip()
        if not normalized_model:
            return None
        for route in self._iter_openai_routes():
            if route.display_model == normalized_model:
                return route
        return None

    def get_openai_models(self) -> list[str]:
        """获取 OpenAI 模型列表。"""

        return [route.display_model for route in self._iter_openai_routes()]

    def get_aliyun_models(self) -> list[str]:
        """获取阿里百炼模型列表。"""

        if not self.config.aliyun.enabled:
            return []
        return [model.strip() for model in self.config.aliyun.models if model.strip()]

    def get_google_models(self) -> list[str]:
        """获取 Google 模型列表。"""

        if not self.config.google.enabled:
            return []
        return [model.strip() for model in self.config.google.models if model.strip()]

    def get_zhipu_models(self) -> list[str]:
        """获取智谱模型列表。"""

        if not self.config.zhipu.enabled:
            return []
        return [model.strip() for model in self.config.zhipu.models if model.strip()]

    def get_volcengine_t2i_models(self) -> list[str]:
        """获取火山引擎文生图模型列表。"""

        if not self.config.volcengine.enabled:
            return []
        return [model.strip() for model in self.config.volcengine.t2i_models if model.strip()]

    def get_volcengine_i2i_models(self) -> list[str]:
        """获取火山引擎图生图模型列表。"""

        if not self.config.volcengine.enabled:
            return []
        return [model.strip() for model in self.config.volcengine.i2i_models if model.strip()]

    def get_volcengine_models(self) -> list[str]:
        """获取火山引擎全部模型列表（文生图 + 图生图，去重保序）。"""

        combined: list[str] = []
        for model in self.get_volcengine_t2i_models() + self.get_volcengine_i2i_models():
            if model not in combined:
                combined.append(model)
        return combined

    def get_siliconflow_models(self) -> list[str]:
        """获取硅基流动模型列表。"""

        if not self.config.siliconflow.enabled:
            return []
        return [model.strip() for model in self.config.siliconflow.models if model.strip()]

    def get_novelai_models(self) -> list[str]:
        """获取 NovelAI / NovelAPI 模型列表。"""

        if not self.config.novelai.enabled:
            return []
        return [model.strip() for model in self.config.novelai.models if model.strip()]

    def get_all_models(self) -> list[str]:
        """获取全部可用模型列表。"""

        return (
            self.get_aliyun_models()
            + self.get_openai_models()
            + self.get_google_models()
            + self.get_zhipu_models()
            + self.get_volcengine_models()
            + self.get_siliconflow_models()
            + self.get_novelai_models()
        )

    def get_model_provider(self, model: str) -> ProviderName | Literal[""]:
        """根据模型名称判断其所属提供商。"""

        normalized_model = model.strip()
        if normalized_model in self.get_aliyun_models():
            return "aliyun"
        if self.resolve_openai_model_route(normalized_model) is not None:
            return "openai"
        if normalized_model in self.get_google_models():
            return "google"
        if normalized_model in self.get_zhipu_models():
            return "zhipu"
        if normalized_model in self.get_volcengine_models():
            return "volcengine"
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

    def resolve_openai_compatibility_mode(self, mode: str = "", model: str = "") -> OpenAICompatibilityMode:
        """解析最终使用的 OpenAI 兼容模式。"""

        normalized_mode = mode.strip()
        if normalized_mode in OPENAI_COMPATIBILITY_MODES:
            return normalized_mode  # type: ignore[return-value]

        if model:
            route = self.resolve_openai_model_route(model)
            if route is not None:
                return self._normalize_openai_compatibility_mode(route.compatibility_mode)
        if self.config.openai.default_openai_compatibility_mode in OPENAI_COMPATIBILITY_MODES:
            return self.config.openai.default_openai_compatibility_mode
        return "auto"

    def resolve_request_timeout_seconds(self) -> int:
        """解析最终使用的请求超时时间。"""

        timeout_seconds = int(self.config.general.request_timeout_seconds)
        if timeout_seconds < 5:
            return 5
        if timeout_seconds > 600:
            return 600
        return timeout_seconds

    def should_rewrite_prompt_to_english(self, provider_name: str, model: str = "") -> bool:
        """判断指定提供商是否需要先把提示词改写为英文。"""

        normalized_provider = provider_name.strip().lower()
        if normalized_provider == "aliyun":
            return self.config.aliyun.rewrite_prompt_to_english
        if normalized_provider == "openai":
            route = self.resolve_openai_model_route(model)
            if route is not None:
                return route.rewrite_prompt_to_english
            return self.config.openai.rewrite_prompt_to_english
        if normalized_provider == "google":
            return self.config.google.rewrite_prompt_to_english
        if normalized_provider == "zhipu":
            return self.config.zhipu.rewrite_prompt_to_english
        if normalized_provider == "volcengine":
            return self.config.volcengine.rewrite_prompt_to_english
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

    def create_openai_provider(self, compatibility_mode: OpenAICompatibilityMode, model: str = "") -> ImageProvider:
        """创建 OpenAI 图片提供商实例。"""

        route = self.resolve_openai_model_route(model)
        if route is None:
            route = OpenAIModelRoute(
                display_model=model.strip(),
                upstream_model=model.strip(),
                instance_name="OpenAI",
                api_key=self.config.openai.api_key,
                base_url=self.config.openai.base_url,
                compatibility_mode=self.config.openai.default_openai_compatibility_mode,
                default_size=self.config.openai.default_size,
                model_size_overrides=parse_model_value_overrides(self.config.openai.model_size_overrides),
                quality=self.config.openai.quality,
                response_format=self.config.openai.response_format,
                output_format=self.config.openai.output_format,
                background=self.config.openai.background,
                moderation=self.config.openai.moderation,
                max_images=self.config.openai.max_images,
                extra_parameters=parse_key_value_options(self.config.openai.extra_parameters),
                rewrite_prompt_to_english=self.config.openai.rewrite_prompt_to_english,
            )

        provider = OpenaiImage(
            api_key=route.api_key,
            base_url=route.base_url,
            compatibility_mode=compatibility_mode,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            default_size=route.default_size,
            model_size_overrides=route.model_size_overrides,
            quality=route.quality,
            response_format=route.response_format,
            output_format=route.output_format,
            background=route.background,
            moderation=route.moderation,
            max_images=route.max_images,
            extra_parameters=route.extra_parameters,
        )
        return RoutedOpenAIImage(provider, route.upstream_model)

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
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            size=self.config.zhipu.size,
            response_format=self.config.zhipu.response_format,
            user=self.config.zhipu.user,
            extra_parameters=parse_key_value_options(self.config.zhipu.extra_parameters),
        )

    def create_volcengine_provider(self) -> VolcengineImage:
        """创建火山引擎图片提供商实例。"""

        return VolcengineImage(
            api_key=self.config.volcengine.api_key,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            default_size=self.config.volcengine.default_size,
            model_size_overrides=parse_model_value_overrides(self.config.volcengine.model_size_overrides),
            model_endpoint_overrides=parse_model_value_overrides(self.config.volcengine.model_endpoint_overrides),
            response_format=self.config.volcengine.response_format,
            guidance_scale=self.config.volcengine.guidance_scale,
            seed=self.config.volcengine.seed,
            watermark=self.config.volcengine.watermark,
            max_images=self.config.volcengine.max_images,
            extra_parameters=parse_key_value_options(self.config.volcengine.extra_parameters),
        )

    def create_siliconflow_provider(self) -> SiliconFlowImage:
        """创建硅基流动图片提供商实例。"""

        return SiliconFlowImage(
            api_key=self.config.siliconflow.api_key,
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

        return not self.get_image_edit_unsupported_reason(model)

    def get_image_edit_unsupported_reason(self, model: str) -> str:
        """返回模型不支持图生图的原因，空字符串表示支持。"""

        normalized_model = model.strip()
        if not normalized_model:
            return "当前未解析到可用绘图模型，无法提交图生图任务"

        configured_unsupported_models = {
            configured_model.strip()
            for configured_model in self.config.general.image_edit_unsupported_models
            if configured_model.strip()
        }
        if normalized_model in configured_unsupported_models:
            return f"当前模型 {normalized_model} 已在配置中标记为不支持图生图"

        provider_name = self.get_model_provider(normalized_model)
        if not provider_name:
            return f"当前模型 {normalized_model} 未归属于任何已配置图片平台，无法判断图生图能力"
        if provider_name == "zhipu":
            return f"当前模型 {normalized_model} 属于智谱平台；该平台当前仅支持文生图，不支持图生图编辑"
        if provider_name == "volcengine":
            i2i_models = self.get_volcengine_i2i_models()
            if not i2i_models:
                return "火山引擎未配置图生图模型（i2i_models 为空），无法提交图生图任务"
            if normalized_model not in i2i_models:
                return f"当前模型 {normalized_model} 属于火山引擎文生图模型；请切换到 i2i 类模型后再使用图生图"
        return ""

    def resolve_volcengine_model_for_task(
        self,
        model: str,
        task_type: str,
    ) -> str:
        """根据任务类型自动解析火山引擎最终使用的模型名。

        火山引擎文生图模型（-t2i）和图生图模型（-i2i）是分离的，
        当用户选定的模型与任务类型不匹配时，自动切换到对应的模型。
        返回最终使用的模型名；无法切换时抛出 ValueError。
        """

        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("火山引擎模型名为空，无法解析")

        t2i_models = self.get_volcengine_t2i_models()
        i2i_models = self.get_volcengine_i2i_models()

        if task_type == "edit_image":
            if normalized_model in i2i_models:
                return normalized_model
            if not i2i_models:
                raise ValueError("火山引擎未配置图生图模型（i2i_models 为空），无法提交图生图任务")
            # 尝试把 -t2i 后缀替换为 -i2i 查找对应模型
            if normalized_model.lower().endswith("-t2i"):
                candidate = normalized_model[:-4] + "-i2i"
                if candidate in i2i_models:
                    return candidate
            # 回退到第一个可用 i2i 模型
            return i2i_models[0]

        # task_type == "draw"（文生图）
        if normalized_model in t2i_models:
            return normalized_model
        if not t2i_models:
            raise ValueError("火山引擎未配置文生图模型（t2i_models 为空），无法提交文生图任务")
        # 尝试把 -i2i 后缀替换为 -t2i 查找对应模型
        if normalized_model.lower().endswith("-i2i"):
            candidate = normalized_model[:-4] + "-t2i"
            if candidate in t2i_models:
                return candidate
        # 回退到第一个可用 t2i 模型
        return t2i_models[0]

    def require_platform_for_model(
        self,
        model: str,
        openai_compatibility_mode: str = "",
    ) -> tuple[ImageProvider, ProviderName]:
        """根据模型解析并创建对应的平台实例，带实例缓存避免重复构造。"""

        provider_type = self.get_model_provider(model)
        normalized_model = model.strip()
        # 非 OpenAI 平台的 provider 不依赖 compatibility_mode，缓存键用空串占位
        cache_key = (provider_type, normalized_model, openai_compatibility_mode.strip() if provider_type == "openai" else "")
        cached_provider = self._provider_cache.get(cache_key)
        if cached_provider is not None:
            return cached_provider, provider_type

        if provider_type == "aliyun":
            provider = self.create_aliyun_provider()
        elif provider_type == "google":
            provider = self.create_google_provider()
        elif provider_type == "zhipu":
            provider = self.create_zhipu_provider()
        elif provider_type == "volcengine":
            provider = self.create_volcengine_provider()
        elif provider_type == "siliconflow":
            provider = self.create_siliconflow_provider()
        elif provider_type == "novelai":
            provider = self.create_novelai_provider()
        elif provider_type == "openai":
            provider = self.create_openai_provider(
                self.resolve_openai_compatibility_mode(openai_compatibility_mode, model),
                model,
            )
        else:
            raise RuntimeError(f"模型未归属于任何已配置提供商：{model}")
        self._provider_cache[cache_key] = provider
        return provider, provider_type
