"""configuration/platforms/zhipu.py 的强类型配置定义。"""

from maibot_sdk import Field

from .common import NegativePromptConfig


class ZhipuModelConfig(NegativePromptConfig):
    """智谱模型配置。"""

    __ui_label__ = "智谱配置"
    __ui_order__ = 6

    enabled: bool = Field(
        default=True,
        description="是否启用智谱平台",
        json_schema_extra={
            "label": "启用智谱平台",
            "hint": "关闭后，本节模型不会出现在可用模型列表，也不会参与路由",
            "order": -1,
        },
    )
    api_key: str = Field(
        default="your-zhipu-api-key",
        description="智谱 API 密钥（必填）",
        json_schema_extra={
            "label": "智谱 API 密钥（必填）",
            "hint": "填入智谱开放平台的 API 密钥",
            "input_type": "password",
            "order": 0,
        },
    )
    models: list[str] = Field(
        default=["glm-image"],
        description="智谱可用图片模型列表（必填，仅支持文生图）",
        json_schema_extra={
            "label": "智谱模型列表（必填）",
            "hint": "默认使用 glm-image；也可填写智谱图像生成接口当前支持的 CogView 模型。仅支持文生图，不支持图生图编辑",
            "order": 1,
        },
    )
    quality: str = Field(
        default="",
        description="智谱图像生成质量（可选）",
        json_schema_extra={
            "label": "生成质量（可选）",
            "hint": "留空时由上游按模型选择默认质量；glm-image 仅支持 hd，CogView 可按官方说明选择 hd 或 standard",
            "placeholder": "hd / standard",
            "order": 2,
        },
    )
    size: str = Field(
        default="1280x1280",
        description="智谱图像生成分辨率（可选）",
        json_schema_extra={
            "label": "分辨率（可选）",
            "hint": "glm-image 默认 1280x1280，支持官方枚举或满足尺寸约束的自定义值；留空则由上游决定",
            "order": 3,
        },
    )
    watermark_enabled: bool = Field(
        default=True,
        description="是否启用智谱生成图片水印（可选）",
        json_schema_extra={
            "label": "启用水印（可选）",
            "hint": "默认启用显式水印及隐式数字水印；关闭水印需要先在智谱平台签署免责声明",
            "order": 4,
        },
    )
    user_id: str = Field(
        default="",
        description="智谱终端用户唯一标识（可选）",
        json_schema_extra={
            "label": "终端用户标识（可选）",
            "hint": "用于上游安全审计，长度须为 6 到 128 个字符；留空则不传",
            "order": 5,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="智谱图像生成额外 JSON 参数（可选）。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数（可选）",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；用于自定义或兼容未来模型参数",
            "order": 6,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用智谱提供商前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "开启后会调用 MaiBot replyer 模型，将非英文提示词改写为英文单词和 NovelAI 友好的英文标点。使用 NovelAI/StableDiffusion 兼容模型时必须开启，否则可能生图失败",
            "order": 7,
        },
    )
