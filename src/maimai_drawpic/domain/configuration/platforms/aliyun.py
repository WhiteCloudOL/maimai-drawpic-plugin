"""configuration/platforms/aliyun.py 的强类型配置定义。"""

from maibot_sdk import Field

from ...models.aliyun_profiles import DEFAULT_ALIYUN_MODELS
from ..types import AliyunImageInputMode, AliyunKlingResultType, AliyunPromptExtendMode

from .common import NegativePromptConfig


class AliyunModelConfig(NegativePromptConfig):
    """阿里百炼模型配置。"""

    __ui_label__ = "阿里百炼配置"
    __ui_order__ = 7

    enabled: bool = Field(
        default=True,
        description="是否启用阿里百炼平台",
        json_schema_extra={
            "label": "启用阿里百炼平台",
            "hint": "关闭后，本节模型不会出现在可用模型列表，也不会参与路由",
            "order": -1,
        },
    )
    base_url: str = Field(
        default="https://dashscope.aliyuncs.com/api/v1",
        description="阿里云 DashScope API 基础地址，需包含 /api/v1",
        json_schema_extra={
            "label": "DashScope Base URL（必填）",
            "hint": "必填。使用百炼工作空间域名时填写 https://{WorkspaceId}.地域.maas.aliyuncs.com/api/v1，不要填写 compatible-mode 地址",
            "order": 0,
        },
    )
    api_key: str = Field(
        default="your-aliyun-api-key",
        description="阿里百炼 API 密钥",
        json_schema_extra={
            "label": "阿里百炼 API 密钥（必填）",
            "hint": "必填。填入与 Base URL 同地域、同工作空间的 DashScope API 密钥",
            "input_type": "password",
            "order": 1,
        },
    )
    models: list[str] = Field(
        default=list(DEFAULT_ALIYUN_MODELS),
        description="阿里百炼可用图片模型列表，插件会自动识别已知模型能力",
        json_schema_extra={
            "label": "阿里百炼模型列表（必填）",
            "hint": "必填。默认仅保留千问 3.0/2.0、Z-Image、可灵 v3 和当前 Vidu 图像模型；旧模型与日期快照可按需手动添加",
            "order": 2,
        },
    )
    default_size: str = Field(
        default="2048*2048",
        description="阿里百炼图片默认分辨率。未在按模型覆盖分辨率中配置的模型会使用该值",
        json_schema_extra={
            "label": "默认分辨率",
            "hint": "格式为 宽*高，例如 2048*2048。不同模型支持范围不同，建议优先通过按模型覆盖分辨率配置",
            "order": 3,
        },
    )
    model_size_overrides: list[str] = Field(
        default=[
            "qwen-image-2.0=2048*2048",
            "qwen-image-2.0-pro=2048*2048",
            "qwen-image-max=1328*1328",
            "qwen-image-plus=1328*1328",
            "qwen-image-edit-max=1024*1024",
            "qwen-image-edit-plus=1024*1024",
        ],
        description="阿里百炼按模型覆盖分辨率。每项格式为 模型名=宽*高",
        json_schema_extra={
            "label": "按模型覆盖分辨率",
            "hint": "每行填写一个 模型名=宽*高，例如 qwen-image-plus=1328*1328。qwen-image-2.0 系列支持自由宽高，总像素需在 512*512 至 2048*2048",
            "order": 4,
        },
    )
    prompt_extend: bool = Field(
        default=True,
        description="是否启用阿里百炼提示词智能改写",
        json_schema_extra={
            "label": "启用提示词智能改写",
            "hint": "开启后百炼会优化正向提示词；不会修改反向提示词",
            "order": 6,
        },
    )
    qwen_prompt_extend_mode: AliyunPromptExtendMode = Field(
        default="direct",
        description="千问 3.0 提示词改写方式",
        json_schema_extra={
            "label": "千问 3.0 改写模式（可选）",
            "hint": "direct 支持文生图和图生图；agent 仅支持文生图",
            "options": ["direct", "agent"],
            "order": 7,
        },
    )
    qwen_enable_thinking: bool = Field(
        default=True,
        description="千问 3.0 是否开启思考模式",
        json_schema_extra={
            "label": "千问 3.0 思考模式（可选）",
            "hint": "可选，仅在 prompt_extend=true 时生效，会增加生成耗时",
            "order": 8,
        },
    )
    zimage_prompt_extend: bool = Field(
        default=False,
        description="Z-Image 是否启用提示词改写",
        json_schema_extra={
            "label": "Z-Image 提示词改写（可选）",
            "hint": "可选。开启会产生额外费用，默认关闭",
            "order": 9,
        },
    )
    seed: int = Field(
        default=0,
        description="阿里云模型随机种子",
        json_schema_extra={
            "label": "随机种子（可选）",
            "hint": "可选，范围 0 到 2147483647；Vidu 中 0 表示随机",
            "order": 10,
        },
    )
    watermark: bool = Field(
        default=False,
        description="是否添加阿里百炼水印",
        json_schema_extra={
            "label": "添加水印",
            "hint": "关闭时请求参数 watermark=false",
            "order": 11,
        },
    )
    max_images: int = Field(
        default=1,
        description="单次阿里百炼请求生成图片数量上限",
        json_schema_extra={
            "label": "单次图片数量",
            "hint": "插件当前默认请求 1 张；这里限制工具未来传入 n 时的最大值",
            "order": 12,
        },
    )
    image_input_mode: AliyunImageInputMode = Field(
        default="auto",
        description="图生图源图输入形式",
        json_schema_extra={
            "label": "源图输入形式（可选）",
            "hint": "auto=千问使用 Base64、可灵/Vidu 使用适配器原始 URL；显式选择不兼容模式会提前报错",
            "options": ["auto", "base64", "url"],
            "order": 13,
        },
    )
    async_poll_interval_seconds: float = Field(
        default=5.0,
        description="可灵和 Vidu 异步任务轮询间隔",
        json_schema_extra={
            "label": "异步轮询间隔（可选）",
            "hint": "可选，单位秒；官方建议约 5 秒，过低可能触发查询限流",
            "order": 14,
        },
    )
    kling_aspect_ratio: str = Field(
        default="1:1",
        description="可灵输出宽高比",
        json_schema_extra={
            "label": "可灵宽高比（可选）",
            "hint": "可选值：16:9、9:16、1:1",
            "options": ["16:9", "9:16", "1:1"],
            "order": 15,
        },
    )
    kling_resolution: str = Field(
        default="1k",
        description="可灵输出分辨率档位",
        json_schema_extra={
            "label": "可灵分辨率（可选）",
            "hint": "普通 V3 支持 1k/2k，Omni 还支持 4k",
            "options": ["1k", "2k", "4k"],
            "order": 16,
        },
    )
    kling_result_type: AliyunKlingResultType = Field(
        default="single",
        description="可灵 Omni 输出模式",
        json_schema_extra={
            "label": "可灵 Omni 输出模式（可选）",
            "hint": "single=独立图片，series=具有连续性的分镜组图",
            "options": ["single", "series"],
            "order": 17,
        },
    )
    kling_series_amount: int = Field(
        default=4,
        description="可灵 Omni 组图输出数量",
        json_schema_extra={
            "label": "可灵 Omni 组图数量（可选）",
            "hint": "可选，仅 result_type=series 时生效，范围 2 到 9",
            "order": 18,
        },
    )
    qwen_extra_parameters: list[str] = Field(
        default=[],
        description="千问族 parameters 额外参数",
        json_schema_extra={
            "label": "千问额外参数（可选）",
            "hint": "可选，每行一个 key=value，只会合并到千问模型请求",
            "order": 19,
        },
    )
    zimage_extra_parameters: list[str] = Field(
        default=[],
        description="Z-Image parameters 额外参数",
        json_schema_extra={
            "label": "Z-Image 额外参数（可选）",
            "hint": "可选，每行一个 key=value，只会合并到 Z-Image 请求",
            "order": 20,
        },
    )
    kling_extra_parameters: list[str] = Field(
        default=[],
        description="可灵 parameters 额外参数",
        json_schema_extra={
            "label": "可灵额外参数（可选）",
            "hint": "可选，每行一个 key=value，只会合并到可灵请求",
            "order": 21,
        },
    )
    vidu_extra_parameters: list[str] = Field(
        default=[],
        description="Vidu parameters 额外参数",
        json_schema_extra={
            "label": "Vidu 额外参数（可选）",
            "hint": "可选，每行一个 key=value，只会合并到 Vidu 请求",
            "order": 22,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="未知兼容模型的 parameters 额外参数。每项格式为 key=value",
        json_schema_extra={
            "label": "兼容模型额外参数（可选）",
            "hint": "可选，仅用于未被自动识别的旧兼容模型，不会串用到已知模型族",
            "order": 23,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用阿里百炼提供商前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "开启后会调用 MaiBot replyer 模型，将非英文提示词改写为英文单词和 NovelAI 友好的英文标点。使用 NovelAI/StableDiffusion 兼容模型时必须开启，否则可能生图失败",
            "order": 24,
        },
    )
