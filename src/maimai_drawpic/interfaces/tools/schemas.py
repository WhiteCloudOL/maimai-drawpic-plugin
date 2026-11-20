"""绘图工具的参数声明。"""

from copy import deepcopy
from typing import Any, Dict, List, Optional

from ...domain.references import ChatReferenceOptions


_MATERIAL_SOURCE_GUIDANCE = {
    "chat": "接续缺前图用 chat。",
    "web": "缺指定角色或物件的参考图、用户要求搜索时用 web，并填 web_reference_subject。结合上下文辨认专名和昵称，含义会改变主体且无法确认时先询问。",
}


def _material_sources_description(sources: List[str]) -> str:
    if not sources:
        return "自动取材已关闭，填 []。"
    return (
        "只画机器人的自画像或自拍时用自我图库，设 self_reference=required。"
        "仅缺额外素材时取材，其余填 []。"
        + "".join(_MATERIAL_SOURCE_GUIDANCE[source] for source in sources)
    )


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
        **ChatReferenceOptions.model_json_schema(),
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
        "可选。缺本轮消息时，可简述取材意图，例如继续改上一张。只用自我参考时无需填写。"
    )
    reference_fields["self_reference_ids"]["description"] = "自我图库图片 ID，优先于 tag。"
    reference_fields["self_reference_tags"]["description"] = "选图标签，如冬装。未指定 ID 时按标签或原话选图，未命中用默认图。"
    reference_fields["material_sources"]["description"] = _material_sources_description(
        list(_MATERIAL_SOURCE_GUIDANCE)
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


def restrict_drawing_material_sources(
    tool_definitions: List[Dict[str, Any]], enabled: List[str],
) -> Optional[List[Dict[str, Any]]]:
    """按当前配置收窄本轮绘图工具声明，保留已注册的完整参数格式。"""
    if len(enabled) == len(_MATERIAL_SOURCE_GUIDANCE):
        return None
    updated = tool_definitions.copy()
    for index, tool in enumerate(tool_definitions):
        function = tool.get("function", {})
        if function.get("name") not in ("draw", "edit_image", "styled_draw"):
            continue
        options = function.get("parameters", {}).get("properties", {}).get("reference_options", {})
        fields = options.get("properties", {})
        sources = fields.get("material_sources")
        if not isinstance(sources, dict):
            continue
        choices = sources.get("items", {}).get("enum")
        if not isinstance(choices, list):
            continue
        allowed = [source for source in enabled if source in choices]
        if allowed == choices and ("web" in allowed or "web_reference_subject" not in fields):
            continue

        updated[index] = deepcopy(tool)
        updated_fields = updated[index]["function"]["parameters"]["properties"]["reference_options"]["properties"]
        if "web" not in allowed:
            updated_fields.pop("web_reference_subject", None)
        material = updated_fields["material_sources"]
        material["maxItems"] = min(material.get("maxItems", len(allowed)), len(allowed))
        material["description"] = _material_sources_description(allowed)
        if allowed:
            material["items"]["enum"] = allowed
        else:
            material["items"].pop("enum")
    return updated if updated != tool_definitions else None
