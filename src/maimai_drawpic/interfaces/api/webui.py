"""只供宿主扩展页面绑定的私有 API。"""

from maibot_sdk import API
from typing import Any, Dict
import asyncio
import base64

from .base import WorkspaceAPIBase, workspace_endpoint
from ...infrastructure.storage.platforms import parse_json_object


class WebUIAPIMixin(WorkspaceAPIBase):
    @API("workspace_references", version="1")
    @workspace_endpoint
    async def workspace_references(self) -> Dict[str, Any]:
        return await asyncio.to_thread(self._workspace().tasks.references.snapshot)

    @API("workspace_reference_image", version="1")
    @workspace_endpoint
    async def workspace_reference_image(self, asset_id: str) -> Dict[str, Any]:
        from ...infrastructure.storage.results import ImageResultStore

        def preview() -> Dict[str, str]:
            store = self._workspace().tasks.references
            item = next((item for item in store.snapshot()["assets"] if item["id"] == asset_id), None)
            if item is None:
                raise ValueError("参考图片不存在")
            image = store.read(asset_id, kind=item["kind"])
            raw = ImageResultStore._preview(image.raw, 480, 40000)
            return {"preview": "data:image/webp;base64," + base64.b64encode(raw).decode("ascii")}

        return await asyncio.to_thread(preview)

    @API("workspace_reference_update", version="1")
    @workspace_endpoint
    async def workspace_reference_update(self, operation: str, revision: int, asset_json: str = "{}", source_id: str = "") -> Dict[str, Any]:
        workspace = self._workspace()
        values = parse_json_object(asset_json)
        if values.keys() - {"asset_id", "name", "tags", "kind", "position", "prompt"}:
            raise ValueError("参考图片包含未知字段")

        async def update() -> Dict[str, Any]:
            config = workspace.get_config()
            referenced = list(config.general.references.self_reference_ids)
            referenced.extend(binding.asset_id for preset in config.style.presets for binding in preset.reference_bindings)
            raw = (await workspace.tasks._sources([source_id], []))[0] if source_id else None
            return await asyncio.to_thread(workspace.tasks.references.update, operation=operation, revision=revision,
                                           raw=raw, referenced_ids=referenced, **values)

        return await workspace._run_transaction(update)

    @API("workspace_provider_models", version="1")
    @workspace_endpoint
    async def workspace_provider_models(self, provider_json: str) -> Dict[str, Any]:
        return await self._workspace().discover_models(provider_json)

    @API("workspace_bootstrap", version="1")
    @workspace_endpoint
    async def workspace_bootstrap(self) -> Dict[str, Any]:
        return await self._workspace().bootstrap()

    @API("workspace_provider_save", version="1")
    @workspace_endpoint
    async def workspace_provider_save(self, provider_json: str, revision: int) -> Dict[str, Any]:
        return await self._workspace().save_provider(provider_json, revision)

    @API("workspace_provider_delete", version="1")
    @workspace_endpoint
    async def workspace_provider_delete(self, provider_id: str, revision: int) -> Dict[str, Any]:
        return await self._workspace().delete_provider(provider_id, revision)

    @API("workspace_provider_enabled", version="1")
    @workspace_endpoint
    async def workspace_provider_enabled(self, provider_id: str, enabled: bool, revision: int) -> Dict[str, Any]:
        return await self._workspace().set_provider_enabled(provider_id, enabled, revision)

    @API("workspace_settings_save", version="1")
    @workspace_endpoint
    async def workspace_settings_save(self, config_json: str, revision: int) -> Dict[str, Any]:
        return await self._workspace().save_settings(config_json, revision)

    @API("workspace_tasks", version="1")
    @workspace_endpoint
    async def workspace_tasks(self, page: int = 1, status: str = "", search: str = "") -> Dict[str, Any]:
        return await self._workspace().tasks.tasks(page=page, status=status, search=search)

    @API("workspace_task", version="1")
    @workspace_endpoint
    async def workspace_task(self, task_id: str) -> Dict[str, Any]:
        return await self._workspace().tasks.detail(task_id, include_prompt=True)

    @API("workspace_image", version="1")
    @workspace_endpoint
    async def workspace_image(self, task_id: str, index: int = 0, thumbnail: bool = False) -> Dict[str, Any]:
        return await asyncio.to_thread(self._workspace().tasks.results.preview, task_id, index, thumbnail)

    @API("workspace_original", version="1")
    @workspace_endpoint
    async def workspace_original(self, task_id: str, index: int = 0, offset: int = 0) -> Dict[str, Any]:
        return await asyncio.to_thread(self._workspace().tasks.results.original_chunk, task_id, index, offset)

    @API("workspace_source", version="1")
    @workspace_endpoint
    async def workspace_source(self, upload_id: str) -> Dict[str, Any]:
        return await self._workspace().tasks.claim_source(upload_id)

    @API("workspace_submit", version="1")
    @workspace_endpoint
    async def workspace_submit(self, request_json: str) -> Dict[str, Any]:
        values = parse_json_object(request_json)
        allowed = {"prompt", "model", "negative_prompt", "style", "task_type", "stream_id", "source_ids", "request_id", "reference_options_json"}
        if values.keys() - allowed:
            raise ValueError("绘图请求包含未知参数")
        return await self._workspace().tasks.submit(**values)

    @API("workspace_cancel", version="1")
    @workspace_endpoint
    async def workspace_cancel(self, task_id: str) -> Dict[str, Any]:
        return await self._workspace().tasks.cancel(task_id)

    @API("workspace_logs", version="1")
    @workspace_endpoint
    async def workspace_logs(
        self, task_id: str = "", level: str = "", limit: int = 120, cursor: str = ""
    ) -> Dict[str, Any]:
        return await asyncio.to_thread(self._workspace().logs.query, task_id, level, limit, cursor)

    @API("workspace_streams", version="1")
    @workspace_endpoint
    async def workspace_streams(self, platform: str = "qq") -> Dict[str, Any]:
        return await self._workspace().streams(platform)
