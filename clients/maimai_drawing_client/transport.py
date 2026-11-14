# SPDX-FileCopyrightText: 2026 WhiteCloudOL
# SPDX-License-Identifier: MIT

"""每次 SDK 调用独立限时；不设置宿主能力超时或创建后台任务。"""

from typing import Any, Dict, Protocol
import asyncio

from .models import DrawingTransportError


class APIProxy(Protocol):
    async def call(self, api_name: str, version: str = "1", **kwargs: Any) -> Any: ...


class DrawingRPC:
    def __init__(self, api: APIProxy, timeout: float) -> None:
        self.api, self.timeout = api, timeout

    async def call(self, name: str, /, *, version: str = "2", **kwargs: Any) -> Dict[str, Any]:
        handles = {"task_id": kwargs.get("task_id"), "request_id": kwargs.get("request_id", "")}
        try:
            async with asyncio.timeout(self.timeout):
                response = await self.api.call(
                    f"maimai-drawpic-plugin.drawpic_{name}{'_v2' if version == '2' else ''}", version=version, **kwargs
                )
        except TimeoutError as exc:
            raise DrawingTransportError("RPC 等待结束，远端响应未确认", **handles) from exc
        except Exception as exc:
            raise DrawingTransportError("SDK 调用失败，远端响应未确认", **handles) from exc
        if not isinstance(response, dict):
            raise DrawingTransportError("API 返回值必须是对象", **handles)
        return response
