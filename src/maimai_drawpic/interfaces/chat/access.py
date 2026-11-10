"""在聊天命令和工具执行前统一检查会话访问规则。"""

from functools import wraps
from inspect import signature
from typing import Any, Awaitable, Callable

from ...application.access import ChatAccessDenied, access_restricted, require_chat_access


def chat_access_endpoint(handler: Callable[..., Awaitable[Any]]) -> Callable:
    parameters = signature(handler)

    @wraps(handler)
    async def invoke(self: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            if access_restricted(self.config.general):
                values = parameters.bind(self, *args, **kwargs).arguments
                context = self._extract_runtime_context(
                    stream_id=values.get("stream_id", ""), kwargs=values.get("kwargs", {}),
                )
                live = await self._require_stream_service().existing_stream_context(context["stream_id"])
                require_chat_access(self.config.general, live, self.ctx.logger)
            return await handler(self, *args, **kwargs)
        except ChatAccessDenied as exc:
            if handler.__name__ == "handle_draw_command":
                return False, str(exc), 1
            return {"success": False, "message": str(exc)}

    return invoke
