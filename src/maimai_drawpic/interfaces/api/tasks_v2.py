"""结构化任务协议；不增加长等待 RPC。"""

from maibot_sdk import API
from typing import Any, Dict, List, Optional

from ...application.workspace.integration import IntegrationTaskService
from .base import WorkspaceAPIBase, integration_api_endpoint


class TaskAPIV2Mixin(WorkspaceAPIBase):
    def _task_api_v2(self) -> IntegrationTaskService:
        return IntegrationTaskService(self._workspace().tasks)

    @API("drawpic_submit_v2", version="2", public=True, description="受理任务，返回持久化句柄与结构化错误")
    @integration_api_endpoint
    async def drawpic_submit_v2(
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
    ) -> Dict[str, Any]:
        return await self._task_api_v2().submit(
            prompt=prompt,
            model=model,
            negative_prompt=negative_prompt,
            style=style,
            task_type=task_type,
            stream_id=stream_id,
            source_images=source_images,
            request_id=request_id,
            openai_compatibility_mode=openai_compatibility_mode,
            novelai_mode=novelai_mode,
            novelai_artist_tags=novelai_artist_tags,
        )

    @API("drawpic_task_v2", version="2", public=True, description="查询状态、结构化错误和图片引用，不返回图片内容")
    @integration_api_endpoint
    async def drawpic_task_v2(self, task_id: str) -> Dict[str, Any]:
        return await self._task_api_v2().task(task_id)

    @API("drawpic_request_v2", version="2", public=True, description="按原 request_id 只读找回任务，不重新提交生成")
    @integration_api_endpoint
    async def drawpic_request_v2(self, request_id: str) -> Dict[str, Any]:
        return await self._task_api_v2().request(request_id)

    @API("drawpic_image_v2", version="2", public=True, description="读取有界图片分块，过期时返回稳定错误码")
    @integration_api_endpoint
    async def drawpic_image_v2(
        self, task_id: str, index: int = 0, kind: str = "original", offset: int = 0
    ) -> Dict[str, Any]:
        return await self._task_api_v2().image(task_id, index, kind, offset)

    @API("drawpic_cancel_v2", version="2", public=True, description="请求取消，返回实际状态，不承诺上游撤单")
    @integration_api_endpoint
    async def drawpic_cancel_v2(self, task_id: str) -> Dict[str, Any]:
        return await self._task_api_v2().cancel(task_id)

    @API("drawpic_tasks_v2", version="2", public=True, description="恢复和管理任务，不夹带缩略图")
    @integration_api_endpoint
    async def drawpic_tasks_v2(self, page: int = 1, status: str = "", search: str = "") -> Dict[str, Any]:
        return await self._task_api_v2().listing(page, status, search)
