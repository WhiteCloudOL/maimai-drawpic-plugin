"""组合运行时配置，保留旧模块导入契约和配置迁移。"""

from collections.abc import Mapping
from maibot_sdk import Field, PluginConfigBase
from typing import Any

from ..models.openai_profiles import OpenAICompatibilityMode as OpenAICompatibilityMode
from .localization import apply_config_i18n
from .common import (
    GeneralConfig as GeneralConfig,
    PluginSectionConfig as PluginSectionConfig,
    ProxyConfig as ProxyConfig,
)
from .styles import StyleConfig as StyleConfig, StylePresetConfig as StylePresetConfig
from .platforms.openai import (
    OpenAICompatibleInstanceConfig as OpenAICompatibleInstanceConfig,
    OpenAIModelConfig as OpenAIModelConfig,
)
from .platforms.google import GoogleModelConfig as GoogleModelConfig
from .platforms.zhipu import ZhipuModelConfig as ZhipuModelConfig
from .platforms.minimax import MiniMaxModelConfig as MiniMaxModelConfig
from .platforms.aliyun import AliyunModelConfig as AliyunModelConfig
from .platforms.volcengine import VolcengineModelConfig as VolcengineModelConfig
from .platforms.siliconflow import SiliconFlowModelConfig as SiliconFlowModelConfig
from .platforms.novelai import NovelAIModelConfig as NovelAIModelConfig
from .platforms.comfyui import ComfyUIModelConfig as ComfyUIModelConfig
from .platforms.agnes import AgnesModelConfig as AgnesModelConfig
from .moderation import ImageModerationConfig as ImageModerationConfig, PromptModerationConfig as PromptModerationConfig
from .types import (
    AliyunImageInputMode as AliyunImageInputMode,
    AliyunKlingResultType as AliyunKlingResultType,
    AliyunPromptExtendMode as AliyunPromptExtendMode,
    ComfyUIPromptMode as ComfyUIPromptMode,
    CommandReplyMode as CommandReplyMode,
    NovelAIMode as NovelAIMode,
    NovelAIModelId as NovelAIModelId,
    ProxyScheme as ProxyScheme,
    QuotaPeriodMode as QuotaPeriodMode,
    VolcengineResponseFormat as VolcengineResponseFormat,
    VolcengineSequentialMode as VolcengineSequentialMode,
)


class DrawpicConfig(PluginConfigBase):
    """插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    style: StyleConfig = Field(default_factory=StyleConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    prompt_review: PromptModerationConfig = Field(default_factory=PromptModerationConfig)
    image_review: ImageModerationConfig = Field(default_factory=ImageModerationConfig)
    openai: OpenAIModelConfig = Field(default_factory=OpenAIModelConfig)
    google: GoogleModelConfig = Field(default_factory=GoogleModelConfig)
    zhipu: ZhipuModelConfig = Field(default_factory=ZhipuModelConfig)
    minimax: MiniMaxModelConfig = Field(default_factory=MiniMaxModelConfig)
    aliyun: AliyunModelConfig = Field(default_factory=AliyunModelConfig)
    volcengine: VolcengineModelConfig = Field(default_factory=VolcengineModelConfig)
    siliconflow: SiliconFlowModelConfig = Field(default_factory=SiliconFlowModelConfig)
    novelai: NovelAIModelConfig = Field(default_factory=NovelAIModelConfig)
    comfyui: ComfyUIModelConfig = Field(default_factory=ComfyUIModelConfig)
    agnes: AgnesModelConfig = Field(default_factory=AgnesModelConfig)


apply_config_i18n(
    (
        PluginSectionConfig,
        GeneralConfig,
        StylePresetConfig,
        StyleConfig,
        ProxyConfig,
        OpenAICompatibleInstanceConfig,
        OpenAIModelConfig,
        GoogleModelConfig,
        ZhipuModelConfig,
        MiniMaxModelConfig,
        AliyunModelConfig,
        VolcengineModelConfig,
        SiliconFlowModelConfig,
        NovelAIModelConfig,
        ComfyUIModelConfig,
        AgnesModelConfig,
        PromptModerationConfig,
        ImageModerationConfig,
    )
)


def migrate_legacy_review_config(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """将旧版独立审核配置节迁移到通用配置。"""

    migrated_config = {
        str(section_name): dict(section_value) if isinstance(section_value, Mapping) else section_value
        for section_name, section_value in config_data.items()
    }
    general_config = migrated_config.setdefault("general", {})
    if not isinstance(general_config, dict):
        return migrated_config

    prompt_review_config = migrated_config.pop("prompt_review", None)
    if isinstance(prompt_review_config, Mapping):
        if "prompt_review_enabled" not in general_config and "enabled" in prompt_review_config:
            general_config["prompt_review_enabled"] = prompt_review_config["enabled"]
        if "prompt_review_prompt" not in general_config and "review_prompt" in prompt_review_config:
            general_config["prompt_review_prompt"] = prompt_review_config["review_prompt"]

    image_review_config = migrated_config.pop("image_review", None)
    if isinstance(image_review_config, Mapping):
        if "image_review_enabled" not in general_config and "enabled" in image_review_config:
            general_config["image_review_enabled"] = image_review_config["enabled"]
        if "image_review_prompt" not in general_config and "review_prompt" in image_review_config:
            general_config["image_review_prompt"] = image_review_config["review_prompt"]

    _migrate_legacy_volcengine_models(migrated_config)

    _migrate_legacy_quota_fields(migrated_config)

    return migrated_config


def _migrate_legacy_volcengine_models(migrated_config: dict[str, Any]) -> None:
    """将旧版火山引擎分组模型列表合并到 models。"""

    volcengine_config = migrated_config.get("volcengine")
    if not isinstance(volcengine_config, dict):
        return

    merged_models: list[str] = []
    for field_name in ("models", "unified_models", "t2i_models", "i2i_models"):
        configured_models = volcengine_config.get(field_name)
        if not isinstance(configured_models, list):
            continue
        for model in configured_models:
            normalized_model = str(model or "").strip()
            if normalized_model and normalized_model not in merged_models:
                merged_models.append(normalized_model)

    if merged_models:
        volcengine_config["models"] = merged_models
    volcengine_config.pop("unified_models", None)
    volcengine_config.pop("t2i_models", None)
    volcengine_config.pop("i2i_models", None)


def _migrate_legacy_quota_fields(migrated_config: dict[str, Any]) -> None:
    """将旧版统一的额度字段迁移到群聊/私聊分离字段。

    仅在新字段缺失且旧字段存在时触发，旧字段值同时写入群聊和私聊，保持旧行为。
    """

    general_config = migrated_config.get("general")
    if not isinstance(general_config, dict):
        return

    legacy_enabled = general_config.get("quota_enabled")
    if legacy_enabled is not None:
        if "group_quota_enabled" not in general_config:
            general_config["group_quota_enabled"] = legacy_enabled
        if "private_quota_enabled" not in general_config:
            general_config["private_quota_enabled"] = legacy_enabled
        general_config.pop("quota_enabled", None)

    legacy_period = general_config.get("quota_period")
    if legacy_period is not None:
        if "group_quota_period" not in general_config:
            general_config["group_quota_period"] = legacy_period
        if "private_quota_period" not in general_config:
            general_config["private_quota_period"] = legacy_period
        general_config.pop("quota_period", None)

    legacy_default_quota = general_config.get("default_quota")
    if legacy_default_quota is not None:
        if "group_default_quota" not in general_config:
            general_config["group_default_quota"] = legacy_default_quota
        if "private_default_quota" not in general_config:
            general_config["private_default_quota"] = legacy_default_quota
        general_config.pop("default_quota", None)
