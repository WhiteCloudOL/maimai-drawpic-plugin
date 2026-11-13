"""绘图偏好与风格预设公开 API。"""

from maibot_sdk import API
from typing import Any, Dict
import asyncio

from ...application.workspace.preferences import IntegrationPreferenceService
from ...infrastructure.storage.platforms import parse_json_object
from .base import WorkspaceAPIBase, integration_api_endpoint, integration_endpoint


class PreferenceAPIMixin(WorkspaceAPIBase):
    @API("drawpic_references_v2", version="2", public=True, description="只读查询自我参考目录与素材来源状态，不返回图片内容")
    @integration_api_endpoint
    @integration_endpoint
    async def drawpic_references_v2(self, page: int = 1) -> Dict[str, Any]:
        if type(page) is not int or not 1 <= page <= 10:
            raise ValueError("参考目录分页无效")
        workspace = self._workspace()
        snapshot = await asyncio.to_thread(workspace.tasks.references.snapshot)
        assets = [item for item in snapshot["assets"] if item["kind"] == "self"]
        config = workspace.get_config().general.references
        return {"page": page, "page_size": 12, "total": len(assets),
                "assets": [{"id": item["id"], "name": item["name"], "tags": item["tags"],
                            "default": item["id"] == snapshot["default_reference_id"]} for item in assets[(page - 1) * 12:page * 12]],
                "self_reference_enabled": config.self_reference_enabled,
                "allow_chat_material_search": config.allow_chat_material_search,
                "allow_web_material_search": config.allow_web_material_search,
                "multi_reference_confirmed": config.multi_reference_confirmed}

    def _preference_api(self) -> IntegrationPreferenceService:
        return IntegrationPreferenceService(self._workspace().tasks.get_service().stream_service, self._require_session_store)

    @API("drawpic_preferences_v2", version="2", public=True, description="读取真实聊天流的绘图偏好")
    @integration_api_endpoint
    @integration_endpoint
    async def drawpic_preferences_v2(self, stream_id: str) -> Dict[str, Any]:
        return await self._preference_api().preferences(stream_id)

    @API("drawpic_preferences_set_v2", version="2", public=True, description="部分更新绘图偏好，不修改平台或密钥")
    @integration_api_endpoint
    @integration_endpoint
    async def drawpic_preferences_set_v2(self, stream_id: str, preference_json: str) -> Dict[str, Any]:
        if not isinstance(preference_json, str):
            raise ValueError("preference_json 必须为 JSON 文本")
        return await self._preference_api().preferences(stream_id, parse_json_object(preference_json))

    @API("drawpic_presets_v2", version="2", public=True, description="查询、保存或删除风格预设，返回结构化错误")
    @integration_api_endpoint
    @integration_endpoint
    async def drawpic_presets_v2(self, operation: str = "list", name: str = "", preset_json: str = "") -> Dict[str, Any]:
        if not all(isinstance(value, str) for value in (operation, name, preset_json)):
            raise ValueError("预设操作与名称必须为文本")
        return await self._workspace().presets(operation, name, preset_json)
