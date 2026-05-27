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
        default="2.10.0",
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
        description="默认模型名称。插件会自动在阿里百炼、OpenAI、Google 与智谱模型列表中查找该模型。",
        json_schema_extra={
            "label": "默认模型",
            "hint": "默认模型名称。插件会自动在阿里百炼、OpenAI、Google 与智谱模型列表中查找该模型。",
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
        description="聊天命令返回形式，可选择图片或文本。",
        json_schema_extra={
            "label": "命令返回形式",
            "hint": "图片=使用粉色图片模板回复命令；文本=直接发送纯文本回复",
            "options": ["图片", "文本"],
            "order": 2,
        },
    )
    permission_enabled: bool = Field(
        default=True,
        description="是否启用权限管理。启用后，仅插件管理员可切换模型、切换兼容模式和修改用户次数。",
        json_schema_extra={
            "label": "启用权限管理",
            "hint": "启用后，模型切换、兼容模式切换和次数管理命令仅允许插件管理员使用",
            "order": 3,
        },
    )
    admin_user_ids: list[str] = Field(
        default=[],
        description="插件管理员用户 ID 列表，通常填写 QQ 号。",
        json_schema_extra={
            "label": "插件管理员列表",
            "hint": "填写允许管理模型、兼容模式和用户次数的用户 ID，通常为 QQ 号",
            "order": 4,
        },
    )
    quota_enabled: bool = Field(
        default=True,
        description="是否启用用户绘图次数管理。管理员不受次数限制。",
        json_schema_extra={
            "label": "启用用户次数管理",
            "hint": "启用后，普通用户每次绘图会消耗次数；管理员不受限制",
            "order": 5,
        },
    )
    quota_period: QuotaPeriodMode = Field(
        default="daily",
        description="用户次数重置周期：daily / weekly / monthly / once。",
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
        description="OpenAI 或 OpenAI 兼容服务基础 URL。手动接口填写根地址，不要带 /v1。",
        json_schema_extra={
            "label": "OpenAI 基础 URL",
            "hint": "OpenAI 或 OpenAI 兼容服务基础 URL。手动接口填写根地址，不要带 /v1。",
            "order": 0,
        },
    )
    api_key: str = Field(
        default="your-openai-api-key",
        description="OpenAI 或 OpenAI 兼容服务的 API 密钥",
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
            "hint": "支持 auto、images_api、chat_completions、novelai_images_api；通常建议使用 auto",
            "order": 3,
        },
    )


class GoogleModelConfig(PluginConfigBase):
    """Google 模型配置。"""

    __ui_label__ = "Google 配置"
    __ui_order__ = 3

    base_url: str = Field(
        default="https://generativelanguage.googleapis.com",
        description="Google Gemini 服务基础 URL。使用官方服务时可留空，使用兼容网关时按网关要求填写。",
        json_schema_extra={
            "label": "Google 基础 URL",
            "hint": "Google Gemini 服务基础 URL。使用官方服务时可留空，使用兼容网关时按网关要求填写。",
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


class ZhipuModelConfig(PluginConfigBase):
    """智谱模型配置。"""

    __ui_label__ = "智谱配置"
    __ui_order__ = 4

    base_url: str = Field(
        default="https://open.bigmodel.cn",
        description="智谱服务基础 URL。请填写根地址，不要带具体接口路径。",
        json_schema_extra={
            "label": "智谱基础 URL",
            "hint": "智谱服务基础 URL。请填写根地址，不要带具体接口路径。",
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


class AliyunModelConfig(PluginConfigBase):
    """阿里百炼模型配置。"""

    __ui_label__ = "阿里百炼配置"
    __ui_order__ = 5

    base_url: str = Field(
        default="https://dashscope.aliyuncs.com",
        description="阿里百炼服务基础 URL。北京地域使用 dashscope.aliyuncs.com，新加坡地域使用 dashscope-intl.aliyuncs.com。",
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
        description="阿里百炼图片默认分辨率。未在按模型覆盖分辨率中配置的模型会使用该值。",
        json_schema_extra={
            "label": "默认分辨率",
            "hint": "格式为 宽*高，例如 2048*2048。不同模型支持范围不同，建议优先通过按模型覆盖分辨率配置。",
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
        description="阿里百炼按模型覆盖分辨率。每项格式为 模型名=宽*高。",
        json_schema_extra={
            "label": "按模型覆盖分辨率",
            "hint": "每行填写一个 模型名=宽*高，例如 qwen-image-plus=1328*1328。qwen-image-2.0 系列支持自由宽高，总像素需在 512*512 至 2048*2048。",
            "order": 4,
        },
    )
    negative_prompt: str = Field(
        default="低分辨率，低画质，肢体畸形，手指畸形，文字模糊，构图混乱，过度光滑，画面具有 AI 感。",
        description="阿里百炼反向提示词，用于描述不希望在图像中出现的内容。",
        json_schema_extra={
            "label": "反向提示词",
            "hint": "留空则不传 negative_prompt；百炼限制长度不超过 500 个字符。",
            "input_type": "textarea",
            "order": 5,
        },
    )
    prompt_extend: bool = Field(
        default=True,
        description="是否启用阿里百炼提示词智能改写。",
        json_schema_extra={
            "label": "启用提示词智能改写",
            "hint": "开启后百炼会优化正向提示词；不会修改反向提示词。",
            "order": 6,
        },
    )


class PromptModerationConfig(PluginConfigBase):
    """提示词审核配置。"""

    __ui_label__ = "提示词审核"
    __ui_order__ = 6

    enabled: bool = Field(
        default=False,
        description="是否启用提示词审核。启用后会调用 MaiBot 当前配置的 replyer 模型进行识别。",
        json_schema_extra={
            "label": "启用提示词审核",
            "hint": "启用后，文生图和图生图的提示词会先交给 MaiBot 的 replyer 模型审核",
            "order": 0,
        },
    )
    review_prompt: str = Field(
        default=(
            "你是绘图提示词审核器。请判断下面的绘图提示词是否适合继续交给绘图模型生成。\n"
            "审核要求：\n"
            "1. 如果提示词涉及明显违法、暴力犯罪、血腥猎奇、未成年人色情、仇恨歧视、现实人物色情深度伪造等高风险内容，必须拒绝。\n"
            "2. 如果提示词内容普通、安全、可接受，则允许通过。\n"
            "3. 你的回复必须严格使用以下格式，不要输出多余内容：\n"
            "结论：PASS 或 REJECT\n"
            "原因：一句简短中文说明\n"
            "\n"
            "待审核提示词：\n"
            "{user_prompt}"
        ),
        description="提示词审核时发送给 replyer 模型的审核提示模板，支持 {user_prompt} 占位符。",
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
    __ui_order__ = 7

    enabled: bool = Field(
        default=False,
        description="是否启用生成图片审核。启用后会调用 MaiBot 当前配置的 vlm 模型进行识别。",
        json_schema_extra={
            "label": "启用生成图片审核",
            "hint": "启用后，生成完成的图片会先交给 MaiBot 的 vlm 模型审核，再决定是否发送",
            "order": 0,
        },
    )
    review_prompt: str = Field(
        default=(
            "你是绘图结果审核器。请审核这张图片是否适合直接发送给普通聊天场景。\n"
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
        description="生成图片审核时发送给 vlm 模型的审核提示模板，支持 {user_prompt} 占位符。",
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
