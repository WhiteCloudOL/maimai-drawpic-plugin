from typing import Literal
import re

from ...domain.models.aliyun_profiles import (
    resolve_aliyun_image_input_mode,
    resolve_aliyun_model_profile,
    supports_aliyun_negative_prompt,
)
from ...domain.models.rinkoai_profiles import RINKOAI_EDIT_UNSUPPORTED_REASON, is_rinkoai_nai_model
from ...domain.models.minimax_profiles import MINIMAX_MODELS, build_minimax_payload, max_reference_images
from ...infrastructure.providers.gemini import GoogleImage
from ...infrastructure.providers.siliconflow import SiliconFlowImage
from ...infrastructure.providers.volcengine import VolcengineImage
from .types import ModelTaskCapability


class TaskCapabilityMixin:
    """TaskCapabilityMixin 的独立绘图职责。"""

    def get_volcengine_t2i_models(self) -> list[str]:
        """按模型后缀和全局黑名单获取可用于文生图的火山模型。"""

        unsupported_models = {
            model.strip() for model in self.config.general.text_to_image_unsupported_models if model.strip()
        }
        return [
            model
            for model in self.get_volcengine_models()
            if not self._has_volcengine_task_marker(model, "i2i") and model not in unsupported_models
        ]

    def get_volcengine_i2i_models(self) -> list[str]:
        """按模型后缀和全局黑名单获取可用于图生图的火山模型。"""

        unsupported_models = {
            model.strip() for model in self.config.general.image_edit_unsupported_models if model.strip()
        }
        return [
            model
            for model in self.get_volcengine_models()
            if not self._has_volcengine_task_marker(model, "t2i") and model not in unsupported_models
        ]

    @staticmethod
    def _has_volcengine_task_marker(model: str, marker: Literal["t2i", "i2i"]) -> bool:
        """识别模型名中由连接符分隔的 t2i / i2i 能力标记。"""

        return re.search(rf"(?:^|[-_.]){marker}(?:$|[-_.])", model.strip().lower()) is not None

    def supports_separate_negative_prompt(self, model: str, task_type: str) -> bool:
        """判断模型当前任务是否支持独立传递反向提示词。"""

        provider_name = self.get_model_provider(model)
        if provider_name == "aliyun":
            return supports_aliyun_negative_prompt(model)
        if provider_name in {"siliconflow", "novelai"}:
            return True
        if provider_name == "google":
            return GoogleImage.supports_negative_prompt(model)
        if provider_name == "comfyui":
            config = self.config.comfyui
            if task_type == "edit_image":
                return config.i2i_prompt_mode == "positive_negative"
            return config.t2i_prompt_mode == "positive_negative"
        return False

    def validate_forced_command_task(self, model: str, task_type: str) -> None:
        """在聊天强制绘图命令提交前验证提供商配置。"""

        if self.get_model_provider(model) == "comfyui":
            self.create_comfyui_provider().validate_task_configuration(task_type)
        elif self.get_model_provider(model) == "minimax":
            provider = self.create_minimax_provider()
            build_minimax_payload(provider.values, "配置校验", model, edit=task_type == "edit_image")

    def supports_image_edit(self, model: str) -> bool:
        """判断模型是否支持图生图编辑。"""

        return not self.get_image_edit_unsupported_reason(model)

    def get_image_edit_unsupported_reason(self, model: str) -> str:
        """返回模型不支持图生图的原因，空字符串表示支持。"""

        return self.get_task_unsupported_reason(model, "edit_image")

    def get_task_unsupported_reason(self, model: str, task_type: str) -> str:
        """返回模型不支持指定任务的原因，空字符串表示支持。"""

        capability = self.evaluate_model_task_capability(model, task_type)
        return "" if capability.allowed else capability.reason

    def evaluate_model_task_capability(
        self,
        model: str,
        task_type: str,
    ) -> ModelTaskCapability:
        """人工名单优先，并结合平台与模型注册表判断任务能力。"""

        normalized_model = model.strip()
        if self.get_model_provider(normalized_model) == "minimax" and normalized_model not in MINIMAX_MODELS:
            return ModelTaskCapability(False, "当前未接入此 MiniMax 图片模型，请选择官方已支持的 H3/image-01 模型", "minimax_registry")
        if not normalized_model:
            return ModelTaskCapability(
                allowed=False,
                reason="当前未解析到可用绘图模型，无法提交绘图任务",
                source="invalid_model",
            )
        if task_type not in {"draw", "edit_image"}:
            return ModelTaskCapability(
                allowed=False,
                reason=f"不支持的绘图任务类型：{task_type}",
                source="invalid_task_type",
            )

        text_to_image_only_models = {
            configured_model.strip()
            for configured_model in self.config.general.image_edit_unsupported_models
            if configured_model.strip()
        }
        image_to_image_only_models = {
            configured_model.strip()
            for configured_model in self.config.general.text_to_image_unsupported_models
            if configured_model.strip()
        }
        if normalized_model in text_to_image_only_models and normalized_model in image_to_image_only_models:
            return ModelTaskCapability(
                allowed=False,
                reason=(f"当前模型 {normalized_model} 同时出现在仅支持文生图与仅支持图生图名单中，请修正配置"),
                source="manual_conflict",
            )
        if task_type == "edit_image" and normalized_model in text_to_image_only_models:
            return ModelTaskCapability(
                allowed=False,
                reason=f"当前模型 {normalized_model} 已在配置中标记为仅支持文生图，不支持图生图",
                source="manual_t2i_only",
            )
        if task_type == "draw" and normalized_model in image_to_image_only_models:
            return ModelTaskCapability(
                allowed=False,
                reason=f"当前模型 {normalized_model} 已在配置中标记为仅支持图生图，不支持文生图",
                source="manual_i2i_only",
            )

        provider_name = self.get_model_provider(normalized_model)
        if not provider_name:
            return ModelTaskCapability(
                allowed=False,
                reason=f"当前模型 {normalized_model} 未归属于任何已配置图片平台，无法判断任务能力",
                source="unknown_provider",
            )
        if provider_name == "openai" and task_type == "edit_image":
            route = self.resolve_openai_model_route(normalized_model)
            if route is not None and is_rinkoai_nai_model(route.base_url, route.upstream_model):
                return ModelTaskCapability(
                    allowed=False,
                    reason=RINKOAI_EDIT_UNSUPPORTED_REASON,
                    source="rinkoai_nai_protocol",
                )
        if provider_name == "aliyun":
            profile = resolve_aliyun_model_profile(normalized_model)
            supported = profile.supports_draw if task_type == "draw" else profile.supports_edit
            if not supported:
                task_name = "文生图" if task_type == "draw" else "图生图"
                return ModelTaskCapability(
                    allowed=False,
                    reason=f"当前阿里云模型 {normalized_model} 不支持{task_name}",
                    source="aliyun_registry",
                )
        if provider_name == "zhipu" and task_type == "edit_image":
            return ModelTaskCapability(
                allowed=False,
                reason=f"当前模型 {normalized_model} 属于智谱平台；该平台当前仅支持文生图，不支持图生图编辑",
                source="provider_builtin",
            )
        if provider_name == "google" and normalized_model.lower().startswith("imagen-"):
            return ModelTaskCapability(
                allowed=False,
                reason="Google Gemini API 已下线 Imagen，请选择 Gemini 图片模型",
                source="provider_builtin",
            )
        if (
            provider_name == "siliconflow"
            and task_type == "draw"
            and normalized_model.lower().startswith("qwen/qwen-image-edit")
        ):
            return ModelTaskCapability(
                allowed=False,
                reason=f"当前硅基流动模型 {normalized_model} 需要参考图片，请使用图生图",
                source="provider_builtin",
            )
        if provider_name == "volcengine":
            allowed_models = (
                self.get_volcengine_t2i_models() if task_type == "draw" else self.get_volcengine_i2i_models()
            )
            if normalized_model not in allowed_models:
                task_name = "文生图" if task_type == "draw" else "图生图"
                current_kind = "图生图模型" if task_type == "draw" else "文生图模型"
                return ModelTaskCapability(
                    allowed=False,
                    reason=(
                        f"当前火山引擎模型 {normalized_model} 的名称标记为{current_kind}，"
                        f"不支持{task_name}；请切换到对应任务模型"
                    ),
                    source="volcengine_model_suffix",
                )
        if (
            provider_name == "comfyui"
            and task_type == "edit_image"
            and not self.config.comfyui.i2i_workflow_path.strip()
        ):
            return ModelTaskCapability(
                allowed=False,
                reason="ComfyUI 未配置图生图工作流（i2i_workflow_path 为空），无法提交图生图任务",
                source="comfyui_workflow",
            )
        return ModelTaskCapability(
            allowed=True,
            reason="",
            source=("aliyun_registry" if provider_name == "aliyun" else "provider_default"),
        )

    def validate_source_image_count(self, model: str, image_count: int) -> None:
        """在审核和额度预留前拒绝超出模型能力的输入，禁止静默丢图。"""

        if image_count == 0:
            return
        maximum = self.get_max_source_images(model)
        if maximum is not None and image_count > maximum:
            raise ValueError(f"当前模型 {model} 最多支持 {maximum} 张参考图片，当前提供了 {image_count} 张")

    def get_max_source_images(self, model: str) -> int | None:
        """返回模型已知的参考图上限；None 表示注册表未声明。"""
        provider = self.get_model_provider(model)
        maximum = None
        if provider == "minimax":
            maximum = max_reference_images(model)
        if provider in {"novelai", "comfyui"}:
            maximum = 1
        elif provider == "siliconflow":
            maximum = SiliconFlowImage.max_reference_images(model)
        elif provider == "google":
            maximum = GoogleImage.max_reference_images(model)
        elif provider == "aliyun":
            maximum = resolve_aliyun_model_profile(model).max_input_images
        elif provider == "volcengine":
            maximum = VolcengineImage._max_reference_images(VolcengineImage._resolve_model_family(model))
        return maximum

    def resolve_volcengine_model_for_task(
        self,
        model: str,
        task_type: str,
    ) -> str:
        """按单一模型列表、任务后缀和全局黑名单验证火山模型。"""

        normalized_model = model.strip()
        if not normalized_model:
            raise ValueError("火山引擎模型名为空，无法解析")
        capability = self.evaluate_model_task_capability(normalized_model, task_type)
        if not capability.allowed:
            raise ValueError(capability.reason)
        return normalized_model

    def validate_local_source_images(self, model: str) -> None:
        """网页与插件 Base64 输入不能满足要求公网原图 URL 的模型。"""
        if self.get_model_provider(model) == "aliyun":
            profile = resolve_aliyun_model_profile(model)
            if resolve_aliyun_image_input_mode(profile, self.config.aliyun.image_input_mode) == "url":
                raise ValueError("当前模型需要公网原图 URL，不能通过网页上传或 Base64 联动接口发起图生图")
