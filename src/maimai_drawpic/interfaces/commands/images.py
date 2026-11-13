"""commands/images.py 的插件组件。"""

from typing import Any
import asyncio
import re

from ...application.access import ChatAccessDenied
from ...infrastructure.observability.redaction import outward_error
from ..chat.message_images import SourceImageInput, collect_command_source_image_inputs, decode_image_base64


class ImageCommandMixin:
    """commands/images.py 对应的插件行为。"""

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

        prompt, negative_prompt = self._split_negative_prompt(rest_payload)
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
        # 火山引擎使用统一模型列表，按模型名能力标记和全局黑名单提前校验。
        check_model = resolved_model
        if provider_name == "volcengine":
            try:
                check_model = router.resolve_volcengine_model_for_task(resolved_model, "edit_image")
            except ValueError:
                check_model = resolved_model
        capability = router.evaluate_model_task_capability(
            check_model,
            "edit_image",
        )
        if not capability.allowed:
            self.ctx.logger.warning(
                "/绘图 图生图拒绝不支持的模型任务: model=%s provider=%s "
                "task_type=edit_image capability_source=%s reason=%s",
                check_model,
                provider_name,
                capability.source,
                capability.reason,
            )
            await self._send_command_reply(
                title="当前模型不支持图生图",
                body=(
                    f"{capability.reason}。\n"
                    "请先用 /绘图 模型 <平台名称/模型名称或索引> 设置支持图生图的首选模型，或改用 /绘图 文生图 <prompt>。"
                ),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "当前模型不支持图生图", 1

        try:
            await asyncio.to_thread(router.validate_forced_command_task, resolved_model, "edit_image")
        except (OSError, ValueError) as exc:
            self.ctx.logger.warning("/绘图 图生图命令配置校验失败: model=%s error=%s", resolved_model, exc)
            await self._send_command_reply(
                title="图生图配置错误",
                body=outward_error(self, exc),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "图生图配置错误", 1

        try:
            (
                source_image_inputs,
                lookup_stream_ids,
                matched_message_id,
            ) = await self._collect_forced_command_source_images(
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
                body=outward_error(self, exc),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "读取源图片失败", 1

        if not source_image_inputs:
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
            source_image_bytes_list = [decode_image_base64(image.base64_data) for image in source_image_inputs]
            source_image_urls = [image.url for image in source_image_inputs]
            self.ctx.logger.info(
                "/绘图 图生图已收集源图: stream_id=%s lookup_stream_ids=%s source_image_count=%s message_id=%s",
                stream_id,
                lookup_stream_ids,
                len(source_image_bytes_list),
                matched_message_id,
            )
            start_result = await self._start_background_image_request(
                defer_prompt_review=True,
                use_reference_features=True,
                reference_options={"user_request": "/绘图 图生图 " + rest_payload},
                reference_task_type="edit_image",
                prompt=prompt,
                stream_id=stream_id,
                requested_model=resolved_model,
                requested_openai_compatibility_mode=session_preference["openai_compatibility_mode"],
                request_negative_prompt=negative_prompt,
                source_image_bytes_list=source_image_bytes_list,
                source_image_urls=source_image_urls,
                matched_message_id=matched_message_id,
                user_id=user_id,
                group_id=group_id,
                platform_name=platform,
                notify_start=True,
            )
        except ChatAccessDenied:
            raise
        except PermissionError as exc:
            await self._send_command_reply(
                title="绘图次数不足",
                body=f"{outward_error(self, exc)}。请联系管理员调整次数后再使用图生图。",
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
                body=outward_error(self, exc),
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
    ) -> tuple[list[SourceImageInput], list[str], str]:
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
        source_image_inputs = await collect_command_source_image_inputs(
            self.ctx,
            lookup_stream_ids,
            command_message,
        )
        matched_message_id = str(command_message.get("message_id") or "").strip()
        return source_image_inputs, lookup_stream_ids, matched_message_id

    @staticmethod
    def _split_negative_prompt(prompt: str) -> tuple[str, str]:
        """拆分指令中的正向提示词与可选反向提示词。"""

        match = re.search(r"\s+--(?:反向|negative)\s+", prompt, flags=re.IGNORECASE)
        if match is None:
            return prompt.strip(), ""
        return prompt[: match.start()].strip(), prompt[match.end() :].strip()

    async def _collect_optional_command_source_images(
        self,
        *,
        message: Any,
        stream_id: str,
        user_id: str,
        group_id: str,
        platform: str,
    ) -> tuple[list[bytes], list[str], str]:
        """仅收集当前指令直接携带或明确引用的图片，不扫描无关历史图片。"""

        source_image_inputs, _, matched_message_id = await self._collect_forced_command_source_images(
            message=message,
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        return (
            [decode_image_base64(image.base64_data) for image in source_image_inputs],
            [image.url for image in source_image_inputs],
            matched_message_id,
        )
