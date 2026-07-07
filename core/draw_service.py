from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

import asyncio
import inspect
import re
import unicodedata

from .moderation import DrawpicModerationService
from .provider_router import ProviderName, ProviderRouter
from .stream_service import ChatStreamService
from .task_store import DrawTaskRecord, DrawTaskStore


@dataclass(frozen=True, slots=True)
class ImageRequestAttempt:
    """一次图片请求尝试使用的最终路由信息。"""

    model: str
    provider_name: ProviderName
    openai_compatibility_mode: str
    is_fallback: bool = False


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

        if not self.router.should_rewrite_prompt_to_english(provider_name, model):
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

    def resolve_fallback_model_name(self, primary_model: str = "") -> str:
        """解析生图备选模型名称。"""

        return self.router.resolve_fallback_model(primary_model)

    def _build_image_request_attempt(
        self,
        *,
        model: str,
        task_type: str,
        openai_compatibility_mode: str,
        is_fallback: bool = False,
    ) -> ImageRequestAttempt:
        """构建一次图片请求尝试的最终模型与提供商信息。"""

        provider_name = self.router.get_model_provider(model)
        if not provider_name:
            raise ValueError(f"指定模型不可用：{model}")

        effective_model = model
        if provider_name == "volcengine":
            effective_model = self.router.resolve_volcengine_model_for_task(model, task_type)
            if effective_model != model:
                self.ctx.logger.info(
                    "火山引擎模型自动切换: task_type=%s original_model=%s effective_model=%s is_fallback=%s",
                    task_type,
                    model,
                    effective_model,
                    is_fallback,
                )

        image_edit_unsupported_reason = self.router.get_image_edit_unsupported_reason(effective_model)
        if task_type == "edit_image" and image_edit_unsupported_reason:
            raise ValueError(f"{image_edit_unsupported_reason}。请改用文生图，或切换到支持图生图的模型")

        return ImageRequestAttempt(
            model=effective_model,
            provider_name=provider_name,
            openai_compatibility_mode=self.router.resolve_openai_compatibility_mode(
                openai_compatibility_mode,
                effective_model,
            ),
            is_fallback=is_fallback,
        )

    def _build_fallback_image_request_attempt(
        self,
        *,
        primary_model: str,
        primary_effective_model: str,
        task_type: str,
        openai_compatibility_mode: str,
    ) -> ImageRequestAttempt | None:
        """在首选模型失败后构建备选模型请求。"""

        fallback_model = self.router.resolve_fallback_model(primary_model)
        fallback_unavailable_reason = self.router.get_fallback_model_unavailable_reason(primary_model)
        if fallback_unavailable_reason:
            self.ctx.logger.warning(
                "生图备选模型不可用，跳过备选尝试: primary_model=%s fallback_model=%s reason=%s",
                primary_model,
                self.router.config.general.fallback_model.strip(),
                fallback_unavailable_reason,
            )
            return None
        if not fallback_model:
            self.ctx.logger.info(
                "未配置生图备选模型，首选模型失败后不再重试: primary_model=%s",
                primary_model,
            )
            return None

        try:
            fallback_attempt = self._build_image_request_attempt(
                model=fallback_model,
                task_type=task_type,
                openai_compatibility_mode=openai_compatibility_mode,
                is_fallback=True,
            )
        except Exception as exc:
            self.ctx.logger.warning(
                "生图备选模型解析失败，跳过备选尝试: primary_model=%s fallback_model=%s task_type=%s error=%s",
                primary_model,
                fallback_model,
                task_type,
                exc,
            )
            return None

        if fallback_attempt.model == primary_effective_model:
            self.ctx.logger.warning(
                "生图备选模型与首选模型最终解析结果相同，跳过备选尝试: primary_model=%s fallback_model=%s effective_model=%s",
                primary_model,
                fallback_model,
                fallback_attempt.model,
            )
            return None

        return fallback_attempt

    async def _run_image_request_attempt(
        self,
        *,
        attempt: ImageRequestAttempt,
        prompt: str,
        task_id: str,
        task_type: str,
        source_image_bytes_list: list[bytes],
        matched_message_id: str,
    ) -> list[bytes]:
        """执行单次图片请求尝试。"""

        image_platform, provider_name = self.router.require_platform_for_model(
            attempt.model,
            attempt.openai_compatibility_mode,
        )
        provider_prompt = await self.rewrite_prompt_to_english_if_needed(
            prompt,
            provider_name,
            attempt.model,
        )

        if task_type == "edit_image":
            self.ctx.logger.info(
                "开始绘图任务尝试: task_id=%s task_type=%s provider=%s model=%s is_fallback=%s source_image_count=%s source_image_bytes_lengths=%s matched_message_id=%s prompt=%s",
                task_id,
                task_type,
                provider_name,
                attempt.model,
                attempt.is_fallback,
                len(source_image_bytes_list),
                [len(image_bytes) for image_bytes in source_image_bytes_list],
                matched_message_id,
                provider_prompt[:120],
            )
            return await self.run_provider_call(
                image_platform.edit_images,
                provider_prompt,
                attempt.model,
                source_image_bytes_list,
                1,
            )

        self.ctx.logger.info(
            "开始绘图任务尝试: task_id=%s task_type=%s provider=%s model=%s is_fallback=%s source_image_count=0 prompt=%s",
            task_id,
            task_type,
            provider_name,
            attempt.model,
            attempt.is_fallback,
            provider_prompt[:120],
        )
        return await self.run_provider_call(
            image_platform.generate_images,
            provider_prompt,
            attempt.model,
            1,
        )

    @staticmethod
    def _format_attempt_error(attempt: ImageRequestAttempt, error_message: str) -> str:
        """格式化一次模型尝试失败信息。"""

        role_name = "备选模型" if attempt.is_fallback else "首选模型"
        return f"{role_name} {attempt.provider_name}:{attempt.model} 失败：{error_message}"

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
        on_task_unsuccessful: Callable[[str, str, str], Awaitable[None] | None] | None = None,
    ) -> None:
        """后台执行绘图任务，源图为空时文生图，存在源图时图生图。"""

        async def _notify_task_unsuccessful(status: str, reason: str) -> None:
            if on_task_unsuccessful is None:
                return
            try:
                result = on_task_unsuccessful(task_id, status, reason)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                self.ctx.logger.error(
                    "绘图任务失败回调执行异常: task_id=%s status=%s reason=%s error=%s",
                    task_id,
                    status,
                    reason,
                    exc,
                    exc_info=True,
                )

        normalized_source_images = source_image_bytes_list or []
        is_image_edit = bool(normalized_source_images)
        task_type = "edit_image" if is_image_edit else "draw"
        running_message = "图片正在编辑中" if is_image_edit else "图片正在生成中"
        timeout_message = "图片编辑超时" if is_image_edit else "图片生成超时"
        try:
            running_record = self.task_store.update_task(
                task_id,
                status="running",
                message=running_message,
            )
            if running_record is None:
                # 任务记录已被配置重载清空，无法继续追踪状态，静默退出避免 KeyError 崩溃
                self.ctx.logger.warning("绘图任务记录已失效，终止后台执行: task_id=%s task_type=%s", task_id, task_type)
                return
            primary_attempt = self._build_image_request_attempt(
                model=resolved_model,
                task_type=task_type,
                openai_compatibility_mode=openai_compatibility_mode,
            )
            self.task_store.update_task(
                task_id,
                status="running",
                message=running_message,
                model=primary_attempt.model,
                provider=primary_attempt.provider_name,
            )

            timeout_seconds = self.resolve_request_timeout_seconds()
            attempt_errors: list[str] = []
            image_bytes_list: list[bytes] = []
            successful_attempt: ImageRequestAttempt | None = None

            try:
                image_bytes_list = await self._run_image_request_attempt(
                    attempt=primary_attempt,
                    prompt=prompt,
                    task_id=task_id,
                    task_type=task_type,
                    source_image_bytes_list=normalized_source_images,
                    matched_message_id=matched_message_id,
                )
                if not image_bytes_list:
                    raise RuntimeError("图片平台没有返回任何图片结果")
                successful_attempt = primary_attempt
            except TimeoutError:
                error_message = f"{timeout_message}，超过 {timeout_seconds} 秒"
                attempt_errors.append(self._format_attempt_error(primary_attempt, error_message))
                self.ctx.logger.warning(
                    "首选模型绘图超时: task_id=%s task_type=%s provider=%s model=%s timeout_seconds=%s",
                    task_id,
                    task_type,
                    primary_attempt.provider_name,
                    primary_attempt.model,
                    timeout_seconds,
                )
            except Exception as exc:
                error_message = str(exc) or exc.__class__.__name__
                attempt_errors.append(self._format_attempt_error(primary_attempt, error_message))
                self.ctx.logger.warning(
                    "首选模型绘图失败: task_id=%s task_type=%s provider=%s model=%s error=%s",
                    task_id,
                    task_type,
                    primary_attempt.provider_name,
                    primary_attempt.model,
                    error_message,
                    exc_info=True,
                )

            if successful_attempt is None:
                fallback_attempt = self._build_fallback_image_request_attempt(
                    primary_model=resolved_model,
                    primary_effective_model=primary_attempt.model,
                    task_type=task_type,
                    openai_compatibility_mode=openai_compatibility_mode,
                )
                if fallback_attempt is not None:
                    self.ctx.logger.warning(
                        "首选模型绘图失败，开始尝试生图备选模型: task_id=%s task_type=%s primary_provider=%s primary_model=%s fallback_provider=%s fallback_model=%s previous_errors=%s",
                        task_id,
                        task_type,
                        primary_attempt.provider_name,
                        primary_attempt.model,
                        fallback_attempt.provider_name,
                        fallback_attempt.model,
                        "；".join(attempt_errors),
                    )
                    self.task_store.update_task(
                        task_id,
                        status="running",
                        message=f"首选模型失败，正在尝试生图备选模型：{fallback_attempt.model}",
                        model=fallback_attempt.model,
                        provider=fallback_attempt.provider_name,
                    )
                    try:
                        image_bytes_list = await self._run_image_request_attempt(
                            attempt=fallback_attempt,
                            prompt=prompt,
                            task_id=task_id,
                            task_type=task_type,
                            source_image_bytes_list=normalized_source_images,
                            matched_message_id=matched_message_id,
                        )
                        if not image_bytes_list:
                            raise RuntimeError("图片平台没有返回任何图片结果")
                        successful_attempt = fallback_attempt
                        self.ctx.logger.info(
                            "生图备选模型绘图成功: task_id=%s task_type=%s provider=%s model=%s previous_errors=%s",
                            task_id,
                            task_type,
                            fallback_attempt.provider_name,
                            fallback_attempt.model,
                            "；".join(attempt_errors),
                        )
                    except TimeoutError:
                        error_message = f"{timeout_message}，超过 {timeout_seconds} 秒"
                        attempt_errors.append(self._format_attempt_error(fallback_attempt, error_message))
                        self.ctx.logger.error(
                            "生图备选模型绘图超时: task_id=%s task_type=%s provider=%s model=%s timeout_seconds=%s",
                            task_id,
                            task_type,
                            fallback_attempt.provider_name,
                            fallback_attempt.model,
                            timeout_seconds,
                        )
                    except Exception as exc:
                        error_message = str(exc) or exc.__class__.__name__
                        attempt_errors.append(self._format_attempt_error(fallback_attempt, error_message))
                        self.ctx.logger.error(
                            "生图备选模型绘图失败: task_id=%s task_type=%s provider=%s model=%s error=%s",
                            task_id,
                            task_type,
                            fallback_attempt.provider_name,
                            fallback_attempt.model,
                            error_message,
                            exc_info=True,
                        )

            if successful_attempt is None:
                failure_message = "；".join(attempt_errors) if attempt_errors else "图片平台没有返回任何图片结果"
                self.task_store.update_task(
                    task_id,
                    status="failed",
                    message=failure_message,
                )
                await _notify_task_unsuccessful("failed", failure_message)
                self.ctx.logger.error(
                    "绘图任务失败: task_id=%s task_type=%s primary_provider=%s primary_model=%s configured_fallback_model=%s errors=%s",
                    task_id,
                    task_type,
                    primary_attempt.provider_name,
                    primary_attempt.model,
                    self.router.config.general.fallback_model.strip(),
                    failure_message,
                )
                return

            reviewed_images, rejected_reasons = await self.filter_reviewed_images(prompt, image_bytes_list)
            if not reviewed_images:
                review_reason_text = "；".join(rejected_reasons) if rejected_reasons else "审核未通过"
                if successful_attempt.is_fallback and attempt_errors:
                    review_reason_text = f"首选模型失败后使用备选模型生成，但图片审核未通过：{review_reason_text}"
                self.task_store.update_task(
                    task_id,
                    status="rejected",
                    message=review_reason_text,
                    model=successful_attempt.model,
                    provider=successful_attempt.provider_name,
                )
                await _notify_task_unsuccessful("rejected", review_reason_text)
                self.ctx.logger.error(
                    "绘图任务审核未通过: task_id=%s task_type=%s provider=%s model=%s is_fallback=%s error=%s",
                    task_id,
                    task_type,
                    successful_attempt.provider_name,
                    successful_attempt.model,
                    successful_attempt.is_fallback,
                    review_reason_text,
                )
                return

            sent_count = await self.stream_service.send_generated_images_with_fallback(
                stream_id=stream_id,
                image_bytes_list=reviewed_images,
                user_id=user_id,
                group_id=group_id,
                platform=platform_name,
                task_id=task_id,
                provider=successful_attempt.provider_name,
                model=successful_attempt.model,
            )
            success_message = f"图片已发送，数量={sent_count}"
            if successful_attempt.is_fallback:
                success_message = f"首选模型失败，已使用生图备选模型发送图片，数量={sent_count}"
            self.task_store.update_task(
                task_id,
                status="completed",
                message=success_message,
                sent_count=sent_count,
                model=successful_attempt.model,
                provider=successful_attempt.provider_name,
            )
            self.ctx.logger.info(
                "绘图任务完成: task_id=%s task_type=%s provider=%s model=%s is_fallback=%s sent_count=%s previous_errors=%s",
                task_id,
                task_type,
                successful_attempt.provider_name,
                successful_attempt.model,
                successful_attempt.is_fallback,
                sent_count,
                "；".join(attempt_errors),
            )
        except asyncio.CancelledError:
            self.task_store.update_task(
                task_id,
                status="failed",
                message="任务已取消",
            )
            await _notify_task_unsuccessful("failed", "任务已取消")
            self.ctx.logger.warning("绘图任务已取消: task_id=%s task_type=%s model=%s", task_id, task_type, resolved_model)
            raise
        except TimeoutError:
            timeout_seconds = self.resolve_request_timeout_seconds()
            self.task_store.update_task(
                task_id,
                status="failed",
                message=f"{timeout_message}，超过 {timeout_seconds} 秒",
            )
            await _notify_task_unsuccessful("failed", f"{timeout_message}，超过 {timeout_seconds} 秒")
            self.ctx.logger.error("绘图任务失败: task_id=%s task_type=%s model=%s error=%s", task_id, task_type, resolved_model, f"{timeout_message}，超过 {timeout_seconds} 秒")
        except Exception as exc:
            self.task_store.update_task(
                task_id,
                status="failed",
                message=str(exc),
            )
            await _notify_task_unsuccessful("failed", str(exc))
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
        on_task_unsuccessful: Callable[[str, str, str], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        """启动后台绘图任务，源图为空时文生图，存在源图时图生图。"""

        normalized_source_images = source_image_bytes_list or []
        is_image_edit = bool(normalized_source_images)
        task_type = "edit_image" if is_image_edit else "draw"

        primary_attempt = self._build_image_request_attempt(
            model=resolved_model,
            task_type=task_type,
            openai_compatibility_mode=resolved_openai_mode,
        )
        if is_image_edit and self.router.get_image_edit_unsupported_reason(primary_attempt.model):
            self.ctx.logger.info(
                "拒绝提交图生图任务: model=%s stream_id=%s user_id=%s group_id=%s platform=%s source_image_count=%s reason=%s",
                primary_attempt.model,
                stream_id,
                user_id,
                group_id,
                platform_name,
                len(normalized_source_images),
                self.router.get_image_edit_unsupported_reason(primary_attempt.model),
            )
            image_edit_unsupported_reason = self.router.get_image_edit_unsupported_reason(primary_attempt.model)
            raise ValueError(f"{image_edit_unsupported_reason}。请改用文生图，或切换到支持图生图的模型")

        fallback_model = self.router.resolve_fallback_model(resolved_model)
        fallback_unavailable_reason = self.router.get_fallback_model_unavailable_reason(resolved_model)
        if fallback_model:
            try:
                fallback_attempt = self._build_image_request_attempt(
                    model=fallback_model,
                    task_type=task_type,
                    openai_compatibility_mode=resolved_openai_mode,
                    is_fallback=True,
                )
                if fallback_attempt.model == primary_attempt.model:
                    fallback_model = ""
                    fallback_unavailable_reason = "生图备选模型与首选模型最终解析结果相同，已忽略备选模型"
            except Exception as exc:
                fallback_unavailable_reason = f"生图备选模型解析失败：{exc}"
                fallback_model = ""
        self.ctx.logger.info(
            "准备提交绘图任务: stream_id=%s task_type=%s primary_provider=%s primary_model=%s configured_model=%s fallback_model=%s configured_fallback_model=%s fallback_unavailable_reason=%s source_image_count=%s",
            stream_id,
            task_type,
            primary_attempt.provider_name,
            primary_attempt.model,
            resolved_model,
            fallback_model or "未启用",
            self.router.config.general.fallback_model.strip() or "未配置",
            fallback_unavailable_reason or "",
            len(normalized_source_images),
        )

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
            model=primary_attempt.model,
            provider=primary_attempt.provider_name,
            message="任务已创建，等待后台执行",
        )
        background_task = asyncio.create_task(
            self._background_image_request(
                task_id=task_record.task_id,
                prompt=prompt,
                stream_id=stream_id,
                resolved_model=primary_attempt.model,
                openai_compatibility_mode=primary_attempt.openai_compatibility_mode,
                source_image_bytes_list=normalized_source_images,
                matched_message_id=matched_message_id,
                user_id=user_id,
                group_id=group_id,
                platform_name=platform_name,
                on_task_unsuccessful=on_task_unsuccessful,
            )
        )
        self.track_background_task(background_task, task_record.task_id)
        if notify_start:
            self.ctx.logger.info(
                "绘图任务已提交: task_id=%s task_type=%s primary_provider=%s primary_model=%s fallback_model=%s stream_id=%s user_id=%s group_id=%s platform=%s source_image_count=%s",
                task_record.task_id,
                task_type,
                primary_attempt.provider_name,
                primary_attempt.model,
                fallback_model or "未启用",
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
            "provider": primary_attempt.provider_name,
            "model": primary_attempt.model,
            "openai_compatibility_mode": primary_attempt.openai_compatibility_mode,
            "fallback_model": fallback_model,
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
