"""runtime/hooks.py 的插件组件。"""

from maibot_sdk import HookHandler
from maibot_sdk.types import HookMode
from typing import Any

from ..application.access import ChatAccessDenied, require_chat_access
from .chat.message_images import cache_source_image_from_message


class HookMixin:
    """runtime/hooks.py 对应的插件行为。"""

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
        log = self.ctx.logger.info if success else self.ctx.logger.debug
        log(
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

        context = {**self._extract_message_context(message), "stream_id": resolved_stream_id}
        try:
            require_chat_access(self.config.general, context, self.ctx.logger)
        except ChatAccessDenied:
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
