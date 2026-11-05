from typing import List, Literal
import re

from ...domain.models.openai_profiles import OPENAI_COMPATIBILITY_MODES, normalize_openai_mode
from ...domain.configuration.models import OpenAICompatibilityMode
from ...domain.parameters import parse_key_value_options, parse_model_value_overrides
from .types import OpenAIModelRoute, ProviderName


class ModelCatalogMixin:
    """ModelCatalogMixin 的独立绘图职责。"""

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

        normalized_mode = normalize_openai_mode(mode)
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
                        negative_prompt_config=self.config.openai,
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
                        negative_prompt_config=instance,
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

    def get_volcengine_models(self) -> list[str]:
        """获取火山引擎单一模型列表。"""

        if not self.config.volcengine.enabled:
            return []
        return list(dict.fromkeys(model.strip() for model in self.config.volcengine.models if model.strip()))

    def get_siliconflow_models(self) -> list[str]:
        """获取硅基流动模型列表。"""

        if not self.config.siliconflow.enabled:
            return []
        return [model.strip() for model in self.config.siliconflow.models if model.strip()]

    def get_novelai_models(self) -> list[str]:
        """获取 NovelAI / NovelAPI 模型列表。"""

        if not self.config.novelai.enabled:
            return []
        configured_models = self.config.novelai.models + self.config.novelai.custom_models
        return list(dict.fromkeys(model.strip() for model in configured_models if model.strip()))

    def get_comfyui_models(self) -> list[str]:
        """获取 ComfyUI 统一模型列表。"""

        if not self.config.comfyui.enabled:
            return []
        return ["comfyui"]

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
            + self.get_comfyui_models()
            + self.get_agnes_models()
        )

    def get_agnes_models(self) -> List[str]:
        """获取已启用 Agnes 实例的图片模型。"""
        return [model.strip() for model in self.config.agnes.models if model.strip()] if self.config.agnes.enabled else []

    def get_model_provider(self, model: str) -> ProviderName | Literal[""]:
        """根据模型名称判断其所属提供商。"""

        normalized_model = model.strip()
        if normalized_model in self.get_agnes_models():
            return "agnes"
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
        if normalized_model in self.get_comfyui_models():
            return "comfyui"
        return ""
