from __future__ import annotations

from io import BytesIO

from PIL import Image as PILImage

MAX_IMAGE_BYTES = 25 * 1024 * 1024


_MIME_TYPE_MAP = {
    "BMP": "image/bmp",
    "GIF": "image/gif",
    "JPEG": "image/jpeg",
    "JPG": "image/jpeg",
    "PNG": "image/png",
    "TIFF": "image/tiff",
    "WEBP": "image/webp",
}


def validate_image_bytes(image_bytes: bytes) -> bytes:
    """校验图片大小与内容，并返回原始字节。"""

    if not image_bytes:
        raise ValueError("图片数据为空")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError(f"图片大小超过限制：{MAX_IMAGE_BYTES} 字节")
    with PILImage.open(BytesIO(image_bytes)) as image:
        image.verify()
    return image_bytes


def detect_mime_type(image_bytes: bytes) -> str:
    """尽量根据图片内容推断 MIME 类型，无法识别时回退 image/png。"""

    with PILImage.open(BytesIO(image_bytes)) as image:
        format_name = str(image.format or "").upper()
    return _MIME_TYPE_MAP.get(format_name, "image/png")


def detect_image_dimensions(image_bytes: bytes) -> tuple[int, int] | None:
    """读取图片像素尺寸，异常或非正尺寸返回 None。"""

    with PILImage.open(BytesIO(image_bytes)) as image:
        width, height = image.size
    if width <= 0 or height <= 0:
        return None
    return width, height


def detect_image_format(image_bytes: bytes) -> str:
    """根据图片字节推断格式名（小写），仅保留常见可发送格式。"""

    with PILImage.open(BytesIO(image_bytes)) as image:
        format_name = str(image.format or "").strip().lower()
    if format_name in {"jpg", "jpeg", "png", "webp", "gif"}:
        return format_name
    return "png"
