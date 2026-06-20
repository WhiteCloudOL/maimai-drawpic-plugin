from __future__ import annotations

from io import BytesIO

from PIL import Image as PILImage


_MIME_TYPE_MAP = {
    "BMP": "image/bmp",
    "GIF": "image/gif",
    "JPEG": "image/jpeg",
    "JPG": "image/jpeg",
    "PNG": "image/png",
    "TIFF": "image/tiff",
    "WEBP": "image/webp",
}


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
