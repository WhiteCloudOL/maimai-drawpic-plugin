"""针对 R1～R5 的真实存储与本机 HTTP 回归，不调用付费平台。"""

from aiohttp import web
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import StringIO
from pathlib import Path
from threading import Barrier
from test_workspace import _PACKAGE, DrawpicConfig, image_bytes, make_plugin as make_plugin, storage
import asyncio
import importlib
import json
import logging
import pytest


def module(name):
    return importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.{name}")


async def serve(handler):
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return runner, f"http://127.0.0.1:{port}"


def test_result_download_recovers_same_url_after_connection_reset():
    async def run():
        downloads = module("infrastructure.media.downloads")
        proxy = module("infrastructure.http").HttpProxySettings.disabled()
        hits = []

        async def handler(request):
            hits.append((request.method, request.path_qs))
            if len(hits) == 1:
                # 先发送响应头，再截断图片，验证真实传输失败而非模拟异常。
                response = web.StreamResponse(headers={"Content-Length": str(len(image_bytes()))})
                await response.prepare(request)
                await response.write(b"\x89PNG")
                request.transport.abort()
                return response
            return web.Response(body=image_bytes(), content_type="image/png")

        runner, base = await serve(handler)
        try:
            raw = await downloads.download_image(
                base + "/result?ticket=fixture", base_url=base, proxy_settings=proxy, timeout_seconds=3
            )
            assert raw == image_bytes()
            assert hits == [("GET", "/result?ticket=fixture")] * 2
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_result_download_blocks_private_markdown_and_cross_origin_redirects(monkeypatch):
    async def run():
        downloads = module("infrastructure.media.downloads")
        proxy = module("infrastructure.http").HttpProxySettings.disabled()
        error = module("domain.errors").ProviderResultError
        hits = []

        async def handler(request):
            hits.append(request.path)
            if request.path == "/redirect":
                raise web.HTTPFound("http://127.0.0.1:9/private")
            return web.Response(body=image_bytes(), content_type="image/png")

        runner, base = await serve(handler)
        try:
            provider = module("infrastructure.providers.openai").OpenaiImage("fake", base_url="https://api.example/v1")
            with pytest.raises(error, match="非公网"):
                await provider._extract_image_bytes_from_string(f"![image]({base}/private)")
            assert hits == []
            assert (
                await downloads.download_image(base + "/ok", base_url=base, proxy_settings=proxy, timeout_seconds=3)
                == image_bytes()
            )
            with pytest.raises(error, match="非公网"):
                await downloads.download_image(
                    base + "/redirect", base_url=base, proxy_settings=proxy, timeout_seconds=3
                )
            assert hits == ["/ok", "/redirect"]
            for url in (
                "file:///etc/passwd",
                "http://user:password@example.com/a",
                "http://169.254.169.254/a",
                "http://[::1]/a",
            ):
                with pytest.raises(error):
                    await downloads.download_image(
                        url, base_url="https://api.example", proxy_settings=proxy, timeout_seconds=3
                    )
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_dns_is_validated_and_the_connection_uses_the_pinned_address(monkeypatch):
    async def run():
        downloads = module("infrastructure.media.downloads")
        proxy = module("infrastructure.http").HttpProxySettings.disabled()
        hosts, resolutions = [], []

        async def handler(request):
            hosts.append(request.host)
            return web.Response(body=image_bytes(), content_type="image/png")

        runner, base = await serve(handler)
        port = base.rsplit(":", 1)[1]

        async def resolve(host, port):
            resolutions.append(host)
            return ["127.0.0.1"]

        monkeypatch.setattr(downloads, "_addresses", resolve)
        try:
            target = f"http://configured.invalid:{port}"
            await downloads.download_image(target + "/image", base_url=target, proxy_settings=proxy, timeout_seconds=3)
            assert hosts == [f"configured.invalid:{port}"] and resolutions == ["configured.invalid"]
            with pytest.raises(module("domain.errors").ProviderResultError, match="非公网"):
                await downloads.download_image(
                    "http://untrusted.invalid/a", base_url=target, proxy_settings=proxy, timeout_seconds=3
                )
            assert len(hosts) == 1
        finally:
            await runner.cleanup()

    asyncio.run(run())


def test_generation_endpoint_does_not_follow_upstream_redirects():
    async def run():
        hits = []

        async def handler(request):
            hits.append(request.path)
            if request.path == "/generation":
                raise web.HTTPFound("/private")
            return web.json_response({})

        runner, base = await serve(handler)
        provider = module("infrastructure.providers.openai").OpenaiImage("FAKE_TOKEN", base_url=base)
        try:
            with pytest.raises(module("infrastructure.providers.openai").OpenAIRequestError):
                await provider._post_json(base + "/generation", {})
            assert hits == ["/generation"]
        finally:
            await runner.cleanup()

    asyncio.run(run())


@pytest.mark.parametrize(
    "failure_kind,expected_status",
    [("moderation", "rejected"), ("result", "failed"), ("timeout", "unconfirmed"), ("unknown", "failed")],
)
def test_non_retryable_failures_never_resubmit_or_switch_models(
    make_plugin, monkeypatch, failure_kind, expected_status
):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        try:
            provider = (await plugin.workspace_bootstrap())["providers"][0]
            provider["config"]["models"] = ["sample-image", "backup-image"]
            await plugin.workspace_provider_save(
                json.dumps({key: provider[key] for key in ("id", "kind", "name", "config")}),
                plugin._platform_store.revision,
            )
            current = storage.common_config(plugin.config.model_dump(mode="json"))
            current["general"].update(request_retry_count=2, fallback_models=[f"{provider['name']}/backup-image"])
            await plugin.workspace_settings_save(json.dumps(current), plugin._platform_store.revision)
            service, calls = plugin._require_draw_service(), []
            errors = module("domain.errors")
            failures = {
                "moderation": module("infrastructure.providers.openai").OpenAIRequestError(
                    400, "content_policy_violation", "", "blocked"
                ),
                "result": errors.ProviderResultError("download generated image failed: status=503"),
                "timeout": TimeoutError("request timeout"),
                "unknown": RuntimeError("download generated image failed: status=503"),
            }

            async def generate(**kwargs):
                calls.append(kwargs)
                raise failures[failure_kind]

            monkeypatch.setattr(service, "_run_image_request_attempt", generate)
            task = await plugin.drawpic_submit("fixture")
            await asyncio.gather(*tuple(service.background_tasks))
            assert len(calls) == 1
            assert (await plugin.drawpic_task(task["task_id"]))["status"] == expected_status
        finally:
            await plugin.on_unload()

    asyncio.run(run())


def test_nested_comfyui_errors_are_redacted_before_host_handlers(tmp_path):
    logger, output = logging.getLogger("comfyui-review-redaction"), StringIO()
    handler = logging.StreamHandler(output)
    logger.addHandler(handler)
    provider = object.__new__(module("infrastructure.providers.comfyui").ComfyUIImage)
    provider.logger = logger
    payload = [
        [
            "execution_error",
            {
                "exception_message": "Authorization: Bearer FAKE_BEARER_SECRET",
                "image_url": "https://images.example/a?signature=FAKE_SIGNATURE",
            },
        ]
    ]
    try:
        provider._log_error("history=%s", payload)
        assert "FAKE_BEARER_SECRET" not in output.getvalue() and "FAKE_SIGNATURE" not in output.getvalue()
    finally:
        logger.removeHandler(handler)


def test_real_http_rejection_keeps_policy_semantics_and_redacts_host_log():
    async def run():
        logger, output = logging.getLogger("volcengine-http-review"), StringIO()
        handler = logging.StreamHandler(output)
        logger.addHandler(handler)
        key = "FAKE_HTTP_INSTANCE_KEY"

        async def rejected(request):
            return web.json_response(
                {
                    "error": {
                        "code": "content_policy_violation",
                        "message": f"api_key={key}; Authorization: Bearer FAKE_BEARER; https://example.com/a?signature=FAKE_SIGN "
                        + "long error " * 100,
                    }
                },
                status=400,
            )

        runner, base = await serve(rejected)
        provider = module("infrastructure.providers.volcengine").VolcengineImage(
            key, logger=logger, base_url=base + "/api/v3"
        )
        try:
            with pytest.raises(module("domain.errors").ProviderRequestError) as captured:
                await provider._post_json(base + "/api/v3/images/generations", {})
            assert captured.value.rejected
            for value in (str(captured.value), output.getvalue()):
                assert key not in value and "FAKE_BEARER" not in value and "FAKE_SIGN" not in value
        finally:
            logger.removeHandler(handler)
            await runner.cleanup()

    asyncio.run(run())


def test_all_instance_keys_and_rotated_keys_are_redacted_before_persistence(make_plugin):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        logger, output = plugin.ctx.logger, StringIO()
        handler = logging.StreamHandler(output)
        logger.addHandler(handler)
        try:
            for index in (1, 2):
                record = {
                    "kind": "volcengine",
                    "name": f"Volc_{index}",
                    "config": {"api_key": f"FAKE_INSTANCE_KEY_{index}"},
                }
                await plugin.workspace_provider_save(json.dumps(record), plugin._platform_store.revision)
            # 主配置只留最后实例，过滤器必须保留所有实例和轮换前的密钥。
            assert plugin.config.volcengine.api_key == "FAKE_INSTANCE_KEY_2"
            message = "FAKE_INSTANCE_KEY_1 FAKE_INSTANCE_KEY_2 https://example.com/a?signature=FAKE_SIGNATURE"
            logger.error("nested=%s", {"details": [message]})
            task = plugin._task_store.create_task(
                session_key="review",
                stream_id="",
                task_type="draw",
                prompt="",
                model="fixture",
                provider="volcengine",
                message=message,
            )
            record = await plugin.drawpic_task(task.task_id)
            assert "FAKE_INSTANCE_KEY" not in record["message"]
            assert "FAKE_INSTANCE_KEY" not in plugin._task_store.path.read_text(encoding="utf-8")
            assert "FAKE_INSTANCE_KEY" not in output.getvalue() and "FAKE_SIGNATURE" not in output.getvalue()
            plugin._platform_store.providers.clear()
            assert "FAKE_INSTANCE_KEY" not in plugin._task_store.sanitize_message(message)
        finally:
            log_path = plugin._workspace_service.logs.path
            logger.removeHandler(handler)
            await plugin.on_unload()
        assert "FAKE_INSTANCE_KEY" not in log_path.read_text(encoding="utf-8")

    asyncio.run(run())


def test_two_concurrent_claims_cannot_exceed_capacity(tmp_path):
    retention = module("infrastructure.storage.retention").ArtifactRetention(tmp_path)
    retention.INPUT_MAX_BYTES = 40000
    uploads, inputs = tmp_path / "uploads", tmp_path / "inputs"
    uploads.mkdir()
    inputs.mkdir()
    (inputs / "existing.image").write_bytes(b"x" * 10000)
    raw = image_bytes().ljust(18000, b"\0")
    paths = [uploads / f"{index}.png" for index in (1, 2)]
    for path in paths:
        path.write_bytes(raw)
    barrier = Barrier(2)

    def claim(path):
        barrier.wait(timeout=5)
        try:
            return retention.claim_input(path, sha256(raw).hexdigest())
        except ValueError as exc:
            assert "清理" in str(exc)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, paths))
    assert any(results)
    assert sum(path.stat().st_size for directory in (uploads, inputs) for path in directory.iterdir()) <= 40000


def test_failed_upload_move_preserves_original_and_releases_transaction(tmp_path, monkeypatch):
    retention = module("infrastructure.storage.retention").ArtifactRetention(tmp_path)
    path = tmp_path / "uploads/source.png"
    path.parent.mkdir()
    raw = image_bytes()
    path.write_bytes(raw)

    def fail_move(*args):
        raise OSError("simulated disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_move)
        with pytest.raises(OSError, match="disk failure"):
            retention.claim_input(path, sha256(raw).hexdigest())
    assert path.read_bytes() == raw
    identifier, _ = retention.claim_input(path, sha256(raw).hexdigest())
    assert (tmp_path / "inputs" / f"{identifier}.image").read_bytes() == raw


@pytest.mark.parametrize("section", ["openai", "general"])
def test_restored_toml_conflicts_preserve_all_files(tmp_path, section):
    config_path = tmp_path / "config.toml"
    original = b'[openai]\napi_key="OLD_FAKE_KEY"\n[general]\ndefault_model="old-model"\n'
    config_path.write_bytes(original)
    config = DrawpicConfig().model_dump(mode="json")
    config["openai"]["api_key"] = "OLD_FAKE_KEY"
    config["general"]["default_model"] = "old-model"
    store = storage.WorkspaceConfigStore(tmp_path / "data", config_path)
    store.initialize(config)
    old_json = {path.name: path.read_bytes() for path in (tmp_path / "data").glob("*.json")}
    restored = (
        original.replace(b"OLD_FAKE_KEY", b"NEW_FAKE_KEY")
        if section == "openai"
        else original.replace(b"old-model", b"new-model")
    )
    config_path.write_bytes(restored)
    restarted = storage.WorkspaceConfigStore(tmp_path / "data", config_path)
    with pytest.raises(ValueError, match="冲突"):
        restarted.initialize(config)
    assert config_path.read_bytes() == restored
    assert {path.name: path.read_bytes() for path in (tmp_path / "data").glob("*.json")} == old_json
    config_path.write_bytes(original)
    restarted.initialize(config)
    assert "openai" not in config_path.read_text(encoding="utf-8")
