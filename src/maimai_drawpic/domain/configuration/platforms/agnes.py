"""Agnes 图像平台配置。"""

from maibot_sdk import Field
from typing import List, Literal

from .common import NegativePromptConfig


class AgnesModelConfig(NegativePromptConfig):
    """Agnes Image 2.0、2.1 和 2.5 Flash 共用的连接与图片参数。"""

    __ui_label__ = "Agnes 配置"
    __ui_order__ = 12

    enabled: bool = Field(default=True, json_schema_extra={"label": "启用 Agnes 平台", "order": -1})
    base_url: str = Field(
        default="https://apihub.agnes-ai.com/v1",
        json_schema_extra={"label": "Agnes 基础 URL", "hint": "填写 API 地址，不是控制台或文档地址。", "order": 0},
    )
    api_key: str = Field(
        default="",
        json_schema_extra={"label": "API 密钥", "input_type": "password", "order": 1},
    )
    models: List[str] = Field(
        default=["agnes-image-2.5-flash", "agnes-image-2.1-flash", "agnes-image-2.0-flash"],
        json_schema_extra={
            "label": "Agnes 模型列表",
            "hint": "填写账号可用的图像模型，支持文生图和多张参考图编辑。",
            "order": 2,
        },
    )
    default_size: str = Field(
        default="1024x1024",
        min_length=1,
        json_schema_extra={
            "label": "默认分辨率",
            "hint": "2.1 / 2.5 推荐 1K～4K 搭配宽高比，也兼容像素尺寸（可能被调整）；2.0 仅使用像素尺寸，可在下方单独覆盖。",
            "order": 3,
        },
    )
    ratio: Literal["1:1", "3:4", "4:3", "16:9", "9:16", "2:3", "3:2", "21:9"] = Field(
        default="1:1",
        json_schema_extra={
            "label": "宽高比",
            "hint": "用于 2.1 / 2.5 的档位式尺寸；2.0 使用像素尺寸，不发送此参数。",
            "order": 4,
        },
    )
    model_size_overrides: List[str] = Field(
        default=[],
        json_schema_extra={"label": "按模型覆盖分辨率", "order": 5},
    )
    response_format: Literal["b64_json", "url"] = Field(
        default="b64_json",
        json_schema_extra={"label": "响应格式", "hint": "自动使用 Agnes 要求的嵌套参数格式。", "order": 6},
    )
    extra_parameters: List[str] = Field(
        default=[],
        json_schema_extra={
            "label": "额外参数",
            "hint": "仅在需要平台扩展参数时添加；extra_body 使用 JSON 对象。",
            "order": 7,
        },
    )
