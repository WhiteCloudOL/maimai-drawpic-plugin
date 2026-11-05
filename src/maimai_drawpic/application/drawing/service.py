from typing import Any, Awaitable, Callable, Dict, Optional
import asyncio
import re
import inspect
from contextlib import contextmanager

from ..moderation import DrawpicModerationService
from ...infrastructure.storage.results import ImageResultStore
from ..routing import ProviderRouter
from ..chat import ChatStreamService
from ...infrastructure.storage.tasks import DrawTaskStore
from .attempts import RequestAttemptRunnerMixin
from .prompts import PromptReviewMixin
from .planning import RequestPlanningMixin
from .execution import ImageExecutionMixin
from .queries import TaskQueryMixin
from .admission import persist_submission, tracked_submission, wait_for_admission
from ...domain.task_errors import task_error


class DrawService(
    RequestAttemptRunnerMixin, PromptReviewMixin, RequestPlanningMixin, ImageExecutionMixin, TaskQueryMixin
):
    """协调平台路由与绘图任务所需的独立职责。"""

    STATUS_RECHECK_INTERVAL_SECONDS = 20
    CANCEL_WAIT_SECONDS = 1.0
    SHUTDOWN_WAIT_SECONDS = 5.0
    TERMINAL_WRITE_ATTEMPTS = 3

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
        result_store: ImageResultStore | None = None,
    ) -> None:
        self.ctx = ctx
        self.router = router
        self.stream_service = stream_service
        self.moderation_service = moderation_service
        self.task_store = task_store
        self.result_store = result_store
        self.background_tasks: set[asyncio.Task[Any]] = set()
        self._submissions: dict[asyncio.Task[Any], int] = {}
        self._started_task_ids: set[str] = set()
        self._settlement_tasks: set[asyncio.Task[Any]] = set()
        self._admission_closed = False

    @property
    def has_active_work(self) -> bool:
        return bool(self.background_tasks or self._submissions or self._settlement_tasks)

    @contextmanager
    def submission_scope(self):
        if self._admission_closed:
            raise RuntimeError("插件正在卸载，不能提交新的绘图任务")
        current = asyncio.current_task()
        self._submissions[current] = self._submissions.get(current, 0) + 1
        try:
            yield
        finally:
            depth = self._submissions[current] - 1
            if depth:
                self._submissions[current] = depth
            else:
                self._submissions.pop(current, None)

    def close_admission(self) -> None:
        self._admission_closed = True

    async def cancel_submissions(self) -> None:
        tasks = [task for task in self._submissions if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self.SHUTDOWN_WAIT_SECONDS)
            if pending:
                raise RuntimeError("卸载尚未完成：任务提交仍在收尾，稍后重试卸载")

    async def wait_settlement(self, *, bounded: bool = False) -> None:
        while self._settlement_tasks:
            if bounded:
                _, pending = await asyncio.wait(tuple(self._settlement_tasks), timeout=self.SHUTDOWN_WAIT_SECONDS)
                if pending:
                    raise RuntimeError("卸载尚未完成：任务结算仍在收尾，稍后重试卸载")
            else:
                await asyncio.gather(*tuple(self._settlement_tasks), return_exceptions=True)

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

    def resolve_fallback_model_name(self, primary_model: str = "") -> str:
        """解析生图备选模型名称。"""

        return self.router.resolve_fallback_model(primary_model)

    def track_background_task(
        self, task: asyncio.Task[Any], task_id: str,
        on_task_unsuccessful: Callable[[str, str, str], Awaitable[None] | None] | None = None,
    ) -> None:
        """Own settlement even when cancellation precedes the coroutine's first step."""
        self.background_tasks.add(task)

        async def settle_unstarted() -> None:
            try:
                await self.persist_terminal(
                    task_id, status="failed", message="任务已取消",
                    error=task_error("CANCELLED", "执行尚未启动，任务已取消"),
                )
            except Exception:
                self.ctx.logger.exception("未启动任务取消状态保存失败: task_id=%s", task_id)
            finally:
                if on_task_unsuccessful is not None:
                    try:
                        result = on_task_unsuccessful(task_id, "failed", "任务已取消")
                        if inspect.isawaitable(result):
                            await result
                    except Exception:
                        self.ctx.logger.exception("未启动任务结算失败: task_id=%s", task_id)

        def finished(done: asyncio.Task[Any]) -> None:
            self.background_tasks.discard(done)
            started = task_id in self._started_task_ids
            self._started_task_ids.discard(task_id)
            if not started:
                cleanup = asyncio.create_task(settle_unstarted())
                self._settlement_tasks.add(cleanup)
                cleanup.add_done_callback(self._settlement_tasks.discard)

        task.add_done_callback(finished)

    async def persist_terminal(self, task_id: str, **changes: Any) -> None:
        """Retry only the exact final mutation, never generation or delivery."""
        async def persist() -> None:
            for attempt in range(self.TERMINAL_WRITE_ATTEMPTS):
                try:
                    await asyncio.to_thread(self.task_store.update_task, task_id, **changes)
                    return
                except OSError:
                    if attempt + 1 < self.TERMINAL_WRITE_ATTEMPTS:
                        await asyncio.sleep(0.05 * (attempt + 1))
                except Exception:
                    break
            self.task_store.defer_terminal(task_id, **changes)
            self.ctx.logger.error(
                "绘图终态待落盘: task_id=%s status=%s；恢复存储后查询或卸载会重试保存，不会重新生成或发送",
                task_id, changes["status"],
            )

        pending = asyncio.create_task(persist())
        self._settlement_tasks.add(pending)
        pending.add_done_callback(self._settlement_tasks.discard)
        await wait_for_admission(pending)

    async def cancel_background_tasks(self) -> None:
        """Bound shutdown without discarding ownership of live SDK threads."""
        tasks = list(self.background_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=self.SHUTDOWN_WAIT_SECONDS)
            if pending:
                self.ctx.logger.error("卸载尚未完成：%s 个绘图任务仍在等待本地工作线程退出", len(pending))
                raise RuntimeError("卸载尚未完成：同步绘图工作线程仍在运行，资源名额保持占用；稍后重试卸载")
        await self.wait_settlement(bounded=True)

    @tracked_submission
    async def start_background_image_request(
        self,
        *,
        prompt: str,
        stream_id: str,
        resolved_model: str,
        resolved_openai_mode: str,
        provider_name: str,
        novelai_mode: str = "",
        novelai_artist_tags: str = "",
        request_negative_prompt: str = "",
        style_negative_prompt_template: str = "",
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
        source_image_bytes_list: list[bytes] | None = None,
        source_image_urls: list[str] | None = None,
        matched_message_id: str = "",
        notify_start: bool = False,
        prompt_reviewed: bool = True,
        on_task_unsuccessful: Callable[[str, str, str], Awaitable[None] | None] | None = None,
        on_task_successful: Callable[[str, str, str], Awaitable[None] | None] | None = None,
        submission: Optional[Dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """启动后台绘图任务，源图为空时文生图，存在源图时图生图。"""

        normalized_source_images = source_image_bytes_list or []
        normalized_source_urls = source_image_urls or [""] * len(normalized_source_images)
        if len(normalized_source_urls) != len(normalized_source_images):
            raise ValueError("源图 URL 数量必须与源图数量一致")
        is_image_edit = bool(normalized_source_images)
        task_type = "edit_image" if is_image_edit else "draw"

        primary_attempt = self._build_image_request_attempt(
            model=resolved_model,
            task_type=task_type,
            openai_compatibility_mode=resolved_openai_mode,
            novelai_mode=novelai_mode,
            novelai_artist_tags=novelai_artist_tags,
        )
        self.router.validate_source_image_count(primary_attempt.model, len(normalized_source_images))
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

        fallback_models = self.router.resolve_fallback_models(resolved_model)
        fallback_model = fallback_models[0] if fallback_models else ""
        self.ctx.logger.info(
            "准备提交绘图任务: stream_id=%s task_type=%s provider=%s model=%s fallback_models=%s source_image_count=%s",
            stream_id,
            task_type,
            primary_attempt.provider_name,
            primary_attempt.model,
            fallback_models,
            len(normalized_source_images),
        )
        unavailable = self.router.get_fallback_model_unavailable_reason(resolved_model)
        if unavailable:
            self.ctx.logger.warning("部分生图备选模型不可用: %s", unavailable)

        task_record = await persist_submission(
            self.task_store,
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
            submission=submission,
        )
        background_task = asyncio.create_task(
            self._background_image_request(
                task_id=task_record.task_id,
                prompt=prompt,
                stream_id=stream_id,
                resolved_model=primary_attempt.model,
                openai_compatibility_mode=resolved_openai_mode,
                novelai_mode=novelai_mode,
                novelai_artist_tags=novelai_artist_tags,
                request_negative_prompt=request_negative_prompt,
                style_negative_prompt_template=style_negative_prompt_template,
                source_image_bytes_list=normalized_source_images,
                source_image_urls=normalized_source_urls,
                matched_message_id=matched_message_id,
                prompt_reviewed=prompt_reviewed,
                user_id=user_id,
                group_id=group_id,
                platform_name=platform_name,
                on_task_unsuccessful=on_task_unsuccessful,
                on_task_successful=on_task_successful,
            ),
            name=f"maimai-drawpic:{task_record.task_id}",
        )
        self.track_background_task(background_task, task_record.task_id, on_task_unsuccessful)
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
            "fallback_models": fallback_models,
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
        source_image_urls: list[str] | None = None,
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
            source_image_urls=source_image_urls,
            matched_message_id=matched_message_id,
        )
