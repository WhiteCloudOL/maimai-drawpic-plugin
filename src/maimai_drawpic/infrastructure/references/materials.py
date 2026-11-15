"""固定次数的素材查找，网页内容不作为可执行指令。"""

from html.parser import HTMLParser
from typing import Any, List
from urllib.parse import urljoin, urlsplit
import asyncio
import re

from ...domain.references import ReferenceImage
from ...domain.errors import ProviderResultError
from ...domain.task_errors import TaskRequestError
from ..http import HttpProxySettings, sanitize_provider_text, sanitize_provider_url
from ..media.downloads import _download_image, download_image
from .deepseek import DeepSeekPageUnavailable, DeepSeekSearch


class ImageLinks(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Any]) -> None:
        values = dict(attrs)
        if tag == "img":
            value = values.get("src") or values.get("data-src")
        elif tag == "meta" and values.get("property") in {"og:image", "twitter:image"}:
            value = values.get("content")
        else:
            return
        if value:
            self.urls.append(value)


def image_links(content: str, page_url: str) -> List[str]:
    content = content[:512 * 1024].replace("\\/", "/")
    parser = ImageLinks()
    parser.feed(content[:512 * 1024])
    links = parser.urls + re.findall(r'https?://[^\s<>"\)]+?\.(?:png|jpe?g|webp)(?:\?[^\s<>"\)]*)?', content[:512 * 1024], re.I)
    result = []
    for link in links:
        absolute = urljoin(page_url, link)
        if urlsplit(absolute).scheme in {"http", "https"} and absolute not in result:
            result.append(absolute)
    return result[:6]


class MaterialSource:
    def __init__(self, ctx: Any, config: Any) -> None:
        self.ctx, self.config = ctx, config

    async def web(self, query: str, *, subject: str = "") -> List[ReferenceImage]:
        settings = self.config.proxy
        proxy = HttpProxySettings(enabled=settings.enabled, use_system_proxy=settings.use_system_proxy,
                                  scheme=settings.scheme, host=settings.host, port=settings.port,
                                  username=settings.username, password=settings.password)
        options = {"base_url": "https://reference.invalid", "proxy_settings": proxy, "timeout_seconds": 15,
                   "skip_ip_check": self.config.general.skip_image_url_ip_check}
        refs = self.config.general.references
        backend = DeepSeekSearch(refs.deepseek_api_key, proxy) if refs.web_search_provider == "deepseek" else self.ctx.web
        result = await backend.search(query, max_results=3)
        if not isinstance(result, dict) or not isinstance(result.get("results"), list):
            raise TaskRequestError("WEB_MATERIAL_UNAVAILABLE", "网络搜索未返回有效网页结果")
        candidates: List[str] = []
        pages = result["results"][:3]
        if subject:
            pages = sorted(pages, key=lambda item: subject.casefold() not in str(item.get("title", "")).casefold() if isinstance(item, dict) else True)
        failures: List[str] = []
        for item in pages:
            if not isinstance(item, dict) or not isinstance(item.get("url"), str):
                raise TaskRequestError("WEB_MATERIAL_UNAVAILABLE", "搜索结果缺少网页链接")
            page_url = item["url"]
            if re.search(r"\.(png|jpe?g|webp)(?:\?|$)", page_url, re.I):
                candidates.append(page_url)
                continue
            content = item.get("content", "")
            if not isinstance(content, str):
                raise TaskRequestError("WEB_MATERIAL_UNAVAILABLE", "搜索结果正文格式无效")
            links = await asyncio.to_thread(image_links, content, page_url)
            if not links:
                try:
                    page = await backend.fetch(page_url)
                except DeepSeekPageUnavailable as exc:
                    self.ctx.logger.warning("跳过无法抓取的素材候选网页: url=%s reason=%s", sanitize_provider_url(page_url), str(exc))
                    failures.append(str(exc))
                    continue
                except TaskRequestError:
                    raise
                except Exception as exc:
                    if refs.web_search_provider != "maibot":
                        raise
                    reason = sanitize_provider_text(str(exc))
                    self.ctx.logger.warning("MaiBot 素材候选网页读取失败: url=%s reason=%s", sanitize_provider_url(page_url), reason)
                    failures.append(reason)
                    continue
                if not isinstance(page, dict) or not isinstance(page.get("content"), str):
                    raise TaskRequestError("WEB_MATERIAL_UNAVAILABLE", "网页正文格式无效")
                links = await asyncio.to_thread(image_links, page["content"], page_url)
            if not links:
                try:
                    document = await _download_image(page_url, image_content=False, **options)
                except ProviderResultError as exc:
                    self.ctx.logger.warning("素材候选网页不可用: url=%s reason=%s", sanitize_provider_url(page_url), str(exc))
                    failures.append(str(exc))
                    continue
                links = await asyncio.to_thread(image_links, document.decode("utf-8"), page_url)
            candidates.extend(links)
            if len(candidates) >= 6:
                break
        images = []
        for url in list(dict.fromkeys(candidates))[:6]:
            try:
                raw = await download_image(url, **options)
            except ProviderResultError as exc:
                self.ctx.logger.warning("素材候选图片不可用: url=%s reason=%s", sanitize_provider_url(url), str(exc))
                failures.append(str(exc))
                continue
            if sum(len(image.raw) for image in images) + len(raw) > 40 * 1024 * 1024:
                raise TaskRequestError("MATERIAL_LIMIT_EXCEEDED", "网络候选素材总计超过 40 MiB")
            images.append(ReferenceImage(raw, "web", url=url))
        if not images and failures:
            raise TaskRequestError("WEB_MATERIAL_UNAVAILABLE", f"候选素材均不可用：{failures[-1]}")
        return images
