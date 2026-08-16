from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp
import json

MAX_PROVIDER_RESPONSE_BYTES = 64 * 1024 * 1024


async def read_response_bytes(
    response: aiohttp.ClientResponse,
    max_bytes: int = MAX_PROVIDER_RESPONSE_BYTES,
) -> bytes:
    """读取受大小限制的 HTTP 响应。"""

    content_length = response.headers.get("Content-Length", "").strip()
    if content_length:
        try:
            parsed_content_length = int(content_length)
            if parsed_content_length < 0:
                raise ValueError
            if parsed_content_length > max_bytes:
                raise RuntimeError(f"图片服务响应超过大小限制：{max_bytes} 字节")
        except ValueError as exc:
            raise RuntimeError(f"图片服务返回了无效的 Content-Length：{content_length}") from exc

    chunks: list[bytes] = []
    total_bytes = 0
    async for chunk in response.content.iter_chunked(64 * 1024):
        total_bytes += len(chunk)
        if total_bytes > max_bytes:
            raise RuntimeError(f"图片服务响应超过大小限制：{max_bytes} 字节")
        chunks.append(chunk)
    return b"".join(chunks)


async def read_response_text(
    response: aiohttp.ClientResponse,
    max_bytes: int = MAX_PROVIDER_RESPONSE_BYTES,
) -> str:
    """读取受大小限制的 HTTP 文本响应。"""

    response_bytes = await read_response_bytes(response, max_bytes=max_bytes)
    encoding = response.charset or "utf-8"
    return response_bytes.decode(encoding, errors="replace")


async def read_response_json(
    response: aiohttp.ClientResponse,
    max_bytes: int = MAX_PROVIDER_RESPONSE_BYTES,
) -> Any:
    """读取并解析受大小限制的 HTTP JSON 响应。"""

    response_bytes = await read_response_bytes(response, max_bytes=max_bytes)
    try:
        return json.loads(response_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("图片服务返回了无效的 JSON 响应") from exc


@dataclass(frozen=True, slots=True)
class HttpProxySettings:
    """图片提供商使用的统一 HTTP 代理设置。"""

    enabled: bool = False
    use_system_proxy: bool = True
    scheme: str = "http"
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""

    @classmethod
    def disabled(cls) -> HttpProxySettings:
        """构造不使用代理的设置。"""

        return cls()

    @property
    def proxy_url(self) -> str:
        """返回手动代理的 URL，并在配置非法时直接报错。"""

        if not self.enabled or self.use_system_proxy:
            return ""
        if not self.host:
            raise ValueError("已启用手动代理，但未填写代理 Host")
        if not 1 <= self.port <= 65535:
            raise ValueError(f"已启用手动代理，但端口无效: {self.port}")
        return f"{self.scheme}://{self.host}:{self.port}"

    def aiohttp_session_kwargs(self) -> dict[str, Any]:
        """生成 aiohttp ClientSession 构造参数。"""

        if self.enabled and self.use_system_proxy:
            return {"trust_env": True}
        return {}

    def aiohttp_request_kwargs(self) -> dict[str, Any]:
        """生成 aiohttp 单次请求的代理参数。"""

        proxy_url = self.proxy_url
        if not proxy_url:
            return {}
        request_kwargs: dict[str, Any] = {"proxy": proxy_url}
        if self.username:
            request_kwargs["proxy_auth"] = aiohttp.BasicAuth(self.username, self.password)
        return request_kwargs

    def google_client_args(self) -> dict[str, Any]:
        """生成 google-genai 底层 httpx 客户端参数。"""

        proxy_url = self.proxy_url
        if not proxy_url:
            return {"trust_env": self.enabled and self.use_system_proxy}
        if self.username:
            proxy_url = (
                f"{self.scheme}://{quote(self.username, safe='')}:{quote(self.password, safe='')}"
                f"@{self.host}:{self.port}"
            )
        return {"proxy": proxy_url}
