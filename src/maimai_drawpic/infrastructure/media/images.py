from __future__ import annotations

from PIL import Image as PILImage
from io import BytesIO

MAX_IMAGE_BYTES = 25 * 1024 * 1024
# MiniMax H3 permits 20 MP, including 4K ratios slightly above a square 4096 raster.
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_DIMENSION = 8192


def check_image_dimensions(image) -> int:
    width, height = image.size
    if (width <= 0 or height <= 0 or max(width, height) > MAX_IMAGE_DIMENSION
            or width * height > MAX_IMAGE_PIXELS):
        raise ValueError("图片像素超过限制：最长边 8192，单张最多 20000000 像素")
    return width * height



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
        check_image_dimensions(image)
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
