"""绘图工具的参数声明。"""

from typing import Any
from ...domain.references import ReferenceOptions

DRAW_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompt": {
            "type": "string",
            "description": "图片提示词，尽量描述清楚主体、风格和画面内容",
        },
        "model": {
            "type": "string",
            "description": "可选，指定要优先使用的图片模型；未传时使用当前会话首选模型",
        },
        "negative_prompt": {
            "type": "string",
            "description": "可选，本次绘图的反向提示词；支持独立反向字段的平台会单独传递，否则合并到正向提示词",
        },
    },
    "required": ["prompt"],
}


EDIT_IMAGE_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompt": {
            "type": "string",
            "description": "图片编辑提示词，描述希望基于源图修改成什么样；不要把源图片描述写在这里替代真实图片",
        },
        "source_message_id": {
            "type": "string",
            "description": "可选，指定要编辑的源图片消息 ID；不填时只取本条或明确引用的图片；接续前图须开启聊天取材，不能任意选择历史图片",
        },
        "source_image_base64": {
            "type": "string",
            "description": "可选，直接传入真实源图片 Base64 或 data:image/...;base64；不要传图片描述文本",
        },
        "model": {
            "type": "string",
            "description": "可选，指定要优先使用的图片模型；未传时使用当前会话首选模型",
        },
        "negative_prompt": {
            "type": "string",
            "description": "可选，本次图生图的反向提示词；会与平台默认反向词合并",
        },
    },
    "required": ["prompt"],
}


for schema in (DRAW_TOOL_PARAMETERS_SCHEMA, EDIT_IMAGE_TOOL_PARAMETERS_SCHEMA):
    schema["properties"]["style"] = {"type": "string", "description": "可选，已配置的绘图预设名称；none 表示不使用预设"}
    schema["properties"]["reference_options"] = {
        **ReferenceOptions.model_json_schema(),
        "description": "按画面中的人物明确填写 self_reference。显式请求 chat/web 取材时提供用户原话，只使用已开启的素材来源。",
    }
    schema["properties"]["reference_options"]["properties"].pop("multi_reference_confirmed")
    self_reference_field = schema["properties"]["reference_options"]["properties"]["self_reference"]
    schema["properties"]["reference_options"]["properties"]["self_reference"] = {
        "description": "只填小写字符串。画面明确包含机器人（如“画你的自拍”“画你和甘雨合照”）填 required；画其他主体（如“你帮我画甘雨”“画我的自拍”）或明确不用自我图库填 off。结合上下文仍不确定是否包含机器人才填 auto。auto 只读取宿主本轮原话，取不到时按 off 继续。tag 仅用于选图。",
        "examples": self_reference_field["examples"],
        "default": "off",
        "anyOf": [
            {"type": "string"}, {"type": "null"}, {"type": "boolean"},
            {"type": "number"}, {"type": "array", "items": {}},
            {"type": "object", "additionalProperties": True},
        ],
    }
    schema["properties"]["reference_options"]["properties"]["user_request"]["description"] = (
        "显式搜索素材时逐字复制本轮用户请求，插件优先读取本轮消息。无需为 auto 补写此字段；模型传入的文本不能启动自身识别。"
    )


DRAW_STATUS_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "task_id": {
            "type": "string",
            "description": "可选，指定要查询的后台绘图任务 ID；不填时默认查询当前会话最近一个任务",
        },
    },
    "required": [],
}


STYLED_DRAW_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompt": {
            "type": "string",
            "description": "用户正向提示词；图生图时可以留空，由风格模板和源图片共同决定画面",
        },
        "style": {
            "type": "string",
            "description": "可选的插件全平台风格模板名称；不填时按普通 draw/edit_image 行为执行",
        },
        "negative_prompt": {
            "type": "string",
            "description": "可选的用户反向提示词，会与风格反向模板及平台默认反向词合并",
        },
        "source_message_id": {
            "type": "string",
            "description": "可选，指定图生图源图片消息 ID",
        },
        "source_image_base64": {
            "type": "string",
            "description": "可选，直接提供真实源图片 Base64 或 data URL",
        },
    },
    "required": [],
}


DRAW_STYLES_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {},
    "required": [],
}

STYLED_DRAW_TOOL_PARAMETERS_SCHEMA["properties"]["reference_options"] = DRAW_TOOL_PARAMETERS_SCHEMA["properties"]["reference_options"]
