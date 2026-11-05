from pathlib import Path
from typing import Any, Dict, Optional

from ...domain.models.openai_profiles import OPENAI_COMPATIBILITY_MODES, normalize_openai_mode
from ...domain.models.aliyun_profiles import resolve_aliyun_model_profile
from ...domain.parameters import negative_prompt_option_parts, parse_key_value_options, v4_negative_prompt_option
from ...domain.configuration.models import DrawpicConfig, OpenAICompatibilityMode
from ...domain.configuration.platforms.common import NegativePromptConfig
from ...domain.styles import deduplicate_negative_prompt
from .types import ImageProvider, OpenAIModelRoute
from .construction import ProviderConstructionMixin
from .catalog import ModelCatalogMixin
from .capabilities import TaskCapabilityMixin


class ProviderRouter(ProviderConstructionMixin, ModelCatalogMixin, TaskCapabilityMixin):
    """协调平台路由与绘图任务所需的独立职责。"""

    def __init__(self, config: DrawpicConfig, logger: Any | None = None, *, data_dir: Path | None = None) -> None:
        self.config = config
        self.logger = logger
        self.data_dir = data_dir
        # Provider 实例缓存：键为 (provider_type, model, openai_compatibility_mode)，
        # 值为已构造的 ImageProvider 实例。ProviderRouter 每次随 _refresh_services 重建，
        # 因此缓存生命周期与配置版本一致，无需手动失效。
        self._provider_cache: dict[tuple[str, str, str], ImageProvider] = {}
        # OpenAI 路由列表缓存，避免每次 get_openai_models / get_model_provider 都重算
        self._openai_routes_cache: list[OpenAIModelRoute] | None = None

    def resolve_default_model(self) -> str:
        """解析当前有效的默认首选模型。"""

        configured_default = self.config.general.default_model.strip()
        if self.get_model_provider(configured_default):
            return configured_default

        all_models = self.get_all_models()
        if all_models:
            return all_models[0]
        raise ValueError("当前未配置任何可用图片模型")

    def resolve_fallback_model(self, primary_model: str = "") -> str:
        """解析当前有效的生图备选模型，未配置或不可用时返回空字符串。"""

        models = self.resolve_fallback_models(primary_model)
        return models[0] if models else ""

    def configured_fallback_models(self) -> list[str]:
        """保留配置顺序，并兼容旧单模型配置。"""
        models = self.config.general.fallback_models
        if not models and self.config.general.fallback_model.strip():
            models = [self.config.general.fallback_model]
        return list(dict.fromkeys(model.strip() for model in models if model.strip()))

    def resolve_fallback_models(self, primary_model: str = "") -> list[str]:
        return [
            model
            for model in self.configured_fallback_models()
            if model != primary_model.strip() and self.get_model_provider(model)
        ]

    def get_fallback_model_unavailable_reason(self, primary_model: str = "") -> str:
        """返回备选模型不可用原因，空字符串表示已可用或未配置。"""

        reasons = []
        for model in self.configured_fallback_models():
            if model == primary_model.strip():
                reasons.append("生图备选模型与首选模型相同，已忽略备选模型")
            elif not self.get_model_provider(model):
                reasons.append(f"生图备选模型未归属于任何已配置图片平台：{model}")
        return "；".join(reasons)

    def resolve_openai_compatibility_mode(self, mode: str = "", model: str = "") -> OpenAICompatibilityMode:
        """解析最终使用的 OpenAI 兼容模式。"""

        normalized_mode = normalize_openai_mode(mode)
        if normalized_mode in OPENAI_COMPATIBILITY_MODES:
            return normalized_mode  # type: ignore[return-value]

        if model:
            route = self.resolve_openai_model_route(model)
            if route is not None:
                return self._normalize_openai_compatibility_mode(route.compatibility_mode)
        return self._normalize_openai_compatibility_mode(self.config.openai.default_openai_compatibility_mode)

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
        if normalized_provider == "comfyui":
            return self.config.comfyui.rewrite_prompt_to_english
        return False

    def get_negative_prompt_config(self, model: str) -> NegativePromptConfig:
        """读取当前模型实际归属实例的反向词设置，兼容旧 OpenAI 实例。"""

        provider_name = self.get_model_provider(model)
        if provider_name == "openai":
            route = self.resolve_openai_model_route(model)
            if route is not None:
                return route.negative_prompt_config
        if not provider_name:
            raise ValueError(f"模型未归属于任何已配置提供商：{model}")
        return self.config.__dict__[provider_name]

    def resolve_negative_prompt(self, model: str, request_negative_prompt: str, task_type: str) -> str:
        """过滤调用方反向词并追加当前实例的默认词，先于风格渲染及英文改写。"""

        config = self.get_negative_prompt_config(model)
        if not config.negative_prompt_enabled:
            return ""
        legacy_default = ""
        if self.get_model_provider(model) == "comfyui":
            comfyui = self.config.comfyui
            prompt_mode, task_default = (
                (comfyui.i2i_prompt_mode, comfyui.i2i_negative_prompt)
                if task_type == "edit_image"
                else (comfyui.t2i_prompt_mode, comfyui.t2i_negative_prompt)
            )
            if prompt_mode == "positive_negative":
                legacy_default = task_default
        extra_parts = negative_prompt_option_parts(
            self._negative_prompt_extra_parameters(model),
            allow_character_captions=self.get_model_provider(model) == "novelai",
        )
        return deduplicate_negative_prompt(request_negative_prompt, config.negative_prompt, legacy_default, *extra_parts)

    def resolve_v4_negative_prompt(self, model: str) -> Optional[Dict[str, Any]]:
        """角色反向词只从当前 NAI 实例读取，关闭时连同旧扩展参数一起忽略。"""

        if not self.get_negative_prompt_config(model).negative_prompt_enabled:
            return None
        return v4_negative_prompt_option(self._negative_prompt_extra_parameters(model))

    def _negative_prompt_extra_parameters(self, model: str) -> Dict[str, Any]:
        """只读取当前实例、当前模型协议实际使用的扩展参数。"""

        provider_name = self.get_model_provider(model)
        if provider_name == "comfyui":
            return {}
        if provider_name == "openai":
            route = self.resolve_openai_model_route(model)
            if route is not None:
                return route.extra_parameters
        field = "extra_parameters"
        if provider_name == "aliyun":
            family = resolve_aliyun_model_profile(model).family
            if family != "legacy":
                field = f"{family}_extra_parameters"
        return parse_key_value_options(self.get_negative_prompt_config(model).__dict__[field])

    def resolve_model_name(self, model: str = "", allow_unknown_model: bool = False) -> str:
        """解析最终使用的模型名。"""

        normalized_model = model.strip()
        if normalized_model and self.get_model_provider(normalized_model):
            return normalized_model
        if normalized_model and allow_unknown_model:
            return normalized_model
        return self.resolve_default_model()

    @staticmethod
    def merge_prompt_parts(*parts: str) -> str:
        """按顺序合并非空提示词片段。"""

        return ", ".join(part.strip(" \t\r\n,") for part in parts if part.strip(" \t\r\n,"))

    def resolve_novelai_mode(self, mode: str = "") -> str:
        """解析会话级 NovelAI mode；空值跟随插件配置。"""

        normalized_mode = mode.strip().lower() or self.config.novelai.default_mode
        if normalized_mode not in {"anime", "furry", "background"}:
            raise ValueError(f"不支持的 NovelAI 模式：{normalized_mode}")
        return normalized_mode

    def resolve_novelai_artist_tags(self, artist_tags: str = "") -> str:
        """解析会话级 NovelAI 画师标签；空值跟随插件默认配置。"""

        return artist_tags.strip() or self.config.novelai.default_artist_tags.strip()

    def resolve_novelai_model_for_mode(self, model: str, mode: str = "") -> str:
        """按 NAI mode 解析 V3 Anime/Furry 的实际模型。"""

        normalized_model = model.strip()
        if self.get_model_provider(normalized_model) != "novelai":
            return normalized_model
        resolved_mode = self.resolve_novelai_mode(mode)
        if normalized_model == "nai-diffusion-3" and resolved_mode == "furry":
            return "nai-diffusion-furry-3"
        if normalized_model == "nai-diffusion-furry-3" and resolved_mode != "furry":
            return "nai-diffusion-3"
        return normalized_model

    def get_default_novelai_model(self) -> str:
        """返回 NAI 指令使用的默认模型。"""

        models = self.get_novelai_models()
        if not models:
            raise ValueError("NovelAI 平台未启用或没有配置可用模型")
        return models[0]

    def resolve_novelai_mode_for_model(self, model: str, mode: str = "") -> str:
        return self.resolve_novelai_mode(mode)

    def resolve_novelai_artist_tags_for_model(self, model: str, tags: str = "") -> str:
        return self.resolve_novelai_artist_tags(tags)

    def describe_model(self, model: str) -> dict[str, str]:
        provider = self.get_model_provider(model)
        route = self.resolve_openai_model_route(model) if provider == "openai" else None
        return {
            "name": model,
            "provider": provider,
            "upstream_model": route.upstream_model if route is not None else model,
            "platform_name": provider,
        }
