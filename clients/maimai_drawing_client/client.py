"""有界等待的正式客户端，所有路径共用 submit/task/image 幂等任务协议。"""

from pathlib import Path
from typing import Any, Dict, Optional, Union, Unpack
from uuid import uuid4
import asyncio
import json
import math
import re

from .images import encode_sources, read_image, save_bytes
from .models import DrawingError, DrawingPreferences, DrawingRequest, DrawingResult, DrawingTransportError, GeneratedImage, TaskHandle
from .protocol import TASK_STATUSES, validate_task
from .transport import APIProxy, DrawingRPC


class DrawingClient:
    def __init__(
        self,
        api: APIProxy,
        *,
        rpc_timeout: float = 8,
        poll_interval: float = 3,
        max_image_bytes: int = 64 * 1024 * 1024,
        max_result_bytes: int = 128 * 1024 * 1024,
    ) -> None:
        if not math.isfinite(rpc_timeout) or not 0 < rpc_timeout <= 30:
            raise ValueError("rpc_timeout 应为 0～30 秒（不含 0）")
        if not math.isfinite(poll_interval) or not 0 < poll_interval <= 60:
            raise ValueError("poll_interval 应为 0～60 秒（不含 0）")
        if (
            type(max_image_bytes) is not int
            or type(max_result_bytes) is not int
            or min(max_image_bytes, max_result_bytes) <= 0
        ):
            raise ValueError("图片与单次结果容量限制必须为正整数")
        self.rpc = DrawingRPC(api, rpc_timeout)
        self.poll_interval, self.max_image_bytes, self.max_result_bytes = (
            poll_interval,
            max_image_bytes,
            max_result_bytes,
        )

    @staticmethod
    def _budget(seconds: float) -> float:
        if not math.isfinite(seconds) or not 0 < seconds <= 3600:
            raise ValueError("等待预算必须为有限的 0～3600 秒（不含 0）")
        return seconds

    async def submit(self, prompt: str, *, request_id: Optional[str] = None, **kwargs: Unpack[DrawingRequest]) -> TaskHandle:
        """立即返回句柄；响应不确定时保留 request_id，绝不换键重画。"""
        request_id = uuid4().hex if request_id is None else request_id
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            raise ValueError("request_id 应为 8～80 位字母、数字、下划线或横线；省略时自动生成")
        unknown = kwargs.keys() - DrawingRequest.__annotations__.keys()
        if unknown:
            raise ValueError("未知绘图参数：" + ", ".join(sorted(unknown)))
        if kwargs.get("source_images") is not None:
            kwargs["source_images"] = await asyncio.to_thread(encode_sources, kwargs["source_images"])
        if "reference_options" in kwargs:
            reference_options = kwargs.pop("reference_options")
            if not isinstance(reference_options, dict):
                raise ValueError("reference_options 必须为对象")
            kwargs["reference_options_json"] = json.dumps(reference_options, ensure_ascii=False, allow_nan=False)
        task_id = None
        try:
            result = await self.rpc.call("submit", prompt=prompt, request_id=request_id, **kwargs)
            # 回执不完整时无法证明未受理，保留原幂等键供调用方恢复。
            if result.get("accepted") is True:
                if isinstance(result.get("task_id"), str) and result["task_id"]:
                    task_id = result["task_id"]
                if (
                    task_id is None
                    or not isinstance(result.get("status"), str)
                    or result["status"] not in TASK_STATUSES
                    or type(result.get("reused")) is not bool
                    or "request_id" in result and result["request_id"] != request_id
                ):
                    raise DrawingTransportError("提交回执缺少任务信息")
            elif result.get("accepted") is not False:
                raise DrawingTransportError("提交回执缺少受理状态或错误信息")
            else:
                raise DrawingError(result.get("error"), request_id=request_id)
        except DrawingTransportError as exc:
            error = DrawingError(
                {"code": "SUBMISSION_UNKNOWN", "message": str(exc), "retry_submit": False},
                task_id=task_id,
                request_id=request_id,
            )
            return TaskHandle(task_id, request_id, "submission_unknown", error=error)
        return TaskHandle(task_id, request_id, result["status"], result["reused"])

    async def task(self, task_id: str) -> Dict[str, Any]:
        result = await self.rpc.call("task", task_id=task_id)
        validate_task(result, task_id)
        return result

    async def request(self, request_id: str) -> Dict[str, Any]:
        """只读找回原请求，不向服务端重新提交提示词、图片或生成任务。"""
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            raise ValueError("request_id 应为 8～80 位字母、数字、下划线或横线")
        result = await self.rpc.call("request", request_id=request_id)
        task_id = result.get("task_id")
        if task_id is None:
            raise DrawingError(result.get("error"), request_id=request_id)
        validate_task(result, task_id)
        if result.get("request_id") != request_id:
            raise DrawingTransportError("查询回执与原请求键不一致", request_id=request_id)
        return result

    async def models(self) -> Dict[str, Any]:
        result = await self.rpc.call("models", version="1")
        if not isinstance(result.get("models"), list) or any(
            not isinstance(model, dict) or not isinstance(model.get("name"), str) for model in result["models"]
        ):
            raise DrawingTransportError("模型目录响应格式无效")
        return result

    async def presets(self) -> Dict[str, Any]:
        return await self._presets("list")

    async def references(self, *, page: int = 1) -> Dict[str, Any]:
        """只读参考目录，不读取图片或修改全局设置。"""
        if type(page) is not int or not 1 <= page <= 10:
            raise ValueError("参考目录页码必须为 1～10")
        result = await self.rpc.call("references", page=page)
        self._resource_error(result)
        if not isinstance(result.get("assets"), list):
            raise DrawingTransportError("参考目录响应格式无效")
        return result

    async def preferences(self, stream_id: str) -> Dict[str, Any]:
        """读取已存在会话的绘图覆盖值；空值表示使用默认配置。"""
        return await self._preferences("preferences", stream_id)

    async def set_preferences(self, stream_id: str, **patch: Unpack[DrawingPreferences]) -> Dict[str, Any]:
        """部分更新，未提供的字段保持原值；空字符串清除该字段的会话覆盖。"""
        if patch.keys() - DrawingPreferences.__annotations__.keys() or any(
            not isinstance(value, str) for value in patch.values()
        ):
            raise ValueError("未知绘图偏好字段或值不是文本")
        return await self._preferences(
            "preferences_set", stream_id, preference_json=json.dumps(patch, ensure_ascii=False, allow_nan=False)
        )

    async def _preferences(self, action: str, stream_id: str, **kwargs: Any) -> Dict[str, Any]:
        if not isinstance(stream_id, str) or not stream_id.strip() or len(stream_id) > 200:
            raise ValueError("必须提供真实聊天流 ID，最长 200 个字符")
        result = await self.rpc.call(action, stream_id=stream_id, **kwargs)
        self._resource_error(result)
        values = result.get("preferences")
        if (
            result.get("stream_id") != stream_id.strip() or not isinstance(values, dict)
            or not DrawingPreferences.__annotations__.keys() <= values.keys()
            or any(not isinstance(values[key], str) for key in DrawingPreferences.__annotations__)
        ):
            raise DrawingTransportError("会话绘图偏好响应格式无效")
        return result

    @staticmethod
    def _resource_error(result: Dict[str, Any]) -> None:
        if "error" not in result:
            raise DrawingTransportError("资源响应缺少业务状态；写入结果可能未确认，请先读取核对")
        if result["error"] is not None:
            raise DrawingError(result["error"])

    async def preset(self, name: str) -> Dict[str, Any]:
        return await self._presets("get", name)

    async def save_preset(self, preset: Dict[str, Any], *, name: Optional[str] = None) -> Dict[str, Any]:
        """创建或更新预设；name 指定旧名称时可重命名，不自动重试写入。"""
        if not isinstance(preset, dict):
            raise ValueError("preset 必须为对象")
        return await self._presets("save", preset.get("name", "") if name is None else name, preset)

    async def delete_preset(self, name: str) -> Dict[str, Any]:
        return await self._presets("delete", name)

    async def _presets(self, operation: str, name: str = "", preset: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not isinstance(name, str) or len(name) > 80:
            raise ValueError("预设名称应为不超过 80 个字符的文本")
        result = await self.rpc.call(
            "presets", operation=operation, name=name,
            preset_json=json.dumps(preset, ensure_ascii=False, allow_nan=False) if preset is not None else "",
        )
        self._resource_error(result)
        if operation == "get":
            if not isinstance(result.get("preset"), dict):
                raise DrawingTransportError("风格预设响应格式无效")
        elif not isinstance(result.get("presets"), list):
            raise DrawingTransportError("风格预设列表响应格式无效")
        return result

    async def tasks(self, *, page: int = 1, status: str = "", search: str = "") -> Dict[str, Any]:
        result = await self.rpc.call("tasks", page=page, status=status, search=search)
        if result.get("error") is not None:
            raise DrawingError(result["error"])
        if (
            not isinstance(result.get("items"), list)
            or type(result.get("total")) is not int or result["total"] < 0
            or type(result.get("page")) is not int or result["page"] != page
            or type(result.get("page_size")) is not int or result["page_size"] <= 0
        ):
            raise DrawingTransportError("任务列表响应格式无效")
        for item in result["items"]:
            if not isinstance(item, dict) or not isinstance(item.get("task_id"), str):
                raise DrawingTransportError("任务列表包含无效任务")
            validate_task(item, item["task_id"])
        return result

    async def cancel(self, task_id: str) -> Dict[str, Any]:
        result = await self.rpc.call("cancel", task_id=task_id)
        validate_task(result, task_id)
        if type(result.get("cancel_requested")) is not bool or result.get("upstream_cancelled") is not None:
            raise DrawingTransportError(
                "取消回执格式无效", task_id=task_id, request_id=result.get("request_id", "")
            )
        return result

    async def read_image(self, task_id: str, index: int = 0) -> bytes:
        return await read_image(self.rpc, task_id, index, self.max_image_bytes)

    async def save_image(
        self, task_id: str, destination: Union[str, Path], index: int = 0, *, overwrite: bool = False
    ) -> Path:
        """保存到调用方明确选择的授予目录；不会使用上游文件名拼接路径。"""
        raw = await self.read_image(task_id, index)
        return await asyncio.to_thread(save_bytes, Path(destination), raw, overwrite)

    async def _wait(self, handle: TaskHandle, result: DrawingResult, read_images: bool) -> DrawingResult:
        while True:
            try:
                snapshot = await self.task(handle.task_id)
            except DrawingTransportError:
                # 只重试只读查询，外层总预算负责结束等待。
                result.error = DrawingError(
                    {"code": "STATUS_UNAVAILABLE", "message": "任务状态查询响应未确认，可继续查询原任务", "retry_query": True},
                    task_id=handle.task_id, request_id=result.request_id,
                )
                await asyncio.sleep(self.poll_interval)
                continue
            except DrawingError as exc:
                exc.request_id = result.request_id or exc.request_id
                raise
            self._apply_snapshot(result, snapshot)
            if result.status not in {"pending", "running"}:
                if read_images and result.image_references:
                    if sum(item["size"] for item in result.image_references) > self.max_result_bytes:
                        result.error = DrawingError(
                            {
                                "code": "RESULT_TOO_LARGE",
                                "message": "图片总大小超过客户端单次结果限制；可调高限制或仅获取原任务图片引用",
                            },
                            task_id=handle.task_id,
                            request_id=result.request_id,
                        )
                        return result
                    for image in result.image_references:
                        try:
                            raw = await self.read_image(handle.task_id, image["index"])
                            if len(raw) != image["size"]:
                                raise DrawingTransportError("图片大小与任务引用不一致", task_id=handle.task_id)
                        except DrawingError as exc:
                            exc.request_id = result.request_id
                            result.error = exc
                            if exc.code != "RESULT_TOO_LARGE":
                                result.results_readable = False
                            break
                        except DrawingTransportError:
                            result.error = DrawingError(
                                {
                                    "code": "RESULT_UNAVAILABLE",
                                    "message": "结果读取响应未确认，可继续读取原任务图片",
                                    "retry_query": True,
                                },
                                task_id=handle.task_id,
                                request_id=result.request_id,
                            )
                            result.results_readable = False
                            break
                        result.images.append(GeneratedImage(raw, image))
                return result
            await asyncio.sleep(max(self.poll_interval, snapshot["retry_after_ms"] / 1000))

    @staticmethod
    def _apply_snapshot(result: DrawingResult, snapshot: Dict[str, Any]) -> None:
        if not result.request_id:
            result.request_id = snapshot.get("request_id", "")
        result.task_id, result.status = snapshot["task_id"], snapshot["status"]
        result.image_references = snapshot["images"]
        result.generation_completed = snapshot["generation_completed"]
        result.results_readable = snapshot["results_readable"]
        result.delivery, result.retry_after_ms = snapshot["delivery"], snapshot["retry_after_ms"]
        result.error = (
            DrawingError(snapshot["error"], task_id=result.task_id, request_id=result.request_id)
            if snapshot["error"] is not None else None
        )

    async def wait(
        self, task: Union[TaskHandle, str], *, request_id: str = "", wait_seconds: float = 120, read_images: bool = True
    ) -> DrawingResult:
        """等待结束保留任务状态与句柄，不取消远端，也不标成绘图失败。"""
        budget = self._budget(wait_seconds)
        handle = task if isinstance(task, TaskHandle) else TaskHandle(task, request_id)
        result = DrawingResult(handle.task_id, handle.request_id, handle.status, error=handle.error)
        if handle.task_id is None:
            return result
        try:
            async with asyncio.timeout(budget):
                return await self._wait(handle, result, read_images)
        except TimeoutError:
            result.wait_expired = True
            return result

    async def generate(
        self,
        prompt: str,
        *,
        request_id: Optional[str] = None,
        wait_seconds: float = 120,
        read_images: bool = True,
        **kwargs: Unpack[DrawingRequest],
    ) -> DrawingResult:
        """一次 await 完成提交、短查询和读取；总预算包含所有 RPC、sleep 与图片读取。"""
        budget = self._budget(wait_seconds)
        request_id = uuid4().hex if request_id is None else request_id
        result = DrawingResult(None, request_id, "submission_unknown")
        try:
            async with asyncio.timeout(budget):
                handle = await self.submit(prompt, request_id=request_id, **kwargs)
                result.task_id, result.status, result.error = handle.task_id, handle.status, handle.error
                if handle.task_id is None:
                    return result
                return await self._wait(handle, result, read_images)
        except TimeoutError:
            result.wait_expired = True
            if result.task_id is None:
                result.error = DrawingError(
                    {"code": "SUBMISSION_UNKNOWN", "message": "等待结束，提交响应未确认，请保留原 request_id"},
                    request_id=request_id,
                )
            return result

    async def recover(
        self, request_id: str, *, wait_seconds: float = 120, read_images: bool = True
    ) -> DrawingResult:
        """使用原 request_id 找回并等待任务；任何情况下都不重新提交生成。"""
        budget = self._budget(wait_seconds)
        result = DrawingResult(None, request_id, "submission_unknown")
        try:
            async with asyncio.timeout(budget):
                snapshot = await self.request(request_id)
                self._apply_snapshot(result, snapshot)
                return await self._wait(TaskHandle(result.task_id, request_id, result.status), result, read_images)
        except DrawingError as exc:
            if exc.code != "REQUEST_NOT_FOUND":
                raise
            result.error = exc
        except DrawingTransportError:
            result.error = DrawingError(
                {"code": "LOOKUP_UNAVAILABLE", "message": "原请求查询响应未确认，请保留原键稍后继续查询", "retry_query": True},
                task_id=result.task_id, request_id=request_id,
            )
        except TimeoutError:
            result.wait_expired = True
        return result
