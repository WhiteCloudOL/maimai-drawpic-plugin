"""实例内统一绘图 API，复用工作台任务、资源及持久化服务。"""

from maibot_sdk import API
from typing import Any, Dict, List, Optional
import asyncio
import json

from ...application.workspace.integration import IntegrationTaskService
from ...application.workspace.preferences import IntegrationPreferenceService
from ...infrastructure.storage.platforms import parse_json_object
from .base import WorkspaceAPIBase, drawing_endpoint


def _object_json(value: Dict[str, Any], label: str) -> str:
    if not isinstance(value, dict):
        raise ValueError(f"{label}必须为对象")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError(f"{label}必须是可序列化的 JSON 对象") from None
    parse_json_object(encoded)
    return encoded


class DrawingAPIMixin(WorkspaceAPIBase):
    def _drawing_tasks(self) -> IntegrationTaskService:
        return IntegrationTaskService(self._workspace().tasks)

    @API("drawpic_models", public=True, description="查询绘图模型、任务能力和源图限制")
    @drawing_endpoint()
    async def drawpic_models(self) -> Dict[str, Any]:
        return self._workspace().models()

    @API("drawpic_submit", public=True, description="提交后台绘图，返回持久任务句柄与受理状态")
    @drawing_endpoint("submit")
    async def drawpic_submit(
        self,
        prompt: str,
        model: str = "",
        negative_prompt: str = "",
        style: str = "",
        task_type: str = "draw",
        stream_id: str = "",
        source_images: Optional[List[str]] = None,
        request_id: str = "",
        openai_compatibility_mode: str = "",
        novelai_mode: str = "",
        novelai_artist_tags: Optional[str] = None,
        reference_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return await self._drawing_tasks().submit(
            prompt=prompt, model=model, negative_prompt=negative_prompt, style=style,
            task_type=task_type, stream_id=stream_id, source_images=source_images,
            request_id=request_id, openai_compatibility_mode=openai_compatibility_mode,
            novelai_mode=novelai_mode, novelai_artist_tags=novelai_artist_tags,
            reference_options_json=_object_json(reference_options, "参考选项") if reference_options is not None else "",
        )

    @API("drawpic_task", public=True, description="查询任务、结构化错误、图片引用及投递状态")
    @drawing_endpoint("task")
    async def drawpic_task(self, task_id: str) -> Dict[str, Any]:
        return await self._drawing_tasks().task(task_id)

    @API("drawpic_request", public=True, description="按原 request_id 只读找回任务，不重新生成")
    @drawing_endpoint("task")
    async def drawpic_request(self, request_id: str) -> Dict[str, Any]:
        return await self._drawing_tasks().request(request_id)

    @API("drawpic_tasks", public=True, description="分页查询绘图任务，不返回图片内容")
    @drawing_endpoint("listing")
    async def drawpic_tasks(self, page: int = 1, status: str = "", search: str = "") -> Dict[str, Any]:
        return await self._drawing_tasks().listing(page, status, search)

    @API("drawpic_image", public=True, description="读取原图分块、预览或缩略图")
    @drawing_endpoint("task")
    async def drawpic_image(self, task_id: str, index: int = 0, kind: str = "original", offset: int = 0) -> Dict[str, Any]:
        return await self._drawing_tasks().image(task_id, index, kind, offset)

    @API("drawpic_cancel", public=True, description="取消本地后台等待，返回实际任务状态")
    @drawing_endpoint("cancel")
    async def drawpic_cancel(self, task_id: str) -> Dict[str, Any]:
        return await self._drawing_tasks().cancel(task_id)

    @API("drawpic_preferences", public=True, description="读取真实聊天流的绘图偏好")
    @drawing_endpoint()
    async def drawpic_preferences(self, stream_id: str) -> Dict[str, Any]:
        service = IntegrationPreferenceService(self._workspace().tasks.get_service().stream_service, self._require_session_store)
        return await service.preferences(stream_id)

    @API("drawpic_preferences_set", public=True, description="部分更新会话绘图偏好，省略字段保持原值")
    @drawing_endpoint()
    async def drawpic_preferences_set(self, stream_id: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
        values = parse_json_object(_object_json(preferences, "绘图偏好"))
        service = IntegrationPreferenceService(self._workspace().tasks.get_service().stream_service, self._require_session_store)
        return await service.preferences(stream_id, values)

    @API("drawpic_presets", public=True, description="查询、保存、重命名或删除两类绘图预设")
    @drawing_endpoint()
    async def drawpic_presets(self, operation: str = "list", name: str = "", preset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not all(isinstance(value, str) for value in (operation, name)):
            raise ValueError("预设操作与名称必须为文本")
        return await self._workspace().presets(operation, name, _object_json(preset, "绘图预设") if preset is not None else "")

    @API("drawpic_references", public=True, description="只读查询自我参考目录及素材设置，不返回图片或密钥")
    @drawing_endpoint()
    async def drawpic_references(self, page: int = 1) -> Dict[str, Any]:
        if type(page) is not int or not 1 <= page <= 10:
            raise ValueError("参考目录分页无效")
        workspace = self._workspace()
        snapshot = await asyncio.to_thread(workspace.tasks.references.snapshot)
        assets = [item for item in snapshot["assets"] if item["kind"] == "self"]
        config = workspace.get_config().general.references
        return {
            "page": page, "page_size": 12, "total": len(assets),
            "assets": [{"id": item["id"], "name": item["name"], "tags": item["tags"],
                        "default": item["id"] == snapshot["default_reference_id"]}
                       for item in assets[(page - 1) * 12:page * 12]],
            "self_reference_enabled": config.self_reference_enabled,
            "allow_chat_material_search": config.allow_chat_material_search,
            "chat_material_search_limit": config.chat_material_search_limit,
            "material_model": config.material_model,
            "allow_web_material_search": config.allow_web_material_search,
            "web_search_provider": config.web_search_provider,
            "multi_reference_confirmed": config.multi_reference_confirmed,
        }
