from copy import deepcopy
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from ...domain.styles import deduplicate_negative_prompt
from ...paths import PLUGIN_DIR
from ...infrastructure.providers.aliyun import AliyunImage
from ...infrastructure.providers.agnes import AgnesImage
from ...infrastructure.providers.comfyui import ComfyUIImage
from ...infrastructure.providers.gemini import GoogleImage
from ...infrastructure.providers.novelai import NovelAIImage
from ...infrastructure.providers.openai import OpenaiImage
from ...infrastructure.providers.siliconflow import SiliconFlowImage
from ...infrastructure.providers.volcengine import VolcengineImage
from ...infrastructure.providers.zhipu import ZhipuImage
from ...infrastructure.providers.minimax import MiniMaxImage
from ...domain.configuration.models import OpenAICompatibilityMode
from ...infrastructure.http import HttpProxySettings
from ...domain.parameters import (
    negative_prompt_option_parts,
    parse_key_value_options,
    parse_model_value_overrides,
    v4_negative_prompt_option,
    without_negative_prompt_options,
)
from .types import ImageProvider, OpenAIModelRoute, ProviderName, RoutedOpenAIImage, _DOMESTIC_PROXY_BYPASS_PROVIDERS


class ProviderConstructionMixin:
    """ProviderConstructionMixin 的独立绘图职责。"""

    def _provider_negative_prompt(
        self,
        provider_name: ProviderName,
        request_negative_prompt: str,
        prepared_negative_prompt: Optional[str],
        legacy_default: str = "",
    ) -> str:
        # 已完成实例过滤、风格合并和改写的内容必须原样传递，不能再追加原始默认词。
        if prepared_negative_prompt is not None:
            return prepared_negative_prompt
        config = self.config.__dict__[provider_name]
        if not config.negative_prompt_enabled:
            return ""
        extra_parts = negative_prompt_option_parts(
            parse_key_value_options(config.__dict__.get("extra_parameters", [])),
            allow_character_captions=provider_name == "novelai",
        )
        return deduplicate_negative_prompt(request_negative_prompt, config.negative_prompt, legacy_default, *extra_parts)

    def create_agnes_provider(self) -> AgnesImage:
        """使用实例自己的密钥、尺寸及响应格式构造 Agnes 适配器。"""
        config = self.config.agnes
        return AgnesImage(
            api_key=config.api_key,
            base_url=config.base_url,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            default_size=config.default_size,
            ratio=config.ratio,
            response_format=config.response_format,
            model_size_overrides=parse_model_value_overrides(config.model_size_overrides),
            extra_parameters=without_negative_prompt_options(parse_key_value_options(config.extra_parameters)),
            proxy_settings=self._get_proxy_settings("agnes"),
            skip_image_url_ip_check=self.config.general.skip_image_url_ip_check,
        )

    def _get_proxy_settings(self, provider_name: ProviderName) -> HttpProxySettings:
        """按提供商解析是否应用插件全局代理。"""

        proxy_config = self.config.proxy
        if not proxy_config.enabled:
            return HttpProxySettings.disabled()
        domestic = provider_name in _DOMESTIC_PROXY_BYPASS_PROVIDERS
        if provider_name == "minimax":
            domestic = urlsplit(self.config.minimax.base_url).hostname in {"api.minimax.cn", "api.minimaxi.com"}
        if proxy_config.bypass_china_providers and domestic:
            return HttpProxySettings.disabled()
        return HttpProxySettings(
            enabled=True,
            use_system_proxy=proxy_config.use_system_proxy,
            scheme=proxy_config.scheme,
            host=proxy_config.host.strip(),
            port=proxy_config.port,
            username=proxy_config.username,
            password=proxy_config.password,
        )

    def create_aliyun_provider(
        self, request_negative_prompt: str = "", *, prepared_negative_prompt: Optional[str] = None
    ) -> AliyunImage:
        """创建阿里百炼图片提供商实例。"""

        return AliyunImage(
            api_key=self.config.aliyun.api_key,
            base_url=self.config.aliyun.base_url,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            default_size=self.config.aliyun.default_size,
            model_size_overrides=parse_model_value_overrides(self.config.aliyun.model_size_overrides),
            negative_prompt=self._provider_negative_prompt(
                "aliyun", request_negative_prompt, prepared_negative_prompt,
            ),
            prompt_extend=self.config.aliyun.prompt_extend,
            qwen_prompt_extend_mode=self.config.aliyun.qwen_prompt_extend_mode,
            qwen_enable_thinking=self.config.aliyun.qwen_enable_thinking,
            zimage_prompt_extend=self.config.aliyun.zimage_prompt_extend,
            seed=self.config.aliyun.seed,
            watermark=self.config.aliyun.watermark,
            max_images=self.config.aliyun.max_images,
            image_input_mode=self.config.aliyun.image_input_mode,
            async_poll_interval_seconds=(self.config.aliyun.async_poll_interval_seconds),
            kling_aspect_ratio=self.config.aliyun.kling_aspect_ratio,
            kling_resolution=self.config.aliyun.kling_resolution,
            kling_result_type=self.config.aliyun.kling_result_type,
            kling_series_amount=self.config.aliyun.kling_series_amount,
            qwen_extra_parameters=without_negative_prompt_options(
                parse_key_value_options(self.config.aliyun.qwen_extra_parameters)
            ),
            zimage_extra_parameters=without_negative_prompt_options(
                parse_key_value_options(self.config.aliyun.zimage_extra_parameters)
            ),
            kling_extra_parameters=without_negative_prompt_options(
                parse_key_value_options(self.config.aliyun.kling_extra_parameters)
            ),
            vidu_extra_parameters=without_negative_prompt_options(
                parse_key_value_options(self.config.aliyun.vidu_extra_parameters)
            ),
            extra_parameters=without_negative_prompt_options(
                parse_key_value_options(self.config.aliyun.extra_parameters)
            ),
            proxy_settings=self._get_proxy_settings("aliyun"),
            skip_image_url_ip_check=self.config.general.skip_image_url_ip_check,
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
                extra_parameters=without_negative_prompt_options(
                    parse_key_value_options(self.config.openai.extra_parameters)
                ),
                rewrite_prompt_to_english=self.config.openai.rewrite_prompt_to_english,
                negative_prompt_config=self.config.openai,
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
            extra_parameters=without_negative_prompt_options(route.extra_parameters),
            proxy_settings=self._get_proxy_settings("openai"),
            skip_image_url_ip_check=self.config.general.skip_image_url_ip_check,
        )
        return RoutedOpenAIImage(provider, route.upstream_model)

    def create_google_provider(
        self, request_negative_prompt: str = "", *, prepared_negative_prompt: Optional[str] = None
    ) -> GoogleImage:
        """创建 Google 图片提供商实例。"""

        return GoogleImage(
            api_key=self.config.google.api_key,
            base_url=self.config.google.base_url,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            aspect_ratio=self.config.google.aspect_ratio,
            image_size=self.config.google.image_size,
            negative_prompt=self._provider_negative_prompt(
                "google", request_negative_prompt, prepared_negative_prompt,
            ),
            seed=self.config.google.seed,
            extra_parameters=without_negative_prompt_options(
                parse_key_value_options(self.config.google.extra_parameters)
            ),
            proxy_settings=self._get_proxy_settings("google"),
        )

    def create_zhipu_provider(self) -> ZhipuImage:
        """创建智谱图片提供商实例。"""

        return ZhipuImage(
            api_key=self.config.zhipu.api_key,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            quality=self.config.zhipu.quality,
            size=self.config.zhipu.size,
            watermark_enabled=self.config.zhipu.watermark_enabled,
            user_id=self.config.zhipu.user_id,
            extra_parameters=without_negative_prompt_options(
                parse_key_value_options(self.config.zhipu.extra_parameters)
            ),
            proxy_settings=self._get_proxy_settings("zhipu"),
            skip_image_url_ip_check=self.config.general.skip_image_url_ip_check,
        )

    def create_minimax_provider(self) -> MiniMaxImage:
        values = self.config.minimax.model_dump(mode="json")
        values["model_size_overrides"] = parse_model_value_overrides(values["model_size_overrides"])
        values["extra_parameters"] = without_negative_prompt_options(parse_key_value_options(values["extra_parameters"]))
        return MiniMaxImage(
            api_key=self.config.minimax.api_key, values=values, logger=self.logger,
            proxy_settings=self._get_proxy_settings("minimax"),
            skip_image_url_ip_check=self.config.general.skip_image_url_ip_check,
        )

    def create_volcengine_provider(self) -> VolcengineImage:
        """创建火山引擎图片提供商实例。"""

        return VolcengineImage(
            api_key=self.config.volcengine.api_key,
            base_url=self.config.volcengine.base_url,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            default_size=self.config.volcengine.default_size,
            model_size_overrides=parse_model_value_overrides(self.config.volcengine.model_size_overrides),
            model_endpoint_overrides=parse_model_value_overrides(self.config.volcengine.model_endpoint_overrides),
            response_format=self.config.volcengine.response_format,
            output_format=self.config.volcengine.output_format,
            sequential_image_generation=self.config.volcengine.sequential_image_generation,
            optimize_prompt_mode=self.config.volcengine.optimize_prompt_mode,
            web_search_enabled=self.config.volcengine.web_search_enabled,
            background=self.config.volcengine.background,
            layer_decomposition=self.config.volcengine.layer_decomposition,
            guidance_scale=self.config.volcengine.guidance_scale,
            seed=self.config.volcengine.seed,
            watermark=self.config.volcengine.watermark,
            max_images=self.config.volcengine.max_images,
            extra_parameters=without_negative_prompt_options(
                parse_key_value_options(self.config.volcengine.extra_parameters)
            ),
            proxy_settings=self._get_proxy_settings("volcengine"),
            skip_image_url_ip_check=self.config.general.skip_image_url_ip_check,
        )

    def create_siliconflow_provider(
        self, request_negative_prompt: str = "", *, prepared_negative_prompt: Optional[str] = None
    ) -> SiliconFlowImage:
        """创建硅基流动图片提供商实例。"""

        return SiliconFlowImage(
            api_key=self.config.siliconflow.api_key,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            image_size=self.config.siliconflow.image_size,
            model_size_overrides=parse_model_value_overrides(self.config.siliconflow.model_size_overrides),
            seed=self.config.siliconflow.seed,
            num_inference_steps=self.config.siliconflow.num_inference_steps,
            guidance_scale=self.config.siliconflow.guidance_scale,
            cfg=self.config.siliconflow.cfg,
            negative_prompt=self._provider_negative_prompt(
                "siliconflow", request_negative_prompt, prepared_negative_prompt,
            ),
            extra_parameters=without_negative_prompt_options(
                parse_key_value_options(self.config.siliconflow.extra_parameters)
            ),
            proxy_settings=self._get_proxy_settings("siliconflow"),
            skip_image_url_ip_check=self.config.general.skip_image_url_ip_check,
        )

    def create_novelai_provider(
        self,
        request_negative_prompt: str = "",
        novelai_mode: str = "",
        novelai_artist_tags: str = "",
        *,
        prepared_negative_prompt: Optional[str] = None,
        prepared_v4_negative_prompt: Optional[Dict[str, Any]] = None,
    ) -> NovelAIImage:
        """创建 NovelAI / NovelAPI 图片提供商实例。"""

        config = self.config.novelai
        negative_prompt = self._provider_negative_prompt("novelai", request_negative_prompt, prepared_negative_prompt)
        raw_extra_parameters = parse_key_value_options(config.extra_parameters)
        extra_parameters = without_negative_prompt_options(raw_extra_parameters)
        if config.negative_prompt_enabled:
            v4_prompt = (
                deepcopy(prepared_v4_negative_prompt)
                if prepared_v4_negative_prompt is not None
                else v4_negative_prompt_option(raw_extra_parameters)
            )
            if v4_prompt is not None:
                # 只回写已处理文本，角色元数据不与全局默认词、风格模板混合。
                v4_prompt["caption"]["base_caption"] = negative_prompt
                v4_prompt["caption"].setdefault("char_captions", [])
                extra_parameters["v4_negative_prompt"] = v4_prompt
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
            artist_tags=self.resolve_novelai_artist_tags(novelai_artist_tags),
            positive_prompt=self.config.novelai.positive_prompt,
            negative_prompt=negative_prompt,
            mode=self.resolve_novelai_mode(novelai_mode),
            uc_preset=config.uc_preset if config.negative_prompt_enabled else None,
            quality_toggle=self.config.novelai.quality_toggle,
            sm=self.config.novelai.sm,
            sm_dyn=self.config.novelai.sm_dyn,
            noise_schedule=self.config.novelai.noise_schedule,
            v4_noise_schedule=self.config.novelai.v4_noise_schedule,
            img2img_strength=self.config.novelai.img2img_strength,
            img2img_noise=self.config.novelai.img2img_noise,
            max_images=self.config.novelai.max_images,
            extra_parameters=extra_parameters,
            proxy_settings=self._get_proxy_settings("novelai"),
            skip_image_url_ip_check=self.config.general.skip_image_url_ip_check,
        )

    def create_comfyui_provider(
        self, request_negative_prompt: str = "", *, prepared_negative_prompt: Optional[str] = None
    ) -> ComfyUIImage:
        """创建 ComfyUI 图片提供商实例。"""

        if self.data_dir is None:
            raise RuntimeError("创建 ComfyUI 提供商前必须注入插件标准数据目录")
        config = self.config.comfyui
        return ComfyUIImage(
            base_url=config.base_url,
            plugin_dir=PLUGIN_DIR,
            data_dir=self.data_dir,
            logger=self.logger,
            request_timeout_seconds=self.resolve_request_timeout_seconds(),
            poll_interval_seconds=config.poll_interval_seconds,
            t2i_workflow_path=config.t2i_workflow_path,
            i2i_workflow_path=config.i2i_workflow_path,
            t2i_prompt_mode=config.t2i_prompt_mode,
            i2i_prompt_mode=config.i2i_prompt_mode,
            t2i_prompt_node_id=config.t2i_prompt_node_id,
            i2i_prompt_node_id=config.i2i_prompt_node_id,
            t2i_positive_prompt_node_id=config.t2i_positive_prompt_node_id,
            t2i_negative_prompt_node_id=config.t2i_negative_prompt_node_id,
            i2i_positive_prompt_node_id=config.i2i_positive_prompt_node_id,
            i2i_negative_prompt_node_id=config.i2i_negative_prompt_node_id,
            t2i_negative_prompt=self._provider_negative_prompt(
                "comfyui", request_negative_prompt, prepared_negative_prompt, config.t2i_negative_prompt,
            ),
            i2i_negative_prompt=self._provider_negative_prompt(
                "comfyui", request_negative_prompt, prepared_negative_prompt, config.i2i_negative_prompt,
            ),
            i2i_image_node_id=config.i2i_image_node_id,
            prompt_input_name=config.prompt_input_name,
            image_input_name=config.image_input_name,
            seed=config.seed,
            seed_input_name=config.seed_input_name,
            t2i_seed_node_id=config.t2i_seed_node_id,
            i2i_seed_node_id=config.i2i_seed_node_id,
            proxy_settings=self._get_proxy_settings("comfyui"),
            skip_image_url_ip_check=self.config.general.skip_image_url_ip_check,
        )

    def require_platform_for_model(
        self,
        model: str,
        openai_compatibility_mode: str = "",
        *,
        request_negative_prompt: str = "",
        novelai_mode: str = "",
        novelai_artist_tags: str = "",
        prepared_negative_prompt: Optional[str] = None,
        prepared_v4_negative_prompt: Optional[Dict[str, Any]] = None,
    ) -> tuple[ImageProvider, ProviderName]:
        """根据模型解析并创建对应的平台实例，带实例缓存避免重复构造。"""

        provider_type = self.get_model_provider(model)
        normalized_model = model.strip()
        normalized_negative_prompt = request_negative_prompt.strip()
        normalized_novelai_mode = novelai_mode.strip().lower()
        normalized_novelai_artist_tags = novelai_artist_tags.strip()
        # 非 OpenAI 平台的 provider 不依赖 compatibility_mode，缓存键用空串占位
        cache_key = (
            provider_type,
            normalized_model,
            openai_compatibility_mode.strip() if provider_type == "openai" else "",
        )
        use_cache = (
            prepared_negative_prompt is None
            and prepared_v4_negative_prompt is None
            and not normalized_negative_prompt
            and not normalized_novelai_mode
            and not normalized_novelai_artist_tags
        )
        if use_cache:
            cached_provider = self._provider_cache.get(cache_key)
            if cached_provider is not None:
                return cached_provider, provider_type

        if provider_type == "aliyun":
            provider = self.create_aliyun_provider(
                normalized_negative_prompt, prepared_negative_prompt=prepared_negative_prompt,
            )
        elif provider_type == "google":
            provider = self.create_google_provider(
                normalized_negative_prompt, prepared_negative_prompt=prepared_negative_prompt,
            )
        elif provider_type == "zhipu":
            provider = self.create_zhipu_provider()
        elif provider_type == "minimax":
            provider = self.create_minimax_provider()
        elif provider_type == "volcengine":
            provider = self.create_volcengine_provider()
        elif provider_type == "siliconflow":
            provider = self.create_siliconflow_provider(
                normalized_negative_prompt, prepared_negative_prompt=prepared_negative_prompt,
            )
        elif provider_type == "novelai":
            provider = self.create_novelai_provider(
                normalized_negative_prompt,
                normalized_novelai_mode,
                normalized_novelai_artist_tags,
                prepared_negative_prompt=prepared_negative_prompt,
                prepared_v4_negative_prompt=prepared_v4_negative_prompt,
            )
        elif provider_type == "comfyui":
            provider = self.create_comfyui_provider(
                normalized_negative_prompt, prepared_negative_prompt=prepared_negative_prompt,
            )
        elif provider_type == "agnes":
            provider = self.create_agnes_provider()
        elif provider_type == "openai":
            provider = self.create_openai_provider(
                self.resolve_openai_compatibility_mode(openai_compatibility_mode, model),
                model,
            )
        else:
            raise RuntimeError(f"模型未归属于任何已配置提供商：{model}")
        if use_cache:
            self._provider_cache[cache_key] = provider
        return provider, provider_type
