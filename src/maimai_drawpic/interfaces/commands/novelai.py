"""commands/novelai.py 的插件组件。"""

from ...infrastructure.observability.redaction import outward_error

from typing import Any
import asyncio

from ..chat.texts import build_novelai_text


class NovelAICommandMixin:
    """commands/novelai.py 对应的插件行为。"""

    @staticmethod
    def _normalize_novelai_mode(mode: str) -> str:
        """归一化 NAI mode 的中英文名称。"""

        aliases = {
            "anime": "anime",
            "动漫": "anime",
            "动画": "anime",
            "furry": "furry",
            "兽人": "furry",
            "福瑞": "furry",
            "background": "background",
            "背景": "background",
        }
        return aliases.get(mode.strip().casefold(), "")

    async def _handle_novelai_command(
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
        """处理 NAI 专属模型、mode、画师标签、参数和绘图指令。"""

        router = self._require_router()
        first_word, remaining = self._split_command_payload(rest_payload)
        normalized_action = first_word.strip().casefold()
        if not first_word or normalized_action in {"帮助", "help", "状态", "status", "参数", "params"}:
            await self._send_command_reply(
                title="NovelAI 绘图",
                body=build_novelai_text(router, session_preference),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return True, "已显示 NovelAI 绘图状态", 2

        if normalized_action in {"模式", "mode", "风格", "style"}:
            mode_value = remaining.strip()
            if not mode_value:
                await self._send_command_reply(
                    title="NovelAI mode",
                    body=build_novelai_text(router, session_preference),
                    stream_id=stream_id,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform,
                )
                return True, "已显示 NovelAI mode", 2
            if not self._can_manage_session(user_id):
                await self._send_command_reply(
                    title="权限不足",
                    body="当前已启用权限管理，只有插件管理员可以切换会话级 NovelAI mode。",
                    stream_id=stream_id,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform,
                )
                return False, "权限不足", 1
            clear_aliases = {"默认", "跟随", "清空", "default", "unset", "clear"}
            novelai_mode = "" if mode_value.casefold() in clear_aliases else self._normalize_novelai_mode(mode_value)
            if not novelai_mode and mode_value.casefold() not in clear_aliases:
                await self._send_command_reply(
                    title="NovelAI mode 无效",
                    body=build_novelai_text(router, session_preference),
                    stream_id=stream_id,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform,
                )
                return False, "NovelAI mode 无效", 1
            next_preference = await asyncio.to_thread(
                self._set_session_preference,
                stream_id,
                user_id,
                group_id,
                platform,
                novelai_mode=novelai_mode,
            )
            effective_mode = next_preference["novelai_mode"] or self.config.novelai.default_mode
            await self._send_command_reply(
                title="NovelAI mode 已切换",
                body=f"当前会话 NAI mode：{effective_mode}",
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return True, "已切换 NovelAI mode", 2

        if normalized_action in {"画师", "artist", "artists"}:
            artist_tags = remaining.strip()
            if not artist_tags:
                await self._send_command_reply(
                    title="NovelAI 画师标签",
                    body=build_novelai_text(router, session_preference),
                    stream_id=stream_id,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform,
                )
                return True, "已显示 NovelAI 画师标签", 2
            if not self._can_manage_session(user_id):
                await self._send_command_reply(
                    title="权限不足",
                    body="当前已启用权限管理，只有插件管理员可以设置会话级 NovelAI 画师标签。",
                    stream_id=stream_id,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform,
                )
                return False, "权限不足", 1
            clear_aliases = {"默认", "跟随", "清空", "default", "unset", "clear"}
            session_artist_tags = "" if artist_tags.casefold() in clear_aliases else artist_tags
            next_preference = await asyncio.to_thread(
                self._set_session_preference,
                stream_id,
                user_id,
                group_id,
                platform,
                novelai_artist_tags=session_artist_tags,
            )
            effective_artist_tags = router.resolve_novelai_artist_tags(next_preference["novelai_artist_tags"])
            await self._send_command_reply(
                title="NovelAI 画师标签已设置",
                body=(
                    f"当前会话 NAI 画师标签：{effective_artist_tags or '未配置'}\n"
                    f"来源：{'会话设置' if next_preference['novelai_artist_tags'] else '插件默认配置'}"
                ),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return True, "已设置 NovelAI 画师标签", 2

        if normalized_action in {"模型", "model"}:
            model_name = remaining.strip()
            if not model_name:
                await self._send_command_reply(
                    title="NovelAI 模型",
                    body=build_novelai_text(router, session_preference),
                    stream_id=stream_id,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform,
                )
                return True, "已显示 NovelAI 模型", 2
            if not self._can_manage_session(user_id):
                await self._send_command_reply(
                    title="权限不足",
                    body="当前已启用权限管理，只有插件管理员可以设置会话级 NovelAI 模型。",
                    stream_id=stream_id,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform,
                )
                return False, "权限不足", 1
            if model_name not in router.get_novelai_models():
                await self._send_command_reply(
                    title="NovelAI 模型不存在",
                    body=build_novelai_text(router, session_preference),
                    stream_id=stream_id,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform,
                )
                return False, "NovelAI 模型不存在", 1
            implied_mode: str | None = None
            upstream_model = router.describe_model(model_name)["upstream_model"]
            if upstream_model == "nai-diffusion-furry-3":
                implied_mode = "furry"
            elif upstream_model == "nai-diffusion-3":
                implied_mode = "anime"
            await asyncio.to_thread(
                self._set_session_preference,
                stream_id,
                user_id,
                group_id,
                platform,
                model=model_name,
                novelai_mode=implied_mode,
            )
            await self._send_command_reply(
                title="NovelAI 模型已设置",
                body=f"当前会话首选绘图模型：novelai：{model_name}",
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return True, "已设置 NovelAI 模型", 2

        forced_task_type = "auto"
        requested_mode = session_preference.get("novelai_mode", "")
        prompt_payload = rest_payload
        if normalized_action in {"文生图", "绘制", "draw"}:
            forced_task_type = "draw"
            prompt_payload = remaining
        elif normalized_action in {"图生图", "编辑", "edit"}:
            forced_task_type = "edit_image"
            prompt_payload = remaining
        else:
            one_shot_mode = self._normalize_novelai_mode(first_word)
            if one_shot_mode and remaining:
                requested_mode = one_shot_mode
                prompt_payload = remaining

        positive_prompt, negative_prompt = self._split_negative_prompt(prompt_payload)
        selected_model = session_preference["model"]
        model = (
            selected_model
            if router.get_model_provider(selected_model) == "novelai"
            else router.get_default_novelai_model()
        )
        try:
            source_images: list[bytes] = []
            source_image_urls: list[str] = []
            matched_message_id = ""
            (
                source_images,
                source_image_urls,
                matched_message_id,
            ) = await self._collect_optional_command_source_images(
                message=message,
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            if forced_task_type == "draw" and source_images:
                raise ValueError("NAI 文生图不能附带或引用图片，请改用 /绘图 nai 图生图 <描述>")
            if forced_task_type == "edit_image" and not source_images:
                raise ValueError("NAI 图生图需要在同一条消息中附带或引用图片")
            if not positive_prompt and not source_images:
                raise ValueError("NAI 文生图提示词不能为空")
            result = await self._start_background_image_request(
                defer_prompt_review=True,
                prompt=positive_prompt,
                request_negative_prompt=negative_prompt,
                requested_model=model,
                requested_novelai_mode=requested_mode,
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
            self.ctx.logger.error("/绘图 nai 命令启动失败: %s", exc, exc_info=True)
            await self._send_draw_failure_notice(
                reason=outward_error(self, exc),
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            return False, "NovelAI 绘图命令执行失败", 1

        return True, f"NovelAI 绘图任务已提交：{result.get('task_id', '')}", 2
