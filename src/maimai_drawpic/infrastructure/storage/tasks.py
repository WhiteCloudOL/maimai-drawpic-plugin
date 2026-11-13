from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from functools import wraps
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Dict, Literal, Optional, Set
from uuid import uuid4
import json
import re

from .atomic import write_json_atomically
from ..http import sanitize_provider_text


DrawTaskStatus = Literal["pending", "running", "completed", "failed", "rejected"]
DrawTaskType = Literal["draw", "edit_image"]


def _synchronized(method):
    """允许事件循环与存储工作线程共享同一份任务状态。"""

    @wraps(method)
    def locked(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return locked


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
    result_count: int = 0
    generated_count: int = 0
    expected_delivery_count: int = 0
    delivery_unconfirmed: bool = False
    persistence_pending: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    last_status_query_at: datetime | None = None
    submission: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None


class DrawTaskStore:
    """管理插件内部后台绘图任务状态。"""

    MAX_TASK_RECORDS = 500

    def __init__(
        self, path: Path, logger: Any | None = None, *, sanitize: Callable[[str], str] = sanitize_provider_text
    ) -> None:
        self._lock = RLock()
        self.path = path
        self.logger = logger
        self.sanitize_message = sanitize
        self._tasks: dict[str, DrawTaskRecord] = {}
        self._load_failed = False
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
            if normalized_user_id:
                return f"{normalized_platform}:group:{normalized_group_id}:user:{normalized_user_id}"
            return f"{normalized_platform}:group:{normalized_group_id}"
        if normalized_user_id:
            return f"{normalized_platform}:user:{normalized_user_id}"
        return f"{normalized_platform}:stream:{normalized_stream_id}"

    @_synchronized
    def load(self) -> None:
        """从本地文件加载后台绘图任务。"""

        if not self.path.exists():
            self._load_failed = False
            self._tasks = {}
            self._latest_task_id_by_session = {}
            return

        # Refuse every subsequent write until a complete valid load succeeds.
        # Unload cleanup must not replace the malformed file with empty state.
        self._load_failed = True
        try:
            raw_text = self.path.read_text(encoding="utf-8")
            raw_data = json.loads(raw_text)
        except Exception as exc:
            raise ValueError("绘图任务文件无法读取，请从备份恢复；未清空幂等记录") from exc

        if not isinstance(raw_data, dict):
            raise ValueError("绘图任务文件格式错误；未清空幂等记录")

        normalized_tasks: dict[str, DrawTaskRecord] = {}
        raw_tasks = raw_data.get("tasks")
        if not isinstance(raw_tasks, dict):
            raise ValueError("绘图任务集合格式错误；未清空幂等记录")
        request_ids: set[str] = set()
        if isinstance(raw_tasks, dict):
            for task_id, task_payload in raw_tasks.items():
                record = self._deserialize_record(task_id, task_payload)
                if record is None:
                    raise ValueError(f"绘图任务记录 {task_id} 无效；未清空幂等记录")
                request_id = record.submission.get("request_id")
                if request_id:
                    if request_id in request_ids:
                        raise ValueError("绘图任务请求键重复；未清空幂等记录")
                    request_ids.add(request_id)
                normalized_tasks[task_id] = record

        normalized_latest: dict[str, str] = {}
        raw_latest = raw_data.get("latest_task_id_by_session", {})
        if not isinstance(raw_latest, dict):
            raise ValueError("绘图任务索引格式错误；未清空幂等记录")
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
        changed = False
        for record in self._tasks.values():
            safe_message = self.sanitize_message(record.message)
            changed = changed or safe_message != record.message
            record.message = safe_message
            if record.error is not None:
                safe_error = self.sanitize_message(record.error["message"])
                changed = changed or safe_error != record.error["message"]
                record.error["message"] = safe_error
        self._latest_task_id_by_session = normalized_latest
        self._prune_tasks()
        self._load_failed = False
        if changed:
            self.save()

    @_synchronized
    def save(self) -> None:
        """保存后台绘图任务到本地文件。"""

        if self._load_failed:
            raise ValueError("绘图任务文件尚未恢复，拒绝覆盖原件或接受新任务；未清空幂等记录")
        serialized_tasks = {
            task_id: self._serialize_record(replace(record, persistence_pending=False))
            for task_id, record in self._tasks.items()
        }
        payload = {
            "tasks": serialized_tasks,
            "latest_task_id_by_session": self._latest_task_id_by_session,
        }
        write_json_atomically(self.path, payload)
        for task_id, record in tuple(self._tasks.items()):
            if record.persistence_pending:
                self._tasks[task_id] = replace(record, persistence_pending=False)

    @_synchronized
    def defer_terminal(self, task_id: str, **changes: Any) -> None:
        """Keep the known outcome queryable when disk is unavailable.

        A later save persists this exact outcome. A process crash before recovery
        still leaves the old durable state; restart must never replay that task.
        """
        record = self._tasks.get(task_id)
        if record is None:
            return
        if changes.get("status") not in {"completed", "failed", "rejected"}:
            raise ValueError("只能保留待落盘的终态")
        changes = dict(changes)
        changes["message"] = self.sanitize_message(changes["message"])
        if changes.get("error") is not None:
            changes["error"] = {**changes["error"], "message": self.sanitize_message(changes["error"]["message"])}
        self._tasks[task_id] = replace(record, **changes, persistence_pending=True, updated_at=datetime.now())

    @_synchronized
    def retry_pending_terminal(self) -> None:
        if not any(record.persistence_pending for record in self._tasks.values()):
            return
        try:
            self.save()
        except OSError:
            # The original failure was logged. Polling must remain useful even
            # during a prolonged outage and must not flood the log.
            pass

    def get_task_count(self) -> int:
        """返回当前缓存中的任务数量。"""

        return len(self._tasks)

    @_synchronized
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
        submission: Optional[Dict[str, Any]] = None,
    ) -> DrawTaskRecord:
        """创建任务记录。"""

        if sum(item.persistence_pending or item.status in {"pending", "running"}
               for item in self._tasks.values()) >= self.MAX_TASK_RECORDS:
            raise ValueError("活动任务记录已满，请等待现有任务结束")
        task_id = uuid4().hex[:12]
        record = DrawTaskRecord(
            task_id=task_id,
            session_key=session_key.strip(),
            stream_id=stream_id.strip(),
            task_type=task_type,
            prompt="",
            model=model,
            provider=provider,
            message=self.sanitize_message(message),
            submission=dict(submission or {}),
        )
        previous_tasks = dict(self._tasks)
        previous_latest = dict(self._latest_task_id_by_session)
        self._tasks[task_id] = record
        self._latest_task_id_by_session[record.session_key] = task_id
        self._prune_tasks()
        try:
            self.save()
        except Exception:
            # 持久化未成功不能留下可被幂等查询误认成已受理的内存记录。
            self._tasks = previous_tasks
            self._latest_task_id_by_session = previous_latest
            raise
        return record

    @_synchronized
    def find_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        """映射与任务在同一原子文件中，保留期与任务记录一致。"""
        return next(
            (
                self._serialize_record(item)
                for item in self._tasks.values()
                if item.submission.get("request_id") == request_id
            ),
            None,
        )

    @_synchronized
    def retained_task_ids(self) -> Set[str]:
        return set(self._tasks)

    def get_task(self, task_id: str) -> DrawTaskRecord | None:
        """根据任务 ID 获取任务。"""

        return self._tasks.get(task_id.strip())

    def get_latest_task(self, session_key: str) -> DrawTaskRecord | None:
        """获取当前会话最近一个任务。"""

        latest_task_id = self._latest_task_id_by_session.get(session_key.strip())
        if not latest_task_id:
            return None
        return self._tasks.get(latest_task_id)

    @_synchronized
    def update_task(
        self,
        task_id: str,
        *,
        status: DrawTaskStatus,
        message: str,
        sent_count: int | None = None,
        model: str | None = None,
        provider: str | None = None,
        result_count: int | None = None,
        error: Optional[Dict[str, Any]] = None,
        generated_count: Optional[int] = None,
        expected_delivery_count: Optional[int] = None,
        delivery_unconfirmed: Optional[bool] = None,
        task_type: Optional[str] = None,
    ) -> DrawTaskRecord | None:
        """更新任务状态；任务不存在时返回 None 而非抛出 KeyError。"""

        record = self._tasks.get(task_id)
        if record is None:
            self._log_warning("更新任务状态时未找到 task_id=%s，可能已被配置重载清理", task_id)
            return None
        if record.status in {"completed", "failed", "rejected"} and status in {"pending", "running"}:
            self._log_warning("忽略迟到的任务进度更新: task_id=%s status=%s", task_id, status)
            return record
        previous = record
        record = replace(record)
        record.status = status
        record.message = self.sanitize_message(message)
        if task_type is not None:
            if task_type not in {"draw", "edit_image"} or record.generated_count and task_type != record.task_type:
                raise ValueError("任务模式只能在生成前确定")
            record.task_type = task_type
        if error is not None:
            record.error = {**error, "message": self.sanitize_message(error["message"])}
        if result_count is not None:
            record.result_count = result_count
        if generated_count is not None:
            record.generated_count = generated_count
        if expected_delivery_count is not None:
            record.expected_delivery_count = expected_delivery_count
        if delivery_unconfirmed is not None:
            record.delivery_unconfirmed = delivery_unconfirmed
        if sent_count is not None:
            record.sent_count = sent_count
        if model is not None:
            record.model = model.strip()
        if provider is not None:
            record.provider = provider.strip()
        record.updated_at = datetime.now()
        self._tasks[task_id] = record
        try:
            self.save()
        except Exception:
            self._tasks[task_id] = previous
            raise
        return record

    @_synchronized
    def mark_status_queried(self, task_id: str) -> DrawTaskRecord | None:
        """记录一次状态查询；任务不存在时返回 None 而非抛出 KeyError。"""

        record = self._tasks.get(task_id)
        if record is None:
            self._log_warning("记录状态查询时未找到 task_id=%s，可能已被配置重载清理", task_id)
            return None
        previous = record
        record = replace(record, last_status_query_at=datetime.now())
        self._tasks[task_id] = record
        try:
            self.save()
        except Exception:
            self._tasks[task_id] = previous
            raise
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

    @_synchronized
    def snapshot(self) -> list[dict[str, Any]]:
        """返回独立快照，查询过程中不修改任务或触发磁盘写入。"""
        return [self._serialize_record(record) for record in self._tasks.values()]

    @staticmethod
    def _deserialize_record(task_id: str, payload: Any) -> DrawTaskRecord | None:
        """反序列化任务记录。"""

        if not isinstance(payload, dict):
            return None
        if not re.fullmatch(r"[a-f0-9]{12}", task_id) or payload.get("task_id", task_id) != task_id:
            return None
        status = payload.get("status", "pending")
        task_type = payload.get("task_type", "draw")
        if not isinstance(status, str) or status not in {"pending", "running", "completed", "failed", "rejected"}:
            return None
        if not isinstance(task_type, str) or task_type not in {"draw", "edit_image"}:
            return None
        if any(not isinstance(payload.get(key), str) for key in ("created_at", "updated_at")):
            return None
        if payload.get("last_status_query_at") is not None and not isinstance(payload["last_status_query_at"], str):
            return None
        for key in ("session_key", "stream_id", "model", "provider", "message"):
            if key in payload and not isinstance(payload[key], str):
                return None
        for key in ("sent_count", "result_count", "generated_count", "expected_delivery_count"):
            if key in payload and (type(payload[key]) is not int or payload[key] < 0):
                return None
        if "delivery_unconfirmed" in payload and type(payload["delivery_unconfirmed"]) is not bool:
            return None
        # Old task files have no submission mapping. A present mapping must never
        # silently discard the key/signature pair protecting against repeat work.
        submission = payload.get("submission", {})
        if not isinstance(submission, dict):
            return None
        if submission:
            if any(not isinstance(submission.get(key), str) or not submission[key].strip()
                   for key in ("request_id", "signature")):
                return None
            if any(key in submission and not isinstance(submission[key], str)
                   for key in ("origin", "prompt", "style")):
                return None
        error = payload.get("error")
        if error is not None and (
            not isinstance(error, dict)
            or not isinstance(error.get("code"), str)
            or not isinstance(error.get("message"), str)
            or any(key in error and type(error[key]) is not bool for key in ("retry_query", "retry_submit"))
        ):
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
                prompt="",
                model=str(payload.get("model") or "").strip(),
                provider=str(payload.get("provider") or "").strip(),
                status=str(payload.get("status") or "pending").strip(),  # type: ignore[arg-type]
                message=str(payload.get("message") or ""),
                sent_count=int(payload.get("sent_count") or 0),
                result_count=int(payload.get("result_count") or 0),
                generated_count=int(payload.get("generated_count") or 0),
                expected_delivery_count=payload.get("expected_delivery_count", 0),
                delivery_unconfirmed=payload.get("delivery_unconfirmed", False),
                created_at=created_at,
                updated_at=updated_at,
                last_status_query_at=last_status_query_at,
                submission=dict(submission),
                error=payload.get("error"),
            )
        except Exception:
            return None

    def _log_warning(self, message: str, *args: Any) -> None:
        """记录警告日志。"""

        if self.logger is not None:
            self.logger.warning(message, *args)

    def _prune_tasks(self) -> None:
        """仅保留最近的任务记录，并重建会话索引。"""

        if len(self._tasks) > self.MAX_TASK_RECORDS:
            newest_tasks = sorted(
                reversed(list(self._tasks.values())),
                key=lambda record: (record.persistence_pending or record.status in {"pending", "running"}, record.created_at),
                reverse=True,
            )[: self.MAX_TASK_RECORDS]
            self._tasks = {record.task_id: record for record in newest_tasks}

        latest_by_session: dict[str, DrawTaskRecord] = {}
        for record in self._tasks.values():
            current = latest_by_session.get(record.session_key)
            if current is None or record.created_at > current.created_at:
                latest_by_session[record.session_key] = record
        self._latest_task_id_by_session = {
            session_key: record.task_id for session_key, record in latest_by_session.items()
        }
