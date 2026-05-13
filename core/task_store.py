from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4


DrawTaskStatus = Literal["pending", "running", "completed", "failed", "rejected"]
DrawTaskType = Literal["draw", "edit_image"]


@dataclass(slots=True)
class DrawTaskRecord:
    """绘图后台任务记录。"""

    task_id: str
    stream_id: str
    task_type: DrawTaskType
    prompt: str
    model: str
    provider: str
    status: DrawTaskStatus = "pending"
    message: str = ""
    sent_count: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_status_query_at: datetime | None = None


class DrawTaskStore:
    """管理插件内部后台绘图任务状态。"""

    def __init__(self) -> None:
        self._tasks: dict[str, DrawTaskRecord] = {}
        self._latest_task_id_by_stream: dict[str, str] = {}

    def create_task(
        self,
        *,
        stream_id: str,
        task_type: DrawTaskType,
        prompt: str,
        model: str,
        provider: str,
        message: str,
    ) -> DrawTaskRecord:
        """创建任务记录。"""

        task_id = uuid4().hex[:12]
        record = DrawTaskRecord(
            task_id=task_id,
            stream_id=stream_id,
            task_type=task_type,
            prompt=prompt,
            model=model,
            provider=provider,
            message=message,
        )
        self._tasks[task_id] = record
        self._latest_task_id_by_stream[stream_id] = task_id
        return record

    def get_task(self, task_id: str) -> DrawTaskRecord | None:
        """根据任务 ID 获取任务。"""

        return self._tasks.get(task_id.strip())

    def get_latest_task(self, stream_id: str) -> DrawTaskRecord | None:
        """获取当前会话最近一个任务。"""

        latest_task_id = self._latest_task_id_by_stream.get(stream_id.strip())
        if not latest_task_id:
            return None
        return self._tasks.get(latest_task_id)

    def update_task(
        self,
        task_id: str,
        *,
        status: DrawTaskStatus,
        message: str,
        sent_count: int | None = None,
    ) -> DrawTaskRecord:
        """更新任务状态。"""

        record = self._tasks[task_id]
        record.status = status
        record.message = message
        if sent_count is not None:
            record.sent_count = sent_count
        record.updated_at = datetime.now()
        return record

    def mark_status_queried(self, task_id: str) -> DrawTaskRecord:
        """记录一次状态查询。"""

        record = self._tasks[task_id]
        record.last_status_query_at = datetime.now()
        return record
