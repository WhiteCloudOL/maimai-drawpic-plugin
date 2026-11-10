"""tools/status.py 的插件组件。"""

from maibot_sdk import Tool
from typing import Any

from ..chat.access import chat_access_endpoint
from .schemas import DRAW_STATUS_TOOL_PARAMETERS_SCHEMA


class StatusToolMixin:
    """tools/status.py 对应的插件行为。"""

    @Tool(
        "draw_status",
        description="查询最近一个绘图后台任务，或查询指定 task_id 的绘图任务状态",
        parameters=DRAW_STATUS_TOOL_PARAMETERS_SCHEMA,
    )
    @chat_access_endpoint
    async def handle_draw_status(
        self,
        user_id: str = "",
        task_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """查询后台绘图任务状态。"""

        context = self._extract_invocation_context(kwargs=kwargs, llm_user_id=user_id)
        live_context = await self._require_stream_service().resolve_live_stream_context(
            stream_id=context["stream_id"],
            user_id=context["user_id"],
            group_id=context["group_id"],
            platform=context["platform"],
        )
        runtime_context = self._merge_resolved_runtime_context(
            live_context,
            user_id=context["user_id"],
            group_id=context["group_id"],
            platform=context["platform"],
        )
        if not runtime_context["stream_id"]:
            return {"success": False, "message": "当前聊天流不可用，无法查询绘图任务状态"}
        return self._require_draw_service().get_task_status_payload(
            stream_id=runtime_context["stream_id"],
            task_id=task_id,
            user_id=runtime_context["user_id"],
            group_id=runtime_context["group_id"],
            platform=runtime_context["platform"],
        )
