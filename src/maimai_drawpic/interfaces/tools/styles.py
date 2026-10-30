"""tools/styles.py 的插件组件。"""

from maibot_sdk import Tool
from typing import Any

from ..chat.message_images import (
    SourceImageInput,
    collect_command_source_image_inputs,
    decode_image_base64,
    find_source_image_inputs,
)
from ...infrastructure.observability.redaction import outward_error
from .schemas import DRAW_STYLES_TOOL_PARAMETERS_SCHEMA, STYLED_DRAW_TOOL_PARAMETERS_SCHEMA


class StyleToolMixin:
    """tools/styles.py 对应的插件行为。"""

    @Tool(
        "draw_styles",
        description=(
            "列出插件配置中当前可用的全平台绘图风格。用户要求指定风格、询问风格列表或准备调用 styled_draw 时，"
            "必须先调用本工具，依据 style_details 中的 description 与用户需求做语义匹配，"
            "再从 styles 中选择精确名称。"
        ),
        parameters=DRAW_STYLES_TOOL_PARAMETERS_SCHEMA,
    )
    async def handle_draw_styles(self, **kwargs: Any) -> dict[str, Any]:
        """向模型提供配置热重载后的最新风格名称与描述。"""

        del kwargs
        resolver = self._require_style_prompt_resolver()
        style_details = resolver.get_style_details()
        styles = [detail.name for detail in style_details]
        return {
            "success": True,
            "message": ("可用绘图风格：" + ("、".join(styles) if styles else "未配置；请改用普通 draw/edit_image")),
            "styles": styles,
            "style_details": [
                {
                    "name": detail.name,
                    "description": detail.description,
                }
                for detail in style_details
            ],
            "default_style": resolver.config.default_style.strip(),
        }

    @Tool(
        "styled_draw",
        description=(
            "使用插件配置的全平台风格提示词模板执行文生图或图生图。"
            "有风格需求时必须先调用 draw_styles，依据 style_details.description 与用户需求做语义匹配，"
            "再把精确名称填入 style。"
            "有真实源图片时自动图生图；没有源图片时文生图。style 不填时保持普通 draw/edit_image 行为。"
        ),
        parameters=STYLED_DRAW_TOOL_PARAMETERS_SCHEMA,
    )
    async def handle_styled_draw(
        self,
        prompt: str = "",
        style: str = "",
        negative_prompt: str = "",
        source_message_id: str = "",
        source_image_base64: str = "",
        user_id: str = "",
        **kwargs: Any,
    ) -> dict[str, Any]:
        """使用全平台风格模板创建或编辑图片。"""

        runtime_context: dict[str, str] = {}
        try:
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
                raise ValueError("当前聊天流不可用，无法回传图片")

            resolved_prompt = self._require_style_prompt_resolver().resolve(
                style_name=style,
                user_prompt=prompt,
                user_negative_prompt=negative_prompt,
            )
            current_message = kwargs.get("message")
            lookup_stream_ids = self._build_image_lookup_stream_ids(
                runtime_context["stream_id"],
                message=current_message,
            )
            source_image_inputs: list[SourceImageInput] = []
            matched_message_id = ""
            if source_image_base64.strip() or source_message_id.strip():
                source_image_inputs, matched_message_id = await find_source_image_inputs(
                    self.ctx,
                    lookup_stream_ids,
                    source_message_id=source_message_id,
                    source_image_base64=source_image_base64,
                    current_message=current_message if isinstance(current_message, dict) else None,
                )
            elif isinstance(current_message, dict):
                source_image_inputs = await collect_command_source_image_inputs(
                    self.ctx,
                    lookup_stream_ids,
                    current_message,
                )
                if source_image_inputs:
                    matched_message_id = str(current_message.get("message_id") or "").strip()

            if not resolved_prompt.positive_prompt and not source_image_inputs:
                raise ValueError("文生图提示词不能为空")
            source_image_bytes_list = [decode_image_base64(image.base64_data) for image in source_image_inputs]
            source_image_urls = [image.url for image in source_image_inputs]
            return await self._start_background_image_request(
                defer_prompt_review=True,
                prompt=resolved_prompt.positive_prompt,
                request_negative_prompt=resolved_prompt.negative_prompt,
                stream_id=runtime_context["stream_id"],
                source_image_bytes_list=source_image_bytes_list,
                source_image_urls=source_image_urls,
                matched_message_id=matched_message_id,
                user_id=runtime_context["user_id"],
                group_id=runtime_context["group_id"],
                platform_name=runtime_context["platform"],
                notify_start=True,
            )
        except Exception as exc:
            reason = outward_error(self, exc)
            self.ctx.logger.error("启动风格化绘图失败: %s", exc, exc_info=True)
            if runtime_context.get("stream_id"):
                await self._send_draw_failure_notice(
                    reason=reason,
                    stream_id=runtime_context["stream_id"],
                    user_id=runtime_context["user_id"],
                    group_id=runtime_context["group_id"],
                    platform=runtime_context["platform"],
                )
            return {"success": False, "message": reason}
