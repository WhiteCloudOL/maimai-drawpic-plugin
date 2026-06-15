from io import BytesIO
from typing import Any

from PIL import Image as PILImage

import base64
import binascii


_MAX_CACHED_SOURCE_IMAGES = 80
# 每条消息可能携带多张图片，因此缓存值为按消息内顺序排列的 Base64 列表。
_SOURCE_IMAGE_CACHE: dict[tuple[str, str], list[str]] = {}
_SOURCE_IMAGE_CACHE_ORDER: list[tuple[str, str]] = []


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


def extract_all_image_base64_from_message(message: dict[str, Any]) -> list[str]:
    """从消息结构中按出现顺序提取所有图片的 Base64。

    `_extract_segments_from_message` 会同时读取 message_segments 与 raw_message，
    同一张图片可能在两个列表中重复出现，这里按 Base64 内容去重。
    """

    image_base64_list: list[str] = []
    for segment in _extract_segments_from_message(message):
        image_base64 = _extract_image_base64_from_segment(segment)
        if image_base64 and image_base64 not in image_base64_list:
            image_base64_list.append(image_base64)
    return image_base64_list


def _is_message_dict(value: dict[str, Any]) -> bool:
    """判断字典本身是否就是一条序列化消息。"""

    return "message_id" in value and ("raw_message" in value or "message_segments" in value)


def extract_reply_target_message_ids(message: dict[str, Any]) -> list[str]:
    """从消息结构中提取 QQ 回复/引用的目标消息 ID。"""

    target_message_ids: list[str] = []

    def _add_target_message_id(value: Any) -> None:
        target_message_id = str(value or "").strip()
        if target_message_id and target_message_id not in target_message_ids:
            target_message_ids.append(target_message_id)

    for key in (
        "reply_to",
        "reply_message_id",
        "quote_message_id",
        "quoted_message_id",
        "target_message_id",
        "source_message_id",
    ):
        _add_target_message_id(message.get(key))

    for nested_key in ("reply", "quote", "quoted_message"):
        nested_value = message.get(nested_key)
        if isinstance(nested_value, dict):
            for key in (
                "target_message_id",
                "message_id",
                "id",
                "reply_to",
                "source_message_id",
            ):
                _add_target_message_id(nested_value.get(key))
        else:
            _add_target_message_id(nested_value)

    for segment in _extract_segments_from_message(message):
        if str(segment.get("type") or "").strip() not in {"reply", "quote"}:
            continue

        segment_data = segment.get("data")
        if isinstance(segment_data, dict):
            for key in (
                "target_message_id",
                "message_id",
                "id",
                "reply_to",
                "source_message_id",
            ):
                _add_target_message_id(segment_data.get(key))
        else:
            _add_target_message_id(segment_data)

    return target_message_ids


def _remember_source_image(stream_id: str, message_id: str, image_base64_list: list[str]) -> None:
    """记录最近收到的真实图片列表，供 QQ 引用消息或命令编辑使用。"""

    if not image_base64_list:
        return

    for cache_key in ((stream_id, message_id), ("", message_id)):
        if cache_key not in _SOURCE_IMAGE_CACHE:
            _SOURCE_IMAGE_CACHE_ORDER.append(cache_key)
        _SOURCE_IMAGE_CACHE[cache_key] = list(image_base64_list)

    while len(_SOURCE_IMAGE_CACHE_ORDER) > _MAX_CACHED_SOURCE_IMAGES * 2:
        expired_key = _SOURCE_IMAGE_CACHE_ORDER.pop(0)
        _SOURCE_IMAGE_CACHE.pop(expired_key, None)


def _validate_image_base64_list(image_base64_list: list[str]) -> list[str]:
    """逐张校验图片 Base64，跳过无法识别的图片。"""

    normalized_list: list[str] = []
    for image_base64 in image_base64_list:
        try:
            normalized_list.append(validate_image_base64(image_base64))
        except ValueError:
            continue
    return normalized_list


def cache_source_image_from_message(stream_id: str, message: dict[str, Any]) -> tuple[str, int] | None:
    """从入站消息中缓存真实图片，返回消息 ID 与缓存到的图片数量。"""

    message_id = str(message.get("message_id") or "").strip()
    if not message_id:
        return None

    image_base64_list = extract_all_image_base64_from_message(message)
    if not image_base64_list:
        return None

    normalized_list = _validate_image_base64_list(image_base64_list)
    if not normalized_list:
        return None

    _remember_source_image(stream_id.strip(), message_id, normalized_list)
    return message_id, len(normalized_list)


def find_cached_source_image(stream_id: str, message_id: str) -> tuple[str, str] | None:
    """按消息 ID 从插件缓存中查找第一张真实图片。"""

    found = find_all_cached_source_images(stream_id, message_id)
    if found is None:
        return None
    image_base64_list, matched_message_id = found
    return image_base64_list[0], matched_message_id


def find_all_cached_source_images(stream_id: str, message_id: str) -> tuple[list[str], str] | None:
    """按消息 ID 从插件缓存中查找全部真实图片。"""

    normalized_message_id = message_id.strip()
    if not normalized_message_id:
        return None

    for cache_key in ((stream_id.strip(), normalized_message_id), ("", normalized_message_id)):
        image_base64_list = _SOURCE_IMAGE_CACHE.get(cache_key)
        if image_base64_list:
            return list(image_base64_list), normalized_message_id
    return None


async def get_message_by_id_for_image_lookup(ctx: Any, stream_id: str, message_id: str) -> dict[str, Any] | None:
    """通过运行时能力读取消息，先限定会话，失败后再全局查询。"""

    normalized_message_id = message_id.strip()
    if not normalized_message_id:
        return None

    lookup_chat_ids = [stream_id.strip(), ""]
    for chat_id in lookup_chat_ids:
        result = await ctx.call_capability(
            "message.get_by_id",
            message_id=normalized_message_id,
            chat_id=chat_id,
            include_binary_data=True,
        )
        message = _unwrap_message_result(result)
        if isinstance(message, dict):
            return message
    return None


async def find_image_from_message_by_id(
    ctx: Any,
    stream_id: str,
    message_id: str,
    visited_message_ids: set[str] | None = None,
) -> tuple[str, str] | None:
    """按消息 ID 查找真实图片。"""

    normalized_message_id = message_id.strip()
    if not normalized_message_id:
        return None
    visited_message_ids = visited_message_ids or set()
    if normalized_message_id in visited_message_ids:
        return None
    visited_message_ids.add(normalized_message_id)

    cached_image = find_cached_source_image(stream_id, normalized_message_id)
    if cached_image is not None:
        return cached_image

    message = await get_message_by_id_for_image_lookup(ctx, stream_id, normalized_message_id)
    if not isinstance(message, dict):
        return None

    # 一条消息可能有多张图片，全部缓存以便后续命令复用，但单图查找只返回第一张。
    image_base64_list = _validate_image_base64_list(extract_all_image_base64_from_message(message))
    if image_base64_list:
        matched_message_id = str(message.get("message_id") or normalized_message_id).strip()
        _remember_source_image(stream_id.strip(), matched_message_id, image_base64_list)
        return image_base64_list[0], matched_message_id

    for target_message_id in extract_reply_target_message_ids(message):
        found = await find_image_from_message_by_id(ctx, stream_id, target_message_id, visited_message_ids)
        if found is not None:
            return found

    return None


async def find_all_images_from_message_by_id(
    ctx: Any,
    stream_id: str,
    message_id: str,
    visited_message_ids: set[str] | None = None,
) -> tuple[list[str], str] | None:
    """按消息 ID 查找该消息（或其引用消息）中的全部真实图片。"""

    normalized_message_id = message_id.strip()
    if not normalized_message_id:
        return None
    visited_message_ids = visited_message_ids or set()
    if normalized_message_id in visited_message_ids:
        return None
    visited_message_ids.add(normalized_message_id)

    collected: list[str] = []
    seen: set[str] = set()
    matched_message_id = ""

    def _add(image_base64_list: list[str]) -> None:
        for image_base64 in image_base64_list:
            if image_base64 and image_base64 not in seen:
                seen.add(image_base64)
                collected.append(image_base64)

    cached_images = find_all_cached_source_images(stream_id, normalized_message_id)
    if cached_images is not None:
        cached_image_base64_list, cached_message_id = cached_images
        _add(cached_image_base64_list)
        matched_message_id = cached_message_id

    message = await get_message_by_id_for_image_lookup(ctx, stream_id, normalized_message_id)
    if not isinstance(message, dict):
        if collected:
            return collected, matched_message_id or normalized_message_id
        return None

    image_base64_list = _validate_image_base64_list(extract_all_image_base64_from_message(message))
    if image_base64_list:
        direct_message_id = str(message.get("message_id") or normalized_message_id).strip()
        _remember_source_image(stream_id.strip(), direct_message_id, image_base64_list)
        _add(image_base64_list)
        if not matched_message_id:
            matched_message_id = direct_message_id

    for target_message_id in extract_reply_target_message_ids(message):
        found = await find_all_images_from_message_by_id(ctx, stream_id, target_message_id, visited_message_ids)
        if found is not None:
            found_image_base64_list, found_message_id = found
            _add(found_image_base64_list)
            if not matched_message_id:
                matched_message_id = found_message_id

    if collected:
        return collected, matched_message_id or normalized_message_id
    return None


async def extract_image_from_reply_message(
    ctx: Any,
    stream_id: str,
    message: dict[str, Any],
) -> tuple[str, str] | None:
    """从一条回复/引用消息中提取被引用的真实图片。"""

    for target_message_id in extract_reply_target_message_ids(message):
        found = await find_image_from_message_by_id(ctx, stream_id, target_message_id)
        if found is not None:
            return found
    return None


def _unwrap_message_result(result: Any) -> dict[str, Any] | None:
    """兼容运行时包装层，提取单条消息对象。"""

    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                return item
        return None

    if not isinstance(result, dict):
        return None

    if _is_message_dict(result):
        return result

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

    image_base64_list, matched_message_id = await find_source_images(
        ctx,
        stream_id,
        source_message_id=source_message_id,
        source_image_base64=source_image_base64,
    )
    return image_base64_list[0], matched_message_id


async def find_source_images(
    ctx: Any,
    stream_id: str,
    source_message_id: str = "",
    source_image_base64: str = "",
    current_message: dict[str, Any] | None = None,
) -> tuple[list[str], str]:
    """查找待编辑的源图片列表，合并当前消息与回复/引用消息中的图片。"""

    normalized_image_base64 = source_image_base64.strip()
    if normalized_image_base64:
        return [validate_image_base64(normalized_image_base64)], source_message_id.strip()

    if isinstance(current_message, dict):
        current_images = await collect_command_source_images(ctx, stream_id, current_message)
        if current_images:
            return current_images, str(current_message.get("message_id") or "").strip()

    normalized_message_id = source_message_id.strip()
    if normalized_message_id:
        found = await find_all_images_from_message_by_id(ctx, stream_id, normalized_message_id)
        if found is not None:
            return found

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
        found = await collect_message_source_images(ctx, stream_id, message)
        if found is not None:
            return found

    raise ValueError("最近消息和引用消息中没有找到可编辑的真实图片，请先发送或回复一张图片")


async def collect_message_source_images(
    ctx: Any,
    stream_id: str,
    message: dict[str, Any],
) -> tuple[list[str], str] | None:
    """收集单条消息直接携带及其回复/引用目标中的全部图片。"""

    image_base64_list = await collect_command_source_images(ctx, stream_id, message)
    if not image_base64_list:
        return None
    return image_base64_list, str(message.get("message_id") or "").strip()


async def collect_command_source_images(
    ctx: Any,
    stream_id: str,
    message: dict[str, Any],
) -> list[str]:
    """收集 `/绘图 图生图` 命令携带的全部源图片 Base64。

    命令进入插件时消息字典已被主链清理掉二进制，因此本条命令直接附带的（非引用）
    图片需要按 message_id 从入站缓存中取回；引用/回复的图片再额外追加。
    收集顺序为：本条命令直接附带的图片在前，引用消息中的图片在后。
    """

    collected: list[str] = []
    seen: set[str] = set()

    def _add(image_base64_list: list[str]) -> None:
        for image_base64 in image_base64_list:
            if image_base64 and image_base64 not in seen:
                seen.add(image_base64)
                collected.append(image_base64)

    # 1) 本条命令消息直接附带的图片（非引用）
    _add(_validate_image_base64_list(extract_all_image_base64_from_message(message)))

    message_id = str(message.get("message_id") or "").strip()
    if message_id:
        cached = find_all_cached_source_images(stream_id, message_id)
        if cached is not None:
            _add(cached[0])
        else:
            found = await find_all_images_from_message_by_id(ctx, stream_id, message_id)
            if found is not None:
                _add(found[0])

    # 2) 引用/回复消息中的图片
    for target_message_id in extract_reply_target_message_ids(message):
        found = await find_all_images_from_message_by_id(ctx, stream_id, target_message_id)
        if found is not None:
            _add(found[0])

    return collected
