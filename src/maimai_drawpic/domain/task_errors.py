"""任务 API 的稳定错误契约，与宿主 RPC 包装分开。"""

from typing import Any, Dict

from .errors import (
    ProviderConnectionError,
    ProviderError,
    ProviderOutcomeUnknown,
    ProviderResultError,
    ProviderSubmittedError,
)


def delivery_unconfirmed_message(sent_count: int) -> str:
    if sent_count:
        return f"图片已生成，已确认发送 {sent_count} 张，其余图片送达状态未确认。请先查看聊天记录。"
    return "图片已生成，送达状态未确认。请先查看聊天记录。"


def task_error(code: str, message: str, *, retry_query: bool = False, retry_submit: bool = False) -> Dict[str, Any]:
    return {"code": code, "message": message, "retry_query": retry_query, "retry_submit": retry_submit}


class TaskRequestError(ValueError):
    def __init__(self, code: str, message: str, *, retry_submit: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retry_submit = retry_submit


def provider_task_error(failure: ProviderError, message: str) -> Dict[str, Any]:
    if failure.rejected:
        return task_error("MODERATION_REJECTED", message)
    if failure.outcome_unknown or isinstance(failure, ProviderOutcomeUnknown):
        return task_error("UPSTREAM_UNCONFIRMED", message)
    if isinstance(failure, (ProviderResultError, ProviderSubmittedError)):
        return task_error("RESULT_UNAVAILABLE", message)
    if isinstance(failure, ProviderConnectionError):
        return task_error("UPSTREAM_UNREACHABLE", message, retry_submit=True)
    return task_error("UPSTREAM_REJECTED", message)
