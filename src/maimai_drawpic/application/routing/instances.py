"""在所有平台类型的命名实例之间路由，不共享不同实例的密钥或参数。"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import asyncio
import inspect

from ...domain.configuration.models import DrawpicConfig
from ...domain.configuration.platforms.common import NegativePromptConfig
from .service import ProviderRouter
from .types import ModelTaskCapability


class InstanceImageProvider:
    """把完整平台模型标识还原为真实模型 ID，兼容异步及同步适配器。"""

    def __init__(self, provider: Any, model: str) -> None:
        self.provider, self.model = provider, model

    async def _call(self, method: Any, *args: Any) -> List[bytes]:
        if inspect.iscoroutinefunction(method):
            return await method(*args)
        return await asyncio.to_thread(method, *args)

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> List[bytes]:
        return await self._call(self.provider.generate_images, prompt, self.model, n)

    async def edit_images(self, prompt: str, model: str, images: List[bytes], n: int = 1) -> List[bytes]:
        return await self._call(self.provider.edit_images, prompt, self.model, images, n)

    async def edit_images_with_urls(
        self, prompt: str, model: str, images: List[bytes], urls: List[str], n: int = 1
    ) -> List[bytes]:
        return await self._call(self.provider.edit_images_with_urls, prompt, self.model, images, urls, n)


@dataclass(frozen=True)
class InstanceModelRoute:
    identifier: str
    name: str
    kind: str
    model: str
    selector: str
    router: ProviderRouter


class InstanceProviderRouter(ProviderRouter):
    """复用单实例路由规则，为每个实例保存独立的配置与适配器缓存。"""

    def __init__(
        self,
        config: DrawpicConfig,
        instances: List[Tuple[Dict[str, Any], DrawpicConfig]],
        logger: Any = None,
        *,
        data_dir: Optional[Path] = None,
    ) -> None:
        super().__init__(config, logger=logger, data_dir=data_dir)
        self.routes: Dict[str, InstanceModelRoute] = {}
        for record, instance_config in instances:
            child = ProviderRouter(instance_config, logger=logger, data_dir=data_dir)
            for model in child.get_all_models():
                selector = f"{record['name']}/{model}"
                if selector in self.routes:
                    raise ValueError("平台名称与模型组合重复")
                self.routes[selector] = InstanceModelRoute(
                    record["id"], record["name"], record["kind"], model, selector, child
                )

    def model_references(self) -> Dict[Tuple[str, str], str]:
        return {(route.identifier, route.model): route.selector for route in self.routes.values()}

    def _matches(self, model: str) -> List[InstanceModelRoute]:
        if model in self.routes:
            return [self.routes[model]]
        return [route for route in self.routes.values() if route.model == model.strip()]

    def _route(self, model: str) -> InstanceModelRoute:
        matches = self._matches(model)
        if len(matches) != 1:
            raise ValueError("模型不存在或匹配多个平台，请选择带平台名称的模型")
        return matches[0]

    def get_all_models(self) -> List[str]:
        return list(self.routes)

    def _models(self, kind: str) -> List[str]:
        return [key for key, value in self.routes.items() if value.kind == kind]

    def get_openai_models(self) -> List[str]:
        return self._models("openai")

    def get_google_models(self) -> List[str]:
        return self._models("google")

    def get_zhipu_models(self) -> List[str]:
        return self._models("zhipu")

    def get_minimax_models(self) -> List[str]:
        return self._models("minimax")

    def get_aliyun_models(self) -> List[str]:
        return self._models("aliyun")

    def get_volcengine_models(self) -> List[str]:
        return self._models("volcengine")

    def get_siliconflow_models(self) -> List[str]:
        return self._models("siliconflow")

    def get_novelai_models(self) -> List[str]:
        return self._models("novelai")

    def get_comfyui_models(self) -> List[str]:
        return self._models("comfyui")

    def get_model_provider(self, model: str) -> str:
        matches = self._matches(model)
        return matches[0].kind if len(matches) == 1 else ""

    def resolve_default_model(self) -> str:
        configured_default = self.config.general.default_model.strip()
        if configured_default:
            # 非空默认值与显式选择遵循相同的唯一匹配规则，不能由实例顺序决定账号。
            return self._route(configured_default).selector
        if self.routes:
            return next(iter(self.routes))
        raise ValueError("当前未配置任何可用图片模型")

    def resolve_model_name(self, model: str = "", allow_unknown_model: bool = False) -> str:
        if not model.strip():
            return self.resolve_default_model()
        return self._route(model.strip()).selector

    def resolve_fallback_models(self, primary_model: str = "") -> List[str]:
        result = []
        primary = self._matches(primary_model)
        primary_selector = primary[0].selector if len(primary) == 1 else primary_model
        for model in self.configured_fallback_models():
            matches = self._matches(model)
            if len(matches) == 1 and matches[0].selector != primary_selector and matches[0].selector not in result:
                result.append(matches[0].selector)
        return result

    def get_fallback_model_unavailable_reason(self, primary_model: str = "") -> str:
        return "；".join(
            f"备选模型不可用或需要选择平台名称：{model}"
            for model in self.configured_fallback_models()
            if len(self._matches(model)) != 1
        )

    def evaluate_model_task_capability(self, model: str, task_type: str) -> ModelTaskCapability:
        route = self._route(model)
        denied = (
            self.config.general.image_edit_unsupported_models
            if task_type == "edit_image"
            else self.config.general.text_to_image_unsupported_models
        )
        if route.selector in denied:
            return ModelTaskCapability(
                allowed=False, reason="该实例模型已在任务能力名单中禁用", source="manual_override"
            )
        return route.router.evaluate_model_task_capability(route.model, task_type)

    def validate_source_image_count(self, model: str, image_count: int) -> None:
        route = self._route(model)
        route.router.validate_source_image_count(route.model, image_count)

    def get_max_source_images(self, model: str) -> int | None:
        route = self._route(model)
        return route.router.get_max_source_images(route.model)

    def validate_forced_command_task(self, model: str, task_type: str) -> None:
        route = self._route(model)
        route.router.validate_forced_command_task(route.model, task_type)

    def validate_local_source_images(self, model: str) -> None:
        route = self._route(model)
        route.router.validate_local_source_images(route.model)

    def supports_separate_negative_prompt(self, model: str, task_type: str) -> bool:
        route = self._route(model)
        return route.router.supports_separate_negative_prompt(route.model, task_type)

    def get_negative_prompt_config(self, model: str) -> NegativePromptConfig:
        route = self._route(model)
        return route.router.get_negative_prompt_config(route.model)

    def resolve_negative_prompt(self, model: str, request_negative_prompt: str, task_type: str) -> str:
        route = self._route(model)
        return route.router.resolve_negative_prompt(route.model, request_negative_prompt, task_type)

    def resolve_v4_negative_prompt(self, model: str) -> Optional[Dict[str, Any]]:
        route = self._route(model)
        return route.router.resolve_v4_negative_prompt(route.model)

    def should_rewrite_prompt_to_english(self, provider_name: str, model: str = "") -> bool:
        route = self._route(model)
        return route.router.should_rewrite_prompt_to_english(provider_name, route.model)

    def resolve_openai_compatibility_mode(self, mode: str = "", model: str = "") -> str:
        if not model:
            return super().resolve_openai_compatibility_mode(mode)
        route = self._route(model)
        return route.router.resolve_openai_compatibility_mode(mode, route.model)

    def resolve_openai_model_route(self, model: str) -> Any:
        route = self._route(model)
        return route.router.resolve_openai_model_route(route.model)

    def _same_instance_model(self, route: InstanceModelRoute, model: str) -> str:
        matches = [
            item.selector
            for item in self.routes.values()
            if item.identifier == route.identifier and item.model == model
        ]
        if not matches:
            raise ValueError(f"当前平台实例未配置所需模型：{model}")
        return matches[0]

    def resolve_volcengine_model_for_task(self, model: str, task_type: str) -> str:
        route = self._route(model)
        return self._same_instance_model(route, route.router.resolve_volcengine_model_for_task(route.model, task_type))

    def resolve_novelai_model_for_mode(self, model: str, mode: str = "") -> str:
        route = self._route(model)
        if route.kind != "novelai":
            return route.selector
        return self._same_instance_model(route, route.router.resolve_novelai_model_for_mode(route.model, mode))

    def resolve_novelai_mode_for_model(self, model: str, mode: str = "") -> str:
        return self._route(model).router.resolve_novelai_mode(mode)

    def resolve_novelai_artist_tags_for_model(self, model: str, tags: str = "") -> str:
        return self._route(model).router.resolve_novelai_artist_tags(tags)

    def require_platform_for_model(
        self, model: str, openai_compatibility_mode: str = "", **kwargs: Any
    ) -> Tuple[InstanceImageProvider, str]:
        route = self._route(model)
        provider, kind = route.router.require_platform_for_model(route.model, openai_compatibility_mode, **kwargs)
        return InstanceImageProvider(provider, route.model), kind

    def describe_model(self, model: str) -> Dict[str, str]:
        route = self._route(model)
        return {
            **route.router.describe_model(route.model),
            "name": route.selector,
            "provider": route.kind,
            "platform_name": route.name,
        }
