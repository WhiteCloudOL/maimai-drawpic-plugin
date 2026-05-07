from pathlib import Path
from typing import Any

import json

from .provider_router import ProviderRouter


class SessionPreferenceStore:
    """管理会话级模型配置。"""

    def __init__(self, path: Path, router: ProviderRouter, logger: Any):
        self.path = path
        self.router = router
        self.logger = logger
        self.preferences: dict[str, dict[str, str]] = {}

    @staticmethod
    def resolve_session_key(
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> str:
        """生成会话级模型配置键。"""

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
        """从本地文件加载会话级模型配置。"""

        if not self.path.exists():
            self.preferences = {}
            return

        try:
            raw_text = self.path.read_text(encoding="utf-8")
            raw_data = json.loads(raw_text)
        except Exception as exc:
            self.logger.warning("读取会话模型配置失败，将使用空配置: %s", exc)
            self.preferences = {}
            return

        if not isinstance(raw_data, dict):
            self.logger.warning("会话模型配置格式不正确，将使用空配置")
            self.preferences = {}
            return

        normalized_preferences: dict[str, dict[str, str]] = {}
        for session_key, session_value in raw_data.items():
            if not isinstance(session_key, str) or not isinstance(session_value, dict):
                continue
            normalized_preferences[session_key] = {
                "model": str(session_value.get("model") or "").strip(),
                "openai_compatibility_mode": str(session_value.get("openai_compatibility_mode") or "").strip(),
            }
        self.preferences = normalized_preferences
        self.normalize_all()

    def save(self) -> None:
        """保存会话级模型配置到本地文件。"""

        self.normalize_all()
        self.path.write_text(
            json.dumps(self.preferences, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def normalize_all(self) -> None:
        """校正所有会话级模型配置。"""

        normalized_preferences: dict[str, dict[str, str]] = {}
        for session_key, session_value in self.preferences.items():
            normalized_preferences[session_key] = {
                "model": self.router.resolve_model_name(
                    session_value.get("model", ""),
                    allow_unknown_model=False,
                ),
                "openai_compatibility_mode": self.router.resolve_openai_compatibility_mode(
                    session_value.get("openai_compatibility_mode", "")
                ),
            }
        self.preferences = normalized_preferences

    def get_preference(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> dict[str, str]:
        """获取并初始化当前会话的模型配置。"""

        session_key = self.resolve_session_key(stream_id, user_id, group_id, platform)
        session_value = self.preferences.get(session_key, {})
        resolved_preference = {
            "model": self.router.resolve_model_name(
                str(session_value.get("model") or ""),
                allow_unknown_model=False,
            ),
            "openai_compatibility_mode": self.router.resolve_openai_compatibility_mode(
                str(session_value.get("openai_compatibility_mode") or "")
            ),
        }
        self.preferences[session_key] = resolved_preference
        return resolved_preference

    def set_preference(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
        *,
        model: str | None = None,
        openai_compatibility_mode: str | None = None,
    ) -> dict[str, str]:
        """更新当前会话的模型配置并持久化。"""

        session_key = self.resolve_session_key(stream_id, user_id, group_id, platform)
        current_value = self.get_preference(stream_id, user_id, group_id, platform)
        next_value = {
            "model": current_value["model"],
            "openai_compatibility_mode": current_value["openai_compatibility_mode"],
        }
        if model is not None:
            next_value["model"] = self.router.resolve_model_name(model, allow_unknown_model=False)
        if openai_compatibility_mode is not None:
            next_value["openai_compatibility_mode"] = self.router.resolve_openai_compatibility_mode(
                openai_compatibility_mode
            )
        self.preferences[session_key] = next_value
        self.save()
        return next_value
