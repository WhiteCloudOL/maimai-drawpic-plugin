from typing import Any


def extract_image_base64_from_message(message: dict[str, Any]) -> str:
    """从消息结构中提取第一张图片的 Base64。"""

    raw_message = message.get("raw_message", [])
    if not isinstance(raw_message, list):
        return ""

    for segment in raw_message:
        if not isinstance(segment, dict):
            continue
        if str(segment.get("type") or "").strip() != "image":
            continue

        image_base64 = segment.get("binary_data_base64")
        if isinstance(image_base64, str) and image_base64.strip():
            return image_base64.strip()
    return ""


async def find_source_image(
    ctx: Any,
    stream_id: str,
    source_message_id: str = "",
    source_image_base64: str = "",
) -> tuple[str, str]:
    """查找待编辑的源图片。"""

    normalized_image_base64 = source_image_base64.strip()
    if normalized_image_base64:
        return normalized_image_base64, source_message_id.strip()

    normalized_message_id = source_message_id.strip()
    if normalized_message_id:
        result = await ctx.call_capability(
            "message.get_by_id",
            message_id=normalized_message_id,
            chat_id=stream_id,
            include_binary_data=True,
        )
        if isinstance(result, dict) and result.get("success"):
            message = result.get("message")
            if isinstance(message, dict):
                image_base64 = extract_image_base64_from_message(message)
                if image_base64:
                    return image_base64, normalized_message_id
        raise ValueError("指定消息中没有可用图片，无法执行图片编辑")

    recent_result = await ctx.call_capability(
        "message.get_recent",
        chat_id=stream_id,
        limit=8,
        include_binary_data=True,
    )
    if not isinstance(recent_result, dict) or not recent_result.get("success"):
        raise ValueError("无法读取最近消息，无法自动寻找待编辑图片")
    recent_messages = recent_result.get("messages", [])
    if not isinstance(recent_messages, list):
        raise ValueError("最近消息返回格式不正确，无法自动寻找待编辑图片")

    for message in reversed(recent_messages):
        if not isinstance(message, dict):
            continue
        image_base64 = extract_image_base64_from_message(message)
        if image_base64:
            return image_base64, str(message.get("message_id") or "").strip()

    raise ValueError("最近消息中没有找到图片，请先发送图片，或显式传入 source_message_id")
