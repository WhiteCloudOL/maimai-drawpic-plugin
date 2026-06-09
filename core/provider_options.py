from __future__ import annotations

from typing import Any

import json


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
