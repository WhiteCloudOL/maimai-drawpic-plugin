"""公开参考资源与限定设置管理，复用工作台事务和持久图库。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional, TYPE_CHECKING
import asyncio
import base64
import re

from ...domain.configuration.models import DrawpicConfig
from ...domain.task_errors import TaskRequestError
from ...infrastructure.media.images import detect_mime_type
from ...infrastructure.storage.platforms import _validate_fields
from ...infrastructure.storage.results import ImageResultStore

if TYPE_CHECKING:
    from .service import WorkspaceService


SELF_FIELDS = {"self_reference_enabled", "self_names", "self_keywords", "self_reference_ids"}
STYLE_FIELDS = {"image_edit_presets_enabled", "default_style", "default_image_edit_preset"}


class ReferenceAPIService:
    def __init__(self, workspace: WorkspaceService) -> None:
        self.workspace = workspace
        self.assets = workspace.tasks.references

    @staticmethod
    def _asset(snapshot: Dict[str, Any], asset_id: str) -> Dict[str, Any]:
        if not isinstance(asset_id, str):
            raise ValueError("参考图片 ID 必须为文本")
        item = next((item for item in snapshot["assets"] if item["id"] == asset_id), None)
        if item is None:
            raise TaskRequestError("REFERENCE_NOT_FOUND", "参考图片不存在")
        return {**item, "default": item["id"] == snapshot["default_reference_id"]}

    async def listing(self, page: int = 1, kind: str = "", search: str = "") -> Dict[str, Any]:
        if type(page) is not int or not 1 <= page <= 10:
            raise ValueError("参考目录分页必须为 1～10")
        if not isinstance(kind, str) or kind not in {"", "self", "preset"}:
            raise ValueError("参考类型只能是 self 或 preset，留空查询全部")
        if not isinstance(search, str) or len(search) > 200:
            raise ValueError("参考搜索词必须为 200 字符以内的文本")
        snapshot = await asyncio.to_thread(self.assets.snapshot)
        matching = [item for item in snapshot["assets"] if (not kind or item["kind"] == kind)
                    and search.casefold() in " ".join([item["name"], *item["tags"]]).casefold()]
        refs = self.workspace.get_config().general.references
        return {"revision": snapshot["revision"], "default_reference_id": snapshot["default_reference_id"],
                "page": page, "page_size": 12, "total": len(matching),
                "assets": [self._asset(snapshot, item["id"]) for item in matching[(page - 1) * 12:page * 12]],
                "self_reference_enabled": refs.self_reference_enabled,
                "allow_chat_material_search": refs.allow_chat_material_search,
                "chat_material_search_limit": refs.chat_material_search_limit, "material_model": refs.material_model,
                "allow_web_material_search": refs.allow_web_material_search,
                "web_search_provider": refs.web_search_provider, "multi_reference_confirmed": refs.multi_reference_confirmed}

    async def get(self, asset_id: str) -> Dict[str, Any]:
        snapshot = await asyncio.to_thread(self.assets.snapshot)
        return {"asset": self._asset(snapshot, asset_id), "revision": snapshot["revision"],
                "default_reference_id": snapshot["default_reference_id"]}

    async def update(self, operation: str, revision: int, reference: Dict[str, Any],
                     image_base64: Optional[str] = None) -> Dict[str, Any]:
        if not isinstance(operation, str) or operation not in {"save", "delete", "default", "move"}:
            raise ValueError("参考图操作只能是 save、delete、default 或 move")
        if type(revision) is not int or revision < 0:
            raise ValueError("必须提供当前图库的 revision")
        allowed = {"asset_id", "name", "tags", "kind", "prompt"} if operation == "save" else {"asset_id", "position"} if operation == "move" else {"asset_id"}
        if reference.keys() - allowed:
            raise ValueError("参考图片包含该操作不支持的字段")
        if "asset_id" in reference and not isinstance(reference["asset_id"], str):
            raise ValueError("参考图片 ID 必须为文本")
        raw = None
        if image_base64 is not None:
            if operation != "save":
                raise ValueError("只有 save 操作可以上传图片")
            raw = (await self.workspace.tasks._sources([], [image_base64]))[0]
            if await asyncio.to_thread(detect_mime_type, raw) not in {"image/png", "image/jpeg", "image/webp"}:
                raise ValueError("参考图片仅支持 PNG、JPEG 或 WebP")

        async def commit() -> Dict[str, Any]:
            snapshot = await asyncio.to_thread(self.assets.snapshot)
            if revision != snapshot["revision"]:
                raise TaskRequestError("REFERENCE_REVISION_CONFLICT", "图库已更新，请读取后重新确认本次修改")
            values = deepcopy(reference)
            identifier = values.get("asset_id", "")
            if operation == "save" and identifier:
                previous = self._asset(snapshot, identifier)
                values = {**{key: previous[key] for key in ("name", "tags", "kind", "prompt")}, **values}
            result = await self.workspace._update_reference(operation, revision, values, raw)
            asset_id = identifier or result["assets"][-1]["id"]
            return {"saved": True, "revision": result["revision"], "asset_id": asset_id,
                    "default_reference_id": result["default_reference_id"],
                    "asset": None if operation == "delete" else self._asset(result, asset_id),
                    "deleted": operation == "delete"}

        return await self.workspace._run_transaction(commit)

    async def image(self, asset_id: str, kind: str, version: str, offset: int) -> Dict[str, Any]:
        if not isinstance(version, str) or version and not re.fullmatch(r"[a-f0-9]{64}", version):
            raise ValueError("asset_version 必须是图片元数据中的 SHA-256 版本")
        if not isinstance(kind, str) or kind not in {"preview", "original"}:
            raise ValueError("参考图片读取类型只能是 preview 或 original")
        if kind == "original":
            try:
                return await asyncio.to_thread(self.assets.original_chunk, asset_id, version, offset)
            except FileNotFoundError:
                raise TaskRequestError("REFERENCE_NOT_FOUND", "参考图片文件缺失，请恢复或替换图片") from None
        if offset != 0 or type(offset) is not int:
            raise ValueError("预览图不使用分块偏移")

        def preview() -> Dict[str, Any]:
            with self.assets.lock:
                snapshot = self.assets.snapshot()
                asset = self._asset(snapshot, asset_id)
                if version and version != asset["version"]:
                    raise TaskRequestError("REFERENCE_VERSION_CONFLICT", "参考图片已被替换")
                image = self.assets.read(asset_id, kind=asset["kind"])
            raw = ImageResultStore._preview(image.raw, 480, 40000)
            return {"asset_id": asset_id, "version": image.version, "mime": "image/webp",
                    "data_url": "data:image/webp;base64," + base64.b64encode(raw).decode("ascii")}

        return await asyncio.to_thread(preview)

    async def settings(self) -> Dict[str, Any]:
        snapshot = await asyncio.to_thread(self.workspace.store.public_snapshot)
        refs = snapshot["settings"]["general"]["references"]
        return {"revision": snapshot["revision"], "runtime_refresh_pending": self.workspace.runtime_refresh_pending,
                "recovery_pending": self.workspace.store.recovery_pending, "settings": {
            **{key: refs[key] for key in SELF_FIELDS | {"multi_reference_confirmed"}},
            **{key: snapshot["settings"]["style"][key] for key in STYLE_FIELDS},
        }}

    async def set_settings(self, patch: Dict[str, Any], revision: int, confirm_multi_reference: bool) -> Dict[str, Any]:
        if patch.keys() - SELF_FIELDS - STYLE_FIELDS or not patch:
            raise ValueError("仅可修改自我参考设置、预设开关及默认预设，且补丁不能为空")
        if type(revision) is not int or revision < 0 or type(confirm_multi_reference) is not bool:
            raise ValueError("配置修订号或多图确认参数无效")

        async def commit() -> Dict[str, Any]:
            if revision != self.workspace.store.revision:
                raise TaskRequestError("CONFIG_REVISION_CONFLICT", "配置已更新，请读取后重新确认本次修改")
            base = await asyncio.to_thread(self.workspace.store.effective_config, self.workspace.get_config().model_dump(mode="json"))
            current = base.model_dump(mode="json")
            refs = current["general"]["references"]
            old_ids = refs["self_reference_ids"]
            refs.update({key: value for key, value in patch.items() if key in SELF_FIELDS})
            current["style"].update({key: value for key, value in patch.items() if key in STYLE_FIELDS})
            if old_ids != refs["self_reference_ids"]:
                refs["multi_reference_confirmed"] = False
            if confirm_multi_reference:
                refs["multi_reference_confirmed"] = True
            # SDK 配置模型默认允许类型转换，公开写入复用工作台的严格字段校验。
            _validate_fields(type(base.general.references), refs)
            if refs["self_reference_enabled"] and len(refs["self_reference_ids"]) > 1 and not refs["multi_reference_confirmed"]:
                raise TaskRequestError("MULTI_REFERENCE_CONFIRMATION_REQUIRED", "请先由用户确认模型支持多图参考")
            checked = DrawpicConfig.model_validate(current)
            await self.workspace._validate_reference_assets(checked)
            updated = await asyncio.to_thread(self.workspace.store.save_common,
                                            {"general": current["general"], "style": current["style"]}, current, revision)
            status = await self.workspace._refresh_committed(updated)
            return {**await self.settings(), **status}

        return await self.workspace._run_transaction(commit)
