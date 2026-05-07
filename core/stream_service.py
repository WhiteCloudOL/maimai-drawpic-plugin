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
            return str(stream.get("session_id") or "").strip()
        return str(getattr(stream, "session_id", "") or "").strip()

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

    async def _scan_streams_for_session_id(
        self,
        *,
        user_id: str,
        group_id: str,
        platform: str,
    ) -> str:
        """通过聊天流列表兜底扫描 session_id。"""

        stream_candidates: Any
        try:
            if group_id:
                stream_candidates = await self.ctx.chat.get_group_streams(platform=platform)
                self.ctx.logger.info("开始扫描群聊流: platform=%s", platform)
            elif user_id:
                stream_candidates = await self.ctx.chat.get_private_streams(platform=platform)
                self.ctx.logger.info("开始扫描私聊流: platform=%s", platform)
            else:
                stream_candidates = await self.ctx.chat.get_all_streams(platform=platform)
                self.ctx.logger.info("开始扫描全部聊天流: platform=%s", platform)
        except Exception as exc:
            self.ctx.logger.warning("扫描聊天流列表失败: %s", exc)
            return ""

        stream_candidates = self._unwrap_stream_list_result(stream_candidates)
        if not isinstance(stream_candidates, list):
            self.ctx.logger.warning("聊天流列表返回格式不正确: %s", type(stream_candidates).__name__)
            return ""

        for stream in stream_candidates:
            session_id = self._extract_session_id_from_stream(stream)
            candidate_user_id = self._extract_user_id_from_stream(stream)
            candidate_group_id = self._extract_group_id_from_stream(stream)
            if group_id and candidate_group_id == group_id and session_id:
                self.ctx.logger.info(
                    "通过群聊流扫描匹配到活跃聊天流: group_id=%s session_id=%s",
                    group_id,
                    session_id,
                )
                return session_id
            if user_id and candidate_user_id == user_id and session_id:
                self.ctx.logger.info(
                    "通过私聊流扫描匹配到活跃聊天流: user_id=%s session_id=%s",
                    user_id,
                    session_id,
                )
                return session_id

        self.ctx.logger.warning(
            "扫描聊天流列表后仍未匹配到活跃聊天流: user_id=%s group_id=%s platform=%s",
            user_id,
            group_id,
            platform,
        )
        return ""

    async def resolve_live_stream_id(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> str:
        """尽量把当前上下文中的标识解析为可发送消息的活跃 session_id。"""

        normalized_stream_id = stream_id.strip()
        normalized_user_id = user_id.strip()
        normalized_group_id = group_id.strip()
        normalized_platform = platform.strip() or "qq"
        self.ctx.logger.info(
            "开始解析活跃聊天流: stream_id=%s user_id=%s group_id=%s platform=%s",
            normalized_stream_id,
            normalized_user_id,
            normalized_group_id,
            normalized_platform,
        )

        if normalized_group_id:
            try:
                stream = await self.ctx.chat.get_stream_by_group_id(
                    group_id=normalized_group_id,
                    platform=normalized_platform,
                )
                self.ctx.logger.info("group_id 查询结果: %s", stream)
                session_id = self._extract_session_id_from_stream(stream)
                if session_id:
                    self.ctx.logger.info(
                        "通过 group_id 解析到活跃聊天流: group_id=%s session_id=%s",
                        normalized_group_id,
                        session_id,
                    )
                    return session_id
            except Exception as exc:
                self.ctx.logger.warning("通过 group_id 解析聊天流失败，将回退到原始 stream_id: %s", exc)

        if normalized_user_id:
            try:
                stream = await self.ctx.chat.get_stream_by_user_id(
                    user_id=normalized_user_id,
                    platform=normalized_platform,
                )
                self.ctx.logger.info("user_id 查询结果: %s", stream)
                session_id = self._extract_session_id_from_stream(stream)
                if session_id:
                    self.ctx.logger.info(
                        "通过 user_id 解析到活跃聊天流: user_id=%s session_id=%s",
                        normalized_user_id,
                        session_id,
                    )
                    return session_id
            except Exception as exc:
                self.ctx.logger.warning("通过 user_id 解析聊天流失败，将回退到原始 stream_id: %s", exc)

        scanned_session_id = await self._scan_streams_for_session_id(
            user_id=normalized_user_id,
            group_id=normalized_group_id,
            platform=normalized_platform,
        )
        if scanned_session_id:
            return scanned_session_id

        if not normalized_stream_id:
            self.ctx.logger.warning("解析活跃聊天流失败，且原始 stream_id 为空")
            return ""

        if normalized_stream_id.isdigit():
            self.ctx.logger.warning(
                "未解析到活跃 session_id，原始 stream_id 看起来像平台 ID，将继续尝试直接发送: %s",
                normalized_stream_id,
            )
        else:
            self.ctx.logger.info("未解析到新的聊天流，回退使用原始 stream_id: %s", normalized_stream_id)
        return normalized_stream_id

    async def send_generated_images(
        self,
        stream_id: str,
        image_bytes_list: list[bytes],
    ) -> int:
        """将生成结果发送回当前会话。"""

        self.ctx.logger.info("准备发送生成图片: stream_id=%s count=%s", stream_id, len(image_bytes_list))
        sent_count = 0
        for index, image_bytes in enumerate(image_bytes_list, start=1):
            self.ctx.logger.info(
                "发送生成图片中: stream_id=%s index=%s bytes=%s",
                stream_id,
                index,
                len(image_bytes),
            )
            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            send_result = await self.ctx.send.image(image_base64, stream_id)
            if not send_result:
                raise RuntimeError(f"发送图片失败，目标聊天流不可用: {stream_id}")
            sent_count += 1
        self.ctx.logger.info("生成图片发送完成: stream_id=%s count=%s", stream_id, sent_count)
        return sent_count

    async def send_generated_images_with_fallback(
        self,
        stream_id: str,
        image_bytes_list: list[bytes],
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
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
            return await self.send_generated_images(resolved_stream_id, image_bytes_list)
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
            return await self.send_generated_images(fallback_stream_id, image_bytes_list)

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
