from typing import Literal

from maibot_sdk import Field, PluginConfigBase


OpenAICompatibilityMode = Literal["auto", "images_api", "chat_completions", "novelai_images_api"]


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
        default="2.5.0",
        description="配置版本",
        json_schema_extra={
            "hint": "配置版本",
        },
    )


class GeneralModelConfig(PluginConfigBase):
    """通用模型配置。"""

    __ui_label__ = "通用模型配置"
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
    default_openai_compatibility_mode: OpenAICompatibilityMode = Field(
        default="auto",
        description="默认 OpenAI 兼容模式。仅在当前会话使用 OpenAI 系模型时生效。",
        json_schema_extra={
            "label": "默认 OpenAI 兼容模式",
            "hint": "支持 auto、images_api、chat_completions、novelai_images_api；通常建议使用 auto",
            "order": 1,
        },
    )
    request_timeout_seconds: int = Field(
        default=150,
        description="单次图片请求超时时间（秒），用于后台图片任务",
        json_schema_extra={
            "label": "图片请求超时",
            "hint": "单次图片请求超时时间（秒），建议设置为 120 到 300",
            "order": 2,
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
        default=["qwen-image-2.0"],
        description="阿里百炼可用图片模型列表（支持文生图与图像编辑）",
        json_schema_extra={
            "label": "阿里百炼模型列表",
            "hint": "这里填写属于阿里百炼图片接口的模型，例如 qwen-image-2.0、qwen-image-2.0-pro、qwen-image-edit",
            "order": 2,
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
    general: GeneralModelConfig = Field(default_factory=GeneralModelConfig)
    prompt_review: PromptModerationConfig = Field(default_factory=PromptModerationConfig)
    image_review: ImageModerationConfig = Field(default_factory=ImageModerationConfig)
    openai: OpenAIModelConfig = Field(default_factory=OpenAIModelConfig)
    google: GoogleModelConfig = Field(default_factory=GoogleModelConfig)
    zhipu: ZhipuModelConfig = Field(default_factory=ZhipuModelConfig)
    aliyun: AliyunModelConfig = Field(default_factory=AliyunModelConfig)
