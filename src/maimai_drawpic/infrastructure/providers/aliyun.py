"""阿里云百炼图像平台传输适配器。"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit
import aiohttp
import asyncio
import base64
import json
import re
import time

from ..media.collection import bounded_results
from ..media.images import detect_mime_type
from ..http import provider_response_error, sanitized_log_args
from ..media.downloads import download_image
from ...domain.errors import ProviderRequestError, ProviderResultError
from .requests import generation_submission, query_submitted_task, submitted_task
from ..http import HttpProxySettings, read_response_text, sanitize_provider_url
from ...domain.models.aliyun_profiles import (
    AliyunRequestOptions,
    build_aliyun_parameters,
    resolve_aliyun_model_profile,
    supports_aliyun_negative_prompt,
    validate_aliyun_task,
)


class AliyunImage:
    """阿里云百炼同步与异步图像接口适配器。"""

    _SYNC_GENERATION_PATH = "services/aigc/multimodal-generation/generation"
    _ASYNC_GENERATION_PATH = "services/aigc/image-generation/generation"
    _ASYNC_HEADER = {"X-DashScope-Async": "enable"}
    _TERMINAL_FAILURE_STATES = {"FAILED", "CANCELED", "UNKNOWN"}

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/api/v1",
        logger: Any | None = None,
        request_timeout_seconds: int = 20,
        default_size: str = "1024*1024",
        model_size_overrides: dict[str, str] | None = None,
        negative_prompt: str = "",
        prompt_extend: bool = True,
        qwen_prompt_extend_mode: str = "direct",
        qwen_enable_thinking: bool = True,
        zimage_prompt_extend: bool = False,
        seed: int = 0,
        watermark: bool = False,
        max_images: int = 1,
        image_input_mode: str = "auto",
        async_poll_interval_seconds: float = 5.0,
        kling_aspect_ratio: str = "1:1",
        kling_resolution: str = "1k",
        kling_result_type: str = "single",
        kling_series_amount: int = 4,
        qwen_extra_parameters: dict[str, Any] | None = None,
        zimage_extra_parameters: dict[str, Any] | None = None,
        kling_extra_parameters: dict[str, Any] | None = None,
        vidu_extra_parameters: dict[str, Any] | None = None,
        extra_parameters: dict[str, Any] | None = None,
        proxy_settings: HttpProxySettings | None = None,
        skip_image_url_ip_check: bool = False,
    ) -> None:
        self.api_key = api_key.strip()
        self.base_url = self._normalize_base_url(base_url)
        self.logger = logger
        self.request_timeout_seconds = max(int(request_timeout_seconds), 1)
        self.image_input_mode = image_input_mode.strip().lower()
        self.async_poll_interval_seconds = max(
            float(async_poll_interval_seconds),
            0.0,
        )
        self.request_options = AliyunRequestOptions(
            default_size=default_size.strip(),
            model_size_overrides={
                str(model).strip(): str(size).strip()
                for model, size in (model_size_overrides or {}).items()
                if str(model).strip() and str(size).strip()
            },
            negative_prompt=negative_prompt.strip(),
            prompt_extend=prompt_extend,
            qwen_prompt_extend_mode=qwen_prompt_extend_mode.strip().lower(),
            qwen_enable_thinking=qwen_enable_thinking,
            zimage_prompt_extend=zimage_prompt_extend,
            seed=int(seed),
            watermark=watermark,
            max_images=max(int(max_images), 1),
            kling_aspect_ratio=kling_aspect_ratio.strip(),
            kling_resolution=kling_resolution.strip().lower(),
            kling_result_type=kling_result_type.strip().lower(),
            kling_series_amount=int(kling_series_amount),
            qwen_extra_parameters=dict(qwen_extra_parameters or {}),
            zimage_extra_parameters=dict(zimage_extra_parameters or {}),
            kling_extra_parameters=dict(kling_extra_parameters or {}),
            vidu_extra_parameters=dict(vidu_extra_parameters or {}),
            legacy_extra_parameters=dict(extra_parameters or {}),
        )
        self.proxy_settings = proxy_settings or HttpProxySettings.disabled()
        self.skip_image_url_ip_check = skip_image_url_ip_check

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """校验并规范化包含 ``/api/v1`` 的 DashScope Base URL。"""

        normalized_url = base_url.strip().rstrip("/")
        parsed_url = urlsplit(normalized_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ValueError("阿里云 DashScope Base URL 必须是有效的 HTTP(S) 地址")
        if parsed_url.query or parsed_url.fragment:
            raise ValueError("阿里云 DashScope Base URL 不能包含查询参数或片段")
        if not parsed_url.path.rstrip("/").endswith("/api/v1"):
            raise ValueError("阿里云 DashScope Base URL 必须包含并以 /api/v1 结尾")
        return normalized_url

    def _build_url(self, path: str) -> str:
        """基于可配置 Base URL 构造接口地址。"""

        return f"{self.base_url}/{path.lstrip('/')}"

    async def generate_images(
        self,
        prompt: str,
        model: str,
        n: int = 1,
    ) -> list[bytes]:
        """按模型能力选择同步或异步文生图接口。"""

        normalized_model = model.strip()
        validate_aliyun_task(
            normalized_model,
            "draw",
            0,
            self.image_input_mode,
        )
        payload = self._build_payload(
            prompt,
            normalized_model,
            "draw",
            [],
            n,
        )
        response = await self._execute_request(normalized_model, payload)
        return await self._extract_images(response, normalized_model)

    async def edit_images(
        self,
        prompt: str,
        model: str,
        image_bytes_list: list[bytes],
        n: int = 1,
    ) -> list[bytes]:
        """兼容旧调用；URL 模型会明确提示需要结构化源图接口。"""

        return await self.edit_images_with_urls(
            prompt,
            model,
            image_bytes_list,
            [""] * len(image_bytes_list),
            n,
        )

    async def edit_images_with_urls(
        self,
        prompt: str,
        model: str,
        image_bytes_list: list[bytes],
        image_urls: list[str],
        n: int = 1,
    ) -> list[bytes]:
        """根据模型要求使用 Base64 或适配器原始 URL 执行图生图。"""

        normalized_model = model.strip()
        image_count = len(image_bytes_list)
        resolved_input_mode = validate_aliyun_task(
            normalized_model,
            "edit_image",
            image_count,
            self.image_input_mode,
        )
        image_values = await asyncio.to_thread(
            self._build_image_values,
            normalized_model,
            resolved_input_mode,
            image_bytes_list,
            image_urls,
        )
        payload = self._build_payload(
            prompt,
            normalized_model,
            "edit_image",
            image_values,
            n,
        )
        response = await self._execute_request(normalized_model, payload)
        return await self._extract_images(response, normalized_model)

    def _build_image_values(
        self,
        model: str,
        input_mode: str,
        image_bytes_list: list[bytes],
        image_urls: list[str],
    ) -> list[str]:
        """构造上游图片值，URL 模式不允许退回 Base64。"""

        if input_mode == "base64":
            image_values: list[str] = []
            for image_bytes in image_bytes_list:
                mime_type = detect_mime_type(image_bytes)
                encoded_image = base64.b64encode(image_bytes).decode("ascii")
                image_values.append(f"data:{mime_type};base64,{encoded_image}")
            return image_values

        if len(image_urls) != len(image_bytes_list):
            raise ValueError(f"阿里云模型 {model} 使用 URL 输入时，源图数据与 URL 数量必须一致")
        normalized_urls: list[str] = []
        for image_url in image_urls:
            parsed_url = urlsplit(image_url.strip())
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                raise ValueError(f"阿里云模型 {model} 需要适配器提供每张源图的 HTTP(S) URL")
            normalized_urls.append(image_url.strip())
        return normalized_urls

    def _build_payload(
        self,
        prompt: str,
        model: str,
        task_type: str,
        image_values: list[str],
        n: int,
    ) -> dict[str, Any]:
        """构造统一消息请求体，模型参数由 models 层负责。"""

        profile = resolve_aliyun_model_profile(model)
        if self.request_options.negative_prompt and not supports_aliyun_negative_prompt(model):
            prompt += f"\nNegative prompt: {self.request_options.negative_prompt}"
        text_content = {"text": prompt}
        image_content = [{"image": image_value} for image_value in image_values]
        if profile.family in {"kling", "vidu"}:
            content = [text_content, *image_content]
        else:
            content = [*image_content, text_content]
        return {
            "model": model,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": content,
                    }
                ]
            },
            "parameters": build_aliyun_parameters(
                model,
                task_type,
                n,
                self.request_options,
            ),
        }

    async def _execute_request(
        self,
        model: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """按模型协议执行同步请求或异步提交与轮询。"""

        profile = resolve_aliyun_model_profile(model)
        if profile.is_async:
            task_id = await self._submit_async_task(model, payload)
            async with submitted_task("阿里云", task_id):
                return await self._poll_async_task(task_id, model)

        response = await self._post_json(
            self._build_url(self._SYNC_GENERATION_PATH),
            payload,
        )
        self._raise_for_business_error(response, model=model, operation="同步生成")
        return response

    async def _submit_async_task(
        self,
        model: str,
        payload: dict[str, Any],
    ) -> str:
        """提交异步图片任务并返回任务 ID。"""

        response = await self._post_json(
            self._build_url(self._ASYNC_GENERATION_PATH),
            payload,
            extra_headers=self._ASYNC_HEADER,
        )
        self._raise_for_business_error(response, model=model, operation="异步任务提交")
        output = response.get("output")
        task_id = output.get("task_id") if isinstance(output, dict) else ""
        if not isinstance(task_id, str) or not task_id.strip():
            request_id = self._response_request_id(response)
            raise RuntimeError(
                f"阿里云模型 {model} 异步任务提交响应缺少 task_id（request_id={request_id or 'unknown'}）"
            )
        self._log_info(
            "阿里云异步任务已提交: model=%s task_id=%s request_id=%s",
            model,
            task_id,
            self._response_request_id(response) or "unknown",
        )
        return task_id.strip()

    async def _poll_async_task(
        self,
        task_id: str,
        model: str,
    ) -> dict[str, Any]:
        """轮询异步任务，仅在状态发生变化时记录日志。"""

        started_at = time.monotonic()
        previous_status = ""
        while True:
            response = await query_submitted_task(
                lambda: self._get_json(self._build_url(f"tasks/{task_id}")),
                poll_interval=self.async_poll_interval_seconds,
            )
            output = response.get("output")
            status_value = output.get("task_status") if isinstance(output, dict) else ""
            status = str(status_value or "").strip().upper()
            request_id = self._response_request_id(response)

            if status != previous_status:
                self._log_info(
                    "阿里云异步任务状态变化: model=%s task_id=%s from=%s to=%s duration=%.2fs request_id=%s",
                    model,
                    task_id,
                    previous_status or "SUBMITTED",
                    status or "MISSING",
                    time.monotonic() - started_at,
                    request_id or "unknown",
                )
                previous_status = status

            if status == "SUCCEEDED":
                return response
            if status in self._TERMINAL_FAILURE_STATES:
                code, message, request_id = self._extract_error_fields(response)
                if code == "unknown":
                    code = status
                if message == "未知错误":
                    message = "异步任务未成功完成"
                error = ProviderRequestError(
                    400,
                    code,
                    f"阿里云模型 {model} 异步任务 {task_id} 终止："
                    f"status={status}, code={code}, message={message}, "
                    f"request_id={request_id or 'unknown'}"
                )
                if error.rejected:
                    # 审核错误保留分类，其他已受理任务的终态失败仍不能触发重绘。
                    error.remote_task_id = task_id
                    error.request_id = request_id
                    raise error
                raise ProviderResultError(str(error))
            if not status:
                self._raise_for_business_error(
                    response,
                    model=model,
                    operation="异步任务查询",
                )
                raise RuntimeError(
                    f"阿里云模型 {model} 异步任务 {task_id} 查询响应缺少 "
                    f"task_status（request_id={request_id or 'unknown'}）"
                )
            if status not in {"PENDING", "RUNNING"}:
                raise RuntimeError(
                    f"阿里云模型 {model} 异步任务 {task_id} 返回未知状态 "
                    f"{status}（request_id={request_id or 'unknown'}）"
                )
            await asyncio.sleep(self.async_poll_interval_seconds)

    def _build_headers(
        self,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """构建鉴权请求头；请求头内容不得进入日志。"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(extra_headers or {})
        return headers

    @generation_submission
    async def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """发送 JSON POST 请求，不记录请求体和鉴权信息。"""

        return await self._request_json(
            "POST",
            url,
            payload=payload,
            extra_headers=extra_headers,
        )

    async def _get_json(self, url: str) -> dict[str, Any]:
        """发送 JSON GET 请求。"""

        return await self._request_json("GET", url)

    async def _request_json(
        self,
        method: str,
        url: str,
        payload: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """执行 HTTP 请求并生成可追踪、脱敏的传输错误。"""

        started_at = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=self.request_timeout_seconds)
        async with aiohttp.ClientSession(
            timeout=timeout,
            **self.proxy_settings.aiohttp_session_kwargs(),
        ) as session:
            async with session.request(
                method,
                url,
                headers=self._build_headers(extra_headers),
                json=payload,
                allow_redirects=False,
                **self.proxy_settings.aiohttp_request_kwargs(),
            ) as response:
                response_text = await read_response_text(response)
                duration = time.monotonic() - started_at
                try:
                    response_json = await asyncio.to_thread(json.loads, response_text)
                except json.JSONDecodeError as exc:
                    self._log_error(
                        "阿里云图片接口返回非 JSON: method=%s status=%s duration=%.2fs url=%s response_length=%s",
                        method,
                        response.status,
                        duration,
                        self._sanitize_url(url),
                        len(response_text),
                    )
                    raise RuntimeError(
                        f"阿里云图片接口返回非 JSON 响应：status={response.status}, duration={duration:.2f}s"
                    ) from exc

                if not isinstance(response_json, dict):
                    raise RuntimeError("阿里云图片接口响应必须为 JSON 对象")
                if response.status != 200:
                    code, message, request_id = self._extract_error_fields(response_json)
                    self._log_error(
                        "阿里云图片接口 HTTP 失败: method=%s status=%s duration=%.2fs "
                        "url=%s code=%s message=%s request_id=%s",
                        method,
                        response.status,
                        duration,
                        self._sanitize_url(url),
                        code,
                        message,
                        request_id,
                    )
                    error = provider_response_error(response.status, response_json, self.api_key, "aliyun 图片接口拒绝")
                    if method.upper() != "POST":
                        raise ProviderResultError(f"已提交任务的查询失败，未重新生成：{error}")
                    raise error
                return response_json

    def _raise_for_business_error(
        self,
        response: dict[str, Any],
        *,
        model: str,
        operation: str,
    ) -> None:
        """将百炼业务错误转换为包含追踪信息的安全异常。"""

        if not response.get("code"):
            return
        code, message, request_id = self._extract_error_fields(response)
        self._log_error(
            "阿里云图片接口业务失败: operation=%s model=%s code=%s message=%s request_id=%s",
            operation,
            model,
            code,
            message,
            request_id,
        )
        error = provider_response_error(
            400, response, self.api_key, f"阿里云模型 {model} {operation}失败 request_id={request_id}"
        )
        if operation == "异步任务查询" and not error.rejected:
            raise ProviderResultError(str(error))
        raise error

    def _extract_error_fields(
        self,
        response: dict[str, Any],
    ) -> tuple[str, str, str]:
        output = response.get("output")
        output = output if isinstance(output, dict) else {}
        code = self._sanitize_text(output.get("code") or response.get("code") or "unknown")
        message = self._sanitize_text(output.get("message") or response.get("message") or "未知错误")
        request_id = self._response_request_id(response) or "unknown"
        return code, message, request_id

    @staticmethod
    def _response_request_id(response: dict[str, Any]) -> str:
        request_id = response.get("request_id")
        return str(request_id).strip() if request_id is not None else ""

    def _sanitize_text(self, value: Any) -> str:
        """移除错误文本中的密钥、Base64 和 URL 查询参数。"""

        text = str(value or "")
        if self.api_key:
            text = text.replace(self.api_key, "[REDACTED]")
        text = re.sub(
            r"data:image/[^;\s]+;base64,[A-Za-z0-9+/=_-]+",
            "[BASE64_REDACTED]",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"Authorization\s*[:=]\s*Bearer\s+\S+",
            "Authorization=[REDACTED]",
            text,
            flags=re.IGNORECASE,
        )
        for url in re.findall(r"https?://[^\s\"'<>]+", text):
            text = text.replace(url, self._sanitize_url(url))
        return text[:500]

    @staticmethod
    def _sanitize_url(url: str) -> str:
        """日志与错误中只保留 URL 的协议、主机和路径。"""

        return sanitize_provider_url(str(url))

    @bounded_results
    async def _extract_images(
        self,
        response: dict[str, Any],
        model: str = "",
    ) -> list[bytes]:
        """从同步或异步响应中提取并下载生成图片。"""

        output = response.get("output")
        choices = output.get("choices") if isinstance(output, dict) else None
        if not isinstance(choices, list):
            request_id = self._response_request_id(response)
            self._log_error(
                "阿里云响应解析失败: model=%s reason=missing_choices request_id=%s",
                model or "unknown",
                request_id or "unknown",
            )
            raise RuntimeError(
                f"阿里云模型 {model or 'unknown'} 响应缺少 output.choices（request_id={request_id or 'unknown'}）"
            )

        image_urls: list[str] = []
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for item in content:
                image_url = item.get("image") if isinstance(item, dict) else None
                if isinstance(image_url, str) and image_url.strip():
                    image_urls.append(image_url.strip())
        if not image_urls:
            request_id = self._response_request_id(response)
            raise RuntimeError(
                f"阿里云模型 {model or 'unknown'} 响应中没有可用图片（request_id={request_id or 'unknown'}）"
            )
        return [await self._download_image(image_url) for image_url in image_urls]

    async def _download_image(self, url: str) -> bytes:
        """下载生成图片，日志中不记录签名查询参数。"""

        return await download_image(
            url,
            base_url=self.base_url,
            proxy_settings=self.proxy_settings,
            skip_ip_check=self.skip_image_url_ip_check,
            timeout_seconds=self.request_timeout_seconds,
        )

    def _log_info(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.info(message, *sanitized_log_args(args, self.api_key))

    def _log_error(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.error(message, *sanitized_log_args(args, self.api_key))
