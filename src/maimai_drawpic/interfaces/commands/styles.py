"""commands/styles.py 的插件组件。"""

from ...infrastructure.observability.redaction import outward_error

from typing import Any

from ..chat.texts import build_style_reply_lines, build_style_text


class StyleCommandMixin:
    """commands/styles.py 对应的插件行为。"""

    async def _handle_style_command(
        self,
        *,
        rest_payload: str,
        message: Any,
        stream_id: str,
        user_id: str,
        group_id: str,
        platform: str,
    ) -> tuple[bool, str, int]:
        """处理全平台风格提示词模板指令。"""

        style_name, prompt_payload = self._split_command_payload(rest_payload)
        if not style_name:
            resolver = self._require_style_prompt_resolver()
            await self._send_command_reply(
                title="绘图风格",
                body=build_style_text(resolver),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
                body_lines=build_style_reply_lines(resolver),
            )
            return True, "已显示绘图风格列表", 2

        positive_prompt, negative_prompt = self._split_negative_prompt(prompt_payload)
        try:
            resolved_prompt = self._require_style_prompt_resolver().resolve(
                style_name=style_name,
                user_prompt=positive_prompt,
                user_negative_prompt=negative_prompt,
            )
            source_images, source_image_urls, matched_message_id = await self._collect_optional_command_source_images(
                message=message,
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            if not resolved_prompt.positive_prompt and not source_images:
                raise ValueError("请提供正向提示词，或在同一条消息中附带/引用图片")
            result = await self._start_background_image_request(
                defer_prompt_review=True,
                prompt=resolved_prompt.positive_prompt,
                request_negative_prompt=resolved_prompt.negative_prompt,
                stream_id=stream_id,
                source_image_bytes_list=source_images,
                source_image_urls=source_image_urls,
                matched_message_id=matched_message_id,
                user_id=user_id,
                group_id=group_id,
                platform_name=platform,
                notify_start=True,
            )
        except Exception as exc:
            self.ctx.logger.error("/绘图 风格命令启动失败: %s", exc, exc_info=True)
            await self._send_draw_failure_notice(
                reason=outward_error(self, exc),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "风格化绘图命令执行失败", 1

        return True, f"风格化绘图任务已提交：{result.get('task_id', '')}", 2
