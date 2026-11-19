"""绘图工具的参数声明。"""

from typing import Any
from ...domain.references import ReferenceOptions

DRAW_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompt": {
            "type": "string",
            "description": "描述画面主体、内容和风格。",
        },
        "model": {
            "type": "string",
            "description": "指定绘图模型。省略时用会话首选模型。",
        },
        "negative_prompt": {
            "type": "string",
            "description": "反向提示词。平台无独立反向字段时并入正向提示词。",
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
            "description": "描述对源图的修改。源图须提供真实图片。",
        },
        "source_message_id": {
            "type": "string",
            "description": "用户指定的源图消息 ID。省略时取本条或引用图。接续未引用的前图须开启聊天取材。",
        },
        "source_image_base64": {
            "type": "string",
            "description": "真实源图的 Base64 或图片 data URL。",
        },
        "model": {
            "type": "string",
            "description": "指定绘图模型。省略时用会话首选模型。",
        },
        "negative_prompt": {
            "type": "string",
            "description": "反向提示词，与平台默认反向词合并。",
        },
    },
    "required": ["prompt"],
}


for schema in (DRAW_TOOL_PARAMETERS_SCHEMA, EDIT_IMAGE_TOOL_PARAMETERS_SCHEMA):
    schema["properties"]["style"] = {"type": "string", "description": "绘图预设的精确名称。用 none 跳过预设。"}
    schema["properties"]["reference_options"] = {
        **ReferenceOptions.model_json_schema(),
        "description": "自我参考、预设参考图和取材选项。",
    }
    reference_fields = schema["properties"]["reference_options"]["properties"]
    reference_fields.pop("multi_reference_confirmed")
    reference_fields["self_reference"] = {
        "description": (
            "用小写字符串。明确画机器人（含合照）填 required。画其他主体或不用自我参考填 off，并省略自我选图字段。"
            "仅不确定机器人是否入画时填 auto。auto 只读宿主本轮原话，缺原话按 off。"
        ),
        "examples": reference_fields["self_reference"]["examples"],
        "default": "off",
        "anyOf": [
            {"type": "string"}, {"type": "null"}, {"type": "boolean"},
            {"type": "number"}, {"type": "array", "items": {}},
            {"type": "object", "additionalProperties": True},
        ],
    }
    reference_fields["user_request"]["description"] = (
        "显式取材时照录本轮用户原话，插件优先读取本轮消息。仅用 auto 时省略。"
    )
    reference_fields["self_reference_ids"]["description"] = "自我图库图片 ID，优先于 tag。"
    reference_fields["self_reference_tags"]["description"] = "选图标签，如冬装。未指定 ID 时按标签或原话选图，未命中用默认图。"
    reference_fields["material_sources"]["description"] = (
        "只画机器人的自画像或自拍时用自我图库，设 self_reference=required。"
        "仅缺额外素材时选已开启的来源，其余填 []。接续缺前图用 chat，缺指定角色、物件或明确要求的参考图用 web。"
    )


DRAW_STATUS_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "task_id": {
            "type": "string",
            "description": "任务 ID。省略时查询当前会话最近的任务。",
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
            "description": "正向提示词。有源图时可留空，由源图和风格模板决定画面。",
        },
        "style": {
            "type": "string",
            "description": "绘图预设的精确名称。省略时按普通绘图处理。",
        },
        "negative_prompt": {
            "type": "string",
            "description": "反向提示词，与风格及平台的反向词合并。",
        },
        "source_message_id": {
            "type": "string",
            "description": "源图消息 ID。",
        },
        "source_image_base64": {
            "type": "string",
            "description": "真实源图的 Base64 或图片 data URL。",
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
