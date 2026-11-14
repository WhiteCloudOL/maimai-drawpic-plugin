# SPDX-FileCopyrightText: 2026 WhiteCloudOL
# SPDX-License-Identifier: MIT

"""严格校验分块协议，保存路径由调用插件明确提供。"""

from pathlib import Path
from typing import List, Sequence, Union
import asyncio
import base64
import binascii
import os
import tempfile

from .models import DrawingError, DrawingTransportError
from .transport import DrawingRPC


def encode_sources(images: Sequence[Union[str, bytes]]) -> List[str]:
    """只负责有界编码；真实图片内容继续交由服务端统一验证。"""
    if not isinstance(images, (list, tuple)) or len(images) > 8:
        raise ValueError("source_images 应为最多 8 张图片的列表或元组")
    result = []
    for image in images:
        if isinstance(image, bytes):
            if not image or 4 * ((len(image) + 2) // 3) > 8 * 1024 * 1024:
                raise ValueError("单张源图编码后应为 1～8 MiB，图片 bytes 过大或为空")
            encoded = base64.b64encode(image).decode("ascii")
        elif isinstance(image, str) and image and len(image) <= 8 * 1024 * 1024:
            encoded = image
        else:
            raise ValueError("源图应为非空图片 bytes 或不超过 8 MiB 的 Base64 文本")
        result.append(encoded)
    return result


async def read_image(rpc: DrawingRPC, task_id: str, index: int, max_bytes: int) -> bytes:
    offset, chunks, expected = 0, [], None
    while True:
        response = None
        for attempt in range(3):
            try:
                response = await rpc.call("image", task_id=task_id, index=index, kind="original", offset=offset)
                break
            except DrawingTransportError:
                if attempt == 2:
                    raise
                await asyncio.sleep(0.5)
        if response.get("error") is not None:
            request_id = response.get("request_id", "")
            if not isinstance(request_id, str):
                raise DrawingTransportError("图片响应请求键格式无效", task_id=task_id)
            raise DrawingError(response["error"], task_id=task_id, request_id=request_id)
        try:
            size = response["size"]
            if type(size) is not int or size <= 0:
                raise ValueError("图片大小无效")
            if size > max_bytes:
                raise DrawingError(
                    {"code": "RESULT_TOO_LARGE", "message": "图片超过客户端单张容量限制；可调高限制后读取原任务"},
                    task_id=task_id,
                )
            identity = (size, response["mime"], response["filename"])
            if expected is not None and identity != expected:
                raise ValueError("图片分块来源或大小改变")
            expected = identity
            if not isinstance(identity[1], str) or identity[1] not in {"image/png", "image/jpeg", "image/webp"}:
                raise ValueError("图片格式无效")
            if not isinstance(identity[2], str) or not identity[2]:
                raise ValueError("图片来源标记无效")
            raw = base64.b64decode(response["data"], validate=True)
            if type(response["offset"]) is not int or response["offset"] != offset or not 0 < len(raw) <= 192 * 1024:
                raise ValueError("图片分块偏移或大小无效")
            offset += len(raw)
            if (
                type(response["next_offset"]) is not int
                or response["next_offset"] != offset
                or offset > size
                or type(response["done"]) is not bool
            ):
                raise ValueError("图片分块进度无效")
            if response["done"] != (offset == size):
                raise ValueError("图片分块终止标记无效")
        except (KeyError, TypeError, ValueError, binascii.Error) as exc:
            raise DrawingTransportError(f"图片分块协议错误：{exc}", task_id=task_id) from exc
        chunks.append(raw)
        if response["done"]:
            return await asyncio.to_thread(b"".join, chunks)


def save_bytes(destination: Path, data: bytes, overwrite: bool) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            temporary.replace(destination)
        else:
            # 排他创建目标，避免“先 exists 再 replace”覆盖并发写入者。
            os.link(temporary, destination)
        return destination
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
