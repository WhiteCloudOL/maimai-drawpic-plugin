from typing import Dict, List
import asyncio
import base64

from .types import ChatStreamUnavailableError, ImageDeliveryUnconfirmedError


class ImageDeliveryMixin:
    """ImageDeliveryMixin 的独立绘图职责。"""

    async def send_generated_images(
        self,
        stream_id: str,
        image_bytes_list: List[bytes],
        *,
        sync_to_maisaka_history: bool = False,
        task_id: str = "",
    ) -> int:
        """将生成结果发送回当前会话。"""

        total = len(image_bytes_list)
        sent_count = 0
        # Host 在确认发送成功后负责历史同步，与图片发送共用一次调用。
        send_options: Dict[str, bool] = {"sync_to_maisaka_history": True} if sync_to_maisaka_history else {}
        for index, image_bytes in enumerate(image_bytes_list, start=1):
            image_base64 = await asyncio.to_thread(lambda raw=image_bytes: base64.b64encode(raw).decode("ascii"))
            self.ctx.logger.info(
                "正在发送绘图结果图片: task_id=%s stream_id=%s progress=%s/%s history_sync_requested=%s",
                task_id,
                stream_id,
                index,
                total,
                sync_to_maisaka_history,
            )
            try:
                send_result = await self.ctx.send.image(image_base64, stream_id, **send_options)
            except Exception as exc:
                self.ctx.logger.warning(
                    "调用平台适配器发送图片异常: task_id=%s stream_id=%s progress=%s/%s "
                    "history_sync_requested=%s error_type=%s error=%s",
                    task_id,
                    stream_id,
                    index,
                    total,
                    sync_to_maisaka_history,
                    type(exc).__name__,
                    exc,
                )
                raise ImageDeliveryUnconfirmedError(
                    f"平台适配器发送响应未确认（{type(exc).__name__}），图片可能已经送达，请先核对聊天记录: stream_id={stream_id}",
                    sent_count=sent_count,
                ) from exc
            if send_result is not True:
                self.ctx.logger.warning(
                    "平台未确认图片发送成功，投递结果未知: task_id=%s stream_id=%s progress=%s/%s "
                    "history_sync_requested=%s；"
                    "请检查平台适配器日志，避免盲目重试",
                    task_id,
                    stream_id,
                    index,
                    total,
                    sync_to_maisaka_history,
                )
                raise ImageDeliveryUnconfirmedError(
                    "图片发送未获得平台成功确认，可能是平台适配器返回失败或响应超时；"
                    "不能据此判定聊天流不可用，图片也可能已经送达: "
                    f"stream_id={stream_id}",
                    sent_count=sent_count,
                )
            sent_count += 1
        return sent_count

    async def send_generated_images_with_fallback(
        self,
        stream_id: str,
        image_bytes_list: List[bytes],
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
        task_id: str = "",
        provider: str = "",
        model: str = "",
        *,
        sync_to_maisaka_history: bool = False,
        task_type: str = "",
        source_image_count: int = 0,
    ) -> int:
        """发送前解析活跃聊天流；发送后的失败或异常均不触发重发。"""

        resolved_stream_id = await self.resolve_live_stream_id(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not resolved_stream_id:
            self.ctx.logger.warning(
                "未能解析到可用聊天流，无法发送绘图结果: original_stream_id=%s user_id=%s group_id=%s platform=%s",
                stream_id,
                user_id,
                group_id,
                platform,
            )
            raise ChatStreamUnavailableError(f"未能解析到可用聊天流，无法发送图片: original_stream_id={stream_id}")
        self.ctx.logger.debug(
            "绘图结果历史同步策略: task_id=%s task_type=%s provider=%s model=%s source_image_count=%s "
            "stream_id=%s history_sync_requested=%s image_count=%s",
            task_id, task_type, provider, model, source_image_count,
            resolved_stream_id, sync_to_maisaka_history, len(image_bytes_list),
        )
        sent_count = await self.send_generated_images(
            resolved_stream_id, image_bytes_list,
            sync_to_maisaka_history=sync_to_maisaka_history, task_id=task_id,
        )
        self.ctx.logger.info(
            "发送绘图结果成功: task_id=%s task_type=%s provider=%s model=%s source_image_count=%s "
            "original_stream_id=%s resolved_stream_id=%s platform=%s count=%s history_sync_requested=%s",
            task_id, task_type, provider, model, source_image_count,
            stream_id, resolved_stream_id, platform, sent_count, sync_to_maisaka_history,
        )
        return sent_count

    async def send_image_bytes_with_fallback(
        self,
        image_bytes: bytes,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> bool:
        """解析真实聊天流后发送一次；未确认不能作为换流重发的依据。"""

        resolved_stream_id = await self.resolve_live_stream_id(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not resolved_stream_id:
            self.ctx.logger.warning("未能解析到可用聊天流，无法发送图片回复")
            return False

        image_base64 = await asyncio.to_thread(lambda: base64.b64encode(image_bytes).decode("ascii"))
        send_result = await self.ctx.send.image(image_base64, resolved_stream_id)
        return send_result is True

    async def send_text_with_fallback(
        self,
        text: str,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> bool:
        """解析真实聊天流后发送一次，保留适配器的未确认结果。"""

        resolved_stream_id = await self.resolve_live_stream_id(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not resolved_stream_id:
            self.ctx.logger.warning("未能解析到可用聊天流，无法发送文本: %s", text)
            return False

        send_result = await self.ctx.send.text(text=text, stream_id=resolved_stream_id)
        return send_result is True
