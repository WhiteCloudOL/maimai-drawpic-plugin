"""逐跳检查结果地址；直连固定 IP，代理保留域名并交由代理解析。"""

from ipaddress import ip_address
from aiohttp.helpers import get_env_proxy_for_url
from typing import List
from yarl import URL
import aiohttp
import asyncio
import socket

from ...domain.errors import ProviderDownloadError, ProviderResultError
from ..http import HttpProxySettings, read_response_bytes, sanitize_provider_url
from .images import validate_image_bytes
from .collection import bounded_results, current_budget


def _public_address(value: str) -> bool:
    address = ip_address(value)
    mapped = address.ipv4_mapped if address.version == 6 else None
    if mapped is not None:
        return _public_address(str(mapped))
    return address.is_global and not any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _url(value: str) -> URL:
    try:
        url = URL(value)
        if url.scheme not in {"http", "https"} or not url.raw_host or url.user is not None or url.password is not None:
            raise ValueError
        if "%" in url.raw_host:
            raise ValueError
        _ = url.port  # 校验端口，拒绝非法 authority。
        return url.with_fragment(None)
    except (ValueError, TypeError):
        raise ProviderResultError("图片结果地址必须为不含凭据的 HTTP(S) URL") from None


async def _addresses(host: str, port: int) -> List[str]:
    try:
        return [str(ip_address(host))]
    except ValueError:
        records = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        # 优先 IPv4；直连把已验证的 IP 交给连接器，避免第二次 DNS 解析改变目标。
        records.sort(key=lambda record: record[0] != socket.AF_INET)
        return list(dict.fromkeys(record[4][0] for record in records))


async def _download_target(current: URL, trusted: URL, *, via_proxy: bool, skip_ip_check: bool) -> URL:
    """按实际出站方式检查地址，避免把本地 Fake-IP 当作代理的目标 IP。"""
    if skip_ip_check:
        return current

    local_origin = current.origin() == trusted.origin()
    if via_proxy:
        # 代理在远端解析域名；本地 DNS 可能返回 Fake-IP，甚至无法解析。
        # 不把域名替换成 IP，否则代理的 DNS、分流和 HTTPS CONNECT 都会失去原始目标。
        host = current.raw_host.rstrip(".").casefold()
        try:
            address = ip_address(host)
        except ValueError:
            try:
                # inet_aton 只解析字面量，不查询 DNS；同时识别十六进制、整数等旧式 IPv4 写法。
                address = ip_address(socket.inet_aton(host))
            except OSError:
                if not local_origin and (host == "localhost" or host.endswith(".localhost")):
                    raise ProviderResultError("图片结果地址指向非公网网络，且不属于已配置服务的同源地址")
                return current
        if not local_origin and not _public_address(str(address)):
            raise ProviderResultError("图片结果地址指向非公网网络，且不属于已配置服务的同源地址")
        return current

    addresses = await _addresses(current.raw_host, current.port)
    if not addresses or (not local_origin and not all(_public_address(value) for value in addresses)):
        raise ProviderResultError("图片结果地址指向非公网网络，且不属于已配置服务的同源地址")
    return current.with_host(addresses[0])


@bounded_results
async def download_image(
    url: str,
    *,
    base_url: str,
    proxy_settings: HttpProxySettings,
    timeout_seconds: int,
    skip_ip_check: bool = False,
) -> bytes:
    """在有限预算内只恢复同一结果地址；每次重新选择代理并校验地址与跳转。"""
    current_budget().available()
    try:
        async with asyncio.timeout(timeout_seconds):
            for attempt in range(3):
                try:
                    raw = await _download_image(
                        url,
                        base_url=base_url,
                        proxy_settings=proxy_settings,
                        timeout_seconds=timeout_seconds,
                        skip_ip_check=skip_ip_check,
                    )
                    return current_budget().accept(raw)
                except ProviderDownloadError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.5 * (attempt + 1))
    except TimeoutError:
        raise ProviderDownloadError("图片已生成，结果下载等待超时，未重新提交生成请求") from None
    raise AssertionError("unreachable download retry state")


async def _download_image(
    url: str,
    *,
    base_url: str,
    proxy_settings: HttpProxySettings,
    timeout_seconds: int,
    skip_ip_check: bool,
) -> bytes:
    """逐跳选择实际代理；直连默认只访问公网或管理员配置的同源服务。"""
    current, trusted = _url(url), _url(base_url)
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with asyncio.timeout(timeout_seconds):
            # 只读取代理环境，不启用 trust_env 的目标站点 .netrc 自动鉴权。
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for hop in range(6):
                    kwargs = proxy_settings.aiohttp_request_kwargs()
                    if proxy_settings.enabled and proxy_settings.use_system_proxy:
                        try:
                            proxy, proxy_auth = get_env_proxy_for_url(current)
                        except LookupError:
                            pass  # NO_PROXY 命中或未配置代理时直连。
                        else:
                            kwargs.update(proxy=proxy, proxy_auth=proxy_auth)
                    # NO_PROXY 或平台绕过代理时仍走直连校验，不能仅按 enabled 跳过 DNS。
                    target = await _download_target(
                        current, trusted, via_proxy=bool(kwargs.get("proxy")), skip_ip_check=skip_ip_check
                    )
                    if current.scheme == "https":
                        kwargs["server_hostname"] = current.raw_host
                    # 不附加生成服务的鉴权头，关闭自动跳转，每一跳重新选择出站并校验地址。
                    async with session.get(
                        target, headers={"Host": current.raw_authority}, allow_redirects=False, **kwargs
                    ) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location or hop == 5:
                                raise ProviderResultError("图片下载重定向无效或超过 5 次")
                            current = _url(str(current.join(URL(location))))
                            continue
                        if response.status != 200:
                            raise ProviderResultError(
                                f"图片结果下载失败: HTTP {response.status} url={sanitize_provider_url(str(current))}"
                            )
                        raw = await read_response_bytes(response, max_bytes=current_budget().available())
                        await asyncio.to_thread(validate_image_bytes, raw)
                        return raw
    except ProviderResultError:
        raise
    except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError, TimeoutError) as exc:
        raise ProviderDownloadError(f"图片结果传输中断（{type(exc).__name__}），未重新提交生成请求") from None
    except (aiohttp.ClientError, OSError, ValueError, RuntimeError) as exc:
        raise ProviderResultError(f"图片结果下载或校验失败（{type(exc).__name__}），未重新提交生成请求") from None
    raise ProviderResultError("图片结果下载未完成")
