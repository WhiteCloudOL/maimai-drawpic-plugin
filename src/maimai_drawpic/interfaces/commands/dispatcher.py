"""commands/dispatcher.py 的插件组件。"""

from ...infrastructure.observability.redaction import outward_error

from maibot_sdk import Command
from typing import Any
import asyncio

from ..chat.texts import (
    build_command_usage_text,
    build_compatible_mode_text,
    build_model_text,
    build_session_status_text,
    format_openai_mode,
)
from ...domain.models.openai_profiles import OPENAI_COMPATIBILITY_MODES, normalize_openai_mode


class CommandMixin:
    """commands/dispatcher.py 对应的插件行为。"""

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
            "风格": "style",
            "style": "style",
            "nai": "novelai",
            "novelai": "novelai",
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

            models = self._require_router().get_all_models()
            if model_name.isascii() and model_name.isdecimal():
                index = int(model_name) if len(model_name) <= 10 else 0
                model_name = models[index - 1] if 1 <= index <= len(models) else ""
            if model_name not in models:
                await self._send_command_reply(
                    title="模型不存在",
                    body="请输入列表中的完整 平台名称/模型名称，或从 1 开始的有效索引；不支持单独填写模型名。\n\n"
                    + build_model_text(self._require_router(), session_preference),
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "模型不存在", 1

            next_preference = await asyncio.to_thread(
                self._set_session_preference,
                normalized_stream_id,
                normalized_user_id,
                normalized_group_id,
                normalized_platform,
                model=model_name,
            )
            await self._send_command_reply(
                title="首选模型已设置",
                body=f"当前会话首选绘图模型：{next_preference['model']}",
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return True, "已设置首选绘图模型", 2

        if normalized_command == "compatible-mode":
            compatibility_mode = normalize_openai_mode(rest_payload)
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
            elif compatibility_mode not in OPENAI_COMPATIBILITY_MODES:
                await self._send_command_reply(
                    title="兼容模式无效",
                    body=build_compatible_mode_text(session_preference["openai_compatibility_mode"]),
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "兼容模式无效", 1

            next_preference = await asyncio.to_thread(
                self._set_session_preference,
                normalized_stream_id,
                normalized_user_id,
                normalized_group_id,
                normalized_platform,
                openai_compatibility_mode=compatibility_mode,
            )
            mode_label = format_openai_mode(next_preference["openai_compatibility_mode"])
            await self._send_command_reply(
                title="兼容模式已切换",
                body=(f"当前会话 OpenAI 兼容模式：{mode_label or '跟随模型配置'}\n该设置仅对 OpenAI 提供商生效。"),
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )
            return True, "已切换 OpenAI 兼容模式", 2

        if normalized_command == "style":
            return await self._handle_style_command(
                rest_payload=rest_payload,
                message=kwargs.get("message"),
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )

        if normalized_command == "novelai":
            return await self._handle_novelai_command(
                rest_payload=rest_payload,
                message=kwargs.get("message"),
                session_preference=session_preference,
                stream_id=normalized_stream_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform=normalized_platform,
            )

        if normalized_command == "draw_text":
            prompt, negative_prompt = self._split_negative_prompt(rest_payload)
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
                resolved_model = self._require_draw_service().resolve_model_name(session_preference["model"])
                await asyncio.to_thread(self._require_router().validate_forced_command_task, resolved_model, "draw")
            except (OSError, ValueError) as exc:
                self.ctx.logger.warning("/绘图 文生图命令配置校验失败: error=%s", exc)
                await self._send_command_reply(
                    title="文生图配置错误",
                    body=outward_error(self, exc),
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                return False, "文生图配置错误", 1

            try:
                try:
                    (
                        source_image_inputs,
                        lookup_stream_ids,
                        matched_message_id,
                    ) = await self._collect_forced_command_source_images(
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

                if source_image_inputs:
                    self.ctx.logger.info(
                        "/绘图 文生图检测到源图，拒绝强制文生图: stream_id=%s lookup_stream_ids=%s source_image_count=%s message_id=%s",
                        normalized_stream_id,
                        lookup_stream_ids,
                        len(source_image_inputs),
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
                    defer_prompt_review=True,
                    prompt=prompt,
                    request_negative_prompt=negative_prompt,
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform_name=normalized_platform,
                )
            except Exception as exc:
                self.ctx.logger.error("/绘图 文生图命令启动失败: %s", exc, exc_info=True)
                await self._send_command_reply(
                    title="绘图请求未能启动",
                    body=outward_error(self, exc),
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
