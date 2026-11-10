"""Small synthetic results test resource gates without network or large rasters."""
from io import BytesIO
from types import SimpleNamespace
import asyncio
import base64
import struct
import zipfile
import zlib

import pytest
from test_provider_request_phases import module, comfy_provider
from test_workspace import image_bytes

collection = module('infrastructure.media.collection')
media = module('infrastructure.media.images')
errors = module('domain.errors')


def png_header(width, height):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(b'')) + chunk(b'IEND', b''))


@pytest.mark.parametrize('kind,classname', [('openai','OpenaiImage'), ('siliconflow','SiliconFlowImage'),
    ('zhipu','ZhipuImage'), ('volcengine','VolcengineImage'), ('novelai','NovelAIImage')])
def test_all_inline_collectors_stop_before_extra_decode(monkeypatch, kind, classname):
    monkeypatch.setattr(collection, 'MAX_RESULT_IMAGES', 2)
    provider = getattr(module('infrastructure.providers.' + kind), classname)('fake')
    raw = image_bytes()
    encoded = base64.b64encode(raw).decode()
    payload = {'data': [{'b64_json': encoded}] * 3}
    parser = provider._extract_images_from_json if kind == 'novelai' else provider._extract_images
    calls = []
    original = collection.base64.b64decode
    def decode(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(collection.base64, 'b64decode', decode)
    with pytest.raises(errors.ProviderResultError) as failure:
        asyncio.run(parser(payload))
    assert len(calls) == 2
    assert not failure.value.retryable and not failure.value.allow_fallback


def test_nested_inline_formats_share_budget(monkeypatch):
    monkeypatch.setattr(collection, 'MAX_RESULT_IMAGES', 2)
    provider = module('infrastructure.providers.openai').OpenaiImage('fake')
    encoded = base64.b64encode(image_bytes()).decode()
    payload = {'choices': [{'message': {'content': [
        {'inlineData': {'data': encoded}}, {'source': {'data': encoded}}, {'b64_json': encoded}
    ]}}]}
    with pytest.raises(errors.ProviderResultError):
        asyncio.run(provider._extract_chat_completion_images(payload))


def test_zip_prechecks_before_extra_inflate(monkeypatch):
    monkeypatch.setattr(collection, 'MAX_RESULT_IMAGES', 2)
    provider = module('infrastructure.providers.novelai').NovelAIImage('fake')
    output = BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for index in range(3):
            archive.writestr(f'{index}.png', image_bytes())
    opened = []
    original = zipfile.ZipFile.open
    def record(self, *args, **kwargs):
        opened.append(1)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(zipfile.ZipFile, 'open', record)
    with pytest.raises(errors.ProviderResultError):
        provider._extract_images_from_zip(output.getvalue())
    assert len(opened) == 2


def test_sdk_collection_is_bounded(monkeypatch):
    monkeypatch.setattr(collection, 'MAX_RESULT_IMAGES', 2)
    part = SimpleNamespace(thought=False, inline_data=SimpleNamespace(data=image_bytes(), mime_type='image/png'))
    response = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part] * 3))])
    with pytest.raises(errors.ProviderResultError):
        module('infrastructure.providers.gemini').GoogleImage._extract_images_from_generate_content_response(response)


def test_aggregate_bytes_checked_before_decode(monkeypatch):
    raw = image_bytes()
    monkeypatch.setattr(collection, 'MAX_RESULT_BYTES', len(raw) * 2 - 1)
    @collection.bounded_results
    def collect():
        collection.decode_result_base64(base64.b64encode(raw))
        collection.decode_result_base64(base64.b64encode(raw))
    with pytest.raises(errors.ProviderResultError):
        collect()
    assert collection._budget.get() is None


@pytest.mark.parametrize('size', [(8000,8000), (8193,1)])
def test_pixels_rejected_before_preview_decode(monkeypatch, size):
    raw = png_header(*size)
    with pytest.raises(ValueError, match='像素'):
        media.validate_image_bytes(raw)
    store = module('infrastructure.storage.results')
    def forbidden(*args, **kwargs):
        pytest.fail('raster decode/transposition should not begin')
    monkeypatch.setattr(store.ImageOps, 'exif_transpose', forbidden)
    with pytest.raises(ValueError, match='像素'):
        store.ImageResultStore._preview(raw, 320, 15000)


def test_4k_dimensions_and_total_pixel_gate(monkeypatch):
    assert media.check_image_dimensions(SimpleNamespace(size=(4096,4096))) == 16777216
    assert media.check_image_dimensions(SimpleNamespace(size=(8192,2048))) == 16777216
    assert media.check_image_dimensions(SimpleNamespace(size=(5000,4000))) == 20000000
    with pytest.raises(ValueError, match='像素'):
        media.check_image_dimensions(SimpleNamespace(size=(5000,4001)))
    monkeypatch.setattr(collection, 'MAX_RESULT_PIXELS', 640 * 400)
    with pytest.raises(errors.ProviderResultError):
        collection.validate_result_images([image_bytes(), image_bytes()])


def test_remaining_budget_reaches_download_reader(monkeypatch):
    downloads = module('infrastructure.media.downloads')
    raw = image_bytes()
    monkeypatch.setattr(collection, 'MAX_RESULT_BYTES', len(raw) * 2 - 1)
    calls = []
    async def fake_download(*args, **kwargs):
        calls.append(collection.current_budget().available())
        return raw
    monkeypatch.setattr(downloads, '_download_image', fake_download)
    @collection.bounded_results
    async def collect():
        for _ in range(3):
            await downloads.download_image('http://example.invalid/image', base_url='http://example.invalid',
                proxy_settings=None, timeout_seconds=1)
    with pytest.raises(errors.ProviderResultError):
        asyncio.run(collect())
    assert calls == [len(raw) * 2 - 1, len(raw) - 1]


@pytest.mark.parametrize('kind', ['aliyun', 'comfyui'])
def test_url_only_collectors_stop_downloads(monkeypatch, tmp_path, kind):
    monkeypatch.setattr(collection, 'MAX_RESULT_IMAGES', 2)
    downloads = module('infrastructure.media.downloads')
    calls = []
    async def download(*args, **kwargs):
        calls.append(1)
        return image_bytes()
    monkeypatch.setattr(downloads, '_download_image', download)
    if kind == 'aliyun':
        provider = module('infrastructure.providers.aliyun').AliyunImage('fake')
        operation = provider._extract_images({'output': {'choices': [{'message': {'content': [
            {'image': 'https://example.invalid/image'}] * 3}}]}})
    else:
        provider = comfy_provider(tmp_path)
        async def queue(*args): return 'remote-id'
        async def history(*args): return {}
        monkeypatch.setattr(provider, '_queue_prompt', queue)
        monkeypatch.setattr(provider, '_wait_for_history', history)
        monkeypatch.setattr(provider, '_extract_image_descriptors', lambda *args: [
            {'filename': 'image.png', 'subfolder': '', 'type': 'output'}] * 3)
        operation = provider._execute_workflow({}, 'draw')
    with pytest.raises(errors.ProviderResultError):
        asyncio.run(operation)
    assert len(calls) == 2


def test_budget_error_never_switches_generation_endpoint(monkeypatch):
    monkeypatch.setattr(collection, 'MAX_RESULT_IMAGES', 2)
    provider = module('infrastructure.providers.openai').OpenaiImage('fake')
    calls = []
    async def modes(*args): return ['images', 'chat_completions']
    async def post(**kwargs):
        calls.append(kwargs['url'])
        return {'data': [{'b64_json': base64.b64encode(image_bytes()).decode()}] * 3}
    monkeypatch.setattr(provider, '_resolve_request_modes', modes)
    monkeypatch.setattr(provider, '_post_json', post)
    with pytest.raises(errors.ProviderResultError):
        asyncio.run(provider.generate_images('test', 'model'))
    assert len(calls) == 1
