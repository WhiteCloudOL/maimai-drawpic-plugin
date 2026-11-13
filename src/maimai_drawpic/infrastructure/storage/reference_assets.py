"""用户持久参考资产，独立于生成图片缓存；所有方法在工作线程调用。"""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional
from uuid import uuid4
import os
import re
import tempfile

from ...domain.references import ReferenceImage, normalize_tag
from ..media.images import validate_image_bytes
from .atomic import write_json_atomically
from .settings import read_json_file


class ReferenceAssetStore:
    MAX_BYTES = 128 * 1024 * 1024
    MAX_ASSETS = 100

    def __init__(self, data_dir: Path) -> None:
        self.root = data_dir / "reference_assets"
        self.index = self.root / "index.json"
        self.lock = RLock()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            if not self.index.exists():
                if self.root.exists() and any(self.root.glob("*.image")):
                    raise ValueError("参考图库索引缺失，已保留图片文件，请恢复索引后重试")
                return {"schema_version": 1, "revision": 0, "default_reference_id": "", "assets": []}
            result = read_json_file(self.index)
            if set(result) != {"schema_version", "revision", "default_reference_id", "assets"} or result["schema_version"] != 1:
                raise ValueError("参考图库索引格式错误，已保留原件")
            if type(result["revision"]) is not int or result["revision"] < 0 or not isinstance(result["assets"], list):
                raise ValueError("参考图库索引内容错误")
            seen = set()
            for item in result["assets"]:
                fields = {"id", "name", "tags", "kind", "version", "size"}
                if not isinstance(item, dict) or set(item) not in (fields, fields | {"prompt"}):
                    raise ValueError("参考图片索引字段错误")
                self._path(item["id"], item["version"])
                if item["id"] in seen or item["kind"] not in {"self", "preset"} or type(item["size"]) is not int or item["size"] <= 0:
                    raise ValueError("参考图片索引不一致")
                self._metadata(item["name"], item["tags"])
                item["prompt"] = self._prompt(item.get("prompt", ""))
                seen.add(item["id"])
            own = [item["id"] for item in result["assets"] if item["kind"] == "self"]
            if (own and result["default_reference_id"] not in own) or (not own and result["default_reference_id"]):
                raise ValueError("默认自我参考图无效")
            return result

    def _path(self, identifier: str, version: str) -> Path:
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("参考图片 ID 无效")
        if not isinstance(version, str) or not re.fullmatch(r"[a-f0-9]{64}", version):
            raise ValueError("参考图片版本无效")
        path = self.root / f"{identifier}-{version}.image"
        if path.is_symlink() or not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("参考图片不属于当前插件")
        return path

    @staticmethod
    def _prompt(prompt: str) -> str:
        if not isinstance(prompt, str) or len(prompt) > 500:
            raise ValueError("参考提示词最多 500 个字符")
        return prompt.strip()

    @staticmethod
    def _metadata(name: str, tags: List[str]) -> List[str]:
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError("参考图片名称必须是 1～80 个字符")
        if not isinstance(tags, list) or len(tags) > 32 or any(not isinstance(tag, str) or len(tag) > 80 for tag in tags):
            raise ValueError("参考 tag 格式或数量无效")
        unique: Dict[str, str] = {}
        for tag in tags:
            if tag.strip():
                unique.setdefault(normalize_tag(tag), tag.strip())
        return list(unique.values())

    def update(self, *, revision: int, operation: str, asset_id: str = "", name: str = "", tags: Optional[List[str]] = None,
               kind: str = "self", raw: Optional[bytes] = None, referenced_ids: Optional[List[str]] = None,
               position: Optional[int] = None, prompt: Optional[str] = None) -> Dict[str, Any]:
        with self.lock:
            current = self.snapshot()
            if type(revision) is not int or revision != current["revision"]:
                raise ValueError("图库已被修改，请刷新后重试")
            target = next((item for item in current["assets"] if item["id"] == asset_id), None)
            written_path: Optional[Path] = None
            if operation == "save":
                if asset_id and target is None:
                    raise ValueError("参考图片不存在")
                clean_tags = self._metadata(name, tags if tags is not None else [])
                clean_prompt = self._prompt(prompt if prompt is not None else target["prompt"] if target else "")
                if kind not in {"self", "preset"} or target and target["kind"] != kind:
                    raise ValueError("参考图片用途归属不可修改")
                if raw is None and target is None:
                    raise ValueError("新增参考图片需要上传真实图片")
                if raw is not None:
                    validate_image_bytes(raw)
                    if len(raw) > 20 * 1024 * 1024:
                        raise ValueError("单张参考图片不能超过 20 MiB")
                    total = sum(self._path(item["id"], item["version"]).stat().st_size for item in current["assets"] if item is not target) + len(raw)
                    if total > self.MAX_BYTES or target is None and len(current["assets"]) >= self.MAX_ASSETS:
                        raise ValueError("参考图库最多 100 张、总容量 128 MiB")
                identifier = asset_id or uuid4().hex
                version = sha256(raw).hexdigest() if raw is not None else target["version"]
                item = {"id": identifier, "name": name.strip(), "tags": clean_tags, "kind": kind, "version": version,
                        "size": len(raw) if raw is not None else target["size"], "prompt": clean_prompt}
                if raw is not None:
                    self.root.mkdir(parents=True, exist_ok=True)
                    destination = self._path(identifier, version)
                    if target is None or target["version"] != version:
                        written_path = destination
                    temporary_path = None
                    try:
                        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as temporary:
                            temporary_path = Path(temporary.name)
                            temporary.write(raw)
                            temporary.flush()
                            os.fsync(temporary.fileno())
                        temporary_path.replace(destination)
                    finally:
                        if temporary_path is not None:
                            temporary_path.unlink(missing_ok=True)
                if target:
                    current["assets"][current["assets"].index(target)] = item
                else:
                    current["assets"].append(item)
                if kind == "self" and not current["default_reference_id"]:
                    current["default_reference_id"] = identifier
            elif operation in {"default", "delete", "move"}:
                if target is None:
                    raise ValueError("参考图片不存在")
                if operation == "default":
                    if target["kind"] != "self":
                        raise ValueError("默认自我参考必须属于自我图库")
                    current["default_reference_id"] = asset_id
                elif operation == "move":
                    if type(position) is not int or not 0 <= position < len(current["assets"]):
                        raise ValueError("参考图片排序位置无效")
                    current["assets"].remove(target)
                    current["assets"].insert(position, target)
                else:
                    if asset_id in (referenced_ids or []):
                        raise ValueError("图片仍被自我配置或图生图预设引用，请先解除引用")
                    current["assets"].remove(target)
                    if current["default_reference_id"] == asset_id:
                        current["default_reference_id"] = next((item["id"] for item in current["assets"] if item["kind"] == "self"), "")
            else:
                raise ValueError("未知图库操作")
            current["revision"] += 1
            try:
                write_json_atomically(self.index, current)
            except BaseException:
                if written_path is not None:
                    written_path.unlink(missing_ok=True)
                raise
            # 索引提交后才清理失去引用的版本；在途任务已持有读取的真实字节。
            keep = {self._path(item["id"], item["version"]).name for item in current["assets"]}
            for path in self.root.glob("*.image"):
                if path.name not in keep:
                    path.unlink()
            return deepcopy(current)

    def read(self, identifier: str, *, kind: str, role: str = "identity", subject: str = "") -> ReferenceImage:
        with self.lock:
            self._path(identifier, "0" * 64)
            item = next((item for item in self.snapshot()["assets"] if item["id"] == identifier), None)
            if item is None or item["kind"] != kind:
                raise ValueError("参考图片不存在或用途归属错误")
            try:
                path = self._path(identifier, item["version"])
                if path.stat().st_size > 20 * 1024 * 1024:
                    raise ValueError("参考图片文件超过 20 MiB")
                raw = path.read_bytes()
            except FileNotFoundError:
                raise ValueError("参考图片文件缺失，请替换图片或恢复原文件") from None
            if len(raw) != item["size"] or sha256(raw).hexdigest() != item["version"]:
                raise ValueError("参考图片内容与索引版本不一致")
            validate_image_bytes(raw)
            return ReferenceImage(raw, kind, role, subject, asset_id=identifier, version=item["version"], note=item["prompt"])

    def select_self(self, tags: List[str], text: str = "") -> str:
        snapshot = self.snapshot()
        own = [item for item in snapshot["assets"] if item["kind"] == "self"]
        if not own:
            raise ValueError("自我参考图库为空，请先上传参考图片")
        requested = {normalize_tag(tag) for tag in tags}
        normalized_text = normalize_tag(text)
        ranked = sorted(enumerate(own), key=lambda pair: (
            -sum(normalize_tag(tag) in requested or normalize_tag(tag) in normalized_text for tag in pair[1]["tags"]),
            pair[0], pair[1]["id"],
        ))
        score = sum(normalize_tag(tag) in requested or normalize_tag(tag) in normalized_text for tag in ranked[0][1]["tags"])
        return ranked[0][1]["id"] if score else snapshot["default_reference_id"]
