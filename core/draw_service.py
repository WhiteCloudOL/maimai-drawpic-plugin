from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncio
import inspect
import re
import unicodedata

from .moderation import DrawpicModerationService
from .provider_router import ProviderRouter
from .stream_service import ChatStreamService
from .task_store import DrawTaskRecord, DrawTaskStore


class DrawService:
    """负责后台绘图执行、审核与任务状态管理。"""

    STATUS_RECHECK_INTERVAL_SECONDS = 20
    ENGLISH_PROMPT_REWRITE_PROMPT = (
        "你是图片生成提示词英文改写器，负责把用户提示词改写成可直接交给 NovelAI / Stable Diffusion / "
        "通用图片生成模型使用的英文提示词。\n"
        "要求：\n"
        "1. 把中文、日文、韩文等非英文文本全部翻译或转写为自然英文单词，不能保留原语言文字。\n"
        "2. 把中文标点、日文标点、全角标点和特殊连接符全部替换为英文半角标点，优先使用英文逗号分隔标签。\n"
        "3. 保留用户原意、角色名、构图、风格、画质、动作、服装、场景和数量关系；已有英文标签可自然整理。\n"
        "4. 不要补充安全审查、解释、标题、引号、Markdown 或多余说明。\n"
        "5. 只输出一行或多行英文提示词本身。\n"
        "\n"
        "用户提示词：\n"
        "{user_prompt}"
    )
    ENGLISH_PROMPT_REPAIR_PROMPT = (
        "下面的改写结果没有通过英文提示词校验。请重新输出 NovelAI / Stable Diffusion 友好的英文提示词。\n"
        "硬性要求：\n"
        "1. 只能使用 ASCII 范围内的英文单词、数字、空格和英文半角标点。\n"
        "2. 不能保留中文、日文、韩文、全角英文、全角数字、全角标点、表情符号或任何非 ASCII 字符。\n"
        "3. 优先用英文逗号分隔标签，只输出提示词本身。\n"
        "\n"
        "失败原因：{validation_error}\n"
        "原始提示词：\n"
        "{user_prompt}\n"
        "\n"
        "上次改写结果：\n"
        "{rewritten_prompt}"
    )
    PROMPT_REWRITE_ATTEMPTS = 3
    NON_ENGLISH_PROMPT_PATTERN = re.compile(r"[^\x00-\x7f]")
    PROMPT_PUNCTUATION_TRANSLATION = str.maketrans(
        {
            "，": ",",
            "。": ".",
            "？": "?",
            "！": "!",
            "；": ";",
            "：": ":",
            "、": ",",
            "（": "(",
            "）": ")",
            "【": "[",
            "】": "]",
            "《": "<",
            "》": ">",
            "“": '"',
            "”": '"',
            "‘": "'",
            "’": "'",
            "…": "...",
            "—": "-",
            "–": "-",
            "−": "-",
            "～": "~",
            "·": ",",
            "￥": "Yuan",
            "¥": "Yen",
            "「": '"',
            "」": '"',
            "『": '"',
            "』": '"',
            "〔": "[",
            "〕": "]",
            "〖": "[",
            "〗": "]",
        }
    )

    def __init__(
        self,
        *,
        ctx: Any,
        router: ProviderRouter,
        stream_service: ChatStreamService,
        moderation_service: DrawpicModerationService,
        task_store: DrawTaskStore,
    ) -> None:
        self.ctx = ctx
        self.router = router
        self.stream_service = stream_service
        self.moderation_service = moderation_service
        self.task_store = task_store
        self.background_tasks: set[asyncio.Task[Any]] = set()

    def resolve_request_timeout_seconds(self) -> int:
        """解析请求超时时间。"""

        return self.router.resolve_request_timeout_seconds()

    def resolve_model_name(self, model: str = "", allow_unknown_model: bool = False) -> str:
        """解析模型名称。"""

        return self.router.resolve_model_name(model, allow_unknown_model)

    async def send_text_with_fallback(
        self,
        text: str,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> bool:
        """发送文本。"""

        return await self.stream_service.send_text_with_fallback(
            text=text,
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )

    async def review_prompt_or_raise(self, prompt: str) -> None:
        """在提交绘图请求前审核提示词。"""

        if not self.moderation_service.is_prompt_review_enabled():
            return

        try:
            review_result = await self.moderation_service.review_prompt(prompt)
        except Exception as exc:
            self.ctx.logger.warning("提示词审核报错: %s", exc)
            raise
        if review_result.passed:
            self.ctx.logger.info("提示词审核通过")
        else:
            self.ctx.logger.info("提示词审核未通过")
        if not review_result.passed:
            reason_suffix = f"原因：{review_result.reason}" if review_result.reason else "原因：审核模型判定为不通过"
            raise ValueError(f"提示词审核未通过，已拒绝本次绘图请求。{reason_suffix}")

    async def rewrite_prompt_to_english_if_needed(
        self,
        prompt: str,
        provider_name: str,
        model: str,
    ) -> str:
        """按提供商配置把提示词改写为英文。"""

        if not self.router.should_rewrite_prompt_to_english(provider_name):
            return prompt

        rewritten_prompt = ""
        validation_error = ""
        for attempt_index in range(self.PROMPT_REWRITE_ATTEMPTS):
            rendered_prompt = (
                self.ENGLISH_PROMPT_REWRITE_PROMPT.format(user_prompt=prompt)
                if attempt_index == 0
                else self.ENGLISH_PROMPT_REPAIR_PROMPT.format(
                    validation_error=validation_error,
                    user_prompt=prompt,
                    rewritten_prompt=rewritten_prompt,
                )
            )
            response = await self.ctx.llm.generate(
                rendered_prompt,
                model="replyer",
                temperature=0.0,
                max_tokens=1024,
            )
            rewritten_prompt = self._normalize_rewritten_prompt(
                DrawpicModerationService._extract_llm_response(response)
            )
            validation_error = self._get_english_prompt_validation_error(rewritten_prompt)
            if not validation_error:
                self.ctx.logger.info(
                    "提示词英文改写完成: provider=%s model=%s original_len=%s rewritten_len=%s",
                    provider_name,
                    model,
                    len(prompt),
                    len(rewritten_prompt),
                )
                return rewritten_prompt

        raise RuntimeError(f"英文提示词改写失败：{validation_error or '改写结果为空'}")

    @classmethod
    def _normalize_rewritten_prompt(cls, prompt: str) -> str:
        """清理 LLM 可能包裹在结果外侧的格式符。"""

        normalized_prompt = prompt.strip()
        if normalized_prompt.startswith("```"):
            lines = normalized_prompt.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            normalized_prompt = "\n".join(lines).strip()
        if (
            len(normalized_prompt) >= 2
            and normalized_prompt[0] == normalized_prompt[-1]
            and normalized_prompt[0] in {'"', "'"}
        ):
            normalized_prompt = normalized_prompt[1:-1].strip()
        normalized_prompt = unicodedata.normalize("NFKC", normalized_prompt)
        normalized_prompt = normalized_prompt.translate(cls.PROMPT_PUNCTUATION_TRANSLATION)
        normalized_prompt = re.sub(r"[ \t]+", " ", normalized_prompt)
        normalized_prompt = re.sub(r"\s*,\s*", ", ", normalized_prompt)
        normalized_prompt = re.sub(r"\s*\n\s*", "\n", normalized_prompt)
        return normalized_prompt.strip(" \t\r\n,")

    @classmethod
    def _get_english_prompt_validation_error(cls, prompt: str) -> str:
        """返回英文提示词校验错误，空字符串表示通过。"""

        if not prompt.strip():
            return "改写结果为空"

        invalid_match = cls.NON_ENGLISH_PROMPT_PATTERN.search(prompt)
        if invalid_match is None:
            return ""

        invalid_char = invalid_match.group(0)
        return f"改写结果仍包含非 ASCII 字符：{invalid_char!r}"

    async def filter_reviewed_images(
        self,
        prompt: str,
        image_bytes_list: list[bytes],
    ) -> tuple[list[bytes], list[str]]:
        """审核生成图片，并返回通过审核的图片列表。"""

        if not self.moderation_service.is_image_review_enabled():
            return image_bytes_list, []

        approved_images: list[bytes] = []
        rejected_reasons: list[str] = []
        for index, image_bytes in enumerate(image_bytes_list, start=1):
            try:
                review_result = await self.moderation_service.review_image(prompt, image_bytes)
            except Exception as exc:
                self.ctx.logger.warning("图片审核报错: index=%s error=%s", index, exc)
                raise
            if review_result.passed:
                self.ctx.logger.info("图片审核通过")
                approved_images.append(image_bytes)
                continue

            rejected_reason = review_result.reason or "审核模型判定为不通过"
            self.ctx.logger.info("图片审核未通过")
            rejected_reasons.append(f"第 {index} 张：{rejected_reason}")

        return approved_images, rejected_reasons

    async def run_provider_call(self, call: Any, *args: Any) -> list[bytes]:
        """执行图片请求，并按插件配置控制后台任务超时。"""

        timeout_seconds = self.resolve_request_timeout_seconds()

        if inspect.iscoroutinefunction(call):
            image_bytes_list = await asyncio.wait_for(call(*args), timeout=timeout_seconds)
        else:
            image_bytes_list = await asyncio.wait_for(asyncio.to_thread(call, *args), timeout=timeout_seconds)
        return image_bytes_list

    def track_background_task(self, task: asyncio.Task[Any], task_id: str) -> None:
        """跟踪后台任务，避免任务对象被提前释放。"""

        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        del task_id

    def cancel_background_tasks(self) -> None:
        """取消当前全部后台任务。"""

        for task in list(self.background_tasks):
            task.cancel()

    def build_task_status_message(self, record: DrawTaskRecord) -> str:
        """构建任务状态说明。"""

        if record.status in {"pending", "running"}:
            return (
                f"绘图任务仍在处理中：task_id={record.task_id}，类型={record.task_type}，"
                f"模型={record.model}。当前不要在本轮继续调用 draw_status，"
                f"请根据上下文自然告知用户任务仍在生成，并至少等待 {self.STATUS_RECHECK_INTERVAL_SECONDS} 秒后再查一次。"
            )
        if record.status == "completed":
            return (
                f"绘图任务已完成：task_id={record.task_id}，类型={record.task_type}，"
                f"模型={record.model}，已发送 {record.sent_count} 张图片到当前聊天流。"
            )
        if record.status == "rejected":
            return f"绘图任务未通过审核：task_id={record.task_id}。{record.message}"
        return f"绘图任务失败：task_id={record.task_id}。{record.message}"

    def get_task_status_payload(
        self,
        stream_id: str,
        task_id: str = "",
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> dict[str, Any]:
        """查询后台绘图任务状态。"""

        normalized_stream_id = stream_id.strip()
        normalized_task_id = task_id.strip()
        if not normalized_stream_id:
            return {"success": False, "message": "当前聊天流 ID 为空，无法查询绘图任务状态"}

        session_key = self.build_session_key(
            stream_id=normalized_stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )

        record = (
            self.task_store.get_task(normalized_task_id)
            if normalized_task_id
            else self.task_store.get_latest_task(session_key)
        )
        if record is None:
            if normalized_task_id:
                return {"success": False, "message": f"未找到 task_id={normalized_task_id} 对应的绘图任务"}
            return {"success": False, "message": "当前会话还没有可查询的绘图任务"}

        seconds_since_last_query: int | None = None
        if record.last_status_query_at is not None:
            seconds_since_last_query = max(
                int((datetime.now() - record.last_status_query_at).total_seconds()),
                0,
            )
        self.task_store.mark_status_queried(record.task_id)

        next_check_after_seconds = 0
        if record.status in {"pending", "running"}:
            if seconds_since_last_query is None:
                next_check_after_seconds = self.STATUS_RECHECK_INTERVAL_SECONDS
            else:
                next_check_after_seconds = max(
                    self.STATUS_RECHECK_INTERVAL_SECONDS - seconds_since_last_query,
                    0,
                )

        message = self.build_task_status_message(record)
        if record.status in {"pending", "running"} and seconds_since_last_query is not None:
            message = (
                f"绘图任务仍在处理中：task_id={record.task_id}，类型={record.task_type}，模型={record.model}。"
                f"距离上次查询仅 {seconds_since_last_query} 秒。当前不要在本轮继续调用 draw_status，"
                f"请根据上下文自然告知用户任务仍在生成，并在 {max(next_check_after_seconds, 1)} 秒后再查。"
            )

        return {
            "success": record.status in {"pending", "running", "completed"},
            "message": message,
            "task_id": record.task_id,
            "status": record.status,
            "task_type": record.task_type,
            "model": record.model,
            "provider": record.provider,
            "sent_count": record.sent_count,
            "is_finished": record.status in {"completed", "failed", "rejected"},
            "should_wait": record.status in {"pending", "running"},
            "next_check_after_seconds": next_check_after_seconds,
        }

    def build_session_key(
        self,
        stream_id: str,
        user_id: str = "",
        group_id: str = "",
        platform: str = "qq",
    ) -> str:
        """构建任务查询使用的稳定会话键。"""

        return self.task_store.resolve_session_key(
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform,
        )

    async def _background_image_request(
        self,
        *,
        task_id: str,
        prompt: str,
        stream_id: str,
        resolved_model: str,
        openai_compatibility_mode: str = "",
        source_image_bytes_list: list[bytes] | None = None,
        matched_message_id: str = "",
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
    ) -> None:
        """后台执行绘图任务，源图为空时文生图，存在源图时图生图。"""

        normalized_source_images = source_image_bytes_list or []
        is_image_edit = bool(normalized_source_images)
        task_type = "edit_image" if is_image_edit else "draw"
        running_message = "图片正在编辑中" if is_image_edit else "图片正在生成中"
        timeout_message = "图片编辑超时" if is_image_edit else "图片生成超时"
        try:
            self.task_store.update_task(
                task_id,
                status="running",
                message=running_message,
            )
            image_platform, provider_name = self.router.require_platform_for_model(
                resolved_model,
                openai_compatibility_mode,
            )
            image_edit_unsupported_reason = self.router.get_image_edit_unsupported_reason(resolved_model)
            if is_image_edit and image_edit_unsupported_reason:
                raise ValueError(f"{image_edit_unsupported_reason}。请改用文生图，或切换到支持图生图的模型")
            provider_prompt = await self.rewrite_prompt_to_english_if_needed(
                prompt,
                provider_name,
                resolved_model,
            )
            if is_image_edit:
                self.ctx.logger.info(
                    "开始绘图任务: task_id=%s task_type=%s provider=%s model=%s source_image_count=%s source_image_bytes_lengths=%s matched_message_id=%s prompt=%s",
                    task_id,
                    task_type,
                    provider_name,
                    resolved_model,
                    len(normalized_source_images),
                    [len(image_bytes) for image_bytes in normalized_source_images],
                    matched_message_id,
                    provider_prompt[:120],
                )
                image_bytes_list = await self.run_provider_call(
                    image_platform.edit_images,
                    provider_prompt,
                    resolved_model,
                    normalized_source_images,
                    1,
                )
            else:
                self.ctx.logger.info(
                    "开始绘图任务: task_id=%s task_type=%s provider=%s model=%s source_image_count=0 prompt=%s",
                    task_id,
                    task_type,
                    provider_name,
                    resolved_model,
                    provider_prompt[:120],
                )
                image_bytes_list = await self.run_provider_call(
                    image_platform.generate_images,
                    provider_prompt,
                    resolved_model,
                    1,
                )
            if not image_bytes_list:
                self.task_store.update_task(
                    task_id,
                    status="failed",
                    message="图片平台没有返回任何图片结果",
                )
                self.ctx.logger.error("绘图任务失败: task_id=%s task_type=%s provider=%s model=%s error=%s", task_id, task_type, provider_name, resolved_model, "图片平台没有返回任何图片结果")
                return

            reviewed_images, rejected_reasons = await self.filter_reviewed_images(prompt, image_bytes_list)
            if not reviewed_images:
                review_reason_text = "；".join(rejected_reasons) if rejected_reasons else "审核未通过"
                self.task_store.update_task(
                    task_id,
                    status="rejected",
                    message=review_reason_text,
                )
                self.ctx.logger.error("绘图任务审核未通过: task_id=%s task_type=%s provider=%s model=%s error=%s", task_id, task_type, provider_name, resolved_model, review_reason_text)
                return

            sent_count = await self.stream_service.send_generated_images_with_fallback(
                stream_id=stream_id,
                image_bytes_list=reviewed_images,
                user_id=user_id,
                group_id=group_id,
                platform=platform_name,
                task_id=task_id,
                provider=provider_name,
                model=resolved_model,
            )
            self.task_store.update_task(
                task_id,
                status="completed",
                message=f"图片已发送，数量={sent_count}",
                sent_count=sent_count,
            )
            self.ctx.logger.info(
                "绘图任务完成: task_id=%s task_type=%s provider=%s model=%s sent_count=%s",
                task_id,
                task_type,
                provider_name,
                resolved_model,
                sent_count,
            )
        except TimeoutError:
            timeout_seconds = self.resolve_request_timeout_seconds()
            self.task_store.update_task(
                task_id,
                status="failed",
                message=f"{timeout_message}，超过 {timeout_seconds} 秒",
            )
            self.ctx.logger.error("绘图任务失败: task_id=%s task_type=%s model=%s error=%s", task_id, task_type, resolved_model, f"{timeout_message}，超过 {timeout_seconds} 秒")
        except Exception as exc:
            self.task_store.update_task(
                task_id,
                status="failed",
                message=str(exc),
            )
            self.ctx.logger.error("绘图任务失败: task_id=%s task_type=%s model=%s error=%s", task_id, task_type, resolved_model, exc, exc_info=True)

    async def start_background_image_request(
        self,
        *,
        prompt: str,
        stream_id: str,
        resolved_model: str,
        resolved_openai_mode: str,
        provider_name: str,
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
        source_image_bytes_list: list[bytes] | None = None,
        matched_message_id: str = "",
        notify_start: bool = False,
    ) -> dict[str, Any]:
        """启动后台绘图任务，源图为空时文生图，存在源图时图生图。"""

        normalized_source_images = source_image_bytes_list or []
        is_image_edit = bool(normalized_source_images)
        image_edit_unsupported_reason = self.router.get_image_edit_unsupported_reason(resolved_model)
        if is_image_edit and image_edit_unsupported_reason:
            self.ctx.logger.info(
                "拒绝提交图生图任务: model=%s stream_id=%s user_id=%s group_id=%s platform=%s source_image_count=%s reason=%s",
                resolved_model,
                stream_id,
                user_id,
                group_id,
                platform_name,
                len(normalized_source_images),
                image_edit_unsupported_reason,
            )
            raise ValueError(f"{image_edit_unsupported_reason}。请改用文生图，或切换到支持图生图的模型")

        task_type = "edit_image" if is_image_edit else "draw"
        task_record = self.task_store.create_task(
            session_key=self.build_session_key(
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform_name,
            ),
            stream_id=stream_id,
            task_type=task_type,
            prompt=prompt,
            model=resolved_model,
            provider=provider_name,
            message="任务已创建，等待后台执行",
        )
        background_task = asyncio.create_task(
            self._background_image_request(
                task_id=task_record.task_id,
                prompt=prompt,
                stream_id=stream_id,
                resolved_model=resolved_model,
                openai_compatibility_mode=resolved_openai_mode,
                source_image_bytes_list=normalized_source_images,
                matched_message_id=matched_message_id,
                user_id=user_id,
                group_id=group_id,
                platform_name=platform_name,
            )
        )
        self.track_background_task(background_task, task_record.task_id)
        if notify_start:
            self.ctx.logger.info(
                "绘图任务已提交: task_id=%s task_type=%s model=%s stream_id=%s user_id=%s group_id=%s platform=%s source_image_count=%s",
                task_record.task_id,
                task_type,
                resolved_model,
                stream_id,
                user_id,
                group_id,
                platform_name,
                len(normalized_source_images),
            )
        message_action = "编辑图片" if is_image_edit else "生成图片"
        payload = {
            "success": True,
            "message": (
                f"已开始后台{message_action}，task_id={task_record.task_id}。"
                "这是异步任务。当前不要立刻反复调用 draw_status；请根据对话上下文自然回复用户任务已开始，"
                f"至少等待 {self.STATUS_RECHECK_INTERVAL_SECONDS} 秒后再查询状态。"
            ),
            "provider": provider_name,
            "model": resolved_model,
            "openai_compatibility_mode": resolved_openai_mode,
            "task_type": task_type,
            "timeout_seconds": self.resolve_request_timeout_seconds(),
            "task_id": task_record.task_id,
        }
        if is_image_edit:
            payload["source_message_id"] = matched_message_id
            payload["source_image_count"] = len(normalized_source_images)
        return payload

    async def start_background_draw_request(
        self,
        *,
        prompt: str,
        stream_id: str,
        resolved_model: str,
        resolved_openai_mode: str,
        provider_name: str,
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
        notify_start: bool = False,
    ) -> dict[str, Any]:
        """启动后台文生图。"""

        return await self.start_background_image_request(
            prompt=prompt,
            stream_id=stream_id,
            resolved_model=resolved_model,
            resolved_openai_mode=resolved_openai_mode,
            provider_name=provider_name,
            user_id=user_id,
            group_id=group_id,
            platform_name=platform_name,
            notify_start=notify_start,
        )

    async def start_background_edit_request(
        self,
        *,
        prompt: str,
        stream_id: str,
        resolved_model: str,
        resolved_openai_mode: str,
        provider_name: str,
        source_image_bytes_list: list[bytes],
        matched_message_id: str,
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
    ) -> dict[str, Any]:
        """启动后台图生图。"""

        if not source_image_bytes_list:
            raise ValueError("没有可用于图生图的源图片")
        return await self.start_background_image_request(
            prompt=prompt,
            stream_id=stream_id,
            resolved_model=resolved_model,
            resolved_openai_mode=resolved_openai_mode,
            provider_name=provider_name,
            user_id=user_id,
            group_id=group_id,
            platform_name=platform_name,
            source_image_bytes_list=source_image_bytes_list,
            matched_message_id=matched_message_id,
        )
