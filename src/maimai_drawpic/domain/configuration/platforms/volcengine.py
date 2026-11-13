"""configuration/platforms/volcengine.py 的强类型配置定义。"""

from maibot_sdk import Field

from ..types import VolcengineResponseFormat, VolcengineSequentialMode

from .common import NegativePromptConfig


class VolcengineModelConfig(NegativePromptConfig):
    """火山引擎方舟模型配置。"""

    __ui_label__ = "火山引擎配置"
    __ui_order__ = 8

    enabled: bool = Field(
        default=True,
        description="是否启用火山引擎平台",
        json_schema_extra={
            "label": "启用火山引擎平台",
            "hint": "关闭后，该平台的模型将不可选。",
            "order": -1,
        },
    )
    api_key: str = Field(
        default="your-volcengine-api-key",
        description="火山引擎方舟 API Key",
        json_schema_extra={
            "label": "火山引擎 API Key",
            "hint": "普通方舟与 Agent Plan 共用这一字段；填入与下方 Base URL 对应的 Key，二者的 Key 本身不可交叉使用",
            "input_type": "password",
            "order": 0,
        },
    )
    base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3",
        description="火山引擎方舟图片生成 API 基础地址",
        json_schema_extra={
            "label": "火山引擎 Base URL",
            "hint": "普通方舟与 Agent Plan 共用这一字段：按量直调和 Token 额度包填 /api/v3，Agent Plan 填 /api/plan/v3；也可填写兼容网关或完整接口地址",
            "order": 0.5,
        },
    )
    models: list[str] = Field(
        default=[
            "doubao-seedream-5-0-flash-260915",
            "doubao-seedream-5-0-pro-260628",
            "doubao-seedream-5-0-260128",
        ],
        description="火山引擎方舟图片模型列表",
        json_schema_extra={
            "label": "火山引擎模型列表",
            "hint": "统一填写 Model ID 或 Endpoint ID；名称含 t2i/i2i 的旧模型会自动限制任务类型，其余模型默认同时支持文生图与图生图",
            "order": 1,
        },
    )
    default_size: str = Field(
        default="2K",
        description="火山引擎图片默认分辨率",
        json_schema_extra={
            "label": "默认分辨率",
            "hint": "填写 1K/1.5K/2K/4K 或宽x高；必须使用小写 x，插件会兼容旧配置中的 * 和 ×",
            "order": 4,
        },
    )
    model_size_overrides: list[str] = Field(
        default=[],
        description="火山引擎按模型覆盖分辨率。每项格式为 模型名=分辨率档位或宽x高",
        json_schema_extra={
            "label": "按模型覆盖分辨率",
            "hint": "每行填写一个 模型名=尺寸，例如 doubao-seedream-5-0-flash-260915=2K",
            "order": 5,
        },
    )
    model_endpoint_overrides: list[str] = Field(
        default=[],
        description="火山引擎按模型覆盖接口地址。每项格式为 模型名=URL或路径",
        json_schema_extra={
            "label": "按模型覆盖接口地址",
            "hint": "通常留空。不同模型需要特殊地址时，每行填写 模型名=完整URL 或 模型名=api/v3/...",
            "order": 6,
        },
    )
    response_format: VolcengineResponseFormat = Field(
        default="url",
        description="火山引擎图片响应格式",
        json_schema_extra={
            "label": "响应格式",
            "hint": "url 返回 24 小时有效下载链接；b64_json 直接返回 Base64 图片数据",
            "options": ["url", "b64_json"],
            "order": 7,
        },
    )
    # 空值表示不传可选参数；使用文本输入避免下拉组件拒绝空字符串选项。
    output_format: str = Field(
        default="",
        pattern=r"^(?:png|jpeg)?$",
        description="火山引擎生成图片的文件格式",
        json_schema_extra={
            "label": "输出文件格式",
            "hint": "可选 png 或 jpeg；仅 Seedream 5.0 系列支持，留空跟随模型默认值",
            "placeholder": "png / jpeg",
            "order": 7.1,
        },
    )
    sequential_image_generation: VolcengineSequentialMode = Field(
        default="disabled",
        description="火山引擎组图生成模式",
        json_schema_extra={
            "label": "组图生成",
            "hint": "auto 允许 Seedream 5.0 lite、4.5、4.0 自动生成组图；其他模型会自动忽略",
            "options": ["disabled", "auto"],
            "order": 7.2,
        },
    )
    optimize_prompt_mode: str = Field(
        default="",
        pattern=r"^(?:standard|fast)?$",
        description="火山引擎服务端提示词优化模式",
        json_schema_extra={
            "label": "提示词优化模式",
            "hint": "standard 质量优先；fast 仅 Seedream 5.0 pro 和 4.0 支持；留空不传",
            "placeholder": "standard / fast",
            "order": 7.3,
        },
    )
    web_search_enabled: bool = Field(
        default=False,
        description="是否允许支持的火山引擎模型调用联网搜索工具",
        json_schema_extra={
            "label": "启用联网搜索",
            "hint": "仅 Seedream 5.0 lite 支持；模型会自行判断是否需要联网，并可能增加延迟",
            "order": 7.4,
        },
    )
    background: str = Field(
        default="",
        pattern=r"^(?:opaque|transparent)?$",
        description="火山引擎图生图透明通道模式",
        json_schema_extra={
            "label": "图生图背景模式",
            "hint": "可选 opaque 或 transparent，留空不传；仅 Seedream 5.0 pro/flash 图生图支持；transparent 要求单张透明源图且不能输出 jpeg",
            "placeholder": "opaque / transparent",
            "order": 7.5,
        },
    )
    layer_decomposition: bool = Field(
        default=False,
        description="是否启用 Seedream 5.0 pro/flash 图层拆分",
        json_schema_extra={
            "label": "启用图层拆分",
            "hint": "仅 Seedream 5.0 pro/flash 图生图支持，且必须只输入一张图片；会返回底图和多个图层",
            "order": 7.6,
        },
    )
    guidance_scale: float = Field(
        default=0.0,
        description="火山引擎提示词引导强度。0 表示不传",
        json_schema_extra={
            "label": "引导强度",
            "hint": "仅 Seedream 3.0/SeedEdit 3.0 支持；当前 Seedream 4.0/5.0 会自动忽略",
            "order": 8,
        },
    )
    seed: int = Field(
        default=-1,
        description="火山引擎随机种子。负数表示不传",
        json_schema_extra={
            "label": "随机种子",
            "hint": "仅 Seedream 3.0/SeedEdit 3.0 支持；当前 Seedream 4.0/5.0 会自动忽略",
            "order": 9,
        },
    )
    watermark: bool = Field(
        default=False,
        description="火山引擎是否添加水印",
        json_schema_extra={
            "label": "添加水印",
            "hint": "关闭时请求参数 watermark=false",
            "order": 10,
        },
    )
    max_images: int = Field(
        default=1,
        description="火山引擎组图最多生成图片数量",
        json_schema_extra={
            "label": "单次图片数量",
            "hint": "仅组图生成 auto 模式生效，范围 1 到 15；输入参考图数量与输出数量之和不会超过 15",
            "order": 11,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="火山引擎图片生成额外 JSON 参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；用于兼容平台新增参数",
            "order": 12,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用火山引擎提供商前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "开启后会调用 MaiBot replyer 模型将非英文提示词改写为英文；多数即梦/豆包模型可直接使用中文",
            "order": 13,
        },
    )
