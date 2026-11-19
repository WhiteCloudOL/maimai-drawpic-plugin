"""runtime/replies.py 的插件组件。"""

from typing import Any
import re

from .image_reply import ReplyTextSpan
from ...infrastructure.http import sanitize_provider_text


class ReplyMixin:
    """runtime/replies.py 对应的插件行为。"""

    async def _send_command_reply(
        self,
        *,
        title: str,
        body: str,
        stream_id: str,
        user_id: str,
        group_id: str,
        platform: str,
        body_lines: list[list[ReplyTextSpan]] | None = None,
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
        image_bytes = (
            self._image_reply_renderer.render_rich(title, body_lines)
            if body_lines is not None
            else self._image_reply_renderer.render(title, body)
        )
        return await self._require_stream_service().send_image_bytes_with_fallback(
            image_bytes=image_bytes,
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )

    def _summarize_failure_reason(self, reason: str) -> str:
        """生成适合直接发送的简短、脱敏错误原因。"""

        redactor = getattr(self, "_redactor", None)
        redact = redactor.redact if redactor is not None else sanitize_provider_text
        normalized_reason = re.sub(r"\s+", " ", redact(reason or "未知错误")).strip()
        normalized_reason = re.sub(
            r"(?i)\b(bearer\s+|api[_ -]?key[=:]\s*|token[=:]\s*)[^\s,;]+",
            r"\1***",
            normalized_reason,
        )
        normalized_reason = re.sub(r"\b(?:sk|sess|gh[opusr])-[A-Za-z0-9_-]{8,}\b", "***", normalized_reason)
        max_length = 300
        if len(normalized_reason) <= max_length:
            return normalized_reason
        return normalized_reason[: max_length - 1].rstrip() + "…"

    async def _send_draw_failure_notice(
        self,
        *,
        reason: str,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
        task_id: str = "",
        status: str = "failed",
        from_command: bool = False,
    ) -> bool:
        """不经 LLM，直接向原聊天流发送绘图失败状态。"""

        if not from_command and not self.config.general.failure_reason_enabled:
            self.ctx.logger.info(
                "绘图失败主动通知已关闭: task_id=%s stream_id=%s status=%s reason=%s",
                task_id,
                stream_id,
                status,
                self._summarize_failure_reason(reason),
            )
            return False

        if status == "delivery_unconfirmed":
            lines = [self._summarize_failure_reason(reason)]
        else:
            title = "绘图未通过审核" if status == "rejected" else "绘图失败"
            lines = [title]
        if task_id.strip():
            lines.append(f"任务 ID：{task_id.strip()}")
        if status != "delivery_unconfirmed":
            lines.append(f"原因：{self._summarize_failure_reason(reason)}")
        try:
            return await self._require_stream_service().send_text_with_fallback(
                text="\n".join(lines),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
        except Exception as exc:
            self.ctx.logger.error(
                "发送绘图失败通知异常: task_id=%s stream_id=%s status=%s error=%s",
                task_id,
                stream_id,
                status,
                exc,
                exc_info=True,
            )
            return False

    async def _send_invocation_failure_notice(
        self,
        *,
        reason: str,
        kwargs: dict[str, Any],
        user_id: str = "",
    ) -> None:
        """尽力从工具运行上下文解析原聊天流并直发失败信息。"""

        try:
            context = self._extract_invocation_context(kwargs=kwargs, llm_user_id=user_id)
            if not context["stream_id"]:
                return
            await self._send_draw_failure_notice(
                reason=reason,
                stream_id=context["stream_id"],
                user_id=context["user_id"],
                group_id=context["group_id"],
                platform=context["platform"],
            )
        except Exception as exc:
            self.ctx.logger.warning("无法从工具上下文发送绘图失败通知: error=%s", exc)
