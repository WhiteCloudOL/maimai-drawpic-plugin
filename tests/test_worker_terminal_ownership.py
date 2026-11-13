"""Cancelled SDK threads and storage-only terminal recovery; no network calls."""
import asyncio
import json
from threading import Event

import pytest

from test_workspace import image_bytes, make_plugin
from test_lifecycle_settlement import configured_plugin, remaining


@pytest.mark.parametrize('timeout', [False, True])
def test_sync_worker_keeps_quota_until_actual_exit(make_plugin, monkeypatch, timeout):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        service = plugin._require_draw_service()
        entered, release = Event(), Event()
        calls, sends = [], []
        def provider():
            calls.append(1)
            entered.set()
            assert release.wait(5)
            return [image_bytes()]
        async def generate(**kwargs):
            return await service.run_provider_call(provider)
        async def send(**kwargs):
            sends.append(1)
            return 1
        monkeypatch.setattr(service, '_run_image_request_attempt', generate)
        monkeypatch.setattr(service.stream_service, 'send_generated_images_with_fallback', send)
        monkeypatch.setattr(service, 'CANCEL_WAIT_SECONDS', .03)
        monkeypatch.setattr(service, 'SHUTDOWN_WAIT_SECONDS', .03)
        if timeout:
            monkeypatch.setattr(service, 'resolve_request_timeout_seconds', lambda: .01)
        try:
            receipt = await plugin.drawpic_submit_v2('cat', stream_id='mock-stream', request_id='owned-worker-key')
            assert await asyncio.to_thread(entered.wait, 2)
            if timeout:
                await asyncio.sleep(.03)
            else:
                result = await plugin.drawpic_cancel_v2(receipt['task_id'])
                assert result['cancel_requested'] and result['status'] == 'running'
            assert service.has_active_work and len(service.background_tasks) == 1
            assert remaining(plugin) == 0
            with pytest.raises(RuntimeError, match='卸载尚未完成'):
                await asyncio.wait_for(plugin.on_unload(), 1)
            assert plugin._workspace_service is not None
            assert service in plugin._draw_services and service.has_active_work
            assert remaining(plugin) == 0
            release.set()
            await asyncio.wait_for(asyncio.gather(*tuple(service.background_tasks), return_exceptions=True), 2)
            assert not service.has_active_work and remaining(plugin) == 1
            assert calls == [1] and not sends
            assert plugin._task_store.get_task(receipt['task_id']).status == 'failed'
        finally:
            release.set()
            await plugin.on_unload()
    asyncio.run(run())


def test_cancelled_sync_workers_still_enforce_four_task_capacity(make_plugin, monkeypatch):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        service = plugin._require_draw_service()
        release = Event()
        entered = [Event() for _ in range(4)]
        calls = []
        def provider(index):
            entered[index].set()
            assert release.wait(5)
            return [image_bytes()]
        async def generate(**kwargs):
            index = len(calls)
            calls.append(index)
            return await service.run_provider_call(provider, index)
        monkeypatch.setattr(service, '_run_image_request_attempt', generate)
        monkeypatch.setattr(service, 'CANCEL_WAIT_SECONDS', .01)
        try:
            for index in range(4):
                receipt = await plugin.drawpic_submit_v2('cat', request_id=f'capacity-worker-{index}')
                assert receipt['accepted']
                assert await asyncio.to_thread(entered[index].wait, 2)
                await plugin.drawpic_cancel_v2(receipt['task_id'])
            blocked = await plugin.drawpic_submit_v2('cat', request_id='capacity-worker-4')
            assert not blocked['accepted'] and blocked['error']['code'] == 'CONCURRENCY_LIMIT'
            assert len(service.background_tasks) == len(calls) == 4
        finally:
            release.set()
            await plugin.on_unload()
    asyncio.run(run())


@pytest.mark.parametrize('failures', [1, 2, 100])
def test_terminal_retry_never_regenerates_or_resends(make_plugin, monkeypatch, failures):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        service, store = plugin._require_draw_service(), plugin._task_store
        original = store.update_task
        calls, sends, writes = [], [], []
        async def generate(**kwargs):
            calls.append(1)
            return [image_bytes()]
        async def send(**kwargs):
            sends.append(1)
            return 1
        def update(*args, **kwargs):
            if kwargs.get('status') == 'completed':
                writes.append(dict(kwargs))
                if len(writes) <= failures:
                    raise OSError('mock terminal disk failure')
            return original(*args, **kwargs)
        monkeypatch.setattr(service, '_run_image_request_attempt', generate)
        monkeypatch.setattr(service.stream_service, 'send_generated_images_with_fallback', send)
        monkeypatch.setattr(store, 'update_task', update)
        original_save = store.save
        def fail_save():
            raise OSError('persistent mock disk failure')
        try:
            receipt = await plugin.drawpic_submit_v2('cat', stream_id='mock-stream', request_id='terminal-retry-key')
            await asyncio.wait_for(asyncio.gather(*tuple(service.background_tasks)), 2)
            assert calls == sends == [1] and remaining(plugin) == 0
            assert all(item == writes[0] for item in writes)
            record = store.get_task(receipt['task_id'])
            assert record.status == 'completed' and record.sent_count == 1
            if failures == 100:
                assert len(writes) == 3 and record.persistence_pending
                monkeypatch.setattr(store, 'save', fail_save)
                detail = await plugin.drawpic_task_v2(receipt['task_id'])
                assert detail['persistence_pending'] and detail['status'] == 'completed'
                assert detail['delivery']['status'] == 'sent'
                assert '终态尚未落盘' in detail['message']
                assert json.loads(store.path.read_text(encoding="utf-8"))['tasks'][record.task_id]['status'] == 'running'
                monkeypatch.setattr(store, 'save', original_save)
                detail = await plugin.drawpic_task_v2(receipt['task_id'])
                assert not detail['persistence_pending']
            else:
                assert len(writes) == failures + 1 and not record.persistence_pending
            assert json.loads(store.path.read_text(encoding="utf-8"))['tasks'][record.task_id]['status'] == 'completed'
            reused = await plugin.drawpic_submit_v2('cat', stream_id='mock-stream', request_id='terminal-retry-key')
            assert reused['reused'] and calls == sends == [1]
        finally:
            monkeypatch.setattr(store, 'save', original_save)
            await plugin.on_unload()
    asyncio.run(run())


def test_unload_keeps_pending_terminal_and_logs_until_storage_recovers(make_plugin, monkeypatch):
    async def run():
        plugin = await configured_plugin(make_plugin, monkeypatch)
        service, store = plugin._require_draw_service(), plugin._task_store
        original = store.update_task
        original_save = store.save
        def fail_save():
            raise OSError('mock unavailable disk')
        def update(*args, **kwargs):
            if kwargs.get('status') == 'completed':
                monkeypatch.setattr(store, 'save', fail_save)
            return original(*args, **kwargs)
        async def generate(**kwargs):
            return [image_bytes()]
        monkeypatch.setattr(service, '_run_image_request_attempt', generate)
        monkeypatch.setattr(store, 'update_task', update)
        try:
            receipt = await plugin.drawpic_submit_v2('cat', request_id='unload-terminal-key')
            await asyncio.wait_for(asyncio.gather(*tuple(service.background_tasks)), 2)
            assert store.get_task(receipt['task_id']).persistence_pending
            with pytest.raises(OSError, match='mock unavailable disk'):
                await asyncio.wait_for(plugin.on_unload(), 2)
            assert plugin._workspace_service is not None
            assert store.get_task(receipt['task_id']).persistence_pending
            monkeypatch.setattr(store, 'save', original_save)
            await plugin.on_unload()
            assert not store.get_task(receipt['task_id']).persistence_pending
            assert json.loads(store.path.read_text(encoding="utf-8"))['tasks'][receipt['task_id']]['status'] == 'completed'
        finally:
            monkeypatch.setattr(store, 'save', original_save)
            await plugin.on_unload()
    asyncio.run(run())
