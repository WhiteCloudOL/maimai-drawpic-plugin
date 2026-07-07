from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from maibot_sdk import CONFIG_RELOAD_SCOPE_SELF, Command, HookHandler, MaiBotPlugin, ON_BOT_CONFIG_RELOAD, ON_MODEL_CONFIG_RELOAD, Tool
from maibot_sdk.types import HookMode

from .core.config import DrawpicConfig, migrate_legacy_review_config
from .core.draw_service import DrawService
from .core.image_reply import PinkImageReplyRenderer
from .core.message_utils import (
    cache_source_image_from_message,
    collect_command_source_images,
    decode_image_base64,
    find_source_images,
)
from .core.moderation import DrawpicModerationService
from .core.provider_router import ProviderRouter
from .core.session_preferences import SessionPreferenceStore
from .core.stream_service import ChatStreamService
from .core.task_store import DrawTaskStore
from .core.texts import (
    build_command_usage_text,
    build_compatible_mode_text,
    build_model_text,
    build_quota_adjust_text,
    build_session_status_text,
)
from .core.usage_store import UserQuotaStore


DRAW_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompt": {
            "type": "string",
            "description": "图片提示词，尽量描述清楚主体、风格和画面内容",
        },
        "model": {
            "type": "string",
            "description": "可选，指定要优先使用的图片模型；未传时使用当前会话首选模型",
        },
    },
    "required": ["prompt"],
}

EDIT_IMAGE_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "prompt": {
            "type": "string",
            "description": "图片编辑提示词，描述希望基于源图修改成什么样；不要把源图片描述写在这里替代真实图片",
        },
        "source_message_id": {
            "type": "string",
            "description": "可选，指定要编辑的源图片消息 ID；不填时自动优先取当前/最近引用消息中的图片，再取最近一张图片",
        },
        "source_image_base64": {
            "type": "string",
            "description": "可选，直接传入真实源图片 Base64 或 data:image/...;base64；不要传图片描述文本",
        },
        "model": {
            "type": "string",
            "description": "可选，指定要优先使用的图片模型；未传时使用当前会话首选模型",
        },
    },
    "required": ["prompt"],
}

DRAW_STATUS_TOOL_PARAMETERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "task_id": {
            "type": "string",
            "description": "可选，指定要查询的后台绘图任务 ID；不填时默认查询当前会话最近一个任务",
        },
    },
    "required": [],
}


class DrawpicPlugin(MaiBotPlugin):
    """麦麦绘图插件。"""

    config_model = DrawpicConfig
    config_reload_subscriptions: ClassVar[tuple[str, ...]] = ("bot", "model")

    def __init__(self) -> None:
        super().__init__()
        self._data_dir = Path(__file__).with_name("data")
        self._session_preferences_path = self._data_dir / "session_preferences.json"
        self._task_store_path = self._data_dir / "draw_tasks.json"
        self._usage_store_path = self._data_dir / "user_quotas.json"
        self._router: ProviderRouter | None = None
        self._session_store: SessionPreferenceStore | None = None
        self._stream_service: ChatStreamService | None = None
        self._moderation_service: DrawpicModerationService | None = None
        self._task_store = DrawTaskStore(path=self._task_store_path)
        self._usage_store = UserQuotaStore(path=self._usage_store_path)
        self._image_reply_renderer = PinkImageReplyRenderer()
        self._draw_service: DrawService | None = None

    def normalize_plugin_config(self, config_data: Mapping[str, Any] | None) -> tuple[dict[str, Any], bool]:
        """归一化配置，并把旧版独立审核节迁移到通用配置。"""

        migrated_config = migrate_legacy_review_config(config_data or {})
        normalized_config, changed = super().normalize_plugin_config(migrated_config)
        normalized_config.pop("prompt_review", None)
        normalized_config.pop("image_review", None)
        return normalized_config, changed or normalized_config != dict(config_data or {})

    def get_default_config(self) -> dict[str, Any]:
        """返回默认配置，不再展示旧版独立审核节。"""

        default_config = super().get_default_config()
        default_config.pop("prompt_review", None)
        default_config.pop("image_review", None)
        return default_config

    def get_webui_config_schema(
        self,
        *,
        plugin_id: str = "",
        plugin_name: str = "",
        plugin_version: str = "",
        plugin_description: str = "",
        plugin_author: str = "",
    ) -> dict[str, Any]:
        """返回不包含旧审核节的 WebUI 配置 Schema。"""

        schema = super().get_webui_config_schema(
            plugin_id=plugin_id,
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            plugin_description=plugin_description,
            plugin_author=plugin_author,
        )
        sections = schema.get("sections")
        if isinstance(sections, dict):
            sections.pop("prompt_review", None)
            sections.pop("image_review", None)
        return schema

    def _prepare_data_dir(self) -> None:
        """准备插件运行时数据目录，并迁移旧位置的数据文件。"""

        self._data_dir.mkdir(parents=True, exist_ok=True)
        legacy_paths = {
            Path(__file__).with_name("session_preferences.json"): self._session_preferences_path,
            Path(__file__).with_name("draw_tasks.json"): self._task_store_path,
        }
        for legacy_path, current_path in legacy_paths.items():
            if legacy_path.exists() and not current_path.exists():
                legacy_path.replace(current_path)

    def _refresh_services(self) -> None:
        """刷新内部服务对象。"""

        self._prepare_data_dir()
        existing_preferences: dict[str, dict[str, str]] = {}
        if self._session_store is not None:
            existing_preferences = dict(self._session_store.preferences)

        self._task_store.bind_logger(self.ctx.logger)
        self._usage_store.bind_logger(self.ctx.logger)
        self._router = ProviderRouter(self.config, logger=self.ctx.logger)
        self._session_store = SessionPreferenceStore(
            path=self._session_preferences_path,
            router=self._router,
            logger=self.ctx.logger,
        )
        self._session_store.preferences = existing_preferences
        self._session_store.normalize_all()
        self._stream_service = ChatStreamService(self.ctx)
        self._moderation_service = DrawpicModerationService(self.config, self.ctx)
        self._image_reply_renderer = PinkImageReplyRenderer()
        self._draw_service = DrawService(
            ctx=self.ctx,
            router=self._router,
            stream_service=self._stream_service,
            moderation_service=self._moderation_service,
            task_store=self._task_store,
        )

    def _require_router(self) -> ProviderRouter:
        """返回当前 Provider 路由器。"""

        if self._router is None:
            raise RuntimeError("插件服务尚未初始化，请等待插件完成加载")
        return self._router

    def _require_session_store(self) -> SessionPreferenceStore:
        """返回当前会话配置存储。"""

        if self._session_store is None:
            raise RuntimeError("插件服务尚未初始化，请等待插件完成加载")
        return self._session_store

    def _require_stream_service(self) -> ChatStreamService:
        """返回聊天流服务。"""

        if self._stream_service is None:
            raise RuntimeError("插件服务尚未初始化，请等待插件完成加载")
        return self._stream_service

    def _require_moderation_service(self) -> DrawpicModerationService:
        """返回审核服务。"""

        if self._moderation_service is None:
            raise RuntimeError("插件服务尚未初始化，请等待插件完成加载")
        return self._moderation_service

    def _require_draw_service(self) -> DrawService:
        """返回绘图服务。"""

        if self._draw_service is None:
            raise RuntimeError("插件服务尚未初始化，请等待插件完成加载")
        return self._draw_service

    def _get_session_preference(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> dict[str, str]:
        """获取当前会话的模型配置。"""

        return self._require_session_store().get_preference(stream_id, user_id, group_id, platform)

    def _set_session_preference(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
        *,
        model: str | None = None,
        openai_compatibility_mode: str | None = None,
    ) -> dict[str, str]:
        """更新当前会话的模型配置。"""

        return self._require_session_store().set_preference(
            stream_id,
            user_id,
            group_id,
            platform,
            model=model,
            openai_compatibility_mode=openai_compatibility_mode,
        )

    def _is_admin(self, user_id: str) -> bool:
        """判断用户是否为插件管理员。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return False
        admin_ids = {str(admin_id).strip() for admin_id in self.config.general.admin_user_ids}
        return normalized_user_id in admin_ids

    def _can_manage_session(self, user_id: str) -> bool:
        """判断用户是否可管理模型、兼容模式与次数。"""

        if not self.config.general.permission_enabled:
            return True
        return self._is_admin(user_id)

    def _resolve_quota_user_id(self, user_id: str, group_id: str, stream_id: str) -> str:
        """解析额度使用的用户键，始终以真实 user_id 为准。"""

        del stream_id  # 额度仅按 user_id 归属，不再用 stream_id 兜底
        normalized_user_id = user_id.strip()
        normalized_group_id = group_id.strip()
        if normalized_group_id and normalized_user_id == normalized_group_id:
            return ""
        return normalized_user_id

    def _quota_status_text(self, user_id: str, group_id: str, stream_id: str) -> str:
        """构建用户额度状态文本。"""

        if not self.config.general.quota_enabled:
            self.ctx.logger.info(
                "绘图额度状态: quota_enabled=false stream_id=%s user_id=%s group_id=%s",
                stream_id,
                user_id,
                group_id,
            )
            return "未启用次数管理"
        if self._is_admin(user_id):
            self.ctx.logger.info(
                "绘图额度状态: admin_user=true stream_id=%s user_id=%s group_id=%s",
                stream_id,
                user_id,
                group_id,
            )
            return "管理员不受次数限制"
        quota_user_id = self._resolve_quota_user_id(user_id, group_id, stream_id)
        if not quota_user_id:
            self.ctx.logger.warning(
                "绘图额度状态失败: 无法识别用户 user_id=%s group_id=%s stream_id=%s",
                user_id,
                group_id,
                stream_id,
            )
            return "无法识别用户身份，不能查询个人次数"
        remaining = self._usage_store.get_remaining(
            quota_user_id,
            period=self.config.general.quota_period,
            default_quota=self.config.general.default_quota,
        )
        self.ctx.logger.info(
            "绘图额度状态: quota_user_id=%s remaining=%s period=%s default_quota=%s stream_id=%s user_id=%s group_id=%s",
            quota_user_id,
            remaining,
            self.config.general.quota_period,
            self.config.general.default_quota,
            stream_id,
            user_id,
            group_id,
        )
        return f"用户 {quota_user_id} 当前周期剩余 {remaining} 次（周期：{self.config.general.quota_period}）"

    def _consume_draw_quota(self, user_id: str, group_id: str, stream_id: str) -> tuple[bool, str, str]:
        """预扣一次绘图额度，返回是否成功、提示文本和实际扣除的用户 ID。"""

        if not self.config.general.quota_enabled:
            self.ctx.logger.info(
                "跳过绘图额度扣除: quota_enabled=false stream_id=%s user_id=%s group_id=%s",
                stream_id,
                user_id,
                group_id,
            )
            return True, "未启用次数管理", ""
        if self._is_admin(user_id):
            self.ctx.logger.info(
                "跳过绘图额度扣除: admin_user=true stream_id=%s user_id=%s group_id=%s",
                stream_id,
                user_id,
                group_id,
            )
            return True, "管理员不受次数限制", ""
        quota_user_id = self._resolve_quota_user_id(user_id, group_id, stream_id)
        if not quota_user_id:
            self.ctx.logger.warning(
                "绘图额度扣除失败: 无法识别用户 user_id=%s group_id=%s stream_id=%s",
                user_id,
                group_id,
                stream_id,
            )
            return False, "无法识别用户身份，不能使用绘图次数", ""
        success, remaining = self._usage_store.consume(
            quota_user_id,
            period=self.config.general.quota_period,
            default_quota=self.config.general.default_quota,
        )
        if not success:
            self.ctx.logger.warning(
                "绘图额度不足: quota_user_id=%s remaining=%s period=%s default_quota=%s stream_id=%s user_id=%s group_id=%s",
                quota_user_id,
                remaining,
                self.config.general.quota_period,
                self.config.general.default_quota,
                stream_id,
                user_id,
                group_id,
            )
            return False, f"用户 {quota_user_id} 的绘图次数已用尽（周期：{self.config.general.quota_period}）", ""
        self.ctx.logger.info(
            "绘图额度已扣除: quota_user_id=%s remaining=%s period=%s default_quota=%s stream_id=%s user_id=%s group_id=%s",
            quota_user_id,
            remaining,
            self.config.general.quota_period,
            self.config.general.default_quota,
            stream_id,
            user_id,
            group_id,
        )
        return True, f"用户 {quota_user_id} 当前周期剩余 {remaining} 次", quota_user_id

    def _refund_draw_quota(
        self,
        quota_user_id: str,
        group_id: str,
        stream_id: str,
        reason: str,
        task_id: str = "",
    ) -> None:
        """回退一次已经预扣的绘图额度。"""

        normalized_quota_user_id = quota_user_id.strip()
        if not normalized_quota_user_id:
            return
        remaining = self._usage_store.refund(
            normalized_quota_user_id,
            period=self.config.general.quota_period,
            default_quota=self.config.general.default_quota,
        )
        self.ctx.logger.info(
            "绘图额度已回退: quota_user_id=%s remaining=%s period=%s stream_id=%s group_id=%s task_id=%s reason=%s",
            normalized_quota_user_id,
            remaining,
            self.config.general.quota_period,
            stream_id,
            group_id,
            task_id,
            reason,
        )

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
        """选择运行期真实用户 ID，QQ 群聊只接受数字用户号。"""

        normalized_candidates = [str(value or "").strip() for value in user_id_candidates]
        if cls._is_qq_platform(platform) and group_id.strip():
            normalized_group_id = group_id.strip()
            for candidate in normalized_candidates:
                if candidate.isdigit() and candidate != normalized_group_id:
                    return candidate
            return ""
        for candidate in normalized_candidates:
            if candidate:
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
            message_context.get("stream_id")
            or payload.get("stream_id")
            or payload.get("chat_id")
            or stream_id
            or ""
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
        if (
            any(str(value or "").strip() for value in (message_context_user_id, payload_user_id))
            and not normalized_user_id
            and normalized_group_id
            and self._is_qq_platform(normalized_platform)
        ):
            self.ctx.logger.warning(
                "绘图运行上下文收到无效QQ用户ID（昵称或群号），将拒绝用于个人额度 stream_id=%s user_id=%s group_id=%s platform=%s",
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
        """判断当前平台是否按 QQ 数字用户号处理额度。"""

        return platform.strip().lower() in {"qq", "qqguild"}

    @classmethod
    def _normalize_runtime_user_id(cls, user_id: str, platform: str) -> str:
        """清理运行期用户 ID，避免 QQ 昵称进入额度账本。"""

        normalized_user_id = user_id.strip()
        if not normalized_user_id:
            return ""
        if cls._is_qq_platform(platform) and not normalized_user_id.isdigit():
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

    @HookHandler(
        "chat.receive.before_process",
        name="prefixed_draw_command_fallback",
        description="处理 reply/at 前缀导致普通命令系统无法识别的 /绘图 命令",
    )
    async def handle_prefixed_draw_command_fallback(self, message: Any = None, stream_id: str = "", **kwargs: Any):
        """兜底处理原始文本段中实际以 /绘图 开头的命令。"""

        del kwargs
        if not isinstance(message, dict):
            return {"success": True, "action": "continue"}

        processed_plain_text = str(message.get("processed_plain_text") or "").strip()
        if processed_plain_text.startswith("/绘图") or processed_plain_text.startswith("/drawpic"):
            return {"success": True, "action": "continue"}

        command_text = self._extract_text_command_from_raw_message(message)
        if not command_text:
            return {"success": True, "action": "continue"}

        command_payload = command_text.split(maxsplit=1)[1] if " " in command_text else ""
        context = self._extract_message_context(message)
        normalized_stream_id = stream_id.strip() or context["stream_id"]
        if not normalized_stream_id:
            self.ctx.logger.warning("兜底绘图命令缺少 session_id，无法执行: %s", command_text)
            return {"success": True, "action": "continue"}

        success, response, intercept_message_level = await self.handle_draw_command(
            stream_id=normalized_stream_id,
            matched_groups={"content": command_payload},
            message=message,
            user_id=context["user_id"],
            group_id=context["group_id"],
            platform=context["platform"],
        )
        action = "abort" if intercept_message_level else "continue"
        self.ctx.logger.info(
            "已通过兜底 Hook 处理绘图命令: success=%s response=%s intercept=%s",
            success,
            response,
            intercept_message_level,
        )
        return {
            "success": True,
            "action": action,
            "custom_result": {
                "success": success,
                "response": response,
                "intercept_message_level": intercept_message_level,
            },
        }

    @HookHandler(
        "chat.receive.before_process",
        name="source_image_cache_handler",
        description="缓存入站图片原文，供 QQ 引用消息编辑使用",
        mode=HookMode.OBSERVE,
    )
    async def handle_source_image_cache(self, message: Any = None, stream_id: str = "", **kwargs: Any):
        """在主链清理图片二进制前缓存真实图片。"""

        del kwargs
        if not isinstance(message, dict):
            return True, True, None, None, None

        resolved_stream_id = stream_id or self._resolve_stream_id_from_hook_message(message)
        if not resolved_stream_id:
            return True, True, None, None, None

        try:
            cached = cache_source_image_from_message(resolved_stream_id, message)
        except ValueError as exc:
            self.ctx.logger.warning("缓存入站图片失败: stream_id=%s error=%s", resolved_stream_id, exc)
            return True, True, None, None, None

        if cached is not None:
            message_id, source_image_count = cached
            self.ctx.logger.info(
                "已缓存入站源图: stream_id=%s message_id=%s source_image_count=%s",
                resolved_stream_id,
                message_id,
                source_image_count,
            )
        return True, True, None, None, None

    async def _send_command_reply(
        self,
        *,
        title: str,
        body: str,
        stream_id: str,
        user_id: str,
        group_id: str,
        platform: str,
    ) -> bool:
        """按配置发送命令回复。"""

        if self.config.general.command_reply_mode == "文本":
            text = f"{title}\n\n{body.strip() or '无内容'}"
            return await self._require_stream_service().send_text_with_fallback(
                text=text,
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
        image_bytes = self._image_reply_renderer.render(title, body)
        return await self._require_stream_service().send_image_bytes_with_fallback(
            image_bytes=image_bytes,
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )

    async def on_load(self) -> None:
        """插件加载时初始化平台。"""

        self._refresh_services()
        self._require_session_store().load()
        self._task_store.load()
        self._usage_store.load()
        router = self._require_router()
        moderation_service = self._require_moderation_service()
        resolved_default_model = router.resolve_default_model()
        resolved_fallback_model = router.resolve_fallback_model(resolved_default_model)
        fallback_unavailable_reason = router.get_fallback_model_unavailable_reason(resolved_default_model)
        self.ctx.logger.info(
            "麦麦绘图插件已加载: default_model=%s fallback_model=%s configured_fallback_model=%s fallback_unavailable_reason=%s timeout=%ss aliyun_models=%s openai_models=%s google_models=%s zhipu_models=%s volcengine_t2i_models=%s volcengine_i2i_models=%s siliconflow_models=%s novelai_models=%s prompt_review=%s image_review=%s session_pref_count=%s task_count=%s",
            resolved_default_model,
            resolved_fallback_model or "未启用",
            self.config.general.fallback_model.strip() or "未配置",
            fallback_unavailable_reason or "",
            router.resolve_request_timeout_seconds(),
            len(router.get_aliyun_models()),
            len(router.get_openai_models()),
            len(router.get_google_models()),
            len(router.get_zhipu_models()),
            len(router.get_volcengine_t2i_models()),
            len(router.get_volcengine_i2i_models()),
            len(router.get_siliconflow_models()),
            len(router.get_novelai_models()),
            moderation_service.is_prompt_review_enabled(),
            moderation_service.is_image_review_enabled(),
            len(self._require_session_store().preferences),
            self._task_store.get_task_count(),
        )

    async def on_unload(self) -> None:
        """插件卸载回调。"""

        self._require_draw_service().cancel_background_tasks()
        self._require_session_store().save()
        self._task_store.save()
        self._usage_store.save()
        self.ctx.logger.info("麦麦绘图插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, Any], version: str) -> None:
        """配置变更时重新初始化平台。"""

        del config_data
        if scope in {CONFIG_RELOAD_SCOPE_SELF, ON_MODEL_CONFIG_RELOAD, ON_BOT_CONFIG_RELOAD}:
            self._refresh_services()
            self._require_session_store().normalize_all()
            self._require_session_store().save()
            self._task_store.load()
            self._usage_store.load()
            router = self._require_router()
            moderation_service = self._require_moderation_service()
            resolved_default_model = router.resolve_default_model()
            resolved_fallback_model = router.resolve_fallback_model(resolved_default_model)
            fallback_unavailable_reason = router.get_fallback_model_unavailable_reason(resolved_default_model)
            self.ctx.logger.info(
                "麦麦绘图插件配置已更新: scope=%s version=%s default_model=%s fallback_model=%s configured_fallback_model=%s fallback_unavailable_reason=%s timeout=%ss aliyun_models=%s openai_models=%s google_models=%s zhipu_models=%s volcengine_t2i_models=%s volcengine_i2i_models=%s siliconflow_models=%s novelai_models=%s prompt_review=%s image_review=%s task_count=%s",
                scope,
                version,
                resolved_default_model,
                resolved_fallback_model or "未启用",
                self.config.general.fallback_model.strip() or "未配置",
                fallback_unavailable_reason or "",
                router.resolve_request_timeout_seconds(),
                len(router.get_aliyun_models()),
                len(router.get_openai_models()),
                len(router.get_google_models()),
                len(router.get_zhipu_models()),
                len(router.get_volcengine_t2i_models()),
                len(router.get_volcengine_i2i_models()),
                len(router.get_siliconflow_models()),
                len(router.get_novelai_models()),
                moderation_service.is_prompt_review_enabled(),
                moderation_service.is_image_review_enabled(),
                self._task_store.get_task_count(),
            )

    async def _start_background_image_request(
        self,
        *,
        prompt: str,
        stream_id: str,
        requested_model: str = "",
        requested_openai_compatibility_mode: str = "",
        source_image_bytes_list: list[bytes] | None = None,
        matched_message_id: str = "",
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
        notify_start: bool = True,
    ) -> dict[str, Any]:
        """按当前会话设置启动后台绘图，源图为空时文生图，存在源图时图生图。"""

        draw_service = self._require_draw_service()
        live_context = await self._require_stream_service().resolve_live_stream_context(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform_name,
        )
        runtime_context = self._merge_resolved_runtime_context(
            live_context,
            user_id=user_id,
            group_id=group_id,
            platform=platform_name,
        )
        resolved_stream_id = runtime_context["stream_id"]
        if not resolved_stream_id:
            raise RuntimeError("当前聊天流不可用，无法回传图片")
        resolved_user_id = runtime_context["user_id"]
        resolved_group_id = runtime_context["group_id"]
        resolved_platform = runtime_context["platform"]
        normalized_source_images = source_image_bytes_list or []
        session_preference = self._get_session_preference(
            resolved_stream_id,
            resolved_user_id,
            resolved_group_id,
            resolved_platform,
        )
        resolved_model = draw_service.resolve_model_name(
            requested_model or session_preference["model"],
            allow_unknown_model=False,
        )
        resolved_openai_mode = self._require_router().resolve_openai_compatibility_mode(
            requested_openai_compatibility_mode or session_preference["openai_compatibility_mode"],
            resolved_model,
        )
        provider_name = self._require_router().get_model_provider(resolved_model)
        if not provider_name:
            raise ValueError(f"指定模型不可用：{resolved_model}")
        # 火山引擎文生图/图生图模型分离，提前检查时需用自动切换后的模型判断图生图能力
        check_model = resolved_model
        if provider_name == "volcengine" and normalized_source_images:
            try:
                check_model = self._require_router().resolve_volcengine_model_for_task(resolved_model, "edit_image")
            except ValueError:
                check_model = resolved_model
        image_edit_unsupported_reason = self._require_router().get_image_edit_unsupported_reason(check_model)
        if normalized_source_images and image_edit_unsupported_reason:
            raise ValueError(f"{image_edit_unsupported_reason}。请改用 /绘图 文生图 <prompt>，或切换到支持图生图的模型")

        await draw_service.review_prompt_or_raise(prompt)
        quota_allowed, quota_message, quota_user_id = self._consume_draw_quota(
            resolved_user_id,
            resolved_group_id,
            resolved_stream_id,
        )
        if not quota_allowed:
            raise PermissionError(quota_message)

        async def _refund_quota_on_task_unsuccessful(task_id: str, status: str, reason: str) -> None:
            self._refund_draw_quota(
                quota_user_id,
                resolved_group_id,
                resolved_stream_id,
                f"{status}: {reason}",
                task_id,
            )

        try:
            return await draw_service.start_background_image_request(
                prompt=prompt,
                stream_id=resolved_stream_id,
                resolved_model=resolved_model,
                resolved_openai_mode=resolved_openai_mode,
                provider_name=provider_name,
                user_id=resolved_user_id,
                group_id=resolved_group_id,
                platform_name=resolved_platform,
                source_image_bytes_list=normalized_source_images,
                matched_message_id=matched_message_id,
                notify_start=notify_start,
                on_task_unsuccessful=_refund_quota_on_task_unsuccessful if quota_user_id else None,
            )
        except Exception as exc:
            self._refund_draw_quota(quota_user_id, resolved_group_id, resolved_stream_id, str(exc))
            raise

    @Tool(
        "draw",
        description="根据纯文本提示调用绘图模型创建新图片，并发送到当前聊天流；用户要求修改、编辑、重绘已有图片时不要调用本工具，应调用 edit_image",
        parameters=DRAW_TOOL_PARAMETERS_SCHEMA,
    )
    async def handle_draw(
        self,
        prompt: str,
        user_id: str = "",
        model: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """创建图片。"""

        if not prompt.strip():
            return {"success": False, "message": "提示词不能为空"}

        try:
            context = self._extract_invocation_context(kwargs=kwargs, llm_user_id=user_id)
            return await self._start_background_image_request(
                prompt=prompt.strip(),
                stream_id=context["stream_id"],
                requested_model=model.strip(),
                user_id=context["user_id"],
                group_id=context["group_id"],
                platform_name=context["platform"],
            )
        except PermissionError as exc:
            return {
                "success": False,
                "message": str(exc),
            }
        except Exception as exc:
            self.ctx.logger.error("启动后台创建图片失败: %s", exc, exc_info=True)
            return {"success": False, "message": f"启动后台创建图片失败：{exc}"}

    @Tool(
        "edit_image",
        description=(
            "基于当前聊天中的真实图片执行图生图编辑；仅当用户明确要求修改、编辑、重绘已有图片时调用。"
            "如果用户回复/引用了一张图片，直接调用本工具，插件会从引用消息中提取真实图片。"
            "找不到真实图片或模型平台不支持图片编辑时，返回原因并由 AI 告知用户无法调用图片编辑"
        ),
        parameters=EDIT_IMAGE_TOOL_PARAMETERS_SCHEMA,
    )
    async def handle_edit_image(
        self,
        prompt: str,
        user_id: str = "",
        source_message_id: str = "",
        source_image_base64: str = "",
        model: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """编辑图片。"""

        if not prompt.strip():
            return {"success": False, "message": "提示词不能为空"}

        try:
            draw_service = self._require_draw_service()
            context = self._extract_invocation_context(kwargs=kwargs, llm_user_id=user_id)
            live_context = await self._require_stream_service().resolve_live_stream_context(
                stream_id=context["stream_id"],
                user_id=context["user_id"],
                group_id=context["group_id"],
                platform=context["platform"],
            )
            runtime_context = self._merge_resolved_runtime_context(
                live_context,
                user_id=context["user_id"],
                group_id=context["group_id"],
                platform=context["platform"],
            )
            normalized_stream_id = runtime_context["stream_id"]
            if not normalized_stream_id:
                return {"success": False, "message": "当前聊天流 ID 为空，无法回传图片"}
            normalized_user_id = runtime_context["user_id"]
            normalized_group_id = runtime_context["group_id"]
            platform_name = runtime_context["platform"]
            session_preference = self._get_session_preference(
                normalized_stream_id,
                normalized_user_id,
                normalized_group_id,
                platform_name,
            )
            resolved_model = draw_service.resolve_model_name(model.strip() or session_preference["model"])
            resolved_openai_mode = session_preference["openai_compatibility_mode"]
            router = self._require_router()
            provider_name = router.get_model_provider(resolved_model)
            if not provider_name:
                return {"success": False, "message": f"指定模型不可用：{resolved_model}"}
            # 火山引擎文生图/图生图模型分离，提前检查时需用自动切换后的模型判断图生图能力
            check_model = resolved_model
            if provider_name == "volcengine":
                try:
                    check_model = router.resolve_volcengine_model_for_task(resolved_model, "edit_image")
                except ValueError:
                    check_model = resolved_model
            image_edit_unsupported_reason = router.get_image_edit_unsupported_reason(check_model)
            if image_edit_unsupported_reason:
                return {
                    "success": False,
                    "message": (
                        f"{image_edit_unsupported_reason}，无法调用 edit_image 图生图。"
                        "请自然告知用户当前只能文生图，不能基于已有图片修改，或提示切换到支持图生图的模型。"
                    ),
                }
            lookup_stream_id = await self._require_stream_service().resolve_live_stream_id(
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=platform_name,
            )
            current_message = kwargs.get("message")
            lookup_stream_ids = self._build_image_lookup_stream_ids(
                lookup_stream_id,
                normalized_stream_id,
                message=current_message,
            )
            image_base64_list, matched_message_id = await find_source_images(
                self.ctx,
                lookup_stream_ids,
                source_message_id=source_message_id,
                source_image_base64=source_image_base64,
                current_message=current_message if isinstance(current_message, dict) else None,
            )
            source_image_bytes_list = [decode_image_base64(image_base64) for image_base64 in image_base64_list]
            self.ctx.logger.info(
                "edit_image 已收集源图: stream_id=%s lookup_stream_ids=%s source_image_count=%s matched_message_id=%s",
                normalized_stream_id,
                lookup_stream_ids,
                len(source_image_bytes_list),
                matched_message_id,
            )
            return await self._start_background_image_request(
                prompt=prompt.strip(),
                stream_id=normalized_stream_id,
                requested_model=resolved_model,
                requested_openai_compatibility_mode=resolved_openai_mode,
                source_image_bytes_list=source_image_bytes_list,
                matched_message_id=matched_message_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform_name=platform_name,
                notify_start=True,
            )
        except PermissionError as exc:
            return {
                "success": False,
                "message": str(exc),
            }
        except ValueError as exc:
            return {
                "success": False,
                "message": (
                    f"{exc}。无法调用 edit_image 图片编辑；请自然告知用户需要先发送一张真实图片，"
                    "或回复/指定包含图片的消息后再编辑。"
                ),
            }
        except Exception as exc:
            self.ctx.logger.error("启动后台编辑图片失败: %s", exc, exc_info=True)
            return {"success": False, "message": f"启动后台编辑图片失败：{exc}"}

    @Tool(
        "draw_status",
        description="查询最近一个绘图后台任务，或查询指定 task_id 的绘图任务状态",
        parameters=DRAW_STATUS_TOOL_PARAMETERS_SCHEMA,
    )
    async def handle_draw_status(
        self,
        user_id: str = "",
        task_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """查询后台绘图任务状态。"""

        context = self._extract_invocation_context(kwargs=kwargs, llm_user_id=user_id)
        live_context = await self._require_stream_service().resolve_live_stream_context(
            stream_id=context["stream_id"],
            user_id=context["user_id"],
            group_id=context["group_id"],
            platform=context["platform"],
        )
        runtime_context = self._merge_resolved_runtime_context(
            live_context,
            user_id=context["user_id"],
            group_id=context["group_id"],
            platform=context["platform"],
        )
        if not runtime_context["stream_id"]:
            return {"success": False, "message": "当前聊天流不可用，无法查询绘图任务状态"}
        return self._require_draw_service().get_task_status_payload(
            stream_id=runtime_context["stream_id"],
            task_id=task_id,
            user_id=runtime_context["user_id"],
            group_id=runtime_context["group_id"],
            platform=runtime_context["platform"],
        )

    @staticmethod
    def _split_command_payload(command_payload: str) -> tuple[str, str]:
        """拆分命令首词与剩余文本。"""

        stripped_payload = command_payload.strip()
        if not stripped_payload:
            return "", ""
        parts = stripped_payload.split(maxsplit=1)
        first_word = parts[0]
        rest_payload = parts[1] if len(parts) > 1 else ""
        return first_word, rest_payload

    @staticmethod
    def _normalize_command_name(command_name: str) -> str:
        """归一化中英文命令名。"""

        command_map = {
            "状态": "status",
            "status": "status",
            "模型": "model",
            "model": "model",
            "兼容模式": "compatible-mode",
            "compatible-mode": "compatible-mode",
            # 文生图：强制走纯文本提示词绘图，"绘制" 为兼容旧版的别名
            "文生图": "draw_text",
            "绘制": "draw_text",
            "draw": "draw_text",
            # 图生图：强制走基于源图片的编辑流程
            "图生图": "draw_image",
            "edit": "draw_image",
            "次数": "times",
            "times": "times",
            "添加": "add",
            "add": "add",
            "减少": "remove",
            "remove": "remove",
            "设置": "set",
            "set": "set",
        }
        return command_map.get(command_name.strip(), "")

    async def _handle_times_command(
        self,
        *,
        rest_payload: str,
        stream_id: str,
        user_id: str,
        group_id: str,
        platform: str,
    ) -> tuple[bool, str, int]:
        """处理用户次数调整命令。"""

        if not self._can_manage_session(user_id):
            await self._send_command_reply(
                title="权限不足",
                body="当前已启用权限管理。\n只有插件管理员可以调整用户绘图次数。",
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "权限不足", 1

        action_word, action_rest = self._split_command_payload(rest_payload)
        action = self._normalize_command_name(action_word)
        if action not in {"add", "remove", "set"}:
            await self._send_command_reply(
                title="次数命令用法",
                body=(
                    "/绘图 添加/减少/设置 用户ID 次数"
                ),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "次数命令参数不足", 1

        target_user_id, count_text = self._split_command_payload(action_rest)
        try:
            count = int(count_text.strip())
        except ValueError:
            count = -1
        if not target_user_id or count < 0 or (action in {"add", "remove"} and count == 0):
            await self._send_command_reply(
                title="次数命令参数无效",
                body="请提供用户ID和有效次数。\n添加/减少需要正整数，设置可设置为 0。",
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "次数命令参数无效", 1

        remaining = self._usage_store.adjust_remaining(
            target_user_id,
            action=action,  # type: ignore[arg-type]
            count=count,
            period=self.config.general.quota_period,
            default_quota=self.config.general.default_quota,
        )
        self.ctx.logger.info(
            "绘图额度已调整: action=%s target_user_id=%s count=%s remaining=%s operator_user_id=%s stream_id=%s group_id=%s period=%s default_quota=%s",
            action,
            target_user_id,
            count,
            remaining,
            user_id,
            stream_id,
            group_id,
            self.config.general.quota_period,
            self.config.general.default_quota,
        )
        action_label_map = {
            "add": "添加",
            "remove": "减少",
            "set": "设置",
        }
        await self._send_command_reply(
            title="次数已更新",
            body=build_quota_adjust_text(action_label_map[action], target_user_id, remaining),
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        return True, "已调整用户绘图次数", 2

    async def _handle_draw_image_command(
        self,
        *,
        rest_payload: str,
        message: Any,
        session_preference: dict[str, str],
        stream_id: str,
        user_id: str,
        group_id: str,
        platform: str,
    ) -> tuple[bool, str, int]:
        """处理 /绘图 图生图 命令，基于命令携带或引用的图片强制走图生图。"""

        prompt = rest_payload.strip()
        if not prompt:
            await self._send_command_reply(
                title="缺少图生图提示词",
                body="请使用：/绘图 图生图 <prompt>，并在同一条消息中附带或引用至少一张图片。",
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "缺少提示词", 1

        draw_service = self._require_draw_service()
        router = self._require_router()
        resolved_model = draw_service.resolve_model_name(session_preference["model"])
        provider_name = router.get_model_provider(resolved_model)
        if not provider_name:
            await self._send_command_reply(
                title="模型不可用",
                body=f"当前会话首选模型不可用：{resolved_model}",
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "模型不可用", 1

        # 部分平台或模型不支持图生图，提前给出清晰提示，且不创建后台任务。
        # 火山引擎文生图/图生图模型分离，提前检查时需用自动切换后的模型判断图生图能力
        check_model = resolved_model
        if provider_name == "volcengine":
            try:
                check_model = router.resolve_volcengine_model_for_task(resolved_model, "edit_image")
            except ValueError:
                check_model = resolved_model
        image_edit_unsupported_reason = router.get_image_edit_unsupported_reason(check_model)
        if image_edit_unsupported_reason:
            await self._send_command_reply(
                title="当前模型不支持图生图",
                body=(
                    f"{image_edit_unsupported_reason}。\n"
                    "请先用 /绘图 模型 <模型名> 设置支持图生图的首选模型，或改用 /绘图 文生图 <prompt>。"
                ),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "当前模型不支持图生图", 1

        try:
            image_base64_list, lookup_stream_ids, matched_message_id = await self._collect_forced_command_source_images(
                message=message,
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
        except Exception as exc:
            self.ctx.logger.error("/绘图 图生图命令收集源图片失败: %s", exc, exc_info=True)
            await self._send_command_reply(
                title="读取源图片失败",
                body=str(exc),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "读取源图片失败", 1

        if not image_base64_list:
            await self._send_command_reply(
                title="未找到可用图片",
                body="没有找到可用于图生图的图片。\n请在 /绘图 图生图 <prompt> 同一条消息中附带图片，或回复/引用包含图片的消息。",
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "未找到可用图片", 1

        try:
            source_image_bytes_list = [decode_image_base64(image_base64) for image_base64 in image_base64_list]
            self.ctx.logger.info(
                "/绘图 图生图已收集源图: stream_id=%s lookup_stream_ids=%s source_image_count=%s message_id=%s",
                stream_id,
                lookup_stream_ids,
                len(source_image_bytes_list),
                matched_message_id,
            )
            start_result = await self._start_background_image_request(
                prompt=prompt,
                stream_id=stream_id,
                requested_model=resolved_model,
                requested_openai_compatibility_mode=session_preference["openai_compatibility_mode"],
                source_image_bytes_list=source_image_bytes_list,
                matched_message_id=matched_message_id,
                user_id=user_id,
                group_id=group_id,
                platform_name=platform,
                notify_start=True,
            )
        except PermissionError as exc:
            await self._send_command_reply(
                title="绘图次数不足",
                body=f"{exc}。请联系管理员调整次数后再使用图生图。",
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "绘图次数不足", 1
        except Exception as exc:
            self.ctx.logger.error("/绘图 图生图命令启动失败: %s", exc, exc_info=True)
            await self._send_command_reply(
                title="图生图请求未能启动",
                body=str(exc),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "图生图命令执行失败", 1

        self.ctx.logger.info(
            "图生图任务已提交: task_id=%s stream_id=%s user_id=%s group_id=%s source_image_count=%s",
            start_result.get("task_id"),
            stream_id,
            user_id,
            group_id,
            len(source_image_bytes_list),
        )
        return True, "已开始处理图生图命令", 2

    async def _collect_forced_command_source_images(
        self,
        *,
        message: Any,
        stream_id: str,
        user_id: str,
        group_id: str,
        platform: str,
    ) -> tuple[list[str], list[str], str]:
        """收集强制绘图命令显式携带或引用的源图。"""

        lookup_stream_id = await self._require_stream_service().resolve_live_stream_id(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        command_message = message if isinstance(message, dict) else {}
        lookup_stream_ids = self._build_image_lookup_stream_ids(
            lookup_stream_id,
            stream_id,
            message=command_message,
        )
        image_base64_list = await collect_command_source_images(
            self.ctx,
            lookup_stream_ids,
            command_message,
        )
        matched_message_id = str(command_message.get("message_id") or "").strip()
        return image_base64_list, lookup_stream_ids, matched_message_id

    @Command("draw_command", description="绘图命令", pattern=r"^/(?:绘图|drawpic)(?:\s+(?P<content>[\s\S]+))?$")
    async def handle_draw_command(
        self,
        stream_id: str = "",
        **kwargs: Any,
    ) -> tuple[bool, str, int]:
        """处理绘图命令。"""

        matched_groups = kwargs.get("matched_groups", {})
        command_payload = str(matched_groups.get("content") or "").strip() if isinstance(matched_groups, dict) else ""
        context = self._extract_runtime_context(stream_id=stream_id, kwargs=kwargs)
        normalized_stream_id = context["stream_id"]
        normalized_user_id = context["user_id"]
        normalized_group_id = context["group_id"]
        normalized_platform = context["platform"]

        live_context = await self._require_stream_service().resolve_live_stream_context(
            stream_id=normalized_stream_id,
            user_id=normalized_user_id,
            group_id=normalized_group_id,
            platform=normalized_platform,
        )
        runtime_context = self._merge_resolved_runtime_context(
            live_context,
            user_id=normalized_user_id,
            group_id=normalized_group_id,
            platform=normalized_platform,
        )
        resolved_stream_id = runtime_context["stream_id"]
        if not resolved_stream_id:
            return False, "当前聊天流不可用，无法执行绘图命令", 1
        normalized_stream_id = resolved_stream_id
        normalized_user_id = runtime_context["user_id"]
        normalized_group_id = runtime_context["group_id"]
        normalized_platform = runtime_context["platform"]

        if not command_payload or command_payload in {"帮助", "help"}:
            await self._send_command_reply(
                title="麦麦绘图",
                body=build_command_usage_text(),
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return True, "已显示绘图帮助", 2

        session_preference = self._get_session_preference(
            normalized_stream_id,
            normalized_user_id,
            normalized_group_id,
            normalized_platform,
        )
        first_word, rest_payload = self._split_command_payload(command_payload)
        normalized_command = self._normalize_command_name(first_word)

        if normalized_command == "status":
            latest_task = self._task_store.get_latest_task(
                self._require_draw_service().build_session_key(
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
            )
            await self._send_command_reply(
                title="绘图状态",
                body=build_session_status_text(
                    self._require_router(),
                    session_preference,
                    latest_task,
                    quota_text=self._quota_status_text(
                        normalized_user_id,
                        normalized_group_id,
                        normalized_stream_id,
                    ),
                ),
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return True, "已显示当前绘图状态", 2

        if normalized_command == "model":
            model_name = rest_payload.strip()
            if not model_name:
                await self._send_command_reply(
                    title="绘图模型",
                    body=build_model_text(self._require_router(), session_preference),
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return True, "已显示模型列表", 2

            if not self._can_manage_session(normalized_user_id):
                await self._send_command_reply(
                    title="权限不足",
                    body="当前已启用权限管理。\n只有插件管理员可以设置本群或本会话使用的首选绘图模型。",
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "权限不足", 1

            provider_name = self._require_router().get_model_provider(model_name)
            if not provider_name:
                await self._send_command_reply(
                    title="模型不存在",
                    body=f"未找到模型：{model_name}\n\n{build_model_text(self._require_router(), session_preference)}",
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "模型不存在", 1

            next_preference = self._set_session_preference(
                normalized_stream_id,
                normalized_user_id,
                normalized_group_id,
                normalized_platform,
                model=model_name,
            )
            await self._send_command_reply(
                title="首选模型已设置",
                body=f"当前会话首选绘图模型：{provider_name}：{next_preference['model']}",
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return True, "已设置首选绘图模型", 2

        if normalized_command == "compatible-mode":
            compatibility_mode = rest_payload.strip()
            if not compatibility_mode:
                await self._send_command_reply(
                    title="OpenAI 兼容模式",
                    body=build_compatible_mode_text(session_preference["openai_compatibility_mode"]),
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return True, "已显示兼容模式说明", 2

            if not self._can_manage_session(normalized_user_id):
                await self._send_command_reply(
                    title="权限不足",
                    body="当前已启用权限管理。\n只有插件管理员可以切换 OpenAI 兼容模式。",
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "权限不足", 1

            clear_mode_aliases = {"默认", "跟随", "清空", "default", "unset", "clear"}
            if compatibility_mode in clear_mode_aliases:
                compatibility_mode = ""
            elif compatibility_mode not in {"auto", "images_api", "chat_completions", "novelai_images_api"}:
                await self._send_command_reply(
                    title="兼容模式无效",
                    body=build_compatible_mode_text(session_preference["openai_compatibility_mode"]),
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "兼容模式无效", 1

            next_preference = self._set_session_preference(
                normalized_stream_id,
                normalized_user_id,
                normalized_group_id,
                normalized_platform,
                openai_compatibility_mode=compatibility_mode,
            )
            await self._send_command_reply(
                title="兼容模式已切换",
                body=(
                    "当前会话 OpenAI 兼容模式："
                    f"{next_preference['openai_compatibility_mode'] or '跟随模型配置'}\n"
                    "该设置仅对 OpenAI 提供商生效。"
                ),
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return True, "已切换 OpenAI 兼容模式", 2

        if normalized_command == "draw_text":
            prompt = rest_payload.strip()
            if not prompt:
                await self._send_command_reply(
                    title="缺少绘图提示词",
                    body="请使用：/绘图 文生图 <prompt>",
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "缺少提示词", 1

            try:
                try:
                    image_base64_list, lookup_stream_ids, matched_message_id = await self._collect_forced_command_source_images(
                        message=kwargs.get("message"),
                        stream_id=normalized_stream_id,
                        user_id=normalized_user_id,
                        group_id=normalized_group_id,
                        platform=normalized_platform,
                    )
                except Exception as exc:
                    self.ctx.logger.error("/绘图 文生图检查源图失败: %s", exc, exc_info=True)
                    await self._send_command_reply(
                        title="无法确认绘图模式",
                        body=(
                            "当前使用的是 /绘图 文生图，但插件无法确认这条消息或引用消息中是否包含图片。\n"
                            "如果要纯文字生成，请不要引用或附带图片后重试；如果要基于图片修改，请使用：/绘图 图生图 <prompt>。"
                        ),
                        stream_id=normalized_stream_id,
                        user_id=normalized_user_id,
                        group_id=normalized_group_id,
                        platform=normalized_platform,
                    )
                    return False, "文生图指令源图检查失败", 1

                if image_base64_list:
                    self.ctx.logger.info(
                        "/绘图 文生图检测到源图，拒绝强制文生图: stream_id=%s lookup_stream_ids=%s source_image_count=%s message_id=%s",
                        normalized_stream_id,
                        lookup_stream_ids,
                        len(image_base64_list),
                        matched_message_id,
                    )
                    await self._send_command_reply(
                        title="绘图模式不匹配",
                        body=(
                            "当前指令是 /绘图 文生图，但消息中检测到了图片或引用图片。\n"
                            "如果要基于图片修改，请使用：/绘图 图生图 <prompt>；如果只想按文字生成，请不要附带或引用图片。"
                        ),
                        stream_id=normalized_stream_id,
                        user_id=normalized_user_id,
                        group_id=normalized_group_id,
                        platform=normalized_platform,
                    )
                    return False, "文生图指令检测到源图", 1

                start_result = await self._start_background_image_request(
                    prompt=prompt,
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform_name=normalized_platform,
                )
            except Exception as exc:
                self.ctx.logger.error("/绘图 文生图命令启动失败: %s", exc, exc_info=True)
                await self._send_command_reply(
                    title="绘图请求未能启动",
                    body=str(exc),
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "绘图命令执行失败", 1

            self.ctx.logger.info(
                "文生图任务已提交: task_id=%s stream_id=%s user_id=%s group_id=%s",
                start_result.get("task_id"),
                normalized_stream_id,
                normalized_user_id,
                normalized_group_id,
            )
            return True, "已开始处理文生图命令", 2

        if normalized_command == "draw_image":
            return await self._handle_draw_image_command(
                rest_payload=rest_payload,
                message=kwargs.get("message"),
                session_preference=session_preference,
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )

        if normalized_command == "times":
            return await self._handle_times_command(
                rest_payload=rest_payload,
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )

        if normalized_command in {"add", "remove", "set"}:
            return await self._handle_times_command(
                rest_payload=f"{normalized_command} {rest_payload}".strip(),
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )

        await self._send_command_reply(
            title="未知子命令",
            body=build_command_usage_text(),
            stream_id=normalized_stream_id,
            user_id=normalized_user_id,
            group_id=normalized_group_id,
            platform=normalized_platform,
        )
        return False, "未知绘图子命令", 1


def create_plugin() -> DrawpicPlugin:
    """创建插件实例。"""

    return DrawpicPlugin()
