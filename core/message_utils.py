from io import BytesIO
from typing import Any

from PIL import Image as PILImage

import base64
import binascii


def _normalize_base64_value(value: Any) -> str:
    """将候选值规范化为可用的 Base64 字符串。"""

    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def _remove_data_url_prefix(value: str) -> str:
    """移除 data URL 前缀，只保留 Base64 数据。"""

    if not value.lower().startswith("data:"):
        return value

    header, separator, payload = value.partition(",")
    if not separator or ";base64" not in header.lower() or not header.lower().startswith("data:image/"):
        raise ValueError("source_image_base64 不是有效的图片 data URL")
    return payload


def normalize_image_base64(value: Any) -> str:
    """规范化图片 Base64，支持 data:image/...;base64 前缀。"""

    normalized_value = _normalize_base64_value(value)
    if not normalized_value:
        return ""

    normalized_value = _remove_data_url_prefix(normalized_value)
    normalized_value = "".join(normalized_value.split())
    if not normalized_value:
        return ""

    padding_remainder = len(normalized_value) % 4
    if padding_remainder == 1:
        raise ValueError("source_image_base64 不是有效的图片 Base64")
    if padding_remainder:
        normalized_value += "=" * (4 - padding_remainder)
    return normalized_value


def decode_image_base64(value: Any) -> bytes:
    """解码并校验真实图片 Base64。"""

    normalized_value = normalize_image_base64(value)
    if not normalized_value:
        raise ValueError("没有可用的真实图片数据")

    try:
        image_bytes = base64.b64decode(normalized_value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("source_image_base64 不是有效的图片 Base64") from exc

    try:
        with PILImage.open(BytesIO(image_bytes)) as image:
            image.verify()
    except Exception as exc:
        raise ValueError("source_image_base64 不是可识别的真实图片") from exc

    return image_bytes


def validate_image_base64(value: Any) -> str:
    """确认候选 Base64 是真实图片，并返回规范化后的 Base64。"""

    normalized_value = normalize_image_base64(value)
    decode_image_base64(normalized_value)
    return normalized_value


def _extract_image_base64_from_segment(segment: dict[str, Any]) -> str:
    """从单个消息段中提取图片 Base64。"""

    segment_type = str(segment.get("type") or "").strip()
    if segment_type != "image":
        return ""

    candidate_keys = (
        "binary_data_base64",
        "base64",
        "image_base64",
        "file_base64",
    )
    for key in candidate_keys:
        image_base64 = _normalize_base64_value(segment.get(key))
        if image_base64:
            return image_base64

    nested_data = segment.get("data")
    if isinstance(nested_data, dict):
        for key in candidate_keys:
            image_base64 = _normalize_base64_value(nested_data.get(key))
            if image_base64:
                return image_base64

    return ""


def _extract_segments_from_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    """兼容不同消息格式，提取统一的消息段列表。"""

    normalized_segments: list[dict[str, Any]] = []
    candidate_segment_lists = (
        message.get("message_segments"),
        message.get("raw_message"),
    )
    for candidate_segments in candidate_segment_lists:
        if not isinstance(candidate_segments, list):
            continue
        for segment in candidate_segments:
            if not isinstance(segment, dict):
                continue
            normalized_segments.append(segment)
    return normalized_segments


def extract_image_base64_from_message(message: dict[str, Any]) -> str:
    """从消息结构中提取第一张图片的 Base64。"""

    for segment in _extract_segments_from_message(message):
        image_base64 = _extract_image_base64_from_segment(segment)
        if image_base64:
            return image_base64
    return ""


def _unwrap_message_result(result: Any) -> dict[str, Any] | None:
    """兼容运行时包装层，提取单条消息对象。"""

    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                return item
        return None

    if not isinstance(result, dict):
        return None

    direct_message = result.get("message")
    if isinstance(direct_message, dict):
        return direct_message

    nested_result = result.get("result")
    if isinstance(nested_result, dict):
        nested_message = nested_result.get("message")
        if isinstance(nested_message, dict):
            return nested_message

    return None


def _unwrap_messages_result(result: Any) -> list[dict[str, Any]]:
    """兼容运行时包装层，提取消息列表。"""

    if isinstance(result, list):
        return [message for message in result if isinstance(message, dict)]

    if not isinstance(result, dict):
        return []

    direct_messages = result.get("messages")
    if isinstance(direct_messages, list):
        return [message for message in direct_messages if isinstance(message, dict)]

    nested_result = result.get("result")
    if isinstance(nested_result, dict):
        nested_messages = nested_result.get("messages")
        if isinstance(nested_messages, list):
            return [message for message in nested_messages if isinstance(message, dict)]

    return []


async def find_source_image(
    ctx: Any,
    stream_id: str,
    source_message_id: str = "",
    source_image_base64: str = "",
) -> tuple[str, str]:
    """查找待编辑的源图片。"""

    normalized_image_base64 = source_image_base64.strip()
    if normalized_image_base64:
        return validate_image_base64(normalized_image_base64), source_message_id.strip()

    normalized_message_id = source_message_id.strip()
    if normalized_message_id:
        result = await ctx.call_capability(
            "message.get_by_id",
            message_id=normalized_message_id,
            chat_id=stream_id,
            include_binary_data=True,
        )
        message = _unwrap_message_result(result)
        if isinstance(message, dict):
            image_base64 = extract_image_base64_from_message(message)
            if image_base64:
                return validate_image_base64(image_base64), normalized_message_id

    recent_result = await ctx.call_capability(
        "message.get_recent",
        chat_id=stream_id,
        limit=8,
        include_binary_data=True,
    )
    if not isinstance(recent_result, (dict, list)):
        raise ValueError("无法读取最近消息，无法自动寻找待编辑图片")
    recent_messages = _unwrap_messages_result(recent_result)
    if not recent_messages:
        raise ValueError("最近消息返回格式不正确，无法自动寻找待编辑图片")

    for message in reversed(recent_messages):
        image_base64 = extract_image_base64_from_message(message)
        if not image_base64:
            continue
        try:
            return validate_image_base64(image_base64), str(message.get("message_id") or "").strip()
        except ValueError:
            continue

    raise ValueError("最近消息中没有找到可编辑的真实图片，请先发送图片，或显式传入 source_message_id")
