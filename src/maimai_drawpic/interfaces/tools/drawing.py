"""tools/drawing.py 的插件组件。"""

from ...infrastructure.observability.redaction import outward_error

from maibot_sdk import Tool
from typing import Any

from ..chat.message_images import decode_image_base64, find_source_image_inputs
from .schemas import DRAW_TOOL_PARAMETERS_SCHEMA, EDIT_IMAGE_TOOL_PARAMETERS_SCHEMA


class DrawingToolMixin:
    """tools/drawing.py 对应的插件行为。"""

    @Tool(
        "draw",
        description=(
            "根据纯文本提示创建独立的后台绘图任务，并在完成后发送到当前聊天流；可选传入反向提示词。"
            "用户要求修改、编辑、重绘已有图片时不要调用本工具，应调用 edit_image"
        ),
        parameters=DRAW_TOOL_PARAMETERS_SCHEMA,
    )
    async def handle_draw(
        self,
        prompt: str,
        user_id: str = "",
        model: str = "",
        negative_prompt: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """创建图片。"""

        if not prompt.strip():
            await self._send_invocation_failure_notice(
                reason="提示词不能为空",
                kwargs=kwargs,
                user_id=user_id,
            )
            return {"success": False, "message": "提示词不能为空"}

        try:
            context = self._extract_invocation_context(kwargs=kwargs, llm_user_id=user_id)
            return await self._start_background_image_request(
                defer_prompt_review=True,
                prompt=prompt.strip(),
                stream_id=context["stream_id"],
                requested_model=model.strip(),
                request_negative_prompt=negative_prompt.strip(),
                user_id=context["user_id"],
                group_id=context["group_id"],
                platform_name=context["platform"],
            )
        except PermissionError as exc:
            reason = outward_error(self, exc)
            await self._send_invocation_failure_notice(reason=reason, kwargs=kwargs, user_id=user_id)
            return {
                "success": False,
                "message": reason,
            }
        except Exception as exc:
            reason = outward_error(self, exc)
            self.ctx.logger.error("启动后台创建图片失败: %s", exc, exc_info=True)
            await self._send_invocation_failure_notice(reason=reason, kwargs=kwargs, user_id=user_id)
            return {"success": False, "message": reason}

    @Tool(
        "edit_image",
        description=(
            "基于当前聊天中的真实图片执行图生图编辑；仅当用户明确要求修改、编辑、重绘已有图片时调用。"
            "如果用户回复/引用了一张图片，直接调用本工具，插件会从引用消息中提取真实图片。"
            "每次调用会创建独立后台任务；找不到真实图片或平台不支持图片编辑时返回原因，"
            "并按插件配置决定是否直接向聊天流发送失败通知"
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
        negative_prompt: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """编辑图片。"""

        if not prompt.strip():
            await self._send_invocation_failure_notice(
                reason="提示词不能为空",
                kwargs=kwargs,
                user_id=user_id,
            )
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
                await self._send_draw_failure_notice(
                    reason=f"指定模型不可用：{resolved_model}",
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=platform_name,
                )
                return {"success": False, "message": f"指定模型不可用：{resolved_model}"}
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
                    "edit_image 拒绝不支持的模型任务: model=%s provider=%s "
                    "task_type=edit_image capability_source=%s reason=%s",
                    check_model,
                    provider_name,
                    capability.source,
                    capability.reason,
                )
                await self._send_draw_failure_notice(
                    reason=capability.reason,
                    stream_id=normalized_stream_id,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=platform_name,
                )
                return {
                    "success": False,
                    "message": (
                        f"{capability.reason}，无法调用 edit_image 图生图。"
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
            source_image_inputs, matched_message_id = await find_source_image_inputs(
                self.ctx,
                lookup_stream_ids,
                source_message_id=source_message_id,
                source_image_base64=source_image_base64,
                current_message=current_message if isinstance(current_message, dict) else None,
            )
            source_image_bytes_list = [decode_image_base64(image.base64_data) for image in source_image_inputs]
            source_image_urls = [image.url for image in source_image_inputs]
            self.ctx.logger.info(
                "edit_image 已收集源图: stream_id=%s lookup_stream_ids=%s source_image_count=%s matched_message_id=%s",
                normalized_stream_id,
                lookup_stream_ids,
                len(source_image_bytes_list),
                matched_message_id,
            )
            return await self._start_background_image_request(
                defer_prompt_review=True,
                prompt=prompt.strip(),
                stream_id=normalized_stream_id,
                requested_model=resolved_model,
                requested_openai_compatibility_mode=resolved_openai_mode,
                request_negative_prompt=negative_prompt.strip(),
                source_image_bytes_list=source_image_bytes_list,
                source_image_urls=source_image_urls,
                matched_message_id=matched_message_id,
                user_id=normalized_user_id,
                group_id=normalized_group_id,
                platform_name=platform_name,
                notify_start=True,
            )
        except PermissionError as exc:
            reason = outward_error(self, exc)
            await self._send_invocation_failure_notice(reason=reason, kwargs=kwargs, user_id=user_id)
            return {
                "success": False,
                "message": reason,
            }
        except ValueError as exc:
            reason = outward_error(self, exc)
            await self._send_invocation_failure_notice(reason=reason, kwargs=kwargs, user_id=user_id)
            return {
                "success": False,
                "message": (
                    f"{reason}。无法调用 edit_image 图片编辑；请自然告知用户需要先发送一张真实图片，"
                    "或回复/指定包含图片的消息后再编辑。"
                ),
            }
        except Exception as exc:
            reason = outward_error(self, exc)
            self.ctx.logger.error("启动后台编辑图片失败: %s", exc, exc_info=True)
            await self._send_invocation_failure_notice(reason=reason, kwargs=kwargs, user_id=user_id)
            return {"success": False, "message": reason}
