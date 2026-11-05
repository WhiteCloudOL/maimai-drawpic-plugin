"""configuration/platforms/novelai.py 的强类型配置定义。"""

from maibot_sdk import Field
from typing import List

from ...models.novelai_catalog import NOVELAI_DEFAULT_MODELS
from ..types import NovelAIMode

from .common import NegativePromptConfig


class NovelAIModelConfig(NegativePromptConfig):
    """NovelAI / NovelAPI 模型配置。"""

    negative_prompt_enabled: bool = Field(
        default=True,
        description="是否接受本次请求的反向提示词并添加平台默认反向词",
        json_schema_extra={
            "label": "启用反向提示词",
            "hint": "关闭时忽略 AI、命令、工作台和 API 传入的反向词及平台默认反向词；风格预设自己的正反向模板仍生效。",
            "order": 80,
        },
    )

    __ui_label__ = "NovelAI / NovelAPI 配置"
    __ui_order__ = 10

    enabled: bool = Field(
        default=True,
        description="是否启用 NovelAI / NovelAPI 平台",
        json_schema_extra={
            "label": "启用 NovelAI / NovelAPI 平台",
            "hint": "关闭后，本节模型不会出现在可用模型列表，也不会参与路由",
            "order": -1,
        },
    )
    base_url: str = Field(
        default="https://image.novelai.net",
        description="NovelAI 官方图片接口基础 URL，或兼容 NovelAI payload 的 NovelAPI 网关根地址。",
        json_schema_extra={
            "label": "NovelAI 基础 URL",
            "hint": "官方默认 https://image.novelai.net；NovelAPI/中转平台按其文档填写根地址",
            "order": 0,
        },
    )
    api_key: str = Field(
        default="your-novelai-api-key",
        description="NovelAI / NovelAPI API 密钥",
        json_schema_extra={
            "label": "NovelAI API 密钥",
            "hint": "填入 NovelAI Bearer Token 或 NovelAPI 平台密钥",
            "input_type": "password",
            "order": 1,
        },
    )
    models: List[str] = Field(
        default_factory=lambda: list(NOVELAI_DEFAULT_MODELS),
        description="NovelAI / NovelAPI 图片模型列表，统一保存预设与自定义模型 ID。",
        json_schema_extra={
            "label": "NovelAI 模型列表",
            "hint": "可从官方模型预设添加，也可直接填写兼容服务的模型 ID；统一在此列表编辑，保存后生效。",
            "order": 2,
        },
    )
    custom_models: list[str] = Field(
        default=[],
        description="仅供读取旧配置的自定义模型；加载平台时合并到 models。",
        json_schema_extra={
            "label": "自定义模型列表",
            "hint": "旧自定义模型会自动合并到统一模型列表，不再单独编辑。",
            "hidden": True,
            "order": 3,
        },
    )
    default_mode: NovelAIMode = Field(
        default="anime",
        description="NovelAI 默认数据集模式。Anime 为普通模式，Furry/Background 会按官方规则在提示词开头加入数据集标签",
        json_schema_extra={
            "label": "默认 NAI 模式",
            "hint": "anime=普通；furry=V4+ 添加 fur dataset，V3 切换到 Furry V3；background=V4.5+ 添加 background dataset",
            "options": ["anime", "furry", "background"],
            "order": 3.5,
        },
    )
    width: int = Field(
        default=832,
        description="NovelAI 图片宽度。",
        json_schema_extra={
            "label": "宽度",
            "hint": "常用值 832、1024、1216 等；以模型实际支持为准。",
            "order": 4,
        },
    )
    height: int = Field(
        default=1216,
        description="NovelAI 图片高度。",
        json_schema_extra={
            "label": "高度",
            "hint": "常用值 832、1024、1216 等；以模型实际支持为准",
            "order": 5,
        },
    )
    model_size_overrides: list[str] = Field(
        default=[],
        description="NovelAI 按模型覆盖尺寸。每项格式为 模型名=宽x高。",
        json_schema_extra={
            "label": "按模型覆盖尺寸",
            "hint": "每行填写一个 模型名=宽x高，例如 nai-diffusion-3=832x1216",
            "order": 6,
        },
    )
    sampler: str = Field(
        default="k_euler_ancestral",
        description="NovelAI 采样器。",
        json_schema_extra={
            "label": "采样器",
            "hint": "常见值：k_euler_ancestral、k_euler、k_dpmpp_2m、ddim 等",
            "order": 7,
        },
    )
    steps: int = Field(
        default=28,
        description="NovelAI 采样步数。",
        json_schema_extra={
            "label": "采样步数",
            "hint": "常见值 20 到 40。",
            "order": 8,
        },
    )
    scale: float = Field(
        default=5.0,
        description="NovelAI Prompt Guidance / CFG Scale。",
        json_schema_extra={
            "label": "Prompt Guidance",
            "hint": "常见值 4 到 8，值越高越贴近提示词",
            "order": 9,
        },
    )
    seed: int = Field(
        default=-1,
        description="NovelAI 随机种子。负数表示随机。",
        json_schema_extra={
            "label": "随机种子",
            "hint": "负数会在本地生成随机种子；非负整数固定 seed",
            "order": 10,
        },
    )
    positive_prompt: str = Field(
        default="",
        description="NovelAI 默认正向提示词，会与每次请求的用户正向提示词合并",
        json_schema_extra={
            "label": "默认正向提示词",
            "hint": "建议填写英文标签；留空表示不额外添加。此项是 NAI 平台默认词，不属于全平台风格模板",
            "input_type": "textarea",
            "x-widget": "textarea",
            "rows": 4,
            "order": 10.5,
        },
    )
    default_artist_tags: str = Field(
        default="",
        description="NovelAI 默认画师标签。会话未单独设置时，将这些标签放在普通正向提示词之前",
        json_schema_extra={
            "label": "默认画师标签",
            "hint": "填写 NovelAI 可识别的原始画师标签，多个标签用英文逗号分隔；例如 artist:name。此项仅对 NAI 平台生效",
            "input_type": "textarea",
            "x-widget": "textarea",
            "rows": 3,
            "order": 10.7,
        },
    )
    negative_prompt: str = Field(
        default="lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry",
        description="NovelAI 默认反向提示词，启用后与本次反向词及风格词去重合并",
        json_schema_extra={
            "label": "默认反向提示词（可选）",
            "hint": "仅在反向提示词开关开启时生效；与本次反向词、风格反向词去重合并，英文改写后写入 uc",
            "input_type": "textarea",
            "order": 81,
        },
    )
    uc_preset: int = Field(
        default=0,
        description="NovelAI / NovelAPI 旧版 undesired content 预设编号。",
        json_schema_extra={
            "label": "旧版 UC 预设",
            "hint": "官方 V3/V4/V5 使用上方反向提示词；兼容网关可按其文档填写旧版编号",
            "order": 12,
        },
    )
    quality_toggle: bool = Field(
        default=True,
        description="NovelAI 是否启用质量标签增强",
        json_schema_extra={
            "label": "质量增强",
            "hint": "官方模型会按 V3、V4、V4.5、V5 自动添加对应质量标签",
            "order": 13,
        },
    )
    sm: bool = Field(
        default=False,
        description="NovelAI smea 开关",
        json_schema_extra={
            "label": "SMEA",
            "hint": "仅 V3 文生图支持；V4 及以上模型和图生图会忽略",
            "order": 14,
        },
    )
    sm_dyn: bool = Field(
        default=False,
        description="NovelAI dynamic smea 开关",
        json_schema_extra={
            "label": "动态 SMEA",
            "hint": "仅 V3 文生图支持；需同时开启 SMEA；V4 及以上模型和图生图会忽略",
            "order": 15,
        },
    )
    noise_schedule: str = Field(
        default="native",
        description="NovelAI noise schedule",
        json_schema_extra={
            "label": "噪声调度",
            "hint": "常见值 native、karras、exponential、polyexponential；留空则不传",
            "order": 16,
        },
    )
    v4_noise_schedule: str = Field(
        default="karras",
        description="NovelAI V4/V4.5 专用 noise schedule；V5 使用官方推荐设置。",
        json_schema_extra={
            "label": "V4/V4.5 噪声调度",
            "hint": "V4/V4.5 默认使用 karras；V5 使用官方推荐设置；留空则不传",
            "order": 17,
        },
    )
    img2img_strength: float = Field(
        default=0.6,
        description="NovelAI 图生图重绘强度",
        json_schema_extra={
            "label": "图生图强度",
            "hint": "仅图生图使用；值越高允许模型对原图改动越大，值越低越接近原图；常见值 0.4 到 0.8",
            "order": 18,
        },
    )
    img2img_noise: float = Field(
        default=0.1,
        description="NovelAI 图生图噪声强度",
        json_schema_extra={
            "label": "图生图噪声",
            "hint": "仅 edit_image 使用；常见值 0 到 0.3",
            "order": 19,
        },
    )
    max_images: int = Field(
        default=1,
        description="单次 NovelAI 请求生成图片数量上限",
        json_schema_extra={
            "label": "单次图片数量",
            "hint": "会写入 n_samples，建议 1 到 4",
            "order": 20,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="NovelAI parameters 额外参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；会合并到 parameters",
            "order": 21,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=True,
        description="是否在调用 NovelAI / NovelAPI 提供商前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "NovelAI 标签体系建议开启，避免中文提示词导致效果差或请求失败",
            "order": 22,
        },
    )
