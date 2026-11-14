# SPDX-FileCopyrightText: 2026 WhiteCloudOL
# SPDX-License-Identifier: MIT

"""只校验客户端依赖的 v2 字段；允许服务器增加额外诊断字段。"""

from typing import Any, Dict

from .models import DrawingError, DrawingTransportError, validate_error


TASK_STATUSES = {"pending", "running", "completed", "failed", "rejected", "unconfirmed", "cancelled"}
DELIVERY_STATUSES = {"not_requested", "pending", "sent", "partial", "failed", "unconfirmed"}


def validate_task(result: Dict[str, Any], task_id: str) -> None:
    request_id = result.get("request_id", "")
    if not isinstance(request_id, str):
        raise DrawingTransportError("任务请求键格式无效", task_id=task_id)
    if result.get("task_id") is None:
        # 缺少 task_id 本身不证明业务拒绝，必须先验证明确的错误回执。
        raise DrawingError(result.get("error"), task_id=task_id, request_id=request_id)

    def invalid(message: str) -> None:
        raise DrawingTransportError(message, task_id=task_id, request_id=request_id)

    if (
        not isinstance(result["task_id"], str) or not result["task_id"] or result["task_id"] != task_id
        or not isinstance(result.get("status"), str)
        or result["status"] not in TASK_STATUSES
        or type(result.get("generation_completed")) is not bool
        or type(result.get("results_readable")) is not bool
        or type(result.get("retry_after_ms")) is not int
        or result["retry_after_ms"] < 0
        or "error" not in result
    ):
        invalid("任务快照字段缺失或格式无效")
    if result["error"] is not None:
        validate_error(result["error"], task_id=task_id, request_id=request_id)
    delivery = result.get("delivery")
    if (
        not isinstance(delivery, dict)
        or type(delivery.get("requested")) is not bool
        or not isinstance(delivery.get("status"), str)
        or delivery["status"] not in DELIVERY_STATUSES
        or type(delivery.get("sent_count")) is not int
        or delivery["sent_count"] < 0
    ):
        invalid("任务投递状态格式无效")
    images = result.get("images")
    if not isinstance(images, list):
        invalid("任务图片引用必须是列表")
    indexes = set()
    for image in images:
        if (
            not isinstance(image, dict)
            or type(image.get("index")) is not int
            or image["index"] < 0
            or image["index"] in indexes
            or type(image.get("size")) is not int
            or image["size"] <= 0
            or "task_id" in image and image["task_id"] != task_id
        ):
            invalid("任务图片引用字段缺失或格式无效")
        indexes.add(image["index"])
