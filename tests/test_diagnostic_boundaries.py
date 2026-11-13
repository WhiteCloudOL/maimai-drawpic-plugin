"""Isolated diagnostics and bounded-log regressions, using fake credentials only."""
from io import StringIO
from types import SimpleNamespace
from threading import Event, Thread
from test_workspace import _PACKAGE
import asyncio
import importlib
import logging
import pytest


def module(name):
    return importlib.import_module(f"{_PACKAGE}.src.maimai_drawpic.{name}")


@pytest.mark.parametrize("diagnostic", [
    'HTTPS://example.invalid/object?X-Amz-Signature=FAKE_SIGNATURE',
    r'{"error":{"message":"https:\/\/example.invalid\/object?X-Amz-Signature=FAKE_SIGNATURE"}}',
    r'{"error":{"message":"\u0068ttps:\u002f\u002fexample.invalid/object?sig=FAKE_SIGNATURE"}}',
    {'nested': [r'https:\/\/example.invalid\/object?X-Amz-Signature=FAKE_SIGNATURE']},
])
def test_url_diagnostics_redacted_at_host_log_and_task_disk(tmp_path, diagnostic):
    redactor = module('infrastructure.observability.redaction').SecretRedactor()
    error = module('infrastructure.http').provider_response_error(400, diagnostic, '', 'mock')
    logger = logging.Logger('diagnostic-test')
    logger.addFilter(redactor)
    output = StringIO()
    logger.addHandler(logging.StreamHandler(output))
    logger.error('%s', error)
    store = module('infrastructure.storage.tasks').DrawTaskStore(tmp_path/'tasks.json', sanitize=redactor.redact)
    task = store.create_task(session_key='mock', stream_id='', task_type='draw', prompt='', model='mock', provider='mock', message=str(error))
    for text in [str(error), task.message, store.path.read_text(encoding="utf-8"), output.getvalue()]:
        assert 'FAKE_SIGNATURE' not in text
        assert 'example.invalid/object' in text
        assert 'HTTP 400' in text


@pytest.mark.parametrize('method', ['handle_draw', 'handle_edit_image', 'handle_styled_draw'])
@pytest.mark.parametrize('error_type', [RuntimeError, PermissionError, ValueError])
@pytest.mark.parametrize('notify', [True, False])
def test_pre_admission_errors_are_safe_in_tools_and_chat(method, error_type, notify):
    Drawing = module('interfaces.tools.drawing').DrawingToolMixin
    Replies = module('interfaces.chat.replies').ReplyMixin
    redactor = module('infrastructure.observability.redaction').SecretRedactor()
    key = 'FAKE_CONFIGURED_CREDENTIAL'
    redactor.add([key])
    error = error_type(f'credential {key} HTTPS://example.invalid/x?Signature=FAKE_SIGNATURE')

    Styles = module('interfaces.tools.styles').StyleToolMixin
    class Probe(Drawing, Styles, Replies):
        def __init__(self):
            self._redactor = redactor
            self.ctx = SimpleNamespace(logger=logging.Logger('tool-test'))
            self.config = SimpleNamespace(general=module('domain.configuration.models').GeneralConfig(failure_reason_enabled=notify))
            self.sent = []
        def _extract_invocation_context(self, **kwargs):
            return dict(stream_id='mock', user_id='mock', group_id='', platform='mock')
        async def _start_background_image_request(self, **kwargs):
            raise error
        async def resolve_live_stream_context(self, **kwargs):
            return kwargs
        def _merge_resolved_runtime_context(self, context, **kwargs):
            return context
        def _require_style_prompt_resolver(self):
            raise error
        def _require_draw_service(self):
            raise error
        def _require_stream_service(self):
            return self
        async def send_text_with_fallback(self, **kwargs):
            self.sent.append(kwargs['text'])
            return True
    probe = Probe()
    response = asyncio.run(getattr(probe, method)('mock prompt'))
    assert response['success'] is False
    assert len(probe.sent) == int(notify)
    for text in [response['message'], *probe.sent]:
        assert key not in text and 'FAKE_SIGNATURE' not in text
        if error_type is RuntimeError:
            assert '错误 ID' in text and 'credential' not in text


def test_failure_notice_uses_rotated_runtime_secrets():
    Replies = module('interfaces.chat.replies').ReplyMixin
    probe = Replies()
    probe._redactor = module('infrastructure.observability.redaction').SecretRedactor()
    probe._redactor.add(['OLD_FAKE_CREDENTIAL'])
    probe._redactor.add(['NEW_FAKE_CREDENTIAL'])
    result = probe._summarize_failure_reason('OLD_FAKE_CREDENTIAL NEW_FAKE_CREDENTIAL https://example.invalid/a?sig=FAKE_SIGNATURE')
    assert 'FAKE_' not in result
    encoded = r'\u004fLD_FAKE_CREDENTIAL \u004eEW_FAKE_CREDENTIAL'
    assert 'FAKE_' not in probe._summarize_failure_reason(encoded)


def test_bounded_queue_drops_nonblocking_and_stops_when_full(tmp_path):
    Logs = module('infrastructure.observability.logging').WorkspaceLogStore
    logger = logging.Logger('bounded-test', logging.INFO)
    store = Logs(tmp_path, logger, lambda: ['FAKE_CONFIGURED_CREDENTIAL'], 1)
    started, release, closed = Event(), Event(), Event()
    original = store.file_handler.emit
    def blocked_emit(record):
        started.set()
        assert release.wait(5)
        original(record)
    store.file_handler.emit = blocked_emit
    sentinel_queued = Event()
    enqueue_sentinel = store.listener.enqueue_sentinel
    def observed_sentinel():
        enqueue_sentinel()
        sentinel_queued.set()
    store.listener.enqueue_sentinel = observed_sentinel
    closer = None
    try:
        logger.info('first')
        assert started.wait(2)
        for index in range(300):
            logger.info('event %s FAKE_CONFIGURED_CREDENTIAL %s', index, 'x'*10000)
        assert store.queue_handler.queue.qsize() == 256
        assert store.dropped_records == 44
        # Queued messages themselves are already bounded and redacted.
        record = store.queue_handler.queue.queue[0]
        assert len(record.msg) <= 500
        assert 'FAKE_CONFIGURED_CREDENTIAL' not in record.msg
        def close():
            store.close()
            closed.set()
        closer = Thread(target=close)
        closer.start()
        assert sentinel_queued.wait(2)
        assert store.dropped_records == 45
        release.set()
        assert closed.wait(5)
        closer.join()
        store.close()
        assert store.listener._thread is None
        assert store.dropped_records >= 44
        assert store.query()['dropped_records'] == store.dropped_records
        assert 'FAKE_CONFIGURED_CREDENTIAL' not in store.path.read_text(encoding="utf-8")
        assert '已丢弃' in store.path.read_text(encoding="utf-8")
    finally:
        release.set()
        if closer:
            closer.join(5)
        store.close()


@pytest.mark.parametrize("error_type", [ValueError, PermissionError])
def test_private_api_expected_error_is_redacted(error_type):
    redactor = module('infrastructure.observability.redaction').SecretRedactor()
    redactor.add(['FAKE_CREDENTIAL'])
    owner = SimpleNamespace(_redactor=redactor)
    @module('interfaces.api.base').workspace_endpoint
    async def handler(self):
        raise error_type(r'bad input \u0046AKE_CREDENTIAL HTTPS://example.invalid/a?sig=FAKE_SIGNATURE')
    result = asyncio.run(handler(owner))
    assert '__workspace_error__' in result
    assert 'bad input' in result['__workspace_error__']
    assert 'FAKE_' not in result['__workspace_error__']
