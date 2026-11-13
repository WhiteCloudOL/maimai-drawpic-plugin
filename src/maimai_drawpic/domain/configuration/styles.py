"""configuration/styles.py 的强类型配置定义。"""

from maibot_sdk import Field, PluginConfigBase
from pydantic import model_validator
from typing import List, Literal


class ReferenceBindingConfig(PluginConfigBase):
    asset_id: str = Field(default="", description="已上传的预设图片 ID", json_schema_extra={"label": "图片 ID"})
    role: Literal["identity", "clothing", "scene", "lighting", "composition", "base"] = Field(default="scene", description="图片仅承担指定用途", json_schema_extra={"label": "图片用途"})
    subject_id: str = Field(default="", description="人物或物件标识，身份参考应标明对应主体", json_schema_extra={"label": "对应主体"})
    note: str = Field(default="", max_length=500, description="需要继承的具体特征", json_schema_extra={"label": "用途说明"})


class StylePresetConfig(PluginConfigBase):
    """单个全平台绘图风格的提示词模板。"""

    preset_type: Literal["text_to_image", "image_to_image"] = Field(default="text_to_image", description="文生图或图生图预设", json_schema_extra={"label": "预设类型"})
    tags: List[str] = Field(default=[], max_length=32, description="用于固定匹配的 tag", json_schema_extra={"label": "预设 tag"})
    apply_to_image_edit: bool = Field(default=False, description="允许文生图文字预设同时用于图生图", json_schema_extra={"label": "同时应用到图生图"})
    reference_bindings: List[ReferenceBindingConfig] = Field(default=[], max_length=8, description="图生图预设的真实图片和用途", json_schema_extra={"label": "预设参考图片"})
    multi_reference_confirmed: bool = Field(default=False, description="已在 dialog 中核实当前预设多图配置", json_schema_extra={"label": "已确认多图参考"})

    @model_validator(mode="after")
    def validate_mode(self) -> "StylePresetConfig":
        if self.preset_type == "text_to_image" and self.reference_bindings:
            raise ValueError("文生图预设不能绑定图片")
        if self.preset_type == "image_to_image" and self.apply_to_image_edit:
            raise ValueError("图生图预设不使用跨模式勾选")
        if len(self.reference_bindings) > 1 and not self.multi_reference_confirmed:
            raise ValueError("请先确认服务商及模型支持多图参考")
        return self

    enabled: bool = Field(
        default=True,
        description="是否启用该绘图风格",
        json_schema_extra={
            "label": "启用",
            "order": 0,
        },
    )
    name: str = Field(
        default="自定义风格",
        description="风格名称，用于工具参数和 /绘图 风格 指令",
        json_schema_extra={
            "label": "风格名称",
            "placeholder": "例如：水彩、赛博朋克",
            "order": 1,
        },
    )
    description: str = Field(
        default="",
        description="风格的语义描述，供用户查看并帮助模型匹配风格",
        json_schema_extra={
            "label": "风格描述（可选）",
            "hint": "简要说明视觉特点和适用场景；留空时只显示风格名称",
            "input_type": "textarea",
            "x-widget": "textarea",
            "rows": 2,
            "order": 2,
        },
    )
    positive_prompt_template: str = Field(
        default="{prompt}",
        description="正向提示词模板。{prompt} 会替换为用户正向提示词；没有占位符时会自动追加用户提示词",
        json_schema_extra={
            "label": "正向提示词模板",
            "hint": "{prompt} 会替换为你本次输入的绘图描述，建议保留它，在前后添加风格词。例如“水彩，{prompt}”遇到“一只猫”会变成“水彩，一只猫”。删除占位符时仍会自动追加本次描述；NovelAI 的 {{tag}} 权重花括号可保留。",
            "input_type": "textarea",
            "x-widget": "textarea",
            "rows": 4,
            "order": 3,
        },
    )
    negative_prompt_template: str = Field(
        default="{negative_prompt}",
        description="反向提示词模板。{negative_prompt} 会替换为用户反向提示词；没有占位符时会自动追加",
        json_schema_extra={
            "label": "反向提示词模板",
            "hint": "{negative_prompt} 会替换为本次反向词与实例默认词，并与模板按词条去重。实例关闭反向词时清空本次输入与实例默认值，保留模板自己的内容；例如“模糊，{negative_prompt}”仍保留“模糊”。无占位符时自动追加；不支持独立反向字段的平台会合并提示词。",
            "input_type": "textarea",
            "x-widget": "textarea",
            "rows": 4,
            "order": 4,
        },
    )


class StyleConfig(PluginConfigBase):
    """全平台通用的风格化提示词模板配置。"""

    __ui_label__ = "绘图风格配置"
    __ui_order__ = 2

    image_edit_presets_enabled: bool = Field(default=False, description="允许图生图任务使用预设，包括兼容的文生图预设", json_schema_extra={"label": "启用图生图预设"})
    default_image_edit_preset: str = Field(default="", description="图生图默认预设；留空时仅在默认文生图预设已勾选兼容时使用它", json_schema_extra={"label": "默认图生图预设"})

    default_style: str = Field(
        default="",
        description="未指定风格或使用“默认”风格名时自动套用的风格。留空表示保持普通绘图行为",
        json_schema_extra={
            "label": "默认风格",
            "hint": "未指定风格的 AI 绘图、普通绘图命令、工作台和插件 API 会自动套用。必须选择已启用风格；留空不自动套用，显式选择“无风格”可跳过本次预设。",
            "order": 0,
        },
    )
    presets: List[StylePresetConfig] = Field(
        default=[],
        description="适用于所有图片平台的正向、反向提示词模板列表",
        json_schema_extra={
            "label": "风格模板",
            "hint": "风格只负责提示词模板，不会修改 NovelAI Anime/Furry mode 或当前会话模型",
            "order": 1,
        },
    )
