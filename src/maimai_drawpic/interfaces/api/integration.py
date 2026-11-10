"""当前 MaiBot 实例内的公开 SDK API；不提供网络监听或配置密钥接口。"""

from maibot_sdk import API
from typing import Any, Dict, List, Optional
import asyncio

from .base import WorkspaceAPIBase, integration_api_endpoint


class IntegrationAPIMixin(WorkspaceAPIBase):
    @API("drawpic_models", version="1", public=True, description="查询可用图片模型与任务能力")
    @integration_api_endpoint
    async def drawpic_models(self) -> Dict[str, Any]:
        return self._workspace().models()

    @API("drawpic_submit", version="1", public=True, description="提交文生图或图生图，立即返回任务 ID")
    @integration_api_endpoint
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
    ) -> Dict[str, Any]:
        return await self._workspace().tasks.submit(
            prompt=prompt,
            model=model,
            negative_prompt=negative_prompt,
            style=style,
            task_type=task_type,
            stream_id=stream_id,
            source_images=source_images,
            request_id=request_id,
            origin="plugin",
        )

    @API("drawpic_task", version="1", public=True, description="只读查询当前实例的任务状态和图片信息")
    @integration_api_endpoint
    async def drawpic_task(self, task_id: str) -> Dict[str, Any]:
        return await self._workspace().tasks.detail(task_id)

    @API("drawpic_tasks", version="1", public=True, description="分页查询当前实例的绘图任务")
    @integration_api_endpoint
    async def drawpic_tasks(self, page: int = 1, status: str = "", search: str = "") -> Dict[str, Any]:
        return await self._workspace().tasks.tasks(page=page, status=status, search=search)

    @API("drawpic_image", version="1", public=True, description="读取任务缩略图、预览或有界原图分块")
    @integration_api_endpoint
    async def drawpic_image(
        self, task_id: str, index: int = 0, kind: str = "preview", offset: int = 0
    ) -> Dict[str, Any]:
        results = self._workspace().tasks.results
        if kind == "original":
            return await asyncio.to_thread(results.original_chunk, task_id, index, offset)
        if kind not in {"preview", "thumbnail"}:
            raise ValueError("图片类型只能是 preview、thumbnail 或 original")
        return await asyncio.to_thread(results.preview, task_id, index, kind == "thumbnail")

    @API("drawpic_cancel", version="1", public=True, description="取消当前实例仍在执行的任务")
    @integration_api_endpoint
    async def drawpic_cancel(self, task_id: str) -> Dict[str, Any]:
        return await self._workspace().tasks.cancel(task_id)

    @API("drawpic_presets", version="1", public=True, description="查询、保存或删除全平台风格预设")
    @integration_api_endpoint
    async def drawpic_presets(self, operation: str = "list", name: str = "", preset_json: str = "") -> Dict[str, Any]:
        return await self._workspace().presets(operation, name, preset_json)
