"""MiniMax H3 与 image-01 的独立官方协议适配器。"""

from io import BytesIO
from PIL import Image
from typing import Any, Dict, List, Optional
import aiohttp
import asyncio
import base64
import json
import time

from ...domain.errors import ProviderOutcomeUnknown, ProviderRequestError, ProviderResultError
from ...domain.models.minimax_profiles import H3_MODELS, build_minimax_payload, max_reference_images, normalize_minimax_base_url
from ..http import HttpProxySettings, read_response_json, read_response_text, sanitize_provider_text, sanitized_log_args
from ..media.collection import bounded_results, decode_result_base64
from ..media.downloads import download_image
from ..media.images import validate_image_bytes
from .requests import generation_submission


class MiniMaxImage:
    def __init__(
        self, api_key: str, values: Dict[str, Any], *, logger: Any = None,
        proxy_settings: Optional[HttpProxySettings] = None, skip_image_url_ip_check: bool = False,
    ) -> None:
        self.api_key, self.values, self.logger = api_key, values, logger
        self.base_url = normalize_minimax_base_url(values["base_url"])
        self.proxy_settings = proxy_settings or HttpProxySettings.disabled()
        self.skip_image_url_ip_check = skip_image_url_ip_check

    async def generate_images(self, prompt: str, model: str, n: int = 1) -> List[bytes]:
        payload = build_minimax_payload(self.values, prompt, model, edit=False, n=n)
        path = "/images/generations" if model in H3_MODELS else "/image_generation"
        return await self._extract_images(await self._post(path, payload), h3=model in H3_MODELS)

    async def edit_images(self, prompt: str, model: str, image_bytes_list: List[bytes], n: int = 1) -> List[bytes]:
        payload = build_minimax_payload(self.values, prompt, model, edit=True, n=n)
        if not 1 <= len(image_bytes_list) <= max_reference_images(model):
            raise ValueError(f"MiniMax {model} 需要 1～{max_reference_images(model)} 张参考图")
        sources = await asyncio.to_thread(self._source_images, image_bytes_list, model in H3_MODELS)
        if model in H3_MODELS:
            payload["images"] = [{"image_url": source} for source in sources]
            path = "/images/edits"
        else:
            payload["subject_reference"] = [{"type": "character", "image_file": source} for source in sources]
            path = "/image_generation"
        return await self._extract_images(await self._post(path, payload), h3=model in H3_MODELS)

    @staticmethod
    def _source_images(images: List[bytes], h3: bool) -> List[str]:
        result: List[str] = []
        for index, raw in enumerate(images, 1):
            validate_image_bytes(raw)
            with Image.open(BytesIO(raw)) as image:
                fmt = image.format
                if fmt not in ({"JPEG", "PNG", "WEBP"} if h3 else {"JPEG", "PNG"}):
                    raise ValueError(f"MiniMax 第 {index} 张参考图格式不支持；image-01 仅支持 JPEG/PNG，H3 另支持 WebP")
                if h3 and (min(image.size) < 128 or max(image.size) > 8192 or max(image.size) / min(image.size) > 4):
                    raise ValueError(f"MiniMax H3 第 {index} 张参考图宽高需在 128～8192，长短边比不超过 4:1")
                if not h3 and len(raw) >= 10 * 1024 * 1024:
                    raise ValueError("MiniMax image-01 人物参考图必须小于 10 MB")
                mime = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[fmt]
            result.append(f"data:{mime};base64," + base64.b64encode(raw).decode("ascii"))
        return result

    def _error(self, status: int, data: Any, request_id: str = "") -> ProviderRequestError:
        if isinstance(data, dict):
            info = data.get("error", data.get("base_resp", data))
            info = info if isinstance(info, dict) else {}
            code = str(info.get("code", info.get("status_code", info.get("type", ""))))
            request_id = str(data.get("request_id", request_id))
        else:
            code = ""
        code = sanitize_provider_text(code, self.api_key, max_chars=100)
        detail = sanitize_provider_text(data, self.api_key, max_chars=1200)
        failure = ProviderRequestError(status, code, f"MiniMax 图片接口失败: HTTP {status} code={code} request_id={sanitize_provider_text(request_id, self.api_key)} {detail}")
        failure.rejected = code in {"1026", "1027"} or failure.rejected
        permanent = code in {"1004", "1008", "2049", "insufficient_balance_error", "authentication_error", "invalid_api_key"}
        failure.retryable = not failure.rejected and not permanent and (status == 429 or code == "1002")
        failure.allow_fallback = failure.retryable
        failure.outcome_unknown = code == "1001" or status >= 500 and not failure.rejected
        self._log("warning", "%s", failure)
        return failure

    @generation_submission
    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key.strip():
            raise ValueError("请填写 MiniMax API 密钥")
        encoded = await asyncio.to_thread(lambda: json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        if len(encoded) > 64 * 1024 * 1024:
            raise ValueError("MiniMax JSON 请求体超过 64 MiB，请减少参考图大小")
        started = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=self.values["request_timeout_seconds"])
        async with aiohttp.ClientSession(timeout=timeout, **self.proxy_settings.aiohttp_session_kwargs()) as session:
            async with session.post(
                self.base_url + path, headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, data=encoded,
                allow_redirects=False, **self.proxy_settings.aiohttp_request_kwargs(),
            ) as response:
                request_id = response.headers.get("x-request-id", "")
                self._log("info", "MiniMax 图片响应: status=%s model=%s endpoint=%s request_id=%s elapsed=%.2fs", response.status, payload["model"], self.base_url + path, request_id, time.monotonic() - started)
                if response.status != 200:
                    raw = await read_response_text(response, max_bytes=64 * 1024)
                    try:
                        data = json.loads(raw)
                    except json.JSONDecodeError:
                        data = raw
                    raise self._error(response.status, data, request_id)
                try:
                    if payload.get("stream"):
                        return await self._read_stream(response, payload["n"], path.endswith("/edits"))
                    data = await read_response_json(response)
                    if not isinstance(data, dict):
                        raise ProviderResultError("MiniMax 响应应为 JSON 对象，未重新生成")
                    data.setdefault("request_id", request_id)
                    return data
                except (ProviderRequestError, ProviderOutcomeUnknown, TimeoutError, aiohttp.ClientConnectionError):
                    raise
                except Exception as exc:
                    raise ProviderResultError(f"MiniMax 已响应但结果解析失败（{type(exc).__name__}），未重新生成") from exc

    async def _read_stream(self, response: Any, count: int, edit: bool) -> Dict[str, Any]:
        prefix = "image_edit" if edit else "image_generation"
        items: Dict[int, Dict[str, Any]] = {}
        terminal: Optional[Dict[str, Any]] = None
        pending, lines, total = b"", [], 0

        def event() -> None:
            nonlocal terminal
            if not lines:
                return
            data = json.loads(b"\n".join(lines))
            if terminal is not None or not isinstance(data, dict):
                raise ProviderResultError("MiniMax SSE 终态后收到事件或事件格式错误")
            kind = data.get("type")
            if kind == "error":
                error = data.get("error", {})
                if not isinstance(error, dict):
                    raise ProviderResultError("MiniMax SSE 错误信息格式无效")
                status = str(error.get("http_code", 500))
                if not status.isdecimal() or not 400 <= int(status) <= 599:
                    raise ProviderResultError("MiniMax SSE 错误 HTTP 状态无效")
                raise self._error(int(status), data)
            if kind == prefix + ".completed":
                terminal = data
                return
            if kind not in {prefix + ".partial_succeeded", prefix + ".partial_failed"}:
                raise ProviderResultError("MiniMax SSE 事件类型与任务不匹配")
            index = data.get("image_index")
            if type(index) is not int or not 0 <= index < count or index in items:
                raise ProviderResultError("MiniMax SSE 图片序号无效或重复")
            items[index] = {"url": data.get("url")} if kind.endswith("partial_succeeded") else {"error": {"code": data.get("code"), "message": data.get("message")}}

        async for chunk in response.content.iter_chunked(16384):
            total += len(chunk)
            if total > 2 * 1024 * 1024:
                raise ProviderResultError("MiniMax SSE 响应超过 2 MiB")
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                line = line.rstrip(b"\r")
                if not line:
                    event()
                    lines.clear()
                elif line.startswith(b"data:"):
                    lines.append(line[5:].lstrip(b" "))
        if pending.startswith(b"data:"):
            lines.append(pending[5:].lstrip(b" "))
        event()
        if terminal is None:
            raise ProviderOutcomeUnknown("MiniMax 流式连接未收到终态，远端结果不确定，未重新生成")
        if len(items) != count:
            raise ProviderResultError("MiniMax SSE 已结束但图片条目不完整，未重新生成")
        return {**terminal, "data": [items[index] for index in range(count)]}

    @bounded_results
    async def _extract_images(self, data: Dict[str, Any], *, h3: bool) -> List[bytes]:
        base = data.get("base_resp")
        if isinstance(base, dict) and base.get("status_code") not in (0, "0"):
            raise self._error(200, data)
        if "error" in data:
            raise self._error(500, data)
        items = data.get("data")
        if not h3 and isinstance(items, dict):
            urls, encoded = items.get("image_urls", []), items.get("image_base64", [])
            if not isinstance(urls, list) or not isinstance(encoded, list):
                raise ProviderResultError("MiniMax image-01 图片字段格式错误")
            items = [{"url": value} for value in urls] or [{"b64_json": value} for value in encoded]
            metadata = data.get("metadata", {})
            if isinstance(metadata, dict) and metadata.get("failed_count") not in (None, 0, "0"):
                self._log("warning", "MiniMax 部分图片未通过内容检查: failed_count=%s request_id=%s", metadata["failed_count"], data.get("request_id", data.get("id", "")))
        if not isinstance(items, list) or not 1 <= len(items) <= 10:
            raise ProviderResultError("MiniMax 响应缺少有效图片列表，未重新生成")
        result: List[bytes] = []
        errors = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ProviderResultError("MiniMax 图片条目不是对象")
            if "error" in item:
                errors.append(item["error"])
                self._log("warning", "MiniMax 单张生成失败，不补画: index=%s request_id=%s error=%s", index, data.get("request_id", ""), item["error"])
                continue
            encoded, url = item.get("b64_json"), item.get("url")
            if isinstance(encoded, str) and encoded:
                try:
                    result.append(await asyncio.to_thread(decode_result_base64, encoded, validate=True))
                except Exception as exc:
                    raise ProviderResultError("MiniMax 图片 Base64 无效，未重新生成") from exc
            elif isinstance(url, str) and url:
                result.append(await download_image(url, base_url=self.base_url, proxy_settings=self.proxy_settings,
                    skip_ip_check=self.skip_image_url_ip_check, timeout_seconds=self.values["request_timeout_seconds"]))
            else:
                raise ProviderResultError("MiniMax 图片条目缺少 URL/Base64，未重新生成")
        if not result:
            if errors:
                code = "1027" if all(isinstance(error, dict) and str(error.get("code")) in {"1026", "1027"} for error in errors) else "1000"
                raise self._error(422 if code == "1027" else 500, {"error": {"code": code, "message": errors}, "request_id": data.get("request_id", "")})
            raise ProviderResultError("MiniMax 没有返回成功图片，未重新生成")
        self._log("info", "MiniMax 图片结果已读取: success_count=%s failed_count=%s request_id=%s", len(result), len(errors), data.get("request_id", data.get("id", "")))
        return result

    def _log(self, level: str, message: str, *args: Any) -> None:
        if self.logger is not None:
            if level == "warning":
                self.logger.warning(message, *sanitized_log_args(args, self.api_key))
            else:
                self.logger.info(message, *sanitized_log_args(args, self.api_key))
