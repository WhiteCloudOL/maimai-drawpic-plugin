from datetime import datetime
from typing import Any

from ...infrastructure.storage.tasks import DrawTaskRecord


class TaskQueryMixin:
    """TaskQueryMixin 的独立绘图职责。"""

    def build_task_status_message(self, record: DrawTaskRecord) -> str:
        """构建任务状态说明。"""

        if record.status in {"pending", "running"}:
            return (
                f"绘图任务仍在处理中：task_id={record.task_id}，类型={record.task_type}，"
                f"模型={record.model}。当前不要在本轮继续调用 draw_status，"
                f"请根据上下文自然告知用户任务仍在生成，并至少等待 {self.STATUS_RECHECK_INTERVAL_SECONDS} 秒后再查一次。"
            )
        if record.status == "completed":
            if record.delivery_unconfirmed:
                return f"{record.message} 任务 ID：{record.task_id}"
            return (
                f"绘图任务已完成：task_id={record.task_id}，类型={record.task_type}，"
                f"模型={record.model}，已发送 {record.sent_count} 张图片到当前聊天流。"
            )
        if record.status == "rejected":
            return f"绘图任务未通过审核：task_id={record.task_id}。{record.message}"
        return f"绘图任务失败：task_id={record.task_id}。{record.message}"

    def get_task_status_payload(
        self,
        stream_id: str,
        task_id: str = "",
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> dict[str, Any]:
        """查询后台绘图任务状态。"""

        normalized_stream_id = stream_id.strip()
        normalized_task_id = task_id.strip()
        if not normalized_stream_id:
            return {"success": False, "message": "当前聊天流 ID 为空，无法查询绘图任务状态"}

        session_key = self.build_session_key(
            stream_id=normalized_stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )

        record = self.task_store.get_task(normalized_task_id) if normalized_task_id else None
        if record is not None and record.session_key != session_key:
            record = None
        if not normalized_task_id:
            record = self.task_store.get_latest_task(session_key)
        if record is None:
            if normalized_task_id:
                return {"success": False, "message": f"未找到 task_id={normalized_task_id} 对应的绘图任务"}
            return {"success": False, "message": "当前会话还没有可查询的绘图任务"}

        seconds_since_last_query: int | None = None
        if record.last_status_query_at is not None:
            seconds_since_last_query = max(
                int((datetime.now() - record.last_status_query_at).total_seconds()),
                0,
            )
        self.task_store.retry_pending_terminal()
        record = self.task_store.get_task(record.task_id) or record
        if not record.persistence_pending:
            self.task_store.mark_status_queried(record.task_id)

        next_check_after_seconds = 0
        if record.status in {"pending", "running"}:
            if seconds_since_last_query is None:
                next_check_after_seconds = self.STATUS_RECHECK_INTERVAL_SECONDS
            else:
                next_check_after_seconds = max(
                    self.STATUS_RECHECK_INTERVAL_SECONDS - seconds_since_last_query,
                    0,
                )

        message = self.build_task_status_message(record)
        if record.persistence_pending:
            message += " 终态尚未落盘，请恢复存储后查询以重试保存；不要重新生成或发送。"
        if record.status in {"pending", "running"} and seconds_since_last_query is not None:
            message = (
                f"绘图任务仍在处理中：task_id={record.task_id}，类型={record.task_type}，模型={record.model}。"
                f"距离上次查询仅 {seconds_since_last_query} 秒。当前不要在本轮继续调用 draw_status，"
                f"请根据上下文自然告知用户任务仍在生成，并在 {max(next_check_after_seconds, 1)} 秒后再查。"
            )

        return {
            "success": record.status in {"pending", "running", "completed"},
            "message": message,
            "task_id": record.task_id,
            "persistence_pending": record.persistence_pending,
            "status": record.status,
            "task_type": record.task_type,
            "model": record.model,
            "provider": record.provider,
            "sent_count": record.sent_count,
            "delivery_unconfirmed": record.delivery_unconfirmed,
            "is_finished": record.status in {"completed", "failed", "rejected"},
            "should_wait": record.status in {"pending", "running"},
            "next_check_after_seconds": next_check_after_seconds,
        }

    def build_session_key(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> str:
        """构建任务查询使用的稳定会话键。"""

        return self.task_store.resolve_session_key(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
