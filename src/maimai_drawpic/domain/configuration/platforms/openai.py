"""configuration/platforms/openai.py 的强类型配置定义。"""

from maibot_sdk import Field
from pydantic import field_validator
from typing import Any

from ...models.openai_profiles import OpenAICompatibilityMode, normalize_openai_mode

from .common import NegativePromptConfig


class OpenAICompatibleInstanceConfig(NegativePromptConfig):
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
        default="https://api.openai.com/v1",
        description="OpenAI 兼容服务 API 根地址，末尾应包含 /v1、/api/v3 等版本路径",
        json_schema_extra={
            "label": "基础 URL",
            "placeholder": "https://api.example.com/v1",
            "hint": "填写完整 API 根路径，例如 OpenAI 的 /v1 或方舟的 /api/v3；插件只会继续追加接口路径",
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
        default="gpt-image-2.5",
        description="该实例可用模型。WebUI 对象列表单项内只能填写单行文本，多个模型可用英文逗号、中文逗号或分号分隔；需要同一上游模型走多个中转时使用 显示名=上游模型名",
        json_schema_extra={
            "label": "模型列表",
            "input_type": "textarea",
            "x-widget": "textarea",
            "rows": 3,
            "placeholder": "gpt-image-2.5, platform-gpt=gpt-image-2.5",
            "hint": "多个模型用逗号分隔。",
            "order": 4,
        },
    )

    # 常用项：影响调用方式与默认输出，多数场景需要关注
    default_openai_compatibility_mode: str = Field(
        default="auto",
        description="该实例默认 OpenAI 兼容模式",
        json_schema_extra={
            "label": "兼容模式",
            "placeholder": "auto / images_api / chat_completions / rinkoai",
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
            "placeholder": "gpt-image-2.5=1024x1024, gemini-image=1536x1024",
            "hint": "多项用逗号分隔。",
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
            "hint": "多项用逗号分隔。",
            "order": 15,
        },
    )


class OpenAIModelConfig(NegativePromptConfig):
    """OpenAI 模型配置。"""

    __ui_label__ = "OpenAI 配置"
    __ui_order__ = 4

    @field_validator("default_openai_compatibility_mode", mode="before")
    @classmethod
    def normalize_compatibility_mode(cls, value: Any) -> Any:
        """读取已移除的 NovelAI Images 名称，Schema 只公开现行模式。"""

        return normalize_openai_mode(value) if isinstance(value, str) else value

    enabled: bool = Field(
        default=True,
        description="是否启用此平台实例。关闭后不影响其他平台实例",
        json_schema_extra={
            "label": "启用此平台实例",
            "hint": "关闭后，该平台的模型将不可选。",
            "order": -1,
        },
    )
    base_url: str = Field(
        default="https://api.openai.com/v1",
        description="OpenAI 兼容服务 API 根地址，末尾应包含 /v1、/api/v3 等版本路径",
        json_schema_extra={
            "label": "OpenAI 基础 URL",
            "hint": "填写完整 API 根路径，例如 https://api.openai.com/v1 或 https://ark.cn-beijing.volces.com/api/v3",
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
        default=["gpt-image-2.5"],
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
            "hint": "支持 auto、images_api、chat_completions（New API 聊天绘图）、rinkoai（RinkoAI NAI 兼容）。auto 优先参考 New API 模型端点信息，缺失时按模型系列选择；只有端点不支持才切换格式。旧 novelai_images_api 值作为 rinkoai 别名。",
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
