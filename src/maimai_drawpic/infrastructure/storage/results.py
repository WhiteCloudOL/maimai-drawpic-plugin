"""保存审核通过的图片，并提供有界预览与原图读取。"""

from PIL import Image, ImageOps
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, List, Optional, Set
import base64
import json
import re

from ...domain.task_errors import TaskRequestError
from ..media.images import check_image_dimensions, stored_image_format
from ..media.collection import validate_result_images
from .atomic import write_json_atomically
from .retention import ArtifactRetention
from ..concurrency import synchronized


class ImageResultStore:
    def __init__(
        self,
        data_dir: Path,
        protected_tasks: Optional[Callable[[], Set[str]]] = None,
        *,
        runtime_dir: Optional[Path] = None,
    ) -> None:
        self.root = (runtime_dir if runtime_dir is not None else data_dir) / "results"
        self.legacy_root = data_dir / "results"
        self.retention = ArtifactRetention(data_dir, runtime_dir)
        self._lock = RLock()
        self.protected_tasks = protected_tasks

    def _directory(self, task_id: str) -> Path:
        if not isinstance(task_id, str) or not re.fullmatch(r"[a-f0-9]{12}", task_id):
            raise ValueError("任务 ID 格式错误")
        root = self.root
        if not (root / task_id).exists() and (self.legacy_root / task_id).exists():
            root = self.legacy_root
        path = root / task_id
        if root.is_symlink() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("图片目录不安全")
        return path

    @staticmethod
    def _preview(raw: bytes, edge: int, max_bytes: int) -> bytes:
        with Image.open(BytesIO(raw)) as original:
            check_image_dimensions(original)
            original.draft("RGB", (edge, edge))
            image = ImageOps.exif_transpose(original).convert("RGBA" if "A" in original.getbands() else "RGB")
            image.thumbnail((edge, edge))
            quality = 85
            while True:
                output = BytesIO()
                image.save(output, format="WEBP", quality=quality, method=4)
                if output.tell() <= max_bytes:
                    return output.getvalue()
                if quality > 45:
                    quality -= 10
                else:
                    image.thumbnail((max(1, image.width * 3 // 4), max(1, image.height * 3 // 4)))

    @synchronized
    def save(self, task_id: str, images: List[bytes]) -> int:
        # 先压缩并计算精确占用，再为整个任务预留容量，避免估算导致误清理或超限。
        validate_result_images(images)
        prepared = []
        for raw in images:
            extension = stored_image_format(raw)
            prepared.append((extension, raw, self._preview(raw, 320, 15000), self._preview(raw, 1400, 280000)))
        incoming = sum(len(raw) + len(thumb) + len(preview) for _, raw, thumb, preview in prepared) + 2048 * len(images)
        self.retention.prune_results(
            {task_id} | (self.protected_tasks() if self.protected_tasks is not None else set()), incoming
        )
        directory = self._directory(task_id)
        directory.mkdir(parents=True, exist_ok=False)
        records = []
        for index, (extension, raw, thumb, preview) in enumerate(prepared):
            filename = f"{index}.{extension}"
            (directory / filename).write_bytes(raw)
            (directory / f"{index}.thumb.webp").write_bytes(thumb)
            (directory / f"{index}.preview.webp").write_bytes(preview)
            with Image.open(BytesIO(raw)) as image:
                records.append(
                    {
                        "file": filename,
                        "width": image.width,
                        "height": image.height,
                        "size": len(raw),
                        "mime": f"image/{'jpeg' if extension in {'jpg', 'jpeg'} else extension}",
                    }
                )
        write_json_atomically(directory / "manifest.json", {"images": records})
        return len(records)

    @synchronized
    def images(self, task_id: str) -> List[Dict[str, Any]]:
        path = self._directory(task_id) / "manifest.json"
        if not path.exists():
            return []
        records = json.loads(path.read_text(encoding="utf-8"))["images"]
        expires_at = datetime.fromtimestamp(
            path.stat().st_mtime + self.retention.RESULT_MAX_AGE, timezone.utc
        ).isoformat()
        return [
            {"index": index, "expires_at": expires_at, **{key: value for key, value in item.items() if key != "file"}}
            for index, item in enumerate(records)
        ]

    @synchronized
    def preview(self, task_id: str, index: int = 0, thumbnail: bool = False) -> Dict[str, Any]:
        records = self.images(task_id)
        if type(index) is not int or not 0 <= index < len(records):
            raise ValueError("该任务没有这张图片；图片已过期或旧任务未保存图片结果")
        suffix = "thumb" if thumbnail else "preview"
        directory = self._directory(task_id)
        path = directory / f"{index}.{suffix}.webp"
        mime = "image/webp"
        if not path.exists():
            # 历史 JPEG 缓存保留读取能力，后续和 WebP 一起参与容量清理。
            path = directory / f"{index}.{suffix}.jpg"
            mime = "image/jpeg"
        data = path.read_bytes()
        return {
            "index": index,
            "data_url": f"data:{mime};base64," + base64.b64encode(data).decode("ascii"),
            **records[index],
        }

    @synchronized
    def original_chunk(self, task_id: str, index: int, offset: int) -> Dict[str, Any]:
        if type(offset) is not int or offset < 0:
            raise ValueError("图片读取偏移无效")
        directory = self._directory(task_id)
        if not self.images(task_id):
            raise ValueError("图片结果已清理或不存在")
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["images"]
        if type(index) is not int or not 0 <= index < len(manifest):
            raise ValueError("图片索引无效")
        record = manifest[index]
        filename = record["file"]
        if Path(filename).name != filename:
            raise ValueError("图片清单包含不安全路径")
        path = directory / filename
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("图片文件不安全")
        if path.stat().st_size != record["size"]:
            raise TaskRequestError("RESULT_UNAVAILABLE", "缓存原图与清单大小不一致")
        if offset >= record["size"]:
            raise ValueError("图片读取偏移超出文件")
        with path.open("rb") as handle:
            handle.seek(offset)
            expected = min(192 * 1024, record["size"] - offset)
            chunk = handle.read(expected)
        if len(chunk) != expected:
            raise TaskRequestError("RESULT_UNAVAILABLE", "缓存原图分块不完整")
        return {
            "data": base64.b64encode(chunk).decode("ascii"),
            "offset": offset,
            "next_offset": offset + len(chunk),
            "size": record["size"],
            "mime": record["mime"],
            "filename": f"{task_id}-{index + 1}{path.suffix}",
            "done": offset + len(chunk) >= record["size"],
        }

    @synchronized
    def cleanup(self, protected: Set[str]) -> Dict[str, int]:
        return self.retention.prune_results(protected)

    @synchronized
    def configure_limits(self, image_max_mb: int, upload_max_mb: int) -> None:
        self.retention.RESULT_MAX_BYTES = image_max_mb * 1024 * 1024
        self.retention.INPUT_MAX_BYTES = upload_max_mb * 1024 * 1024
