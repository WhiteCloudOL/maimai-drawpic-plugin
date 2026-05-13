from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import json


DrawTaskStatus = Literal["pending", "running", "completed", "failed", "rejected"]
DrawTaskType = Literal["draw", "edit_image"]


@dataclass(slots=True)
class DrawTaskRecord:
    """绘图后台任务记录。"""

    task_id: str
    session_key: str
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

    def __init__(self, path: Path, logger: Any | None = None) -> None:
        self.path = path
        self.logger = logger
        self._tasks: dict[str, DrawTaskRecord] = {}
        self._latest_task_id_by_session: dict[str, str] = {}

    def bind_logger(self, logger: Any | None) -> None:
        """绑定运行期 logger。"""

        self.logger = logger

    @staticmethod
    def resolve_session_key(
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> str:
        """生成任务归属的稳定会话键。"""

        normalized_platform = platform.strip() or "qq"
        normalized_group_id = group_id.strip()
        normalized_user_id = user_id.strip()
        normalized_stream_id = stream_id.strip()

        if normalized_group_id:
            return f"{normalized_platform}:group:{normalized_group_id}"
        if normalized_user_id:
            return f"{normalized_platform}:user:{normalized_user_id}"
        return f"{normalized_platform}:stream:{normalized_stream_id}"

    def load(self) -> None:
        """从本地文件加载后台绘图任务。"""

        if not self.path.exists():
            self._tasks = {}
            self._latest_task_id_by_session = {}
            return

        try:
            raw_text = self.path.read_text(encoding="utf-8")
            raw_data = json.loads(raw_text)
        except Exception as exc:
            self._log_warning("读取绘图任务缓存失败，将使用空状态: %s", exc)
            self._tasks = {}
            self._latest_task_id_by_session = {}
            return

        if not isinstance(raw_data, dict):
            self._log_warning("绘图任务缓存格式不正确，将使用空状态")
            self._tasks = {}
            self._latest_task_id_by_session = {}
            return

        normalized_tasks: dict[str, DrawTaskRecord] = {}
        raw_tasks = raw_data.get("tasks", {})
        if isinstance(raw_tasks, dict):
            for task_id, task_payload in raw_tasks.items():
                record = self._deserialize_record(task_id, task_payload)
                if record is not None:
                    normalized_tasks[task_id] = record

        normalized_latest: dict[str, str] = {}
        raw_latest = raw_data.get("latest_task_id_by_session", {})
        if isinstance(raw_latest, dict):
            for session_key, task_id in raw_latest.items():
                if (
                    isinstance(session_key, str)
                    and isinstance(task_id, str)
                    and session_key.strip()
                    and task_id.strip()
                    and task_id in normalized_tasks
                ):
                    normalized_latest[session_key.strip()] = task_id.strip()

        self._tasks = normalized_tasks
        self._latest_task_id_by_session = normalized_latest

    def save(self) -> None:
        """保存后台绘图任务到本地文件。"""

        serialized_tasks = {
            task_id: self._serialize_record(record)
            for task_id, record in self._tasks.items()
        }
        payload = {
            "tasks": serialized_tasks,
            "latest_task_id_by_session": self._latest_task_id_by_session,
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_task_count(self) -> int:
        """返回当前缓存中的任务数量。"""

        return len(self._tasks)

    def create_task(
        self,
        *,
        session_key: str,
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
            session_key=session_key.strip(),
            stream_id=stream_id.strip(),
            task_type=task_type,
            prompt=prompt,
            model=model,
            provider=provider,
            message=message,
        )
        self._tasks[task_id] = record
        self._latest_task_id_by_session[record.session_key] = task_id
        self.save()
        return record

    def get_task(self, task_id: str) -> DrawTaskRecord | None:
        """根据任务 ID 获取任务。"""

        return self._tasks.get(task_id.strip())

    def get_latest_task(self, session_key: str) -> DrawTaskRecord | None:
        """获取当前会话最近一个任务。"""

        latest_task_id = self._latest_task_id_by_session.get(session_key.strip())
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
        self.save()
        return record

    def mark_status_queried(self, task_id: str) -> DrawTaskRecord:
        """记录一次状态查询。"""

        record = self._tasks[task_id]
        record.last_status_query_at = datetime.now()
        self.save()
        return record

    @staticmethod
    def _serialize_record(record: DrawTaskRecord) -> dict[str, Any]:
        """序列化任务记录。"""

        payload = asdict(record)
        payload["created_at"] = record.created_at.isoformat()
        payload["updated_at"] = record.updated_at.isoformat()
        payload["last_status_query_at"] = (
            record.last_status_query_at.isoformat() if record.last_status_query_at is not None else None
        )
        return payload

    @staticmethod
    def _deserialize_record(task_id: str, payload: Any) -> DrawTaskRecord | None:
        """反序列化任务记录。"""

        if not isinstance(payload, dict):
            return None

        try:
            created_at = datetime.fromisoformat(str(payload.get("created_at") or ""))
            updated_at = datetime.fromisoformat(str(payload.get("updated_at") or ""))
            last_status_query_raw = payload.get("last_status_query_at")
            last_status_query_at = (
                datetime.fromisoformat(str(last_status_query_raw))
                if isinstance(last_status_query_raw, str) and last_status_query_raw.strip()
                else None
            )
            return DrawTaskRecord(
                task_id=str(payload.get("task_id") or task_id).strip(),
                session_key=str(payload.get("session_key") or "").strip(),
                stream_id=str(payload.get("stream_id") or "").strip(),
                task_type=str(payload.get("task_type") or "draw").strip(),  # type: ignore[arg-type]
                prompt=str(payload.get("prompt") or ""),
                model=str(payload.get("model") or "").strip(),
                provider=str(payload.get("provider") or "").strip(),
                status=str(payload.get("status") or "pending").strip(),  # type: ignore[arg-type]
                message=str(payload.get("message") or ""),
                sent_count=int(payload.get("sent_count") or 0),
                created_at=created_at,
                updated_at=updated_at,
                last_status_query_at=last_status_query_at,
            )
        except Exception:
            return None

    def _log_warning(self, message: str, *args: Any) -> None:
        """记录警告日志。"""

        if self.logger is not None:
            self.logger.warning(message, *args)
