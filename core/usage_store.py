from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import json


QuotaPeriod = Literal["daily", "weekly", "monthly", "once"]
QuotaAction = Literal["add", "remove", "set"]


@dataclass(slots=True)
class UserQuotaRecord:
    """用户额度记录。"""

    period_key: str
    used: int = 0
    quota_override: int | None = None


class UserQuotaStore:
    """管理用户绘图次数。"""

    def __init__(self, path: Path, logger: Any | None = None) -> None:
        self.path = path
        self.logger = logger
        self.records: dict[str, UserQuotaRecord] = {}

    def bind_logger(self, logger: Any | None) -> None:
        """绑定运行期 logger。"""

        self.logger = logger

    def load(self) -> None:
        """读取额度数据。"""

        if not self.path.exists():
            self.records = {}
            return
        try:
            raw_data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log_warning("读取用户额度数据失败，将使用空状态: %s", exc)
            self.records = {}
            return
        if not isinstance(raw_data, dict):
            self.records = {}
            return

        records: dict[str, UserQuotaRecord] = {}
        for user_id, payload in raw_data.items():
            if not isinstance(user_id, str) or not isinstance(payload, dict):
                continue
            records[user_id] = UserQuotaRecord(
                period_key=str(payload.get("period_key") or ""),
                used=max(int(payload.get("used") or 0), 0),
                quota_override=(
                    max(int(payload["quota_override"]), 0)
                    if payload.get("quota_override") is not None
                    else None
                ),
            )
        self.records = records

    def save(self) -> None:
        """保存额度数据。"""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {user_id: asdict(record) for user_id, record in self.records.items()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def get_remaining(self, user_id: str, *, period: QuotaPeriod, default_quota: int) -> int:
        """获取当前周期剩余次数。"""

        record = self._get_record(user_id, period)
        quota = self._resolve_quota(record, default_quota)
        return max(quota - record.used, 0)

    def consume(self, user_id: str, *, period: QuotaPeriod, default_quota: int) -> tuple[bool, int]:
        """消耗一次额度，返回是否成功与剩余次数。"""

        record = self._get_record(user_id, period)
        quota = self._resolve_quota(record, default_quota)
        if record.used >= quota:
            return False, 0
        record.used += 1
        self.records[user_id] = record
        self.save()
        return True, max(quota - record.used, 0)

    def adjust_remaining(
        self,
        user_id: str,
        *,
        action: QuotaAction,
        count: int,
        period: QuotaPeriod,
        default_quota: int,
    ) -> int:
        """调整用户当前周期剩余次数，并返回调整后的剩余次数。"""

        record = self._get_record(user_id, period)
        quota = self._resolve_quota(record, default_quota)
        remaining = max(quota - record.used, 0)
        if action == "add":
            next_remaining = remaining + count
        elif action == "remove":
            next_remaining = max(remaining - count, 0)
        else:
            next_remaining = max(count, 0)
        record.quota_override = record.used + next_remaining
        self.records[user_id] = record
        self.save()
        return next_remaining

    @classmethod
    def _period_key(cls, period: QuotaPeriod) -> str:
        now = datetime.now()
        if period == "daily":
            return now.strftime("%Y-%m-%d")
        if period == "weekly":
            year, week, _ = now.isocalendar()
            return f"{year}-W{week:02d}"
        if period == "monthly":
            return now.strftime("%Y-%m")
        return "once"

    def _get_record(self, user_id: str, period: QuotaPeriod) -> UserQuotaRecord:
        period_key = self._period_key(period)
        record = self.records.get(user_id)
        if record is None or record.period_key != period_key:
            return UserQuotaRecord(period_key=period_key)
        return record

    @staticmethod
    def _resolve_quota(record: UserQuotaRecord, default_quota: int) -> int:
        if record.quota_override is not None:
            return max(record.quota_override, 0)
        return max(int(default_quota), 0)

    def _log_warning(self, message: str, *args: Any) -> None:
        if self.logger is not None:
            self.logger.warning(message, *args)
