from collections.abc import Mapping
from typing import Any, Literal

from maibot_sdk import Field, PluginConfigBase


OpenAICompatibilityMode = Literal["auto", "images_api", "chat_completions", "novelai_images_api"]
NovelAIModelId = Literal[
    "nai-diffusion-4-5-full",
    "nai-diffusion-4-5-curated",
    "nai-diffusion-4-full",
    "nai-diffusion-4-curated-preview",
    "nai-diffusion-3",
    "nai-diffusion-furry-3",
]
QuotaPeriodMode = Literal["daily", "weekly", "monthly", "once"]
ProxyScheme = Literal["http", "https"]
CommandReplyMode = Literal["图片", "文本"]
ComfyUIPromptMode = Literal["single_prompt", "positive_negative"]


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
        default="2.19.0",
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
        description="默认首选模型名称。插件会自动在各平台模型列表中查找该模型",
        json_schema_extra={
            "label": "默认首选模型",
            "hint": "默认首选模型名称。插件会自动在各平台模型列表中查找该模型",
            "order": 0,
        },
    )
    fallback_model: str = Field(
        default="",
        description="生图备选模型名称。首选模型调用失败或未返回图片时，后台任务会自动尝试该模型；留空表示不启用",
        json_schema_extra={
            "label": "生图备选模型",
            "hint": "首选模型调用失败或未返回图片时自动尝试；需填写已在下方任一平台模型列表中配置的模型名，留空表示不启用",
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
    command_reply_mode: CommandReplyMode = Field(
        default="图片",
        description="聊天命令返回形式，可选择图片或文本",
        json_schema_extra={
            "label": "命令返回形式",
            "hint": "图片=使用粉色图片模板回复命令；文本=直接发送纯文本回复",
            "options": ["图片", "文本"],
            "order": 3,
        },
    )
    permission_enabled: bool = Field(
        default=True,
        description="是否启用权限管理。启用后，仅插件管理员可设置首选模型、切换兼容模式和修改用户次数",
        json_schema_extra={
            "label": "启用权限管理",
            "hint": "启用后，首选模型设置、兼容模式切换和次数管理命令仅允许插件管理员使用",
            "order": 4,
        },
    )
    admin_user_ids: list[str] = Field(
        default=[],
        description="插件管理员用户 ID 列表，通常填写 QQ 号",
        json_schema_extra={
            "label": "插件管理员列表",
            "hint": "填写允许管理模型、兼容模式和用户次数的用户 ID，通常为 QQ 号",
            "order": 5,
        },
    )
    group_quota_enabled: bool = Field(
        default=True,
        description="是否启用群聊绘图次数管理。管理员不受次数限制",
        json_schema_extra={
            "label": "启用群聊次数管理",
            "hint": "启用后，群聊每次绘图会消耗该群剩余次数；管理员不受限制",
            "order": 6,
        },
    )
    group_quota_period: QuotaPeriodMode = Field(
        default="daily",
        description="群聊次数重置周期：daily / weekly / monthly / once",
        json_schema_extra={
            "label": "群聊次数周期",
            "hint": "daily=每日，weekly=每周，monthly=每月，once=一次性不自动重置",
            "order": 7,
        },
    )
    group_default_quota: int = Field(
        default=5,
        description="群聊在当前周期内默认可用绘图次数。",
        json_schema_extra={
            "label": "群聊默认可用次数",
            "hint": "群聊在所选周期内默认可用的绘图次数",
            "order": 8,
        },
    )
    private_quota_enabled: bool = Field(
        default=True,
        description="是否启用私聊绘图次数管理。管理员不受次数限制",
        json_schema_extra={
            "label": "启用私聊次数管理",
            "hint": "启用后，私聊每次绘图会消耗该用户剩余次数；管理员不受限制",
            "order": 9,
        },
    )
    private_quota_period: QuotaPeriodMode = Field(
        default="daily",
        description="私聊次数重置周期：daily / weekly / monthly / once",
        json_schema_extra={
            "label": "私聊次数周期",
            "hint": "daily=每日，weekly=每周，monthly=每月，once=一次性不自动重置",
            "order": 10,
        },
    )
    private_default_quota: int = Field(
        default=5,
        description="私聊用户在当前周期内默认可用绘图次数。",
        json_schema_extra={
            "label": "私聊默认可用次数",
            "hint": "私聊用户在所选周期内默认可用的绘图次数",
            "order": 11,
        },
    )
    image_edit_unsupported_models: list[str] = Field(
        default=[],
        description="额外标记为不支持图生图的模型名列表。命中后强制图生图和 edit_image 会提前拒绝提交任务",
        json_schema_extra={
            "label": "不支持图生图模型",
            "hint": "每行一个模型名。用于标记平台列表中存在但只能文生图的模型，命中后不会创建后台图生图任务",
            "order": 12,
        },
    )
    prompt_review_enabled: bool = Field(
        default=False,
        description="是否启用提示词审核。启用后会调用 MaiBot 当前配置的 replyer 模型进行识别",
        json_schema_extra={
            "label": "启用提示词审核",
            "hint": "启用后，文生图和图生图的提示词会先交给 MaiBot 的 replyer 模型审核",
            "order": 13,
        },
    )
    prompt_review_prompt: str = Field(
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
            "{user_prompt}\n"
        ),
        description="提示词审核模板，支持 {user_prompt} 占位符",
        json_schema_extra={
            "label": "提示词审核模板",
            "hint": "支持 {user_prompt} 占位符；建议要求模型只返回 PASS 或 REJECT 及简短原因",
            "x-widget": "textarea",
            "rows": 8,
            "order": 14,
        },
    )
    image_review_enabled: bool = Field(
        default=False,
        description="是否启用生成图片审核。启用后会调用 MaiBot 当前配置的 vlm 模型进行识别",
        json_schema_extra={
            "label": "启用生成图片审核",
            "hint": "启用后，生成完成的图片会先交给 MaiBot 的 vlm 模型审核，再决定是否发送",
            "order": 15,
        },
    )
    image_review_prompt: str = Field(
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
            "{user_prompt}\n"
        ),
        description="生成图片审核模板，支持 {user_prompt} 占位符",
        json_schema_extra={
            "label": "生成图片审核模板",
            "hint": "支持 {user_prompt} 占位符；建议要求模型只返回 PASS 或 REJECT 及简短原因",
            "x-widget": "textarea",
            "rows": 8,
            "order": 16,
        },
    )


class ProxyConfig(PluginConfigBase):
    """图片提供商的全局代理配置。"""

    __ui_label__ = "网络代理"
    __ui_order__ = 2

    enabled: bool = Field(
        default=False,
        description="是否为图片提供商启用全局 HTTP 代理。",
        json_schema_extra={
            "label": "启用全局代理",
            "hint": "开启后，除已配置绕过的国内提供商外，所有图片请求都会使用代理",
            "order": 0,
        },
    )
    use_system_proxy: bool = Field(
        default=True,
        description="是否读取系统环境变量中的 HTTP/HTTPS 代理。",
        json_schema_extra={
            "label": "使用系统代理",
            "hint": "开启后读取 HTTP_PROXY、HTTPS_PROXY 和 NO_PROXY；关闭后使用下方手动代理地址",
            "order": 1,
        },
    )
    scheme: ProxyScheme = Field(
        default="http",
        description="手动代理使用的协议。",
        json_schema_extra={
            "label": "手动代理协议",
            "hint": "仅支持 HTTP 或 HTTPS 代理；使用系统代理时忽略",
            "options": ["http", "https"],
            "order": 2,
        },
    )
    host: str = Field(
        default="127.0.0.1",
        description="手动代理 Host。",
        json_schema_extra={
            "label": "手动代理 Host",
            "hint": "例如 127.0.0.1、localhost 或代理服务器域名；使用系统代理时忽略",
            "order": 3,
        },
    )
    port: int = Field(
        default=7890,
        ge=1,
        le=65535,
        description="手动代理端口。",
        json_schema_extra={
            "label": "手动代理端口",
            "hint": "例如 7890；使用系统代理时忽略",
            "order": 4,
        },
    )
    username: str = Field(
        default="",
        description="手动代理认证用户名。",
        json_schema_extra={
            "label": "代理用户名",
            "hint": "代理无需认证时留空；使用系统代理时忽略",
            "order": 5,
        },
    )
    password: str = Field(
        default="",
        description="手动代理认证密码。",
        json_schema_extra={
            "label": "代理密码",
            "hint": "代理无需认证时留空；使用系统代理时忽略",
            "input_type": "password",
            "order": 6,
        },
    )
    bypass_china_providers: bool = Field(
        default=True,
        description="是否让阿里云、火山引擎和硅基流动绕过全局代理。",
        json_schema_extra={
            "label": "国内提供商绕过代理",
            "hint": "开启后，阿里云、火山引擎、硅基流动直连；其他提供商仍按全局代理设置请求",
            "order": 7,
        },
    )


class OpenAICompatibleInstanceConfig(PluginConfigBase):
    """OpenAI 兼容接口实例配置。"""

    # 必填项：缺一项实例就无法正常调用
    enabled: bool = Field(
        default=True,
        description="是否启用该 OpenAI 兼容接口实例",
        json_schema_extra={
            "label": "启用",
            "order": 0,
        },
    )
    name: str = Field(
        default="openai-compatible",
        description="实例名称，仅用于菜单和日志中区分不同中转站",
        json_schema_extra={
            "label": "实例名称",
            "placeholder": "例如 platform-1、newapi-1",
            "order": 1,
        },
    )
    base_url: str = Field(
        default="https://api.openai.com",
        description="OpenAI 兼容服务基础 URL。可填写根地址，粘贴带 /v1 的地址时插件会自动兼容",
        json_schema_extra={
            "label": "基础 URL",
            "placeholder": "https://api.example.com",
            "order": 2,
        },
    )
    api_key: str = Field(
        default="your-openai-compatible-api-key",
        description="OpenAI 兼容服务的 API 密钥",
        json_schema_extra={
            "label": "API 密钥",
            "input_type": "password",
            "placeholder": "sk-...",
            "order": 3,
        },
    )
    models: str = Field(
        default="gpt-image-2",
        description="该实例可用模型。WebUI 对象列表单项内只能填写单行文本，多个模型可用英文逗号、中文逗号或分号分隔；需要同一上游模型走多个中转时使用 显示名=上游模型名",
        json_schema_extra={
            "label": "模型列表",
            "input_type": "textarea",
            "x-widget": "textarea",
            "rows": 3,
            "placeholder": "gpt-image-2, platform-gpt=gpt-image-2",
            "hint": "WebUI 内为单行输入，多个模型用 , 或 ， 分隔；TOML 源代码模式可换行",
            "order": 4,
        },
    )

    # 常用项：影响调用方式与默认输出，多数场景需要关注
    default_openai_compatibility_mode: str = Field(
        default="auto",
        description="该实例默认 OpenAI 兼容模式",
        json_schema_extra={
            "label": "兼容模式",
            "placeholder": "auto / images_api / chat_completions / novelai_images_api",
            "order": 5,
        },
    )
    default_size: str = Field(
        default="1024x1024",
        description="该实例默认分辨率",
        json_schema_extra={
            "label": "默认分辨率",
            "placeholder": "1024x1024",
            "order": 6,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用该实例前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "使用 Stable Diffusion / NovelAI 兼容模型时建议开启，避免中文提示词导致效果差或请求失败",
            "order": 7,
        },
    )

    # 细化项：按需填写，覆盖默认行为
    model_size_overrides: str = Field(
        default="",
        description="该实例按模型覆盖分辨率。WebUI 对象列表单项内只能填写单行文本，多条可用英文逗号、中文逗号或分号分隔，每条格式为 模型名=宽x高",
        json_schema_extra={
            "label": "按模型覆盖分辨率",
            "input_type": "textarea",
            "x-widget": "textarea",
            "rows": 3,
            "placeholder": "gpt-image-2=1024x1024, gemini-image=1536x1024",
            "hint": "WebUI 内为单行输入，多条用 , 或 ， 分隔；TOML 源代码模式可换行",
            "order": 8,
        },
    )
    max_images: int = Field(
        default=1,
        description="单次 OpenAI 请求生成图片数量上限",
        json_schema_extra={
            "label": "单次图片数量",
            "order": 9,
        },
    )
    quality: str = Field(
        default="",
        description="OpenAI Images API 质量参数",
        json_schema_extra={
            "label": "质量",
            "placeholder": "auto / low / medium / high",
            "order": 10,
        },
    )

    # 高级项：OpenAI Images API 细节参数，多数中转不需要
    response_format: str = Field(
        default="",
        description="OpenAI Images API 响应格式",
        json_schema_extra={
            "label": "响应格式",
            "placeholder": "b64_json / url",
            "order": 11,
        },
    )
    output_format: str = Field(
        default="",
        description="OpenAI Images API 输出图片格式",
        json_schema_extra={
            "label": "输出格式",
            "placeholder": "png / jpeg / webp",
            "order": 12,
        },
    )
    background: str = Field(
        default="",
        description="OpenAI Images API 背景参数",
        json_schema_extra={
            "label": "背景",
            "placeholder": "transparent / opaque / auto",
            "order": 13,
        },
    )
    moderation: str = Field(
        default="",
        description="OpenAI Images API 审核强度参数",
        json_schema_extra={
            "label": "审核强度",
            "placeholder": "auto / low",
            "order": 14,
        },
    )

    # 扩展项：兼容中转自定义字段
    extra_parameters: str = Field(
        default="",
        description="OpenAI 兼容接口额外 JSON 参数。WebUI 对象列表单项内只能填写单行文本，多条可用英文逗号、中文逗号或分号分隔，每条格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "input_type": "textarea",
            "x-widget": "textarea",
            "rows": 3,
            "placeholder": "custom_field=true, extra_option=auto",
            "hint": "WebUI 内为单行输入，多条用 , 或 ， 分隔；TOML 源代码模式可换行",
            "order": 15,
        },
    )


class OpenAIModelConfig(PluginConfigBase):
    """OpenAI 模型配置。"""

    __ui_label__ = "OpenAI 配置"
    __ui_order__ = 3

    enabled: bool = Field(
        default=True,
        description="是否启用本节主 OpenAI 配置。关闭后不影响下方额外 OpenAI 兼容实例",
        json_schema_extra={
            "label": "启用主 OpenAI 配置",
            "hint": "关闭后，本节 base_url/api_key/models 不参与模型路由；下方额外实例仍可单独启用",
            "order": -1,
        },
    )
    base_url: str = Field(
        default="https://api.openai.com",
        description="OpenAI兼容服务基础 URL。可填写根地址，粘贴带 /v1 的地址时插件会自动兼容",
        json_schema_extra={
            "label": "OpenAI 基础 URL",
            "hint": "OpenAI兼容服务基础 URL。建议填写根地址；如果粘贴了带 /v1 的地址，插件会自动去重处理",
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
    instances: list[OpenAICompatibleInstanceConfig] = Field(
        default_factory=list,
        description="额外 OpenAI 兼容接口实例列表",
        json_schema_extra={
            "label": "额外 OpenAI 兼容实例",
            "hint": "用于同时接入多个 OpenAI 兼容中转站。模型可写 显示名=上游模型名，避免多个实例使用同名模型时无法区分",
            "order": 14,
        },
    )


class GoogleModelConfig(PluginConfigBase):
    """Google 模型配置。"""

    __ui_label__ = "Google 配置"
    __ui_order__ = 4

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
    __ui_order__ = 5

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
        description="智谱 API 密钥",
        json_schema_extra={
            "label": "智谱 API 密钥",
            "hint": "填入智谱开放平台的 API 密钥",
            "input_type": "password",
            "order": 0,
        },
    )
    models: list[str] = Field(
        default=["glm-image"],
        description="智谱可用图片模型列表（仅支持文生图）",
        json_schema_extra={
            "label": "智谱模型列表",
            "hint": "这里填写属于智谱图像生成接口的模型；当前仅支持文生图，不支持图生图编辑",
            "order": 1,
        },
    )
    size: str = Field(
        default="1280x1280",
        description="智谱图像生成分辨率。",
        json_schema_extra={
            "label": "分辨率",
            "hint": "常见值：1024x1024、1280x1280、768x1344、1344x768；以官方/模型实际支持为准",
            "order": 2,
        },
    )
    response_format: str = Field(
        default="url",
        description="智谱图片响应格式。",
        json_schema_extra={
            "label": "响应格式",
            "hint": "常见值：url、b64_json；留空则不传",
            "order": 3,
        },
    )
    user: str = Field(
        default="",
        description="智谱终端用户标识",
        json_schema_extra={
            "label": "用户标识",
            "hint": "可选，用于上游安全审计；留空则不传",
            "order": 4,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="智谱图像生成额外 JSON 参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；用于兼容新模型参数",
            "order": 5,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用智谱提供商前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "开启后会调用 MaiBot replyer 模型，将非英文提示词改写为英文单词和 NovelAI 友好的英文标点。使用 NovelAI/StableDiffusion 兼容模型时必须开启，否则可能生图失败",
            "order": 6,
        },
    )


class AliyunModelConfig(PluginConfigBase):
    """阿里百炼模型配置。"""

    __ui_label__ = "阿里百炼配置"
    __ui_order__ = 6

    enabled: bool = Field(
        default=True,
        description="是否启用阿里百炼平台",
        json_schema_extra={
            "label": "启用阿里百炼平台",
            "hint": "关闭后，本节模型不会出现在可用模型列表，也不会参与路由",
            "order": -1,
        },
    )
    api_key: str = Field(
        default="your-aliyun-api-key",
        description="阿里百炼 API 密钥",
        json_schema_extra={
            "label": "阿里百炼 API 密钥",
            "hint": "填入阿里百炼（DashScope / Model Studio）的 API 密钥",
            "input_type": "password",
            "order": 0,
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
            "order": 1,
        },
    )
    default_size: str = Field(
        default="2048*2048",
        description="阿里百炼图片默认分辨率。未在按模型覆盖分辨率中配置的模型会使用该值",
        json_schema_extra={
            "label": "默认分辨率",
            "hint": "格式为 宽*高，例如 2048*2048。不同模型支持范围不同，建议优先通过按模型覆盖分辨率配置",
            "order": 2,
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
            "order": 3,
        },
    )
    negative_prompt: str = Field(
        default="低分辨率，低画质，肢体畸形，手指畸形，文字模糊，构图混乱，过度光滑，画面具有 AI 感",
        description="阿里百炼反向提示词，用于描述不希望在图像中出现的内容",
        json_schema_extra={
            "label": "反向提示词",
            "hint": "留空则不传 negative_prompt；百炼限制长度不超过 500 个字符",
            "input_type": "textarea",
            "order": 4,
        },
    )
    prompt_extend: bool = Field(
        default=True,
        description="是否启用阿里百炼提示词智能改写",
        json_schema_extra={
            "label": "启用提示词智能改写",
            "hint": "开启后百炼会优化正向提示词；不会修改反向提示词",
            "order": 5,
        },
    )
    watermark: bool = Field(
        default=False,
        description="是否添加阿里百炼水印",
        json_schema_extra={
            "label": "添加水印",
            "hint": "关闭时请求参数 watermark=false",
            "order": 6,
        },
    )
    max_images: int = Field(
        default=1,
        description="单次阿里百炼请求生成图片数量上限",
        json_schema_extra={
            "label": "单次图片数量",
            "hint": "插件当前默认请求 1 张；这里限制工具未来传入 n 时的最大值",
            "order": 7,
        },
    )
    extra_parameters: list[str] = Field(
        default=[],
        description="阿里百炼 parameters 额外参数。每项格式为 key=value",
        json_schema_extra={
            "label": "额外参数",
            "hint": "每行一个 key=value，值支持 true/false、数字或 JSON；会合并到 parameters",
            "order": 8,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用阿里百炼提供商前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "开启后会调用 MaiBot replyer 模型，将非英文提示词改写为英文单词和 NovelAI 友好的英文标点。使用 NovelAI/StableDiffusion 兼容模型时必须开启，否则可能生图失败",
            "order": 9,
        },
    )


class VolcengineModelConfig(PluginConfigBase):
    """火山引擎方舟模型配置。"""

    __ui_label__ = "火山引擎配置"
    __ui_order__ = 7

    enabled: bool = Field(
        default=True,
        description="是否启用火山引擎平台",
        json_schema_extra={
            "label": "启用火山引擎平台",
            "hint": "关闭后，本节模型不会出现在可用模型列表，也不会参与路由",
            "order": -1,
        },
    )
    api_key: str = Field(
        default="your-volcengine-api-key",
        description="火山引擎方舟 API Key",
        json_schema_extra={
            "label": "火山引擎 API Key",
            "hint": "填入火山方舟 API Key。接口地址由插件内置，不需要配置 BaseURL",
            "input_type": "password",
            "order": 0,
        },
    )
    models: list[str] = Field(
        default=[],
        description="火山引擎方舟图片模型列表（旧字段，已拆分为统一、文生图和图生图模型列表；留空时自动兼容）",
        json_schema_extra={
            "label": "火山引擎模型列表（旧）",
            "hint": "已拆分为统一模型、文生图模型和图生图模型；填写下方任一新字段后本字段被忽略",
            "order": 1,
        },
    )
    unified_models: list[str] = Field(
        default=[],
        description="火山引擎同时支持文生图和图生图的统一模型列表",
        json_schema_extra={
            "label": "统一模型列表",
            "hint": "填写同时支持文生图和图生图的模型或 endpoint 名称。列表中的模型可直接作为会话首选模型，插件会按任务类型调用对应能力",
            "order": 2,
        },
    )
    t2i_models: list[str] = Field(
        default=["doubao-seedream-3-0-t2i"],
        description="火山引擎文生图模型列表，仅用于文生图任务",
        json_schema_extra={
            "label": "文生图模型列表",
            "hint": "填写火山方舟控制台中以 -t2i 结尾的即梦 AI / 豆包生图模型或 endpoint 名称",
            "order": 2,
        },
    )
    i2i_models: list[str] = Field(
        default=["doubao-seedream-3-0-i2i"],
        description="火山引擎图生图模型列表，仅用于图生图编辑任务",
        json_schema_extra={
            "label": "图生图模型列表",
            "hint": "填写火山方舟控制台中以 -i2i 结尾的即梦 AI / 豆包生图模型或 endpoint 名称；留空则该平台不支持图生图",
            "order": 3,
        },
    )
    default_size: str = Field(
        default="2048*2048",
        description="火山引擎图片默认分辨率",
        json_schema_extra={
            "label": "默认分辨率",
            "hint": "常见值：1024*1024、1328*1328、2048*2048；以模型实际支持为准",
            "order": 4,
        },
    )
    model_size_overrides: list[str] = Field(
        default=[],
        description="火山引擎按模型覆盖分辨率。每项格式为 模型名=宽*高",
        json_schema_extra={
            "label": "按模型覆盖分辨率",
            "hint": "每行填写一个 模型名=宽*高，例如 doubao-seedream-3-0-t2i=1024*1024",
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
    response_format: str = Field(
        default="url",
        description="火山引擎图片响应格式",
        json_schema_extra={
            "label": "响应格式",
            "hint": "常见值：url、b64_json；留空则不传",
            "order": 7,
        },
    )
    guidance_scale: float = Field(
        default=0.0,
        description="火山引擎提示词引导强度。0 表示不传",
        json_schema_extra={
            "label": "引导强度",
            "hint": "大于 0 时传入 guidance_scale；仅模型支持时生效",
            "order": 8,
        },
    )
    seed: int = Field(
        default=-1,
        description="火山引擎随机种子。负数表示不传",
        json_schema_extra={
            "label": "随机种子",
            "hint": "非负整数会传入 seed；仅模型支持时生效",
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
        description="单次火山引擎请求生成图片数量上限",
        json_schema_extra={
            "label": "单次图片数量",
            "hint": "插件当前默认请求 1 张；这里限制工具未来传入 n 时的最大值",
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


class SiliconFlowModelConfig(PluginConfigBase):
    """硅基流动模型配置。"""

    __ui_label__ = "硅基流动配置"
    __ui_order__ = 8

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
    batch_size: int = Field(
        default=1,
        description="硅基流动单次生成图片数量。",
        json_schema_extra={
            "label": "生成数量",
            "hint": "会写入 batch_size；插件当前默认请求 1 张，可按平台模型支持调整",
            "order": 4,
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
            "hint": "常见值 3 到 12；0 或负数则不传",
            "order": 7,
        },
    )
    negative_prompt: str = Field(
        default="",
        description="硅基流动反向提示词",
        json_schema_extra={
            "label": "反向提示词",
            "hint": "留空则不传 negative_prompt",
            "input_type": "textarea",
            "order": 8,
        },
    )
    output_format: str = Field(
        default="png",
        description="硅基流动输出图片格式。",
        json_schema_extra={
            "label": "输出格式",
            "hint": "官方参数 output_format；常见值 png、jpeg、webp",
            "order": 9,
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


class NovelAIModelConfig(PluginConfigBase):
    """NovelAI / NovelAPI 模型配置。"""

    __ui_label__ = "NovelAI / NovelAPI 配置"
    __ui_order__ = 9

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
    models: list[NovelAIModelId] = Field(
        default=[
            "nai-diffusion-4-5-full",
            "nai-diffusion-4-5-curated",
            "nai-diffusion-4-full",
            "nai-diffusion-4-curated-preview",
            "nai-diffusion-3",
            "nai-diffusion-furry-3",
        ],
        description="可多选的 NovelAI 官方图片模型列表。",
        json_schema_extra={
            "label": "NovelAI 模型列表",
            "hint": "仅提供 NovelAI 当前官方模型；可多选。NovelAPI 网关的扩展模型请填写下方自定义模型列表",
            "order": 2,
        },
    )
    custom_models: list[str] = Field(
        default=[],
        description="NovelAI / NovelAPI 自定义图片模型列表。",
        json_schema_extra={
            "label": "自定义模型列表",
            "hint": "用于 NovelAPI 网关或其他兼容服务的扩展模型；每行填写一个模型 ID，会与上方官方模型列表合并",
            "order": 3,
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
    negative_prompt: str = Field(
        default="lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry",
        description="NovelAI 反向提示词",
        json_schema_extra={
            "label": "反向提示词",
            "hint": "会写入 uc；留空则不传",
            "input_type": "textarea",
            "order": 11,
        },
    )
    uc_preset: int = Field(
        default=0,
        description="NovelAI undesired content 预设",
        json_schema_extra={
            "label": "UC 预设",
            "hint": "常见值 0 到 3；不同模型含义可能不同",
            "order": 12,
        },
    )
    quality_toggle: bool = Field(
        default=True,
        description="NovelAI 是否启用质量标签增强",
        json_schema_extra={
            "label": "质量增强",
            "hint": "对应 qualityToggle。",
            "order": 13,
        },
    )
    sm: bool = Field(
        default=False,
        description="NovelAI smea 开关",
        json_schema_extra={
            "label": "SMEA",
            "hint": "对应 sm。",
            "order": 14,
        },
    )
    sm_dyn: bool = Field(
        default=False,
        description="NovelAI dynamic smea 开关",
        json_schema_extra={
            "label": "动态 SMEA",
            "hint": "对应 sm_dyn。",
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
        description="NovelAI V4/V4.5 专用 noise schedule。",
        json_schema_extra={
            "label": "V4/V4.5 噪声调度",
            "hint": "V4/V4.5 默认使用 karras；留空则不传",
            "order": 17,
        },
    )
    img2img_strength: float = Field(
        default=0.6,
        description="NovelAI 图生图参考图强度",
        json_schema_extra={
            "label": "图生图强度",
            "hint": "仅 edit_image 使用，值越高越接近原图；常见值 0.4 到 0.8",
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


class ComfyUIModelConfig(PluginConfigBase):
    """ComfyUI 本地工作流配置。"""

    __ui_label__ = "ComfyUI 配置"
    __ui_order__ = 10

    enabled: bool = Field(
        default=False,
        description="是否启用 ComfyUI 本地工作流提供商",
        json_schema_extra={
            "label": "启用 ComfyUI",
            "hint": "开启后，模型列表会提供统一模型名 comfyui；它会按任务类型自动选择文生图或图生图工作流",
            "order": -1,
        },
    )
    base_url: str = Field(
        default="http://127.0.0.1:8188",
        description="ComfyUI 服务地址",
        json_schema_extra={
            "label": "ComfyUI 地址",
            "hint": "默认 http://127.0.0.1:8188。可填写局域网地址，例如 http://192.168.1.14:8188；末尾 / 会自动忽略",
            "order": 0,
        },
    )
    t2i_workflow_path: str = Field(
        default="data/workflows/t2i.json",
        description="ComfyUI 文生图 API 工作流 JSON 路径",
        json_schema_extra={
            "label": "文生图工作流 JSON",
            "hint": "相对路径以插件目录为基准，默认 data/workflows/t2i.json；也可填写 Windows、Linux 或 macOS 的绝对路径。必须是 ComfyUI 导出的 API 格式 JSON",
            "order": 1,
        },
    )
    i2i_workflow_path: str = Field(
        default="data/workflows/i2i.json",
        description="ComfyUI 图生图 API 工作流 JSON 路径",
        json_schema_extra={
            "label": "图生图工作流 JSON",
            "hint": "相对路径以插件目录为基准，默认 data/workflows/i2i.json；也可填写 Windows、Linux 或 macOS 的绝对路径。必须含可读取上传图片的节点",
            "order": 2,
        },
    )
    t2i_prompt_mode: ComfyUIPromptMode = Field(
        default="positive_negative",
        description="文生图工作流的提示词写入方式",
        json_schema_extra={
            "label": "文生图提示词模式",
            "hint": "positive_negative=分别写入正向和反向节点；single_prompt=仅写入一个提示词节点",
            "options": ["positive_negative", "single_prompt"],
            "order": 3,
        },
    )
    i2i_prompt_mode: ComfyUIPromptMode = Field(
        default="positive_negative",
        description="图生图工作流的提示词写入方式",
        json_schema_extra={
            "label": "图生图提示词模式",
            "hint": "positive_negative=分别写入正向和反向节点；single_prompt=仅写入一个提示词节点",
            "options": ["positive_negative", "single_prompt"],
            "order": 4,
        },
    )
    prompt_input_name: str = Field(
        default="text",
        description="提示词节点的输入字段名",
        json_schema_extra={
            "label": "提示词输入字段名",
            "hint": "标准 CLIPTextEncode 节点为 text。若自定义节点输入字段不是 text，请填写实际字段名",
            "order": 5,
        },
    )
    t2i_prompt_node_id: str = Field(
        default="",
        description="文生图单提示词节点 ID，仅 single_prompt 模式使用",
        json_schema_extra={
            "label": "文生图单提示词节点 ID",
            "hint": "仅 t2i_prompt_mode=single_prompt 时必填。填写 API 工作流中的节点 ID，例如 3",
            "order": 6,
        },
    )
    t2i_positive_prompt_node_id: str = Field(
        default="",
        description="文生图正向提示词节点 ID，仅 positive_negative 模式使用",
        json_schema_extra={
            "label": "文生图正向提示词节点 ID",
            "hint": "仅 t2i_prompt_mode=positive_negative 时必填。填写 API 工作流中的节点 ID",
            "order": 7,
        },
    )
    t2i_negative_prompt_node_id: str = Field(
        default="",
        description="文生图反向提示词节点 ID，仅 positive_negative 模式使用",
        json_schema_extra={
            "label": "文生图反向提示词节点 ID",
            "hint": "仅 t2i_prompt_mode=positive_negative 时必填。填写 API 工作流中的节点 ID",
            "order": 8,
        },
    )
    t2i_negative_prompt: str = Field(
        default="",
        description="文生图反向提示词",
        json_schema_extra={
            "label": "文生图反向提示词",
            "hint": "仅正反提示词模式使用；内容会覆盖工作流中反向提示词节点的原始文本，留空表示传入空字符串",
            "input_type": "textarea",
            "order": 9,
        },
    )
    i2i_prompt_node_id: str = Field(
        default="",
        description="图生图单提示词节点 ID，仅 single_prompt 模式使用",
        json_schema_extra={
            "label": "图生图单提示词节点 ID",
            "hint": "仅 i2i_prompt_mode=single_prompt 时必填。填写 API 工作流中的节点 ID",
            "order": 10,
        },
    )
    i2i_positive_prompt_node_id: str = Field(
        default="",
        description="图生图正向提示词节点 ID，仅 positive_negative 模式使用",
        json_schema_extra={
            "label": "图生图正向提示词节点 ID",
            "hint": "仅 i2i_prompt_mode=positive_negative 时必填。填写 API 工作流中的节点 ID",
            "order": 11,
        },
    )
    i2i_negative_prompt_node_id: str = Field(
        default="",
        description="图生图反向提示词节点 ID，仅 positive_negative 模式使用",
        json_schema_extra={
            "label": "图生图反向提示词节点 ID",
            "hint": "仅 i2i_prompt_mode=positive_negative 时必填。填写 API 工作流中的节点 ID",
            "order": 12,
        },
    )
    i2i_negative_prompt: str = Field(
        default="",
        description="图生图反向提示词",
        json_schema_extra={
            "label": "图生图反向提示词",
            "hint": "仅正反提示词模式使用；内容会覆盖工作流中反向提示词节点的原始文本，留空表示传入空字符串",
            "input_type": "textarea",
            "order": 13,
        },
    )
    i2i_image_node_id: str = Field(
        default="",
        description="图生图源图读取节点 ID",
        json_schema_extra={
            "label": "图生图源图节点 ID",
            "hint": "填写 API 工作流中 LoadImage 或兼容节点的 ID。插件会先上传源图，再将文件名写入该节点",
            "order": 14,
        },
    )
    image_input_name: str = Field(
        default="image",
        description="图生图源图节点的输入字段名",
        json_schema_extra={
            "label": "图生图源图输入字段名",
            "hint": "标准 LoadImage 节点为 image。若自定义节点输入字段不同，请填写实际字段名",
            "order": 15,
        },
    )
    poll_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="ComfyUI 任务完成状态的轮询间隔（秒）",
        json_schema_extra={
            "label": "任务轮询间隔",
            "hint": "默认 1 秒。总超时仍使用 general.request_timeout_seconds",
            "order": 16,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用 ComfyUI 前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "Stable Diffusion、Flux 等英文提示词工作流可按需开启；中文提示词模型可保持关闭",
            "order": 17,
        },
    )


class PromptModerationConfig(PluginConfigBase):
    """提示词审核配置。"""

    __ui_label__ = "提示词审核"
    __ui_order__ = 11

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
    __ui_order__ = 12

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
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    prompt_review: PromptModerationConfig = Field(default_factory=PromptModerationConfig)
    image_review: ImageModerationConfig = Field(default_factory=ImageModerationConfig)
    openai: OpenAIModelConfig = Field(default_factory=OpenAIModelConfig)
    google: GoogleModelConfig = Field(default_factory=GoogleModelConfig)
    zhipu: ZhipuModelConfig = Field(default_factory=ZhipuModelConfig)
    aliyun: AliyunModelConfig = Field(default_factory=AliyunModelConfig)
    volcengine: VolcengineModelConfig = Field(default_factory=VolcengineModelConfig)
    siliconflow: SiliconFlowModelConfig = Field(default_factory=SiliconFlowModelConfig)
    novelai: NovelAIModelConfig = Field(default_factory=NovelAIModelConfig)
    comfyui: ComfyUIModelConfig = Field(default_factory=ComfyUIModelConfig)


def migrate_legacy_review_config(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """将旧版独立审核配置节迁移到通用配置。"""

    migrated_config = {
        str(section_name): dict(section_value) if isinstance(section_value, Mapping) else section_value
        for section_name, section_value in config_data.items()
    }
    general_config = migrated_config.setdefault("general", {})
    if not isinstance(general_config, dict):
        return migrated_config

    prompt_review_config = migrated_config.pop("prompt_review", None)
    if isinstance(prompt_review_config, Mapping):
        if "prompt_review_enabled" not in general_config and "enabled" in prompt_review_config:
            general_config["prompt_review_enabled"] = prompt_review_config["enabled"]
        if "prompt_review_prompt" not in general_config and "review_prompt" in prompt_review_config:
            general_config["prompt_review_prompt"] = prompt_review_config["review_prompt"]

    image_review_config = migrated_config.pop("image_review", None)
    if isinstance(image_review_config, Mapping):
        if "image_review_enabled" not in general_config and "enabled" in image_review_config:
            general_config["image_review_enabled"] = image_review_config["enabled"]
        if "image_review_prompt" not in general_config and "review_prompt" in image_review_config:
            general_config["image_review_prompt"] = image_review_config["review_prompt"]

    _migrate_legacy_volcengine_models(migrated_config)

    _migrate_legacy_quota_fields(migrated_config)

    return migrated_config


def _migrate_legacy_volcengine_models(migrated_config: dict[str, Any]) -> None:
    """将旧版火山引擎 models 列表自动分配到 t2i_models / i2i_models。

    仅在 t2i_models / i2i_models 均未填写时触发，按后缀 -t2i / -i2i 拆分；
    无法识别后缀的模型同时加入两个列表，保证兼容性。
    """

    volcengine_config = migrated_config.get("volcengine")
    if not isinstance(volcengine_config, dict):
        return
    legacy_models = volcengine_config.get("models")
    if not isinstance(legacy_models, list) or not legacy_models:
        return
    # 仅在新的两个字段都缺失或为空时才迁移
    has_t2i = isinstance(volcengine_config.get("t2i_models"), list) and volcengine_config["t2i_models"]
    has_i2i = isinstance(volcengine_config.get("i2i_models"), list) and volcengine_config["i2i_models"]
    if has_t2i or has_i2i:
        return
    t2i_models: list[str] = []
    i2i_models: list[str] = []
    for model in legacy_models:
        normalized_model = str(model or "").strip()
        if not normalized_model:
            continue
        lowered = normalized_model.lower()
        if lowered.endswith("-t2i"):
            t2i_models.append(normalized_model)
        elif lowered.endswith("-i2i"):
            i2i_models.append(normalized_model)
        else:
            # 无法识别后缀，同时加入两个列表
            t2i_models.append(normalized_model)
            i2i_models.append(normalized_model)
    volcengine_config["t2i_models"] = t2i_models
    volcengine_config["i2i_models"] = i2i_models


def _migrate_legacy_quota_fields(migrated_config: dict[str, Any]) -> None:
    """将旧版统一的额度字段迁移到群聊/私聊分离字段。

    仅在新字段缺失且旧字段存在时触发，旧字段值同时写入群聊和私聊，保持旧行为。
    """

    general_config = migrated_config.get("general")
    if not isinstance(general_config, dict):
        return

    legacy_enabled = general_config.get("quota_enabled")
    if legacy_enabled is not None:
        if "group_quota_enabled" not in general_config:
            general_config["group_quota_enabled"] = legacy_enabled
        if "private_quota_enabled" not in general_config:
            general_config["private_quota_enabled"] = legacy_enabled
        general_config.pop("quota_enabled", None)

    legacy_period = general_config.get("quota_period")
    if legacy_period is not None:
        if "group_quota_period" not in general_config:
            general_config["group_quota_period"] = legacy_period
        if "private_quota_period" not in general_config:
            general_config["private_quota_period"] = legacy_period
        general_config.pop("quota_period", None)

    legacy_default_quota = general_config.get("default_quota")
    if legacy_default_quota is not None:
        if "group_default_quota" not in general_config:
            general_config["group_default_quota"] = legacy_default_quota
        if "private_default_quota" not in general_config:
            general_config["private_default_quota"] = legacy_default_quota
        general_config.pop("default_quota", None)
