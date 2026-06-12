from typing import Literal

from maibot_sdk import Field, PluginConfigBase


OpenAICompatibilityMode = Literal["auto", "images_api", "chat_completions", "novelai_images_api"]
QuotaPeriodMode = Literal["daily", "weekly", "monthly", "once"]
CommandReplyMode = Literal["图片", "文本"]


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__ = "插件基础配置"
    __ui_icon__ = "package"
    __ui_order__ = 0

    enabled: bool = Field(
        default=True,
        description="是否启用插件",
        json_schema_extra={
            "label": "启用插件",
        },
    )
    config_version: str = Field(
        default="2.12.0",
        description="配置版本",
        json_schema_extra={
            "hint": "配置版本",
        },
    )


class GeneralConfig(PluginConfigBase):
    """通用配置。"""

    __ui_label__ = "通用配置"
    __ui_order__ = 1

    default_model: str = Field(
        default="gpt-image-2",
        description="默认模型名称。插件会自动在各平台模型列表中查找该模型",
        json_schema_extra={
            "label": "默认模型",
            "hint": "默认模型名称。插件会自动在各平台模型列表中查找该模型",
            "order": 0,
        },
    )
    request_timeout_seconds: int = Field(
        default=150,
        description="单次图片请求超时时间（秒），用于后台图片任务",
        json_schema_extra={
            "label": "图片请求超时",
            "hint": "单次图片请求超时时间（秒），建议设置为 120 到 300",
            "order": 1,
        },
    )
    command_reply_mode: CommandReplyMode = Field(
        default="图片",
        description="聊天命令返回形式，可选择图片或文本",
        json_schema_extra={
            "label": "命令返回形式",
            "hint": "图片=使用粉色图片模板回复命令；文本=直接发送纯文本回复",
            "options": ["图片", "文本"],
            "order": 2,
        },
    )
    permission_enabled: bool = Field(
        default=True,
        description="是否启用权限管理。启用后，仅插件管理员可切换模型、切换兼容模式和修改用户次数",
        json_schema_extra={
            "label": "启用权限管理",
            "hint": "启用后，模型切换、兼容模式切换和次数管理命令仅允许插件管理员使用",
            "order": 3,
        },
    )
    admin_user_ids: list[str] = Field(
        default=[],
        description="插件管理员用户 ID 列表，通常填写 QQ 号",
        json_schema_extra={
            "label": "插件管理员列表",
            "hint": "填写允许管理模型、兼容模式和用户次数的用户 ID，通常为 QQ 号",
            "order": 4,
        },
    )
    quota_enabled: bool = Field(
        default=True,
        description="是否启用用户绘图次数管理。管理员不受次数限制",
        json_schema_extra={
            "label": "启用用户次数管理",
            "hint": "启用后，普通用户每次绘图会消耗次数；管理员不受限制",
            "order": 5,
        },
    )
    quota_period: QuotaPeriodMode = Field(
        default="daily",
        description="用户次数重置周期：daily / weekly / monthly / once",
        json_schema_extra={
            "label": "次数周期",
            "hint": "daily=每日，weekly=每周，monthly=每月，once=一次性不自动重置",
            "order": 6,
        },
    )
    default_quota: int = Field(
        default=5,
        description="普通用户在当前周期内默认可用绘图次数。",
        json_schema_extra={
            "label": "默认可用次数",
            "hint": "普通用户在所选周期内默认可用的绘图次数",
            "order": 7,
        },
    )


class OpenAIModelConfig(PluginConfigBase):
    """OpenAI 模型配置。"""

    __ui_label__ = "OpenAI 配置"
    __ui_order__ = 2

    base_url: str = Field(
        default="https://api.openai.com",
        description="OpenAI兼容服务基础 URL。手动接口填写根地址，不要带 /v1",
        json_schema_extra={
            "label": "OpenAI 基础 URL",
            "hint": "OpenAI兼容服务基础 URL。手动接口填写根地址，不要带 /v1",
            "order": 0,
        },
    )
    api_key: str = Field(
        default="your-openai-api-key",
        description="OpenAI兼容服务的 API 密钥",
        json_schema_extra={
            "label": "OpenAI API 密钥",
            "hint": "填入 OpenAI 或 OpenAI 兼容服务的 API 密钥",
            "input_type": "password",
            "order": 1,
        },
    )
    models: list[str] = Field(
        default=["gpt-image-2"],
        description="OpenAI 可用图片模型列表",
        json_schema_extra={
            "label": "OpenAI 模型列表",
            "hint": "这里填写属于 OpenAI 或 OpenAI 兼容接口的图片模型",
            "order": 2,
        },
    )
    default_openai_compatibility_mode: OpenAICompatibilityMode = Field(
        default="auto",
        description="默认 OpenAI 兼容模式。仅在当前会话使用 OpenAI 系模型时生效。",
        json_schema_extra={
            "label": "默认 OpenAI 兼容模式",
            "hint": "支持 auto、images_api、chat_completions、novelai_images_api；通常建议使用 auto。NovelAI 官方平台请优先使用独立 NovelAI 配置。",
            "order": 3,
        },
    )
    default_size: str = Field(
        default="1024x1024",
        description="OpenAI Images API 默认分辨率。",
        json_schema_extra={
            "label": "默认分辨率",
            "hint": "常见值：1024x1024、1024x1536、1536x1024、auto；OpenAI 兼容中转可按自身要求填写",
            "order": 4,
        },
    )
    model_size_overrides: list[str] = Field(
        default=[],
        description="OpenAI 按模型覆盖分辨率。每项格式为 模型名=宽x高。",
        json_schema_extra={
            "label": "按模型覆盖分辨率",
            "hint": "每行填写一个 模型名=宽x高，例如 gpt-image-1=1024x1024。",
            "order": 5,
        },
    )
    quality: str = Field(
        default="",
        description="OpenAI Images API 质量参数。",
        json_schema_extra={
            "label": "质量",
            "hint": "常见值：auto、low、medium、high、standard、hd；留空则不传",
            "order": 6,
        },
    )
    response_format: str = Field(
        default="",
        description="OpenAI Images API 响应格式。",
        json_schema_extra={
            "label": "响应格式",
            "hint": "常见值：b64_json 或 url；gpt-image 系列官方接口不支持 response_format 时请留空",
            "order": 7,
        },
    )
    output_format: str = Field(
        default="",
        description="OpenAI Images API 输出图片格式。",
        json_schema_extra={
            "label": "输出格式",
            "hint": "常见值：png、jpeg、webp；兼容平台不支持时请留空。",
            "order": 8,
        },
    )
    background: str = Field(
        default="",
        description="OpenAI Images API 背景参数。",
        json_schema_extra={
            "label": "背景",
            "hint": "常见值：transparent、opaque、auto；留空则不传。",
            "order": 9,
        },
    )
    moderation: str = Field(
        default="",
        description="OpenAI Images API 审核强度参数。",
        json_schema_extra={
            "label": "审核强度",
            "hint": "官方常见值：auto、low；留空则不传。",
            "order": 10,
        },
    )
    max_images: int = Field(
        default=1,
        description="单次 OpenAI 请求生成图片数量上限。",
        json_schema_extra={
            "label": "单次图片数量",
            "hint": "插件当前默认请求 1 张；这里限制工具未来传入 n 时的最大值，建议 1 到 4",
            "order": 11,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="OpenAI 兼容接口额外 JSON 参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；用于 NewAPI 等中转自定义字段",
            "order": 12,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用 OpenAI 提供商前将提示词改写为英文。",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "开启后会调用 MaiBot replyer 模型，将非英文提示词改写为英文单词和 NovelAI 友好的英文标点。使用 NovelAI/StableDiffusion 兼容模型时必须开启，否则可能生图失败",
            "order": 13,
        },
    )


class GoogleModelConfig(PluginConfigBase):
    """Google 模型配置。"""

    __ui_label__ = "Google 配置"
    __ui_order__ = 3

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
        default=["gemini-3.1-flash-image-preview", "gemini-3-pro-image-preview"],
        description="Google 可用图片模型列表",
        json_schema_extra={
            "label": "Google 模型列表",
            "hint": "这里填写属于 Google Gemini 接口的图片模型",
            "order": 2,
        },
    )
    number_of_images: int = Field(
        default=1,
        description="Google 图片生成数量",
        json_schema_extra={
            "label": "生成图片数量",
            "hint": "Google generate_images/edit_image 支持 number_of_images；generateContent 图片模型通常只返回 1 张",
            "order": 3,
        },
    )
    aspect_ratio: str = Field(
        default="1:1",
        description="Google 图片宽高比",
        json_schema_extra={
            "label": "宽高比",
            "hint": "常见值：1:1、3:4、4:3、9:16、16:9；generateContent 图片模型可能忽略该参数",
            "order": 4,
        },
    )
    output_mime_type: str = Field(
        default="image/png",
        description="Google 输出图片 MIME 类型",
        json_schema_extra={
            "label": "输出 MIME 类型",
            "hint": "常见值：image/png、image/jpeg；留空则使用 SDK 默认",
            "order": 5,
        },
    )
    person_generation: str = Field(
        default="",
        description="Google 人物生成策略",
        json_schema_extra={
            "label": "人物生成策略",
            "hint": "按 Google 模型支持填写，例如 allow_adult；留空则不传",
            "order": 6,
        },
    )
    negative_prompt: str = Field(
        default="",
        description="Google 反向提示词",
        json_schema_extra={
            "label": "反向提示词",
            "hint": "Imagen/edit_image 路径支持 negative_prompt；Gemini generateContent 图片模型可能忽略",
            "input_type": "textarea",
            "order": 7,
        },
    )
    seed: int = Field(
        default=-1,
        description="Google 随机种子。负数表示不传",
        json_schema_extra={
            "label": "随机种子",
            "hint": "非负整数会传入 seed；仅模型/接口支持时生效。",
            "order": 8,
        },
    )
    guidance_scale: float = Field(
        default=0.0,
        description="Google 提示词引导强度。",
        json_schema_extra={
            "label": "引导强度",
            "hint": "大于 0 时传入 guidance_scale；仅模型/接口支持时生效",
            "order": 9,
        },
    )
    add_watermark: bool = Field(
        default=False,
        description="Google 是否添加水印",
        json_schema_extra={
            "label": "添加水印",
            "hint": "仅在 SDK/模型支持 add_watermark 时生效",
            "order": 10,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="Google 图片配置额外参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；仅 SDK 当前配置类支持的字段会被传入",
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


class ZhipuModelConfig(PluginConfigBase):
    """智谱模型配置。"""

    __ui_label__ = "智谱配置"
    __ui_order__ = 4

    base_url: str = Field(
        default="https://open.bigmodel.cn",
        description="智谱服务基础 URL。请填写根地址，不要带具体接口路径",
        json_schema_extra={
            "label": "智谱基础 URL",
            "hint": "智谱服务基础 URL。请填写根地址，不要带具体接口路径",
            "order": 0,
        },
    )
    api_key: str = Field(
        default="your-zhipu-api-key",
        description="智谱 API 密钥",
        json_schema_extra={
            "label": "智谱 API 密钥",
            "hint": "填入智谱开放平台的 API 密钥",
            "input_type": "password",
            "order": 1,
        },
    )
    models: list[str] = Field(
        default=["glm-image"],
        description="智谱可用图片模型列表（仅支持文生图）",
        json_schema_extra={
            "label": "智谱模型列表",
            "hint": "这里填写属于智谱图像生成接口的模型；当前仅支持文生图，不支持图生图编辑",
            "order": 2,
        },
    )
    size: str = Field(
        default="1280x1280",
        description="智谱图像生成分辨率。",
        json_schema_extra={
            "label": "分辨率",
            "hint": "常见值：1024x1024、1280x1280、768x1344、1344x768；以官方/模型实际支持为准",
            "order": 3,
        },
    )
    response_format: str = Field(
        default="url",
        description="智谱图片响应格式。",
        json_schema_extra={
            "label": "响应格式",
            "hint": "常见值：url、b64_json；留空则不传",
            "order": 4,
        },
    )
    user: str = Field(
        default="",
        description="智谱终端用户标识",
        json_schema_extra={
            "label": "用户标识",
            "hint": "可选，用于上游安全审计；留空则不传",
            "order": 5,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="智谱图像生成额外 JSON 参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；用于兼容新模型参数",
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


class AliyunModelConfig(PluginConfigBase):
    """阿里百炼模型配置。"""

    __ui_label__ = "阿里百炼配置"
    __ui_order__ = 5

    base_url: str = Field(
        default="https://dashscope.aliyuncs.com",
        description="阿里百炼服务基础 URL。北京地域使用 dashscope.aliyuncs.com，新加坡地域使用 dashscope-intl.aliyuncs.com",
        json_schema_extra={
            "label": "阿里百炼基础 URL",
            "hint": "填写百炼根地址，不要带具体接口路径；北京地域默认 https://dashscope.aliyuncs.com",
            "order": 0,
        },
    )
    api_key: str = Field(
        default="your-aliyun-api-key",
        description="阿里百炼 API 密钥",
        json_schema_extra={
            "label": "阿里百炼 API 密钥",
            "hint": "填入阿里百炼（DashScope / Model Studio）的 API 密钥",
            "input_type": "password",
            "order": 1,
        },
    )
    models: list[str] = Field(
        default=[
            "qwen-image-2.0",
            "qwen-image-2.0-pro",
            "qwen-image-max",
            "qwen-image-plus",
            "qwen-image-edit-max",
            "qwen-image-edit-plus",
        ],
        description="阿里百炼可用图片模型列表（支持文生图与图像编辑）",
        json_schema_extra={
            "label": "阿里百炼模型列表",
            "hint": "这里填写属于阿里百炼图片接口的模型，例如 qwen-image-2.0、qwen-image-2.0-pro、qwen-image-edit-max",
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
    negative_prompt: str = Field(
        default="低分辨率，低画质，肢体畸形，手指畸形，文字模糊，构图混乱，过度光滑，画面具有 AI 感",
        description="阿里百炼反向提示词，用于描述不希望在图像中出现的内容",
        json_schema_extra={
            "label": "反向提示词",
            "hint": "留空则不传 negative_prompt；百炼限制长度不超过 500 个字符",
            "input_type": "textarea",
            "order": 5,
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
    watermark: bool = Field(
        default=False,
        description="是否添加阿里百炼水印",
        json_schema_extra={
            "label": "添加水印",
            "hint": "关闭时请求参数 watermark=false",
            "order": 7,
        },
    )
    max_images: int = Field(
        default=1,
        description="单次阿里百炼请求生成图片数量上限",
        json_schema_extra={
            "label": "单次图片数量",
            "hint": "插件当前默认请求 1 张；这里限制工具未来传入 n 时的最大值",
            "order": 8,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="阿里百炼 parameters 额外参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；会合并到 parameters",
            "order": 9,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用阿里百炼提供商前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "开启后会调用 MaiBot replyer 模型，将非英文提示词改写为英文单词和 NovelAI 友好的英文标点。使用 NovelAI/StableDiffusion 兼容模型时必须开启，否则可能生图失败",
            "order": 10,
        },
    )


class SiliconFlowModelConfig(PluginConfigBase):
    """硅基流动模型配置。"""

    __ui_label__ = "硅基流动配置"
    __ui_order__ = 6

    base_url: str = Field(
        default="https://api.siliconflow.cn",
        description="硅基流动服务基础 URL。请填写根地址，不要带 /v1",
        json_schema_extra={
            "label": "硅基流动基础 URL",
            "hint": "官方默认 https://api.siliconflow.cn；兼容网关可按实际根地址填写",
            "order": 0,
        },
    )
    api_key: str = Field(
        default="your-siliconflow-api-key",
        description="硅基流动 API 密钥",
        json_schema_extra={
            "label": "硅基流动 API 密钥",
            "hint": "填入硅基流动 API 密钥",
            "input_type": "password",
            "order": 1,
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
            "order": 2,
        },
    )
    image_size: str = Field(
        default="1024x1024",
        description="硅基流动图片尺寸。",
        json_schema_extra={
            "label": "图片尺寸",
            "hint": "官方参数 image_size；可填 1024x1024 等固定尺寸，或模型支持的枚举值",
            "order": 3,
        },
    )
    model_size_overrides: list[str] = Field(
        default=[],
        description="硅基流动按模型覆盖图片尺寸。每项格式为 模型名=宽x高",
        json_schema_extra={
            "label": "按模型覆盖图片尺寸",
            "hint": "每行填写一个 模型名=宽x高，例如 Kwai-Kolors/Kolors=1024x1024。",
            "order": 4,
        },
    )
    batch_size: int = Field(
        default=1,
        description="硅基流动单次生成图片数量。",
        json_schema_extra={
            "label": "生成数量",
            "hint": "会写入 batch_size；插件当前默认请求 1 张，可按平台模型支持调整",
            "order": 5,
        },
    )
    seed: int = Field(
        default=-1,
        description="硅基流动随机种子。负数表示不传",
        json_schema_extra={
            "label": "随机种子",
            "hint": "负数表示不固定；非负整数会传入 seed",
            "order": 6,
        },
    )
    num_inference_steps: int = Field(
        default=20,
        description="硅基流动采样步数。",
        json_schema_extra={
            "label": "采样步数",
            "hint": "常见值 20 到 50；留 0 或负数则不传。",
            "order": 7,
        },
    )
    guidance_scale: float = Field(
        default=7.5,
        description="硅基流动提示词引导强度。",
        json_schema_extra={
            "label": "引导强度",
            "hint": "常见值 3 到 12；0 或负数则不传",
            "order": 8,
        },
    )
    negative_prompt: str = Field(
        default="",
        description="硅基流动反向提示词",
        json_schema_extra={
            "label": "反向提示词",
            "hint": "留空则不传 negative_prompt",
            "input_type": "textarea",
            "order": 9,
        },
    )
    output_format: str = Field(
        default="png",
        description="硅基流动输出图片格式。",
        json_schema_extra={
            "label": "输出格式",
            "hint": "官方参数 output_format；常见值 png、jpeg、webp",
            "order": 10,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="硅基流动图片生成额外 JSON 参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；用于兼容平台新增参数",
            "order": 11,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用硅基流动提供商前将提示词改写为英文。",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "使用 Stable Diffusion 类模型时建议开启。",
            "order": 12,
        },
    )


class NovelAIModelConfig(PluginConfigBase):
    """NovelAI / NovelAPI 模型配置。"""

    __ui_label__ = "NovelAI / NovelAPI 配置"
    __ui_order__ = 7

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
    models: list[str] = Field(
        default=[
            "nai-diffusion-4-full",
            "nai-diffusion-4-curated-preview",
            "nai-diffusion-3",
        ],
        description="NovelAI / NovelAPI 可用图片模型列表",
        json_schema_extra={
            "label": "NovelAI 模型列表",
            "hint": "这里填写属于 NovelAI 官方图片接口或 NovelAPI 网关的模型",
            "order": 2,
        },
    )
    width: int = Field(
        default=832,
        description="NovelAI 图片宽度。",
        json_schema_extra={
            "label": "宽度",
            "hint": "常用值 832、1024、1216 等；以模型实际支持为准。",
            "order": 3,
        },
    )
    height: int = Field(
        default=1216,
        description="NovelAI 图片高度。",
        json_schema_extra={
            "label": "高度",
            "hint": "常用值 832、1024、1216 等；以模型实际支持为准",
            "order": 4,
        },
    )
    model_size_overrides: list[str] = Field(
        default=[],
        description="NovelAI 按模型覆盖尺寸。每项格式为 模型名=宽x高。",
        json_schema_extra={
            "label": "按模型覆盖尺寸",
            "hint": "每行填写一个 模型名=宽x高，例如 nai-diffusion-3=832x1216",
            "order": 5,
        },
    )
    sampler: str = Field(
        default="k_euler_ancestral",
        description="NovelAI 采样器。",
        json_schema_extra={
            "label": "采样器",
            "hint": "常见值：k_euler_ancestral、k_euler、k_dpmpp_2m、ddim 等",
            "order": 6,
        },
    )
    steps: int = Field(
        default=28,
        description="NovelAI 采样步数。",
        json_schema_extra={
            "label": "采样步数",
            "hint": "常见值 20 到 40。",
            "order": 7,
        },
    )
    scale: float = Field(
        default=5.0,
        description="NovelAI Prompt Guidance / CFG Scale。",
        json_schema_extra={
            "label": "Prompt Guidance",
            "hint": "常见值 4 到 8，值越高越贴近提示词",
            "order": 8,
        },
    )
    seed: int = Field(
        default=-1,
        description="NovelAI 随机种子。负数表示随机。",
        json_schema_extra={
            "label": "随机种子",
            "hint": "负数会在本地生成随机种子；非负整数固定 seed",
            "order": 9,
        },
    )
    negative_prompt: str = Field(
        default="lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry",
        description="NovelAI 反向提示词",
        json_schema_extra={
            "label": "反向提示词",
            "hint": "会写入 uc；留空则不传",
            "input_type": "textarea",
            "order": 10,
        },
    )
    uc_preset: int = Field(
        default=0,
        description="NovelAI undesired content 预设",
        json_schema_extra={
            "label": "UC 预设",
            "hint": "常见值 0 到 3；不同模型含义可能不同",
            "order": 11,
        },
    )
    quality_toggle: bool = Field(
        default=True,
        description="NovelAI 是否启用质量标签增强",
        json_schema_extra={
            "label": "质量增强",
            "hint": "对应 qualityToggle。",
            "order": 12,
        },
    )
    sm: bool = Field(
        default=False,
        description="NovelAI smea 开关",
        json_schema_extra={
            "label": "SMEA",
            "hint": "对应 sm。",
            "order": 13,
        },
    )
    sm_dyn: bool = Field(
        default=False,
        description="NovelAI dynamic smea 开关",
        json_schema_extra={
            "label": "动态 SMEA",
            "hint": "对应 sm_dyn。",
            "order": 14,
        },
    )
    noise_schedule: str = Field(
        default="native",
        description="NovelAI noise schedule",
        json_schema_extra={
            "label": "噪声调度",
            "hint": "常见值 native、karras、exponential、polyexponential；留空则不传",
            "order": 15,
        },
    )
    img2img_strength: float = Field(
        default=0.6,
        description="NovelAI 图生图参考图强度",
        json_schema_extra={
            "label": "图生图强度",
            "hint": "仅 edit_image 使用，值越高越接近原图；常见值 0.4 到 0.8",
            "order": 16,
        },
    )
    img2img_noise: float = Field(
        default=0.1,
        description="NovelAI 图生图噪声强度",
        json_schema_extra={
            "label": "图生图噪声",
            "hint": "仅 edit_image 使用；常见值 0 到 0.3",
            "order": 17,
        },
    )
    max_images: int = Field(
        default=1,
        description="单次 NovelAI 请求生成图片数量上限",
        json_schema_extra={
            "label": "单次图片数量",
            "hint": "会写入 n_samples，建议 1 到 4",
            "order": 18,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="NovelAI parameters 额外参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；会合并到 parameters",
            "order": 19,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=True,
        description="是否在调用 NovelAI / NovelAPI 提供商前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "NovelAI 标签体系建议开启，避免中文提示词导致效果差或请求失败",
            "order": 20,
        },
    )


class PromptModerationConfig(PluginConfigBase):
    """提示词审核配置。"""

    __ui_label__ = "提示词审核"
    __ui_order__ = 8

    enabled: bool = Field(
        default=False,
        description="是否启用提示词审核。启用后会调用 MaiBot 当前配置的 replyer 模型进行识别",
        json_schema_extra={
            "label": "启用提示词审核",
            "hint": "启用后，文生图和图生图的提示词会先交给 MaiBot 的 replyer 模型审核",
            "order": 0,
        },
    )
    review_prompt: str = Field(
        default=(
            "你是绘图提示词审核器。请判断下面的绘图提示词是否适合继续交给绘图模型生成\n"
            "审核要求：\n"
            "1. 如果提示词涉及明显违法、暴力犯罪、血腥猎奇、未成年人色情、仇恨歧视、现实人物色情深度伪造等高风险内容，必须拒绝\n"
            "2. 如果提示词内容普通、安全、可接受，则允许通过\n"
            "3. 你的回复必须严格使用以下格式，不要输出多余内容：\n"
            "结论：PASS 或 REJECT\n"
            "原因：一句简短中文说明\n"
            "\n"
            "待审核提示词：\n"
            "{user_prompt}"
        ),
        description="提示词审核时发送给 replyer 模型的审核提示模板，支持 {user_prompt} 占位符",
        json_schema_extra={
            "label": "提示词审核提示词",
            "hint": "支持 {user_prompt} 占位符；建议要求模型只返回 PASS 或 REJECT 及简短原因",
            "input_type": "textarea",
            "order": 1,
        },
    )


class ImageModerationConfig(PluginConfigBase):
    """生成图片审核配置。"""

    __ui_label__ = "生成图片审核"
    __ui_order__ = 9

    enabled: bool = Field(
        default=False,
        description="是否启用生成图片审核。启用后会调用 MaiBot 当前配置的 vlm 模型进行识别",
        json_schema_extra={
            "label": "启用生成图片审核",
            "hint": "启用后，生成完成的图片会先交给 MaiBot 的 vlm 模型审核，再决定是否发送",
            "order": 0,
        },
    )
    review_prompt: str = Field(
        default=(
            "你是绘图结果审核器。请审核这张图片是否适合直接发送给普通聊天场景\n"
            "审核要求：\n"
            "1. 如果图片包含明显违法、暴力犯罪、血腥猎奇、未成年人色情、仇恨歧视、现实人物色情深度伪造等高风险内容，必须拒绝。\n"
            "2. 如果图片内容普通、安全、可接受，则允许通过。\n"
            "3. 结合本次生成提示词一起判断。\n"
            "4. 你的回复必须严格使用以下格式，不要输出多余内容：\n"
            "结论：PASS 或 REJECT\n"
            "原因：一句简短中文说明\n"
            "\n"
            "本次生成提示词：\n"
            "{user_prompt}"
        ),
        description="生成图片审核时发送给 vlm 模型的审核提示模板，支持 {user_prompt} 占位符",
        json_schema_extra={
            "label": "生成图片审核提示词",
            "hint": "支持 {user_prompt} 占位符；建议要求模型只返回 PASS 或 REJECT 及简短原因",
            "input_type": "textarea",
            "order": 1,
        },
    )


class DrawpicConfig(PluginConfigBase):
    """插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    general: GeneralConfig = Field(default_factory=GeneralConfig)
    prompt_review: PromptModerationConfig = Field(default_factory=PromptModerationConfig)
    image_review: ImageModerationConfig = Field(default_factory=ImageModerationConfig)
    openai: OpenAIModelConfig = Field(default_factory=OpenAIModelConfig)
    google: GoogleModelConfig = Field(default_factory=GoogleModelConfig)
    zhipu: ZhipuModelConfig = Field(default_factory=ZhipuModelConfig)
    aliyun: AliyunModelConfig = Field(default_factory=AliyunModelConfig)
    siliconflow: SiliconFlowModelConfig = Field(default_factory=SiliconFlowModelConfig)
    novelai: NovelAIModelConfig = Field(default_factory=NovelAIModelConfig)
