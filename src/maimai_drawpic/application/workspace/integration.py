"""公开绘图任务契约，独立表达受理、生成、缓存和投递结果。"""

from typing import Any, Dict
import asyncio
import re

from ...domain.task_errors import TaskRequestError, task_error
from .tasks import WorkspaceTaskService, validate_task_id


def public_status(status: str, error: Dict[str, Any] | None) -> str:
    code = error["code"] if error is not None else ""
    if code in {"UPSTREAM_UNCONFIRMED", "RESTART_UNCONFIRMED"}:
        return "unconfirmed"
    return "cancelled" if code == "CANCELLED" else status


class IntegrationTaskService:
    def __init__(self, tasks: WorkspaceTaskService) -> None:
        self.tasks = tasks

    def error_response(self, exc: Exception) -> Dict[str, Any]:
        code = exc.code if isinstance(exc, TaskRequestError) else "INVALID_REQUEST"
        if isinstance(exc, PermissionError):
            code = "PERMISSION_DENIED"
        return {
            "task_id": None,
            "status": "not_accepted",
            "images": [],
            "retry_after_ms": 0,
            "error": task_error(
                code,
                self.tasks.task_store.sanitize_message(str(exc)),
                retry_submit=isinstance(exc, TaskRequestError) and exc.retry_submit,
            ),
        }

    async def submit(self, **kwargs: Any) -> Dict[str, Any]:
        try:
            receipt = await self.tasks.submit(**kwargs, origin="plugin", require_existing_stream=True)
        except (ValueError, PermissionError) as exc:
            return {**self.error_response(exc), "accepted": False, "request_id": kwargs.get("request_id", "")}
        return {**await self.task(receipt["task_id"]), **receipt, "accepted": True}

    async def request(self, request_id: str) -> Dict[str, Any]:
        """只查询持久化请求映射；未找到不证明从未受理，也不能据此自动重画。"""
        if not isinstance(request_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request_id):
            return self.error_response(ValueError("request_id 应为 8～80 位字母、数字、下划线或横线"))
        # 与提交共享锁，避免已进入提交持久化阶段的请求被误报为不存在。
        async with self.tasks.lock:
            record = await asyncio.to_thread(self.tasks.task_store.find_request, request_id)
        if record is None:
            return {
                **self.error_response(TaskRequestError(
                    "REQUEST_NOT_FOUND", "未找到保留期内的请求记录，可能尚未完成受理或已淘汰；不能据此自动重新生成"
                )),
                "request_id": request_id,
            }
        return await self.task(record["task_id"])

    async def task(self, task_id: str) -> Dict[str, Any]:
        try:
            validate_task_id(task_id)
            record = await asyncio.to_thread(self.tasks.task_store.get_task, task_id)
            if record is None:
                raise TaskRequestError("TASK_NOT_FOUND", "当前实例不存在该任务或记录已淘汰")
            detail = await self.tasks.detail(task_id)
        except ValueError as exc:
            return self.error_response(exc)
        status, error = public_status(detail["status"], detail["error"]), detail["error"]
        if error is None and status in {"failed", "rejected"}:
            error = task_error("MODERATION_REJECTED" if status == "rejected" else "EXECUTION_FAILED", detail["message"])
        if status == "completed" and not detail["images"]:
            error = task_error(
                "RESULT_EXPIRED" if detail["result_count"] else "RESULT_UNAVAILABLE",
                "图片结果已过期、被清理或未能缓存；不会重新生成",
            )
        images = [
            {**image, "task_id": task_id, "format": image["mime"].split("/", 1)[1], "available": True}
            for image in detail["images"]
        ]
        requested = bool(record.stream_id)
        delivery = "not_requested" if not requested else "pending"
        if requested and detail.get("delivery_unconfirmed", False):
            # 已确认的前几张不能掩盖后续图片结果未知；也不能据此自动补发。
            delivery = "unconfirmed"
        elif requested and detail["sent_count"]:
            expected = detail.get("expected_delivery_count", 0)
            # 旧记录没有审核后计数，且 completed 也可能代表部分发送。
            # 不使用 generated_count，因其中包含审核未通过、不能投递的图片。
            delivery = (
                ("sent" if detail["sent_count"] >= expected else "partial") if expected else "unconfirmed"
            )
        elif requested and status not in {"pending", "running"}:
            delivery = "unconfirmed" if status in {"unconfirmed", "cancelled"} else "failed"
        return {
            **detail,
            "status": status,
            "images": images,
            "error": error,
            "request_id": record.submission.get(
                "request_id", self.tasks.metadata.get(task_id, {}).get("request_id", "")
            ),
            "retry_after_ms": 3000 if status in {"pending", "running"} else 0,
            "generation_completed": detail["status"] == "completed"
            or detail["generated_count"] > 0
            or detail["result_count"] > 0,
            "results_readable": bool(images),
            "delivery": {"requested": requested, "status": delivery, "sent_count": detail["sent_count"]},
        }

    async def image(self, task_id: str, index: int = 0, kind: str = "original", offset: int = 0) -> Dict[str, Any]:
        task = await self.task(task_id)
        if task["task_id"] is None:
            return task

        def error_result(error: Dict[str, Any]) -> Dict[str, Any]:
            # 图片读取拒绝不改变已受理任务；保留调用方继续查询所需的句柄。
            return {"task_id": task_id, "request_id": task["request_id"], "error": error}

        if (
            type(index) is not int
            or index < 0
            or not isinstance(kind, str)
            or kind not in {"original", "preview", "thumbnail"}
        ):
            return error_result(task_error("INVALID_REQUEST", "图片索引或类型无效"))
        if not task["images"]:
            if task["status"] in {"pending", "running"}:
                return error_result(task_error("RESULT_NOT_READY", "任务尚未产生可读取图片", retry_query=True))
            return error_result(task_error("RESULT_EXPIRED", "图片结果已过期、被清理或尚未产生"))
        if index >= len(task["images"]):
            return error_result(task_error("INVALID_REQUEST", "图片索引无效"))
        try:
            if kind == "original":
                result = await asyncio.to_thread(self.tasks.results.original_chunk, task_id, index, offset)
            else:
                result = await asyncio.to_thread(self.tasks.results.preview, task_id, index, kind == "thumbnail")
            return {**result, "error": None}
        except FileNotFoundError:
            return error_result(task_error("RESULT_EXPIRED", "读取过程中图片被缓存清理"))
        except ValueError as exc:
            return error_result(self.error_response(exc)["error"])

    async def cancel(self, task_id: str) -> Dict[str, Any]:
        try:
            validate_task_id(task_id)
        except ValueError as exc:
            return {**self.error_response(exc), "cancel_requested": False, "upstream_cancelled": None}
        record = self.tasks.task_store.get_task(task_id)
        requested = record is not None and record.status in {"pending", "running"}
        if requested:
            try:
                await self.tasks.cancel(task_id)
            except ValueError:
                # 取消与完成竞争时返回实际终态，不能把已完成的任务改成已取消。
                pass
        task = await self.task(task_id)
        return {**task, "cancel_requested": requested, "upstream_cancelled": None}

    async def listing(self, page: int = 1, status: str = "", search: str = "") -> Dict[str, Any]:
        if type(page) is not int or not 1 <= page <= 100 or not isinstance(search, str) or len(search) > 200:
            return self.error_response(ValueError("分页或搜索参数无效"))
        if not isinstance(status, str) or status not in {
            "",
            "pending",
            "running",
            "completed",
            "failed",
            "rejected",
            "unconfirmed",
            "cancelled",
        }:
            return self.error_response(ValueError("任务状态无效"))
        records = sorted(
            await asyncio.to_thread(self.tasks.task_store.snapshot), key=lambda item: item["created_at"], reverse=True
        )
        filtered = [
            record
            for record in records
            if (not status or public_status(record["status"], record["error"]) == status)
            and search.casefold() in f"{record['task_id']} {record['model']} {record['message']}".casefold()
        ]
        items = [await self.task(record["task_id"]) for record in filtered[(page - 1) * 12 : page * 12]]
        return {"items": items, "total": len(filtered), "page": page, "page_size": 12, "error": None}
