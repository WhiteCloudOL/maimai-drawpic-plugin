"""固定次数的素材查找，网页内容不作为可执行指令。"""

from html.parser import HTMLParser
from typing import Any, List
from urllib.parse import urljoin, urlsplit
import asyncio
import re

from ...domain.references import ReferenceImage
from ...domain.task_errors import TaskRequestError
from ..http import HttpProxySettings
from ..media.downloads import _download_image, download_image


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

    async def web(self, query: str) -> List[ReferenceImage]:
        settings = self.config.proxy
        proxy = HttpProxySettings(enabled=settings.enabled, use_system_proxy=settings.use_system_proxy,
                                  scheme=settings.scheme, host=settings.host, port=settings.port,
                                  username=settings.username, password=settings.password)
        options = {"base_url": "https://reference.invalid", "proxy_settings": proxy, "timeout_seconds": 15,
                   "skip_ip_check": self.config.general.skip_image_url_ip_check}
        result = await self.ctx.web.search(query, max_results=3)
        if not isinstance(result.get("results"), list):
            raise TaskRequestError("WEB_MATERIAL_UNAVAILABLE", "网络搜索未返回有效网页结果")
        candidates: List[str] = []
        for item in result["results"][:3]:
            page_url = item["url"]
            if re.search(r"\.(png|jpe?g|webp)(?:\?|$)", page_url, re.I):
                candidates.append(page_url)
                continue
            page = await self.ctx.web.fetch(page_url)
            links = await asyncio.to_thread(image_links, page["content"], page_url)
            if not links:
                document = await _download_image(page_url, image_content=False, **options)
                links = await asyncio.to_thread(image_links, document.decode("utf-8"), page_url)
            candidates.extend(links)
            if len(candidates) >= 6:
                break
        images = []
        for url in list(dict.fromkeys(candidates))[:6]:
            raw = await download_image(url, **options)
            if sum(len(image.raw) for image in images) + len(raw) > 40 * 1024 * 1024:
                raise TaskRequestError("MATERIAL_LIMIT_EXCEEDED", "网络候选素材总计超过 40 MiB")
            images.append(ReferenceImage(raw, "web", url=url))
        return images
