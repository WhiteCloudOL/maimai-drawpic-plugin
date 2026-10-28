"""结果下载的真实本机代理回归，不调用图片生成服务。"""

from aiohttp import BasicAuth, web
from aiohttp.abc import AbstractResolver
from socket import AF_INET
from typing import Any, Dict, List
from unittest.mock import AsyncMock
from yarl import URL
import asyncio
import pytest

from test_review_regressions import module, serve
from test_workspace import image_bytes


@pytest.mark.parametrize("system_proxy", [False, True])
def test_proxy_resolves_original_hosts_and_rechecks_redirects(monkeypatch, system_proxy: bool) -> None:
    async def run() -> None:
        downloads = module("infrastructure.media.downloads")
        proxy_type = module("infrastructure.http").HttpProxySettings
        hits: List[Dict[str, Any]] = []
        resolutions: List[str] = []
        raw = image_bytes()

        async def handler(request):
            hits.append({
                "target": request.raw_path,
                "host": request.host,
                "authorization": request.headers.get("Authorization"),
                "proxy_authorization": request.headers.get("Proxy-Authorization"),
            })
            if len(hits) == 1:
                raise web.HTTPFound("http://other-cdn.invalid/final.png?ticket=fixture")
            return web.Response(body=raw, content_type="image/png")

        runner, proxy_url = await serve(handler)
        resolver = AsyncMock(return_value=["198.18.0.2"])
        monkeypatch.setattr(downloads, "_addresses", resolver)

        def environment_proxy(url):
            resolutions.append(url.raw_host)
            return URL(proxy_url), BasicAuth("fixture-user", "fixture-password")

        monkeypatch.setattr(downloads, "get_env_proxy_for_url", environment_proxy)
        proxy = proxy_type(
            enabled=True, use_system_proxy=system_proxy,
            host="127.0.0.1", port=int(URL(proxy_url).port),
            username="fixture-user", password="fixture-password",
        )
        try:
            result = await downloads.download_image(
                "http://cdn.invalid/start.png", base_url="https://api.invalid/v1",
                proxy_settings=proxy, timeout_seconds=3,
            )
            assert result == raw
            assert [hit["target"] for hit in hits] == [
                "http://cdn.invalid/start.png", "http://other-cdn.invalid/final.png?ticket=fixture",
            ]
            assert [hit["host"] for hit in hits] == ["cdn.invalid", "other-cdn.invalid"]
            assert all(hit["authorization"] is None for hit in hits)
            expected_auth = BasicAuth("fixture-user", "fixture-password").encode()
            assert all(hit["proxy_authorization"] == expected_auth for hit in hits)
            assert resolutions == (["cdn.invalid", "other-cdn.invalid"] if system_proxy else [])
            resolver.assert_not_awaited()
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_https_proxy_connect_keeps_original_authority(monkeypatch) -> None:
    async def run() -> None:
        downloads = module("infrastructure.media.downloads")
        proxy_type = module("infrastructure.http").HttpProxySettings
        requests: List[bytes] = []

        async def handle_connect(reader, writer):
            try:
                requests.append(await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=3))
                # 不建立外网隧道；CONNECT 的原始域名就是本回归要验证的传输契约。
                writer.write(b"HTTP/1.1 502 Fixture\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
                await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle_connect, "127.0.0.1", 0)
        resolver = AsyncMock(side_effect=AssertionError("代理目标不应在本地解析"))
        monkeypatch.setattr(downloads, "_addresses", resolver)
        try:
            port = server.sockets[0].getsockname()[1]
            proxy = proxy_type(enabled=True, use_system_proxy=False, host="127.0.0.1", port=port)
            with pytest.raises(module("domain.errors").ProviderResultError):
                await downloads.download_image(
                    "https://cdn.invalid:8443/result.png", base_url="https://api.invalid/v1",
                    proxy_settings=proxy, timeout_seconds=3,
                )
            assert len(requests) == 1
            assert requests[0].split(b"\r\n", 1)[0] == b"CONNECT cdn.invalid:8443 HTTP/1.1"
            resolver.assert_not_awaited()
        finally:
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_system_proxy_no_proxy_redirect_keeps_direct_ip_checks(monkeypatch) -> None:
    async def run() -> None:
        downloads = module("infrastructure.media.downloads")
        proxy_type = module("infrastructure.http").HttpProxySettings
        hits: List[str] = []

        async def handler(request):
            hits.append(request.raw_path)
            raise web.HTTPFound("http://127.0.0.1:9/private")

        runner, proxy_url = await serve(handler)
        # 使用 aiohttp 实际的环境代理选择，避免只验证一个模拟的 NO_PROXY 分支。
        for name in ("http_proxy", "https_proxy", "all_proxy", "no_proxy", "REQUEST_METHOD"):
            monkeypatch.delenv(name, raising=False)
            monkeypatch.delenv(name.upper(), raising=False)
        monkeypatch.setenv("http_proxy", proxy_url)
        monkeypatch.setenv("no_proxy", "127.0.0.1")
        try:
            with pytest.raises(module("domain.errors").ProviderResultError, match="非公网"):
                await downloads.download_image(
                    "http://cdn.invalid/start", base_url="https://api.invalid/v1",
                    proxy_settings=proxy_type(enabled=True, use_system_proxy=True), timeout_seconds=3,
                )
            assert hits == ["http://cdn.invalid/start"]
        finally:
            await runner.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize("host", [
    "127.0.0.1", "169.254.169.254", "[::1]", "localhost", "a.localhost",
    "127.0.0.1.", "2130706433", "0x7f000001", "127.1", "0177.0.0.1",
])
def test_proxy_still_blocks_explicit_private_targets(host: str) -> None:
    async def run() -> None:
        downloads = module("infrastructure.media.downloads")
        proxy_type = module("infrastructure.http").HttpProxySettings
        with pytest.raises(module("domain.errors").ProviderResultError, match="非公网"):
            await downloads.download_image(
                f"http://{host}/private", base_url="https://api.invalid/v1",
                proxy_settings=proxy_type(enabled=True, use_system_proxy=False, host="127.0.0.1", port=9),
                timeout_seconds=3,
            )

    asyncio.run(run())


def test_skip_ip_check_allows_cross_origin_local_images(monkeypatch) -> None:
    async def run() -> None:
        downloads = module("infrastructure.media.downloads")
        proxy = module("infrastructure.http").HttpProxySettings.disabled()
        raw = image_bytes()
        hits: List[str] = []

        async def handler(request):
            hits.append(request.path)
            if request.path == "/start":
                raise web.HTTPFound("/image.png")
            return web.Response(body=raw, content_type="image/png")

        runner, base = await serve(handler)
        try:
            with pytest.raises(module("domain.errors").ProviderResultError, match="非公网"):
                await downloads.download_image(
                    base + "/start", base_url="https://api.invalid/v1", proxy_settings=proxy, timeout_seconds=3,
                )
            assert hits == []
            resolver = AsyncMock(side_effect=AssertionError("已明确关闭 IP 校验"))
            monkeypatch.setattr(downloads, "_addresses", resolver)
            assert await downloads.download_image(
                base + "/start", base_url="https://api.invalid/v1", proxy_settings=proxy,
                timeout_seconds=3, skip_ip_check=True,
            ) == raw
            assert hits == ["/start", "/image.png"]
            resolver.assert_not_awaited()
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_tun_only_fake_ip_keeps_hostname_when_ip_checks_are_disabled(monkeypatch) -> None:
    async def run() -> None:
        downloads = module("infrastructure.media.downloads")
        proxy = module("infrastructure.http").HttpProxySettings.disabled()
        hits: List[str] = []
        resolutions: List[str] = []
        raw = image_bytes()

        class TunResolver(AbstractResolver):
            async def resolve(self, host, port=0, family=AF_INET):
                # 模拟 TUN 将保留域名的连接接管到实际图床，不暴露公网地址或依赖本机 DNS。
                resolutions.append(host)
                return [{
                    "hostname": host, "host": "127.0.0.1", "port": port,
                    "family": AF_INET, "proto": 0, "flags": 0,
                }]

            async def close(self):
                pass

        async def handler(request):
            hits.append(request.host)
            return web.Response(body=raw, content_type="image/png")

        runner, base = await serve(handler)
        original_session = downloads.aiohttp.ClientSession

        def tun_session(**kwargs):
            connector = downloads.aiohttp.TCPConnector(resolver=TunResolver())
            return original_session(connector=connector, **kwargs)

        monkeypatch.setattr(downloads.aiohttp, "ClientSession", tun_session)
        monkeypatch.setattr(downloads, "_addresses", AsyncMock(return_value=["198.18.0.2"]))
        target = URL(base).with_host("fake-image.invalid").with_path("/image.png")
        try:
            with pytest.raises(module("domain.errors").ProviderResultError, match="非公网"):
                await downloads.download_image(
                    str(target), base_url="https://api.invalid/v1", proxy_settings=proxy, timeout_seconds=3,
                )
            assert hits == resolutions == []
            assert await downloads.download_image(
                str(target), base_url="https://api.invalid/v1", proxy_settings=proxy,
                timeout_seconds=3, skip_ip_check=True,
            ) == raw
            assert resolutions == ["fake-image.invalid"]
            assert hits == [target.raw_authority]
        finally:
            await runner.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize("location", ["file:///etc/passwd", "http://user:password@example.invalid/image"])
def test_skip_ip_check_keeps_redirect_url_validation(location: str) -> None:
    async def run() -> None:
        downloads = module("infrastructure.media.downloads")
        proxy = module("infrastructure.http").HttpProxySettings.disabled()
        hits: List[str] = []

        async def handler(request):
            hits.append(request.path)
            return web.Response(status=302, headers={"Location": location})

        runner, base = await serve(handler)
        try:
            with pytest.raises(module("domain.errors").ProviderResultError, match="HTTP"):
                await downloads.download_image(
                    base + "/start", base_url=base, proxy_settings=proxy,
                    timeout_seconds=3, skip_ip_check=True,
                )
            assert hits == ["/start"]
        finally:
            await runner.cleanup()

    asyncio.run(run())
