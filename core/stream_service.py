from typing import Any

import base64


class ChatStreamService:
    """负责聊天流解析与消息回发。"""

    def __init__(self, ctx: Any):
        self.ctx = ctx

    @staticmethod
    def _unwrap_stream_result(stream: Any) -> Any:
        """解包聊天流查询结果，兼容 SDK 的 success/result/stream 包装。"""

        current = stream
        for _ in range(4):
            if not isinstance(current, dict):
                return current
            if "stream" in current:
                current = current["stream"]
                continue
            if "result" in current:
                current = current["result"]
                continue
            return current
        return current

    @staticmethod
    def _unwrap_stream_list_result(streams: Any) -> Any:
        """解包聊天流列表查询结果，兼容 SDK 的 success/result/streams 包装。"""

        current = streams
        for _ in range(4):
            if not isinstance(current, dict):
                return current
            if "streams" in current:
                current = current["streams"]
                continue
            if "result" in current:
                current = current["result"]
                continue
            return current
        return current

    @classmethod
    def _extract_session_id_from_stream(cls, stream: Any) -> str:
        """从聊天流对象或字典中提取 session_id。"""

        stream = cls._unwrap_stream_result(stream)
        if isinstance(stream, dict):
            return str(stream.get("session_id") or stream.get("stream_id") or "").strip()
        return str(getattr(stream, "session_id", "") or getattr(stream, "stream_id", "") or "").strip()

    @classmethod
    def _extract_user_id_from_stream(cls, stream: Any) -> str:
        """从聊天流对象或字典中提取 user_id。"""

        stream = cls._unwrap_stream_result(stream)
        if isinstance(stream, dict):
            user_info = stream.get("user_info")
            if isinstance(user_info, dict):
                return str(user_info.get("user_id") or "").strip()
            return str(stream.get("user_id") or "").strip()

        user_info = getattr(stream, "user_info", None)
        if user_info is not None:
            return str(getattr(user_info, "user_id", "") or "").strip()
        return str(getattr(stream, "user_id", "") or "").strip()

    @classmethod
    def _extract_group_id_from_stream(cls, stream: Any) -> str:
        """从聊天流对象或字典中提取 group_id。"""

        stream = cls._unwrap_stream_result(stream)
        if isinstance(stream, dict):
            group_info = stream.get("group_info")
            if isinstance(group_info, dict):
                return str(group_info.get("group_id") or "").strip()
            return str(stream.get("group_id") or "").strip()

        group_info = getattr(stream, "group_info", None)
        if group_info is not None:
            return str(getattr(group_info, "group_id", "") or "").strip()
        return str(getattr(stream, "group_id", "") or "").strip()

    @staticmethod
    def _is_qq_platform(platform: str) -> bool:
        """判断当前平台是否按 QQ 数字 ID 解析私聊目标。"""

        return platform.strip().lower() in {"qq", "qqguild"}

    @classmethod
    def _is_usable_private_target_id(cls, target_id: str, platform: str) -> bool:
        """判断目标值是否适合作为私聊平台 ID。"""

        normalized_target_id = target_id.strip()
        if not normalized_target_id:
            return False
        if cls._is_qq_platform(platform):
            return normalized_target_id.isdigit()
        return True

    @classmethod
    def _extract_context_from_stream(cls, stream: Any) -> dict[str, str]:
        """从 SDK 聊天流结果提取插件需要的聊天上下文。"""

        unwrapped_stream = cls._unwrap_stream_result(stream)
        session_id = cls._extract_session_id_from_stream(unwrapped_stream)
        if not session_id:
            return {}
        if isinstance(unwrapped_stream, dict):
            platform = str(unwrapped_stream.get("platform") or "").strip()
        else:
            platform = str(getattr(unwrapped_stream, "platform", "") or "").strip()
        return {
            "stream_id": session_id,
            "user_id": cls._extract_user_id_from_stream(unwrapped_stream),
            "group_id": cls._extract_group_id_from_stream(unwrapped_stream),
            "platform": platform,
        }

    async def _resolve_target_context_with_sdk(
        self,
        *,
        platform: str,
        target_id: str,
        chat_type: str,
    ) -> dict[str, str]:
        """通过 SDK 聊天流能力按平台目标解析真实聊天流。"""

        try:
            if chat_type == "group":
                stream = await self.ctx.chat.get_stream_by_group_id(
                    group_id=target_id,
                    platform=platform,
                )
            else:
                stream = await self.ctx.chat.get_stream_by_user_id(
                    user_id=target_id,
                    platform=platform,
                )
        except Exception as exc:
            self.ctx.logger.warning(
                "通过 SDK 解析聊天流失败: platform=%s target_id=%s chat_type=%s error=%s",
                platform,
                target_id,
                chat_type,
                exc,
            )
            return {}

        return self._extract_context_from_stream(stream)

    async def _open_target_context_with_sdk(
        self,
        *,
        platform: str,
        target_id: str,
        chat_type: str,
    ) -> dict[str, str]:
        """通过 SDK 打开目标聊天流，交给宿主解析真实 session_id。"""

        open_session = getattr(self.ctx.chat, "open_session", None)
        if open_session is None:
            return {}

        try:
            if chat_type == "group":
                stream = await open_session(
                    platform=platform,
                    chat_type="group",
                    group_id=target_id,
                )
            else:
                stream = await open_session(
                    platform=platform,
                    chat_type="private",
                    user_id=target_id,
                )
        except Exception as exc:
            self.ctx.logger.warning(
                "通过 SDK 打开聊天流失败: platform=%s target_id=%s chat_type=%s error=%s",
                platform,
                target_id,
                chat_type,
                exc,
            )
            return {}

        return self._extract_context_from_stream(stream)

    async def _scan_streams_for_context(
        self,
        *,
        session_id: str = "",
        user_id: str,
        group_id: str,
        platform: str,
    ) -> dict[str, str]:
        """通过聊天流列表兜底扫描真实聊天流上下文。"""

        stream_candidates: Any
        try:
            if session_id:
                stream_candidates = await self.ctx.chat.get_all_streams(platform=platform)
            elif group_id:
                stream_candidates = await self.ctx.chat.get_group_streams(platform=platform)
            elif user_id:
                stream_candidates = await self.ctx.chat.get_private_streams(platform=platform)
            else:
                stream_candidates = await self.ctx.chat.get_all_streams(platform=platform)
        except Exception as exc:
            self.ctx.logger.warning("扫描聊天流列表失败: %s", exc)
            return {}

        stream_candidates = self._unwrap_stream_list_result(stream_candidates)
        if not isinstance(stream_candidates, list):
            self.ctx.logger.warning("聊天流列表返回格式不正确: %s", type(stream_candidates).__name__)
            return {}

        for stream in stream_candidates:
            context = self._extract_context_from_stream(stream)
            candidate_session_id = context.get("stream_id", "")
            candidate_user_id = context.get("user_id", "")
            candidate_group_id = context.get("group_id", "")
            if session_id and candidate_session_id == session_id:
                return context
            if group_id and candidate_group_id == group_id and candidate_session_id:
                return context
            if user_id and candidate_user_id == user_id and candidate_session_id:
                return context

        self.ctx.logger.warning(
            "扫描聊天流列表后仍未匹配到活跃聊天流: session_id=%s user_id=%s group_id=%s platform=%s",
            session_id,
            user_id,
            group_id,
            platform,
        )
        return {}

    async def _scan_streams_for_session_id(
        self,
        *,
        session_id: str = "",
        user_id: str,
        group_id: str,
        platform: str,
    ) -> str:
        """通过聊天流列表兜底扫描 session_id。"""

        context = await self._scan_streams_for_context(
            session_id=session_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if context:
            return str(context.get("stream_id") or "").strip()
        return ""

    @staticmethod
    def _merge_context(
        context: dict[str, str],
        *,
        user_id: str,
        group_id: str,
        platform: str,
    ) -> dict[str, str]:
        """补齐解析结果中的上下文字段。"""

        if not context:
            return {}
        return {
            "stream_id": str(context.get("stream_id") or "").strip(),
            "user_id": str(context.get("user_id") or "").strip() or user_id,
            "group_id": str(context.get("group_id") or "").strip() or group_id,
            "platform": str(context.get("platform") or "").strip() or platform,
        }

    async def _resolve_context_by_target(
        self,
        *,
        platform: str,
        target_id: str,
        chat_type: str,
        user_id: str,
        group_id: str,
    ) -> dict[str, str]:
        """按平台目标解析真实聊天流上下文。"""

        context = await self._resolve_target_context_with_sdk(
            platform=platform,
            target_id=target_id,
            chat_type=chat_type,
        )
        if context:
            return self._merge_context(context, user_id=user_id, group_id=group_id, platform=platform)

        scanned_context = await self._scan_streams_for_context(
            user_id=target_id if chat_type == "private" else "",
            group_id=target_id if chat_type == "group" else "",
            platform=platform,
        )
        if scanned_context:
            return self._merge_context(scanned_context, user_id=user_id, group_id=group_id, platform=platform)

        context = await self._open_target_context_with_sdk(
            platform=platform,
            target_id=target_id,
            chat_type=chat_type,
        )
        if context:
            return self._merge_context(context, user_id=user_id, group_id=group_id, platform=platform)
        return {}

    async def resolve_live_stream_context(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> dict[str, str]:
        """尽量把当前上下文解析为可发送消息的真实聊天流上下文。"""

        normalized_stream_id = stream_id.strip()
        normalized_user_id = user_id.strip()
        normalized_group_id = group_id.strip()
        normalized_platform = platform.strip() or "qq"

        if normalized_stream_id:
            context = await self._scan_streams_for_context(
                session_id=normalized_stream_id,
                user_id="",
                group_id="",
                platform=normalized_platform,
            )
            if context:
                return self._merge_context(
                    context,
                    user_id=normalized_user_id,
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )

        if normalized_group_id:
            context = await self._resolve_context_by_target(
                platform=normalized_platform,
                target_id=normalized_group_id,
                chat_type="group",
                user_id="",
                group_id=normalized_group_id,
            )
            if context:
                return context

        private_target_ids: list[str] = []
        if not normalized_group_id:
            if self._is_usable_private_target_id(normalized_user_id, normalized_platform):
                private_target_ids.append(normalized_user_id)
            if (
                normalized_stream_id
                and normalized_stream_id not in private_target_ids
                and self._is_usable_private_target_id(normalized_stream_id, normalized_platform)
            ):
                private_target_ids.append(normalized_stream_id)

        for private_target_id in private_target_ids:
            context = await self._resolve_context_by_target(
                platform=normalized_platform,
                target_id=private_target_id,
                chat_type="private",
                user_id=private_target_id,
                group_id="",
            )
            if context:
                return context

        if not normalized_stream_id:
            self.ctx.logger.warning("解析活跃聊天流失败，且原始 stream_id 为空")
            return {}

        self.ctx.logger.warning(
            "未解析到真实 session_id，已拒绝直接使用原始 stream_id 发送: %s",
            normalized_stream_id,
        )
        return {}

    async def resolve_live_stream_id(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> str:
        """尽量把当前上下文中的标识解析为可发送消息的活跃 session_id。"""

        context = await self.resolve_live_stream_context(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        return str(context.get("stream_id") or "").strip()

    async def send_generated_images(
        self,
        stream_id: str,
        image_bytes_list: list[bytes],
    ) -> int:
        """将生成结果发送回当前会话。"""

        total = len(image_bytes_list)
        sent_count = 0
        for index, image_bytes in enumerate(image_bytes_list, start=1):
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            self.ctx.logger.info(
                "正在发送绘图结果图片: stream_id=%s progress=%s/%s",
                stream_id,
                index,
                total,
            )
            send_result = await self.ctx.send.image(image_base64, stream_id)
            if not send_result:
                raise RuntimeError(f"发送图片失败，目标聊天流不可用: {stream_id}")
            sent_count += 1
        return sent_count

    async def send_generated_images_with_fallback(
        self,
        stream_id: str,
        image_bytes_list: list[bytes],
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
        task_id: str = "",
        provider: str = "",
        model: str = "",
    ) -> int:
        """发送图片，并在必要时重新解析活跃聊天流后重试。"""

        resolved_stream_id = await self.resolve_live_stream_id(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not resolved_stream_id:
            raise RuntimeError("未能解析到可用聊天流，无法发送图片")
        try:
            sent_count = await self.send_generated_images(resolved_stream_id, image_bytes_list)
            self.ctx.logger.info(
                "发送绘图结果成功: task_id=%s provider=%s model=%s original_stream_id=%s resolved_stream_id=%s platform=%s count=%s",
                task_id,
                provider,
                model,
                stream_id,
                resolved_stream_id,
                platform,
                sent_count,
            )
            return sent_count
        except Exception as first_error:
            self.ctx.logger.warning(
                "首次发送图片失败，尝试重新解析聊天流: original_stream_id=%s resolved_stream_id=%s error=%s",
                stream_id,
                resolved_stream_id,
                first_error,
            )
            fallback_stream_id = await self.resolve_live_stream_id(
                stream_id="",
                user_id=user_id,
                group_id=group_id,
                platform=platform,
            )
            if not fallback_stream_id or fallback_stream_id == resolved_stream_id:
                raise
            self.ctx.logger.info(
                "使用重新解析的聊天流重试发送图片: original_stream_id=%s fallback_stream_id=%s",
                stream_id,
                fallback_stream_id,
            )
            sent_count = await self.send_generated_images(fallback_stream_id, image_bytes_list)
            self.ctx.logger.info(
                "发送绘图结果成功: task_id=%s provider=%s model=%s original_stream_id=%s resolved_stream_id=%s platform=%s count=%s",
                task_id,
                provider,
                model,
                stream_id,
                fallback_stream_id,
                platform,
                sent_count,
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
        """发送单张图片，并在必要时重新解析活跃聊天流后重试。"""

        resolved_stream_id = await self.resolve_live_stream_id(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not resolved_stream_id:
            self.ctx.logger.warning("未能解析到可用聊天流，无法发送图片回复")
            return False

        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        send_result = await self.ctx.send.image(image_base64, resolved_stream_id)
        if send_result:
            return True

        self.ctx.logger.warning(
            "首次发送图片回复失败，尝试重新解析聊天流: original_stream_id=%s resolved_stream_id=%s",
            stream_id,
            resolved_stream_id,
        )
        fallback_stream_id = await self.resolve_live_stream_id(
            stream_id="",
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not fallback_stream_id or fallback_stream_id == resolved_stream_id:
            return False
        return bool(await self.ctx.send.image(image_base64, fallback_stream_id))

    async def send_text_with_fallback(
        self,
        text: str,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> bool:
        """发送文本，并在必要时重新解析活跃聊天流后重试。"""

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
        if send_result:
            return True

        self.ctx.logger.warning(
            "首次发送文本失败，尝试重新解析聊天流: original_stream_id=%s resolved_stream_id=%s",
            stream_id,
            resolved_stream_id,
        )
        fallback_stream_id = await self.resolve_live_stream_id(
            stream_id="",
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )
        if not fallback_stream_id or fallback_stream_id == resolved_stream_id:
            return False
        return await self.ctx.send.text(text, fallback_stream_id)
