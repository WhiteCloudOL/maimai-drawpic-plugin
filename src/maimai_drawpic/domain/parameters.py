from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional
import json
import re


NEGATIVE_PROMPT_OPTION_KEYS = {"negative_prompt", "uc", "v4_negative_prompt"}
_OPTION_ASSIGNMENT_PATTERN = re.compile(r"\s*[^\s=,，;；\[\]{}\"']+\s*=")


def split_inline_key_value_options(value: str) -> List[str]:
    """兼容旧版内联参数，同时保留 JSON、引号及文本值中的分隔符。"""

    parts: List[str] = []
    start = 0
    depth = 0
    quote = ""
    escaped = False
    for index, character in enumerate(value):
        if quote:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = ""
            continue
        if character in "\"'" and (depth > 0 or value[start:index].rstrip().endswith("=")):
            quote = character
        elif character in "[{":
            depth += 1
        elif character in "]}":
            depth -= 1
        elif depth == 0 and (
            character == "\n"
            or character in ",，;；" and _OPTION_ASSIGNMENT_PATTERN.match(value, index + 1)
        ):
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return [part for part in parts if part]


def without_negative_prompt_options(options: Dict[str, Any]) -> Dict[str, Any]:
    """反向字段由实例处理，禁止扩展参数在发送时覆盖处理结果。"""

    return {key: value for key, value in options.items() if key not in NEGATIVE_PROMPT_OPTION_KEYS}


def v4_negative_prompt_option(options: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """校验并复制 NAI 结构化反向词，保留角色顺序、坐标和协议标记。"""

    value = options.get("v4_negative_prompt")
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("caption"), dict):
        raise ValueError("扩展参数 v4_negative_prompt.caption 必须是对象")
    caption = value["caption"]
    if not isinstance(caption.get("base_caption", ""), str):
        raise ValueError("扩展参数 v4_negative_prompt.caption.base_caption 必须是字符串")
    characters = caption.get("char_captions", [])
    if not isinstance(characters, list):
        raise ValueError("扩展参数 v4_negative_prompt.caption.char_captions 必须是列表")
    for index, character in enumerate(characters, start=1):
        if not isinstance(character, dict) or not isinstance(character.get("char_caption", ""), str):
            raise ValueError(f"扩展参数 v4_negative_prompt 第 {index} 个角色必须是对象且 char_caption 必须是字符串")
    return deepcopy(value)


def negative_prompt_option_parts(
    options: Dict[str, Any], *, allow_character_captions: bool = False,
) -> List[str]:
    """读取旧扩展参数中的反向文本，交给实例统一过滤、去重和改写。"""

    parts: List[str] = []
    for key in ("negative_prompt", "uc"):
        value = options.get(key, "")
        if value is None:
            continue
        if not isinstance(value, str):
            raise ValueError(f"扩展参数 {key} 必须是字符串")
        parts.append(value)
    v4_prompt = v4_negative_prompt_option(options)
    if v4_prompt is not None:
        caption = v4_prompt["caption"]
        if caption.get("char_captions") and not allow_character_captions:
            raise ValueError("扩展参数 v4_negative_prompt 的角色反向词需要使用 NovelAI 平台实例")
        parts.append(caption.get("base_caption", ""))
    return parts


def parse_key_value_options(items: list[str]) -> dict[str, Any]:
    """解析 WebUI 友好的 key=value 列表，值会尽量转换为 JSON/布尔/数字。"""

    options: dict[str, Any] = {}
    for item in items:
        normalized_item = str(item).strip()
        if not normalized_item or "=" not in normalized_item:
            continue
        key, raw_value = normalized_item.split("=", maxsplit=1)
        key = key.strip()
        if not key:
            continue
        options[key] = parse_option_value(raw_value.strip())
    return options


def parse_model_value_overrides(items: list[str]) -> dict[str, str]:
    """解析 模型名=值 格式的覆盖配置。"""

    overrides: dict[str, str] = {}
    for item in items:
        normalized_item = str(item).strip()
        if not normalized_item or "=" not in normalized_item:
            continue
        model_name, value = normalized_item.split("=", maxsplit=1)
        model_name = model_name.strip()
        value = value.strip()
        if model_name and value:
            overrides[model_name] = value
    return overrides


def parse_option_value(value: str) -> Any:
    """把配置字符串转换为接口请求更常用的数据类型。"""

    normalized_value = value.strip()
    lower_value = normalized_value.lower()
    if lower_value == "true":
        return True
    if lower_value == "false":
        return False
    if lower_value in {"none", "null"}:
        return None

    if normalized_value.startswith(("{", "[")):
        try:
            return json.loads(normalized_value)
        except json.JSONDecodeError:
            return normalized_value

    try:
        return int(normalized_value)
    except ValueError:
        pass

    try:
        return float(normalized_value)
    except ValueError:
        return normalized_value


def resolve_model_override(model: str, default_value: str, overrides: dict[str, str]) -> str:
    """按模型名解析覆盖值。"""

    normalized_model = model.strip()
    return overrides.get(normalized_model, default_value.strip())


def resolve_positive_int(value: int, *, default_value: int, max_value: int) -> int:
    """解析正整数配置，并限制最大值。"""

    resolved_value = int(value)
    if resolved_value <= 0:
        return default_value
    if resolved_value > max_value:
        return max_value
    return resolved_value
