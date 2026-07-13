from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import aiohttp


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
