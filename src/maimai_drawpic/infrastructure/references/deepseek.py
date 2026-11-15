"""DeepSeek 独立 Search/Fetch API；不执行模型工具循环。"""

from typing import Any, Dict
import aiohttp

from ...domain.task_errors import TaskRequestError
from ..http import HttpProxySettings, provider_response_error, read_response_json, read_response_text


class DeepSeekPageUnavailable(TaskRequestError):
    """搜索命中的单个网页无法抓取，不代表搜索服务失效。"""


class DeepSeekSearch:
    def __init__(self, api_key: str, proxy: HttpProxySettings) -> None:
        self.api_key = api_key.strip()
        self.proxy = proxy

    async def _post(self, operation: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key:
            raise TaskRequestError("WEB_MATERIAL_UNAVAILABLE", "请在素材来源中填写 DeepSeek API Key")
        url = f"https://api.deepseek.com/v1/tools/{operation}"
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15), **self.proxy.aiohttp_session_kwargs()) as session:
            async with session.post(
                url, json=payload, headers={"Authorization": f"Bearer {self.api_key}"},
                allow_redirects=False, **self.proxy.aiohttp_request_kwargs(),
            ) as response:
                if response.status != 200:
                    text = await read_response_text(response, max_bytes=4 * 1024 * 1024)
                    error = provider_response_error(response.status, text, self.api_key, f"DeepSeek {operation}")
                    if operation == "fetch" and response.status in {403, 404}:
                        raise DeepSeekPageUnavailable("WEB_MATERIAL_UNAVAILABLE", str(error)) from error
                    raise TaskRequestError("WEB_MATERIAL_UNAVAILABLE", str(error)) from error
                result = await read_response_json(response, max_bytes=4 * 1024 * 1024)
        if not isinstance(result, dict):
            raise TaskRequestError("WEB_MATERIAL_UNAVAILABLE", f"DeepSeek {operation} 返回格式无效")
        return result

    async def search(self, query: str, *, max_results: int = 3) -> Dict[str, Any]:
        return await self._post("search", {"query": query, "count": max_results, "need_content": True})

    async def fetch(self, url: str) -> Dict[str, Any]:
        return await self._post("fetch", {"url": url})
