"""独立搜索协议、候选边界和工作台密钥所有权；全部使用模拟服务。"""

from types import SimpleNamespace
import asyncio
import json
import logging

import pytest

from test_references import module
from test_workspace import image_bytes, make_plugin


@pytest.mark.parametrize("operation,payload,status,expected", [
    ("search", {"query": "甘雨", "count": 3, "need_content": True}, 200, "ok"),
    ("fetch", {"url": "https://example.com/page"}, 200, "ok"),
    ("search", {}, 401, "error"),
    ("search", {}, 402, "error"),
    ("fetch", {}, 404, "page"),
    ("fetch", {}, 403, "page"),
    ("fetch", {}, 429, "error"),
])
def test_deepseek_http_protocol_and_errors(monkeypatch, operation, payload, status, expected):
    async def run():
        backend = module("infrastructure.references.deepseek")
        requests = []
        key = "fake-deepseek-secret"
        class Response:
            headers = {}
            charset = "utf-8"
            def __init__(self):
                self.status = status
                self.content = self
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def iter_chunked(self, size):
                yield json.dumps({"results": [], "content": "正文"} if status == 200 else {"error": {"message": key, "code": "denied"}}).encode()
        class Session:
            def __init__(self, **kwargs): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def post(self, url, **kwargs):
                requests.append((url, kwargs))
                return Response()
        monkeypatch.setattr(backend.aiohttp, "ClientSession", Session)
        client = backend.DeepSeekSearch(key, module("infrastructure.http").HttpProxySettings.disabled())
        if expected == "ok":
            if operation == "search": await client.search("甘雨")
            else: await client.fetch("https://example.com/page")
        else:
            error_type = backend.DeepSeekPageUnavailable if expected == "page" else module("domain.task_errors").TaskRequestError
            with pytest.raises(error_type) as error:
                await client._post(operation, payload)
            assert key not in str(error.value) and f"HTTP {status}" in str(error.value)
        assert len(requests) == 1
        assert requests[0][0] == f"https://api.deepseek.com/v1/tools/{operation}"
        assert requests[0][1]["allow_redirects"] is False
        assert requests[0][1]["headers"] == {"Authorization": f"Bearer {key}"}
        assert requests[0][1]["json"] == payload
    asyncio.run(run())


def test_deepseek_missing_key_makes_no_http_call(monkeypatch):
    async def run():
        backend = module("infrastructure.references.deepseek")
        def unexpected(*args, **kwargs): raise AssertionError("HTTP called without a key")
        monkeypatch.setattr(backend.aiohttp, "ClientSession", unexpected)
        with pytest.raises(ValueError, match="API Key"):
            await backend.DeepSeekSearch("", module("infrastructure.http").HttpProxySettings.disabled()).search("甘雨")
    asyncio.run(run())


@pytest.mark.parametrize("provider", ["maibot", "deepseek"])
def test_search_provider_is_explicit_and_uses_available_content_before_fetch(monkeypatch, provider):
    async def run():
        materials = module("infrastructure.references.materials")
        config = module("domain.configuration.models").DrawpicConfig()
        config.general.references.web_search_provider = provider
        calls = []
        async def search(query, *, max_results):
            calls.append((provider, query, max_results))
            return {"results": [{"title": "甘雨", "url": "https://example.com/page", "content": '![甘雨](https://example.com/ganyu.webp)'}]}
        async def no_fetch(*args, **kwargs): raise AssertionError("Available image link was ignored")
        async def download(url, **kwargs):
            assert url == "https://example.com/ganyu.webp"
            return image_bytes()
        actual = SimpleNamespace(search=search, fetch=no_fetch)
        wrong = SimpleNamespace(search=no_fetch, fetch=no_fetch)
        monkeypatch.setattr(materials, "DeepSeekSearch", lambda *args: actual if provider == "deepseek" else wrong)
        monkeypatch.setattr(materials, "download_image", download)
        context = SimpleNamespace(web=actual if provider == "maibot" else wrong, logger=logging.getLogger("search-test"))
        images = await materials.MaterialSource(context, config).web("甘雨", subject="甘雨")
        assert len(images) == 1 and images[0].source == "web" and calls == [(provider, "甘雨", 3)]
    asyncio.run(run())


def test_individual_unavailable_page_and_image_do_not_hide_other_candidates(monkeypatch):
    async def run():
        materials = module("infrastructure.references.materials")
        deepseek = module("infrastructure.references.deepseek")
        config = module("domain.configuration.models").DrawpicConfig()
        config.general.references.web_search_provider = "deepseek"
        visits = []
        async def search(*args, **kwargs):
            return {"results": [
                {"title": "其他", "url": "https://example.com/other"},
                {"title": "甘雨", "url": "https://example.com/ganyu"},
            ]}
        async def fetch(url):
            visits.append(url)
            if url.endswith("ganyu"):
                raise deepseek.DeepSeekPageUnavailable("WEB_MATERIAL_UNAVAILABLE", "HTTP 404")
            return {"content": '<img src="/bad.webp"><img src="/valid.webp">'}
        async def download(url, **kwargs):
            if url.endswith("bad.webp"):
                raise module("domain.errors").ProviderResultError("HTTP 404")
            return image_bytes()
        monkeypatch.setattr(materials, "DeepSeekSearch", lambda *args: SimpleNamespace(search=search, fetch=fetch))
        monkeypatch.setattr(materials, "download_image", download)
        context = SimpleNamespace(logger=logging.getLogger("search-test"))
        images = await materials.MaterialSource(context, config).web("甘雨", subject="甘雨")
        assert visits[0].endswith("ganyu") and len(images) == 1 and images[0].url.endswith("valid.webp")
    asyncio.run(run())


def test_maibot_page_failure_keeps_other_candidates(monkeypatch):
    async def run():
        materials = module("infrastructure.references.materials")
        config = module("domain.configuration.models").DrawpicConfig()
        async def search(*args, **kwargs):
            return {"results": [{"url": "https://example.com/missing"},
                                {"url": "https://example.com/page", "content": '<img src="/valid.webp">'}]}
        async def fetch(url):
            raise RuntimeError("SDK candidate fetch unavailable")
        async def download(*args, **kwargs): return image_bytes()
        monkeypatch.setattr(materials, "download_image", download)
        context = SimpleNamespace(web=SimpleNamespace(search=search, fetch=fetch), logger=logging.getLogger("search-test"))
        images = await materials.MaterialSource(context, config).web("甘雨")
        assert len(images) == 1 and images[0].url.endswith("valid.webp")
    asyncio.run(run())


def test_deepseek_key_is_masked_preserved_rotated_and_explicitly_cleared(make_plugin):
    async def run():
        plugin = make_plugin(False)
        await plugin.on_load()
        try:
            async def save(key, *, clear=False):
                snapshot = await plugin.workspace_bootstrap()
                settings = snapshot["settings"]
                settings["general"]["references"].update(web_search_provider="deepseek", deepseek_api_key=key)
                if clear: settings["clear_deepseek_api_key"] = True
                await plugin.workspace_settings_save(json.dumps(settings), snapshot["revision"])
            await save("first-fake-secret")
            snapshot = await plugin.workspace_bootstrap()
            assert snapshot["deepseek_search_key_configured"]
            assert snapshot["settings"]["general"]["references"]["deepseek_api_key"] == ""
            assert "first-fake-secret" not in json.dumps(snapshot)
            invalid = snapshot["settings"]
            invalid_key = "never-expose-this-" + "x" * 600
            invalid["general"]["references"]["deepseek_api_key"] = invalid_key
            error = await plugin.workspace_settings_save(json.dumps(invalid), snapshot["revision"])
            assert error.get("__workspace_error__") and invalid_key not in json.dumps(error)
            await save("")
            assert plugin.config.general.references.deepseek_api_key == "first-fake-secret"
            saved = await plugin.drawpic_presets("save", preset={"name": "搜索验证", "positive_prompt_template": "{prompt}"})
            assert saved["error"] is None and saved["presets"]
            assert plugin.config.general.references.deepseek_api_key == "first-fake-secret"
            deleted = await plugin.drawpic_presets("delete", "搜索验证")
            assert deleted["error"] is None and not deleted["presets"]
            assert plugin.config.general.references.deepseek_api_key == "first-fake-secret"
            await save("second-fake-secret")
            assert "first-fake-secret" not in plugin._redactor.redact("first-fake-secret second-fake-secret")
            assert "second-fake-secret" not in plugin._redactor.redact("first-fake-secret second-fake-secret")
            public = await plugin.drawpic_references()
            assert public["web_search_provider"] == "deepseek" and "deepseek_api_key" not in public
            assert "references" not in plugin.get_default_config().get("general", {})
            await save("", clear=True)
            assert plugin.config.general.references.deepseek_api_key == ""
            assert not (await plugin.workspace_bootstrap())["deepseek_search_key_configured"]
        finally:
            await plugin.on_unload()
    asyncio.run(run())
