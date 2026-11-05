"""所有绘图平台实例共用的反向提示词配置。"""

from maibot_sdk import Field, PluginConfigBase


class NegativePromptConfig(PluginConfigBase):
    """将调用方反向词与平台默认值的开关独立于风格预设。"""

    negative_prompt_enabled: bool = Field(
        default=False,
        description="是否接受本次请求的反向提示词并添加平台默认反向词",
        json_schema_extra={
            "label": "启用反向提示词",
            "hint": "关闭时忽略 AI、命令、工作台和 API 传入的反向词及平台默认反向词；风格预设自己的正反向模板仍生效。",
            "order": 80,
        },
    )
    negative_prompt: str = Field(
        default="",
        max_length=16000,
        description="启用反向提示词后，追加到本次反向词的默认内容",
        json_schema_extra={
            "label": "默认反向提示词（可选）",
            "hint": "仅在上方开关开启时生效。在本次反向词后追加，并与风格反向词按词条去重；开启英文改写时一并改写。不支持独立反向字段的平台会将最终内容合并到提示词。",
            "input_type": "textarea",
            "rows": 3,
            "order": 81,
        },
    )
