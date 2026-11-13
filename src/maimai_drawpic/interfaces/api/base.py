"""薄接口层共享工作台服务入口。"""

from functools import wraps
from inspect import signature
from typing import Any, Awaitable, Callable, Dict, Optional

from ...application.workspace.service import WorkspaceService
from ...application.access import access_restricted, require_chat_access, require_integration_api
from ...domain.task_errors import TaskRequestError, task_error
from ...infrastructure.observability.redaction import outward_error


class WorkspaceAPIBase:
    _workspace_service: Optional[WorkspaceService]

    def _workspace(self) -> WorkspaceService:
        if self._workspace_service is None:
            raise RuntimeError("绘图工作台尚未完成加载")
        return self._workspace_service


def integration_api_endpoint(handler: Callable[..., Awaitable[Dict[str, Any]]]) -> Callable:
    """公开联动入口独立开关；v2 保持结构化的拒绝响应。"""
    parameters = signature(handler)

    @wraps(handler)
    async def invoke(self: Any, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        values = parameters.bind(self, *args, **kwargs).arguments
        workspace = self._workspace()
        try:
            config = workspace.get_config().general
            require_integration_api(config, workspace.ctx.logger, handler.__name__)
            stream_id = values.get("stream_id", "")
            if isinstance(stream_id, str) and stream_id.strip() and access_restricted(config):
                context = await workspace.tasks.get_service().stream_service.existing_stream_context(stream_id.strip())
                require_chat_access(workspace.get_config().general, context, workspace.ctx.logger)
        except PermissionError as exc:
            if not handler.__name__.endswith("_v2"):
                raise
            result = {
                "task_id": None, "status": "not_accepted", "images": [], "retry_after_ms": 0,
                "error": task_error("PERMISSION_DENIED", str(exc)),
            }
            if handler.__name__ == "drawpic_submit_v2":
                result.update(accepted=False, request_id=values.get("request_id", ""))
            return result
        return await handler(self, *args, **kwargs)

    return invoke


def workspace_endpoint(handler: Callable[..., Awaitable[Dict[str, Any]]]) -> Callable:
    """可预期的输入错误回传页面；运行异常继续交由 Runner 完整记录。"""

    @wraps(handler)
    async def invoke(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        try:
            return await handler(*args, **kwargs)
        except (ValueError, PermissionError) as exc:
            return {"__workspace_error__": outward_error(args[0], exc)}

    return invoke


def integration_endpoint(handler: Callable[..., Awaitable[Dict[str, Any]]]) -> Callable:
    """公开资源 API 返回稳定输入错误；未知运行异常仍由 Runner 记录。"""

    @wraps(handler)
    async def invoke(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        try:
            return {**await handler(*args, **kwargs), "error": None}
        except (ValueError, PermissionError) as exc:
            return {"error": {
                "code": exc.code if isinstance(exc, TaskRequestError) else "PERMISSION_DENIED" if isinstance(exc, PermissionError) else "INVALID_REQUEST",
                "message": outward_error(args[0], exc),
                "retry_query": False,
                "retry_submit": False,
            }}

    return invoke
