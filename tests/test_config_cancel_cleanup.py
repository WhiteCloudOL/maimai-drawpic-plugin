"""Owned configuration commits and failed atomic writes use temporary data only."""
import asyncio
import importlib
from contextlib import contextmanager
from pathlib import Path
from threading import Event

import pytest

from test_workspace import _PACKAGE, make_plugin

atomic = importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.infrastructure.storage.atomic")


@pytest.mark.parametrize("operation", ["settings", "provider_save", "provider_delete", "preset_save", "preset_delete"])
def test_cancelled_commit_keeps_lock_refresh_and_shutdown_ownership(make_plugin, monkeypatch, operation):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        workspace = plugin._workspace_service
        entered, release = Event(), Event()
        if operation == "preset_delete":
            await workspace.presets("save", preset_json='{"name":"temporary"}')
        revision = workspace.store.revision
        snapshot = workspace.store.public_snapshot()
        if operation == "provider_save":
            method = "save_provider"
            call = lambda: workspace.save_provider('{"kind":"google","name":"new_provider","config":{}}', revision)
        elif operation == "provider_delete":
            method = "delete_provider"
            call = lambda: workspace.delete_provider(snapshot["providers"][0]["id"], revision)
        elif operation == "settings":
            method = "save_common"
            call = lambda: workspace.save_settings('{"general":{"request_retry_count":2}}', revision)
        else:
            method = "save_common"
            call = (lambda: workspace.presets("save", preset_json='{"name":"temporary"}')) if operation == "preset_save" else (lambda: workspace.presets("delete", "temporary"))
        original = getattr(workspace.store, method)
        refreshed = []
        refresh, apply = workspace.refresh, workspace.apply_settings

        async def record_refresh():
            await refresh()
            refreshed.append(True)

        async def record_apply(values):
            await apply(values)
            refreshed.append(True)

        def blocked(*args, **kwargs):
            result = original(*args, **kwargs)
            entered.set()
            assert release.wait(5)
            return result

        monkeypatch.setattr(workspace.store, method, blocked)
        monkeypatch.setattr(workspace, "refresh", record_refresh)
        monkeypatch.setattr(workspace, "apply_settings", record_apply)
        caller = asyncio.create_task(call())
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert workspace.lock.locked()
            assert workspace.store.revision > revision
            pending = await workspace.bootstrap()
            assert pending["config_update_pending"] and pending["runtime_refresh_pending"]
            # A queued caller cancelled before admission must never commit later.
            queued = asyncio.create_task(workspace.save_settings('{}', workspace.store.revision))
            await asyncio.sleep(0)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
            closing = asyncio.create_task(workspace.close())
            await asyncio.sleep(0)
            assert not closing.done()
            release.set()
            await closing
            assert refreshed == [True]
            assert not workspace.lock.locked()
            assert not (await workspace.bootstrap())["runtime_refresh_pending"]
            if operation == "settings":
                assert plugin.config.general.request_retry_count == 2
            with pytest.raises(RuntimeError, match="关闭"):
                await workspace.save_settings('{}', workspace.store.revision)
        finally:
            release.set()
            await workspace.close()
            await plugin.on_unload()
    asyncio.run(run())


def test_cancellation_during_refresh_preserves_serialization_and_pending_failure(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        workspace = plugin._workspace_service
        entered, release = asyncio.Event(), asyncio.Event()

        async def blocked_refresh(values):
            entered.set()
            await release.wait()
            raise OSError("mock refresh failure")

        monkeypatch.setattr(workspace, "apply_settings", blocked_refresh)
        caller = asyncio.create_task(workspace.save_settings('{}', workspace.store.revision))
        try:
            await entered.wait()
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert workspace.lock.locked()
            release.set()
            await workspace.close()
            snapshot = await workspace.bootstrap()
            assert snapshot["runtime_refresh_pending"]
            assert not snapshot["config_update_pending"]
        finally:
            release.set()
            await plugin.on_unload()
    asyncio.run(run())


def test_failed_commit_never_claims_success(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        workspace = plugin._workspace_service
        revision = workspace.store.revision
        def fail(*args):
            raise OSError("mock write failure")
        monkeypatch.setattr(workspace.store, "save_common", fail)
        try:
            with pytest.raises(OSError, match="mock write failure"):
                await workspace.save_settings('{}', revision)
            assert workspace.store.revision == revision
            assert not workspace.lock.locked()
            assert not workspace.runtime_refresh_pending
        finally:
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize("failure", ["dump", "write", "flush", "fsync", "replace"])
def test_atomic_failures_cleanup_and_preserve_destination(tmp_path, monkeypatch, failure):
    target = tmp_path / "state.json"
    target.write_text('{"old": true}')
    def fail(*args, **kwargs):
        raise OSError("original write error")
    if failure == "dump":
        monkeypatch.setattr(atomic.json, "dump", fail)
    elif failure in {"write", "flush"}:
        original_temporary = atomic.tempfile.NamedTemporaryFile

        class FailedFile:
            def __init__(self, handle):
                self.handle = handle

            def __getattr__(self, name):
                return fail if name == failure else getattr(self.handle, name)

        @contextmanager
        def failing_file(*args, **kwargs):
            with original_temporary(*args, **kwargs) as handle:
                yield FailedFile(handle)

        monkeypatch.setattr(atomic.tempfile, "NamedTemporaryFile", failing_file)
    elif failure == "fsync":
        monkeypatch.setattr(atomic.os, "fsync", fail)
    else:
        monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="original write error"):
        atomic.write_json_atomically(target, {"value": "x" * 1000})
    assert target.read_text(encoding="utf-8") == '{"old": true}'
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_cleanup_failure_preserves_original_error_and_reports(tmp_path, monkeypatch, caplog):
    def fail_write(*args, **kwargs):
        raise OSError("original write error")
    def fail_cleanup(*args, **kwargs):
        raise PermissionError("cleanup error")
    monkeypatch.setattr(atomic.os, "fsync", fail_write)
    monkeypatch.setattr(Path, "unlink", fail_cleanup)
    with pytest.raises(OSError, match="original write error"):
        atomic.write_json_atomically(tmp_path / "state.json", {"value": 1})
    assert "cleanup failed" in caplog.text
    assert "PermissionError" in caplog.text


def test_following_save_waits_for_cancelled_callers_runtime_refresh(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin()
        await plugin.on_load()
        workspace = plugin._workspace_service
        entered, release = asyncio.Event(), asyncio.Event()
        original_apply = workspace.apply_settings
        refreshes = []

        async def first_refresh(values):
            if not refreshes:
                entered.set()
                await release.wait()
            await original_apply(values)
            refreshes.append(plugin.config.general.request_retry_count)

        monkeypatch.setattr(workspace, "apply_settings", first_refresh)
        first = asyncio.create_task(workspace.save_settings('{"general":{"request_retry_count":1}}', workspace.store.revision))
        try:
            await entered.wait()
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            committed_revision = workspace.store.revision
            second = asyncio.create_task(workspace.save_settings('{"general":{"request_retry_count":2}}', committed_revision))
            await asyncio.sleep(0)
            assert not second.done()
            assert workspace.store.revision == committed_revision
            release.set()
            result = await second
            assert result["saved"]
            assert refreshes == [1, 2]
            assert plugin.config.general.request_retry_count == 2
        finally:
            release.set()
            await workspace.close()
            await plugin.on_unload()
    asyncio.run(run())
