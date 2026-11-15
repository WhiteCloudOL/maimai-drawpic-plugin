"""薄接口层共享工作台服务入口。"""

from functools import wraps
from inspect import signature
from typing import Any, Awaitable, Callable, Dict, Literal, Optional

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


def drawing_endpoint(kind: Literal["resource", "task", "submit", "cancel", "listing"] = "resource") -> Callable:
    """统一公开接口的权限、参数错误和业务状态，不依赖接口名称判断协议。"""
    def decorate(handler: Callable[..., Awaitable[Dict[str, Any]]]) -> Callable:
        parameters = signature(handler)

        @wraps(handler)
        async def invoke(self: Any, *args: Any, **kwargs: Any) -> Dict[str, Any]:
            workspace = self._workspace()
            values = dict(kwargs)
            try:
                try:
                    values = parameters.bind(self, *args, **kwargs).arguments
                except TypeError:
                    raise ValueError("接口参数缺失或包含未知参数") from None
                config = workspace.get_config().general
                require_integration_api(config, workspace.ctx.logger, handler.__name__)
                stream_id = values.get("stream_id", "")
                if isinstance(stream_id, str) and stream_id.strip() and access_restricted(config):
                    context = await workspace.tasks.get_service().stream_service.existing_stream_context(stream_id.strip())
                    require_chat_access(workspace.get_config().general, context, workspace.ctx.logger)
                result = await handler(self, *args, **kwargs)
            except (ValueError, PermissionError) as exc:
                result = {"error": task_error(
                    exc.code if isinstance(exc, TaskRequestError) else "PERMISSION_DENIED" if isinstance(exc, PermissionError) else "INVALID_REQUEST",
                    outward_error(self, exc),
                    retry_submit=isinstance(exc, TaskRequestError) and exc.retry_submit,
                )}
                if kind in {"task", "submit", "cancel"}:
                    result.update(task_id=None, status="not_accepted", images=[], retry_after_ms=0)
                if kind == "submit":
                    result.update(accepted=False, request_id=values.get("request_id", ""))
                elif kind == "cancel":
                    result.update(cancel_requested=False, upstream_cancelled=None)
                elif kind == "listing":
                    result.update(items=[], total=0, page_size=12)
            return {"error": None, **result}

        return invoke

    return decorate


def workspace_endpoint(handler: Callable[..., Awaitable[Dict[str, Any]]]) -> Callable:
    """可预期的输入错误回传页面；运行异常继续交由 Runner 完整记录。"""

    @wraps(handler)
    async def invoke(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        try:
            return await handler(*args, **kwargs)
        except (ValueError, PermissionError) as exc:
            return {"__workspace_error__": outward_error(args[0], exc)}

    return invoke
