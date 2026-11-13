"""当前真实会话的有界图片读取，复用既有消息图片解析。"""

from typing import Any, List
import asyncio

from ...domain.references import ReferenceImage
from ...domain.task_errors import TaskRequestError
from ...interfaces.chat.message_images import decode_image_base64, extract_source_images_from_message


async def read_chat_materials(ctx: Any, stream_id: str) -> List[ReferenceImage]:
    response = await ctx.message.get_recent(chat_id=stream_id, limit=8, include_binary_data=True)
    if not isinstance(response, list) or any(not isinstance(message, dict) for message in response):
        raise TaskRequestError("CHAT_MATERIAL_UNAVAILABLE", "聊天素材响应格式无效")

    def collect() -> List[ReferenceImage]:
        result: List[ReferenceImage] = []
        for message in reversed(response):
            if message.get("is_bot") or message.get("is_self"):
                continue
            for source in extract_source_images_from_message(message):
                raw = decode_image_base64(source.base64_data)
                result.append(ReferenceImage(raw, "chat", url=source.url))
                if sum(len(image.raw) for image in result) > 40 * 1024 * 1024:
                    raise TaskRequestError("MATERIAL_LIMIT_EXCEEDED", "聊天候选素材总计超过 40 MiB")
                if len(result) == 6:
                    return result
        return result

    return await asyncio.to_thread(collect)
