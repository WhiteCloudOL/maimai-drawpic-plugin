"""runtime/context.py 的插件组件。"""

from collections.abc import Mapping
from typing import Any, Dict, List

from ...domain.platform_identity import is_qq_identifier, is_qq_platform


def user_request_from_segments(segments: List[Any]) -> str:
    """读取宿主原始消息段中的用户文本、语音转写和提及对象。"""
    parts: List[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        data = segment.get("data")
        if segment.get("type") in {"text", "voice"} and isinstance(data, str):
            parts.append(data)
        elif segment.get("type") == "at" and isinstance(data, dict):
            name = data.get("target_user_cardname") or data.get("target_user_nickname") or data.get("target_user_id")
            if isinstance(name, str) and name.strip():
                parts.append("@" + name.strip())
    return "".join(parts).strip()


class ContextMixin:
    """runtime/context.py 对应的插件行为。"""

    @staticmethod
    def _resolve_stream_id_from_hook_message(message: Any) -> str:
        """从命名 Hook 的消息载荷中解析聊天流 ID。"""

        if not isinstance(message, dict):
            return ""
        return str(message.get("session_id") or "").strip()

    @staticmethod
    def _build_image_lookup_stream_ids(*stream_ids: Any, message: Any = None) -> list[str]:
        """构建图片查询用的聊天流候选 ID。"""

        lookup_stream_ids: list[str] = []

        def _add(value: Any) -> None:
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    _add(item)
                return
            normalized_value = str(value or "").strip()
            if normalized_value and normalized_value not in lookup_stream_ids:
                lookup_stream_ids.append(normalized_value)

        if isinstance(message, dict):
            _add(message.get("session_id"))
        for stream_id in stream_ids:
            _add(stream_id)
        if not lookup_stream_ids:
            lookup_stream_ids.append("")
        return lookup_stream_ids

    @staticmethod
    def _extract_text_command_from_raw_message(message: Any) -> str:
        """从原始消息文本段中提取被 reply/at 前缀遮挡的绘图命令。"""

        if not isinstance(message, dict):
            return ""
        text_parts: list[str] = []
        raw_message = message.get("raw_message")
        if isinstance(raw_message, list):
            for segment in raw_message:
                if not isinstance(segment, dict):
                    continue
                if str(segment.get("type") or "").strip() != "text":
                    continue
                text_parts.append(str(segment.get("data") or ""))
        command_text = "".join(text_parts).strip()
        if command_text.startswith("/绘图") or command_text.startswith("/drawpic"):
            return command_text
        return ""

    @staticmethod
    def _read_context_value(source: Any, key: str) -> Any:
        """读取 dict 或消息对象中的同名上下文字段。"""

        if source is None:
            return None
        if isinstance(source, Mapping):
            return source.get(key)
        return getattr(source, key, None)

    @classmethod
    def _first_context_value(cls, source: Any, *keys: str) -> Any:
        """按顺序读取第一个非空上下文字段。"""

        for key in keys:
            value = cls._read_context_value(source, key)
            if value not in (None, ""):
                return value
        return ""

    @classmethod
    def _select_runtime_user_id(
        cls,
        *,
        platform: str,
        group_id: str,
        user_id_candidates: list[Any],
    ) -> str:
        """选择运行期真实用户 ID，兼容 OneBot 与 QQ 官方身份。"""

        normalized_candidates = [str(value or "").strip() for value in user_id_candidates]
        normalized_group_id = group_id.strip()
        for candidate in normalized_candidates:
            if not candidate or candidate == normalized_group_id:
                continue
            if not cls._is_qq_platform(platform) or is_qq_identifier(candidate):
                return candidate
        return ""

    @classmethod
    def _extract_message_context(cls, message: Any) -> dict[str, str]:
        """从 Hook 原始消息中提取命令处理需要的上下文字段。"""

        message_info = cls._read_context_value(message, "message_info")
        user_info = cls._read_context_value(message_info, "user_info")
        group_info = cls._read_context_value(message_info, "group_info")

        return {
            "stream_id": str(cls._first_context_value(message, "session_id", "stream_id", "chat_id")).strip(),
            "user_id": str(
                cls._first_context_value(user_info, "user_id") or cls._first_context_value(message, "user_id")
            ).strip(),
            "group_id": str(
                cls._first_context_value(group_info, "group_id") or cls._first_context_value(message, "group_id")
            ).strip(),
            "platform": str(cls._first_context_value(message, "platform") or "qq").strip() or "qq",
        }

    def _extract_runtime_context(
        self,
        *,
        stream_id: str = "",
        kwargs: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        """从 SDK 注入参数或命令消息中提取聊天上下文。"""

        payload = kwargs or {}
        message = payload.get("message")
        message_context = self._extract_message_context(message) if message is not None else {}
        normalized_platform = str(message_context.get("platform") or payload.get("platform") or "qq").strip() or "qq"
        normalized_stream_id = str(
            message_context.get("stream_id") or payload.get("stream_id") or payload.get("chat_id") or stream_id or ""
        ).strip()
        normalized_group_id = str(message_context.get("group_id") or payload.get("group_id") or "").strip()
        message_context_user_id = message_context.get("user_id")
        payload_user_id = payload.get("user_id")
        normalized_user_id = self._select_runtime_user_id(
            platform=normalized_platform,
            group_id=normalized_group_id,
            user_id_candidates=[message_context_user_id, payload_user_id],
        )
        self.ctx.logger.debug(
            "工具上下文提取: message_present=%s payload_stream_id=%s payload_user_id=%s payload_group_id=%s payload_platform=%s "
            "候选user_id=[message_context=%s, payload=%s] 选中user_id=%s 最终stream_id=%s group_id=%s platform=%s",
            message is not None,
            payload.get("stream_id"),
            payload_user_id,
            payload.get("group_id"),
            payload.get("platform"),
            message_context_user_id,
            payload_user_id,
            normalized_user_id,
            normalized_stream_id,
            normalized_group_id,
            normalized_platform,
        )
        invalid_qq_user_id = (
            any(str(value or "").strip() for value in (message_context_user_id, payload_user_id))
            and not normalized_user_id
            and normalized_group_id
            and self._is_qq_platform(normalized_platform)
        )
        if invalid_qq_user_id and self._resolve_quota_config(normalized_group_id)[0]:
            self.ctx.logger.warning(
                "绘图运行上下文收到无效 QQ 用户身份，将拒绝用于额度 stream_id=%s user_id=%s group_id=%s platform=%s",
                normalized_stream_id,
                message_context_user_id or payload_user_id or "",
                normalized_group_id,
                normalized_platform,
            )
        return {
            "stream_id": normalized_stream_id,
            "user_id": normalized_user_id,
            "group_id": normalized_group_id,
            "platform": normalized_platform,
        }

    def _extract_invocation_context(
        self,
        *,
        kwargs: dict[str, Any] | None = None,
        llm_user_id: str = "",
    ) -> dict[str, str]:
        """从 SDK 注入参数和 LLM 填入参数中提取工具调用上下文。

        SDK 注入的上下文更接近真实消息事件，LLM 填入的 user_id 仅作为旧版兼容兜底。
        """

        payload = kwargs or {}
        llm_user_id = str(llm_user_id or "").strip()
        runtime_context = self._extract_runtime_context(kwargs=payload)
        if runtime_context["user_id"] or not llm_user_id:
            return runtime_context

        fallback_context = self._extract_runtime_context(kwargs={**payload, "user_id": llm_user_id})
        if fallback_context["user_id"]:
            self.ctx.logger.warning(
                "工具上下文未从主程序解析到 user_id，已使用 LLM 参数作为兼容兜底: stream_id=%s user_id=%s group_id=%s platform=%s",
                fallback_context["stream_id"],
                fallback_context["user_id"],
                fallback_context["group_id"],
                fallback_context["platform"],
            )
            return fallback_context
        return runtime_context

    @staticmethod
    def _is_qq_platform(platform: str) -> bool:
        """判断当前平台是否使用 QQ 身份规则。"""

        return is_qq_platform(platform)

    @classmethod
    def _normalize_runtime_user_id(cls, user_id: str, platform: str) -> str:
        """清理运行期用户 ID，避免 QQ 昵称进入额度账本。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return ""
        if cls._is_qq_platform(platform) and not is_qq_identifier(normalized_user_id):
            return ""
        return normalized_user_id

    @classmethod
    def _merge_resolved_runtime_context(
        cls,
        live_context: dict[str, str],
        *,
        user_id: str,
        group_id: str,
        platform: str,
    ) -> dict[str, str]:
        """合并真实聊天流上下文，群聊保留本次发起用户用于额度。"""

        resolved_platform = str(live_context.get("platform") or "").strip() or platform.strip() or "qq"
        resolved_group_id = str(live_context.get("group_id") or "").strip() or group_id.strip()
        incoming_user_id = cls._normalize_runtime_user_id(user_id, resolved_platform)
        if resolved_group_id:
            if incoming_user_id == resolved_group_id:
                incoming_user_id = ""
            resolved_user_id = incoming_user_id
        else:
            live_user_id = cls._normalize_runtime_user_id(
                str(live_context.get("user_id") or "").strip(),
                resolved_platform,
            )
            resolved_user_id = live_user_id or incoming_user_id
        return {
            "stream_id": str(live_context.get("stream_id") or "").strip(),
            "user_id": resolved_user_id,
            "group_id": resolved_group_id,
            "platform": resolved_platform,
        }
