"""configuration/platforms/google.py 的强类型配置定义。"""

from maibot_sdk import Field

from .common import NegativePromptConfig


class GoogleModelConfig(NegativePromptConfig):
    """Google 模型配置。"""

    __ui_label__ = "Google 配置"
    __ui_order__ = 5

    enabled: bool = Field(
        default=True,
        description="是否启用 Google 平台",
        json_schema_extra={
            "label": "启用 Google 平台",
            "hint": "关闭后，本节模型不会出现在可用模型列表，也不会参与路由",
            "order": -1,
        },
    )
    base_url: str = Field(
        default="https://generativelanguage.googleapis.com",
        description="Google Gemini 服务基础 URL。使用官方服务时可留空，使用兼容网关时按网关要求填写",
        json_schema_extra={
            "label": "Google 基础 URL",
            "hint": "Google Gemini 服务基础 URL。使用官方服务时可留空，使用兼容网关时按网关要求填写",
            "order": 0,
        },
    )
    api_key: str = Field(
        default="your-google-api-key",
        description="Google Gemini API 密钥",
        json_schema_extra={
            "label": "Google API 密钥",
            "hint": "填入 Google Gemini 或兼容网关的 API 密钥",
            "input_type": "password",
            "order": 1,
        },
    )
    models: list[str] = Field(
        default=["gemini-3.1-flash-image", "gemini-3-pro-image"],
        description="Google 可用图片模型列表",
        json_schema_extra={
            "label": "Google 模型列表",
            "hint": "这里填写属于 Google Gemini 接口的图片模型",
            "order": 2,
        },
    )
    aspect_ratio: str = Field(
        default="",
        description="Google 图片宽高比，留空时跟随模型或参考图片",
        json_schema_extra={
            "label": "宽高比",
            "hint": "可填 1:1、3:4、4:3、9:16、16:9 等；留空时不强制输出比例",
            "order": 4,
        },
    )
    image_size: str = Field(
        default="",
        description="Gemini 图片输出分辨率档位",
        json_schema_extra={
            "label": "图片分辨率档位",
            "hint": "可填 1K、2K、4K；Gemini 3.1 Flash 还支持 512。需使用大写 K，留空使用模型默认分辨率",
            "placeholder": "1K / 2K / 4K",
            "order": 5,
        },
    )
    seed: int = Field(
        default=-1,
        description="Google 随机种子。负数表示不传",
        json_schema_extra={
            "label": "随机种子",
            "hint": "非负整数作为 GenerateContentConfig.seed 发送；留 -1 时由平台随机选择",
            "order": 8,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="Google 图片配置额外参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value；用于 temperature、thinking_config、tools 等生成配置，不支持的参数会明确报错",
            "order": 11,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用 Google 提供商前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "开启后会调用 MaiBot replyer 模型，将非英文提示词改写为英文单词和 NovelAI 友好的英文标点。使用 NovelAI/StableDiffusion 兼容模型时必须开启，否则可能生图失败",
            "order": 12,
        },
    )
