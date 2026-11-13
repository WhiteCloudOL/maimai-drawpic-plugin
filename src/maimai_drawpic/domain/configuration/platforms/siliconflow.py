"""configuration/platforms/siliconflow.py 的强类型配置定义。"""

from maibot_sdk import Field

from .common import NegativePromptConfig


class SiliconFlowModelConfig(NegativePromptConfig):
    """硅基流动模型配置。"""

    __ui_label__ = "硅基流动配置"
    __ui_order__ = 9

    enabled: bool = Field(
        default=True,
        description="是否启用硅基流动平台",
        json_schema_extra={
            "label": "启用硅基流动平台",
            "hint": "关闭后，本节模型不会出现在可用模型列表，也不会参与路由",
            "order": -1,
        },
    )
    api_key: str = Field(
        default="your-siliconflow-api-key",
        description="硅基流动 API 密钥",
        json_schema_extra={
            "label": "硅基流动 API 密钥",
            "hint": "填入硅基流动 API 密钥",
            "input_type": "password",
            "order": 0,
        },
    )
    models: list[str] = Field(
        default=[
            "Kwai-Kolors/Kolors",
            "stabilityai/stable-diffusion-3-5-large",
        ],
        description="硅基流动可用图片模型列表",
        json_schema_extra={
            "label": "硅基流动模型列表",
            "hint": "这里填写属于硅基流动图片生成接口的模型",
            "order": 1,
        },
    )
    image_size: str = Field(
        default="1024x1024",
        description="硅基流动图片尺寸。",
        json_schema_extra={
            "label": "图片尺寸",
            "hint": "官方参数 image_size；可填 1024x1024 等固定尺寸，或模型支持的枚举值",
            "order": 2,
        },
    )
    model_size_overrides: list[str] = Field(
        default=[],
        description="硅基流动按模型覆盖图片尺寸。每项格式为 模型名=宽x高",
        json_schema_extra={
            "label": "按模型覆盖图片尺寸",
            "hint": "每行填写一个 模型名=宽x高，例如 Kwai-Kolors/Kolors=1024x1024。",
            "order": 3,
        },
    )
    seed: int = Field(
        default=-1,
        description="硅基流动随机种子。负数表示不传",
        json_schema_extra={
            "label": "随机种子",
            "hint": "负数表示不固定；非负整数会传入 seed",
            "order": 5,
        },
    )
    num_inference_steps: int = Field(
        default=20,
        description="硅基流动采样步数。",
        json_schema_extra={
            "label": "采样步数",
            "hint": "常见值 20 到 50；留 0 或负数则不传。",
            "order": 6,
        },
    )
    guidance_scale: float = Field(
        default=7.5,
        description="硅基流动提示词引导强度。",
        json_schema_extra={
            "label": "引导强度",
            "hint": "仅 Kolors 使用 guidance_scale；Qwen Image 使用下方 CFG，0 表示不传",
            "order": 7,
        },
    )
    cfg: float = Field(
        default=0.0,
        ge=0,
        le=20,
        description="Qwen Image 提示词匹配强度",
        json_schema_extra={
            "label": "Qwen Image CFG",
            "hint": "仅 Qwen Image 系列使用；0 不传，常用值 4；Kolors 使用上方引导强度",
            "order": 7.5,
        },
    )
    watermark_enabled: bool = Field(
        default=True,
        description="是否启用硅基流动生成图片的显式 AI 生成水印。",
        json_schema_extra={
            "label": "启用「AI 生成」显式水印",
            "hint": "默认开启。关闭时发送请求头 X-Enable-Watermark: 0，隐式水印仍保留。官方要求仅在继续处理生成图时关闭，并为最终输出补充显式标识。",
            "order": 8,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="硅基流动图片生成额外 JSON 参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；用于兼容平台新增参数",
            "order": 10,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用硅基流动提供商前将提示词改写为英文。",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "使用 Stable Diffusion 类模型时建议开启。",
            "order": 11,
        },
    )
