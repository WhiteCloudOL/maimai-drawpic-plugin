from __future__ import annotations

from datetime import datetime
from typing import Any

import asyncio
import inspect

from .moderation import DrawpicModerationService
from .provider_router import ProviderRouter
from .stream_service import ChatStreamService
from .task_store import DrawTaskRecord, DrawTaskStore


class DrawService:
    """负责后台绘图执行、审核与任务状态管理。"""

    STATUS_RECHECK_INTERVAL_SECONDS = 20

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
        call_name = getattr(call, "__name__", call.__class__.__name__)
        self.ctx.logger.info("开始调用图片平台: call=%s timeout=%ss", call_name, timeout_seconds)
        if args:
            prompt_preview = str(args[0])[:80] if isinstance(args[0], str) else ""
            model_name = str(args[1]) if len(args) > 1 else ""
            self.ctx.logger.info(
                "图片平台调用参数: call=%s model=%s prompt_preview=%s",
                call_name,
                model_name,
                prompt_preview,
            )

        if inspect.iscoroutinefunction(call):
            image_bytes_list = await asyncio.wait_for(call(*args), timeout=timeout_seconds)
        else:
            image_bytes_list = await asyncio.wait_for(asyncio.to_thread(call, *args), timeout=timeout_seconds)
        self.ctx.logger.info("图片平台调用完成: call=%s result_count=%s", call_name, len(image_bytes_list))
        return image_bytes_list

    def track_background_task(self, task: asyncio.Task[Any]) -> None:
        """跟踪后台任务，避免任务对象被提前释放。"""

        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
        self.ctx.logger.info("后台图片任务已登记: task_id=%s pending_count=%s", id(task), len(self.background_tasks))

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
                f"请直接回复用户“还在生成中”，并至少等待 {self.STATUS_RECHECK_INTERVAL_SECONDS} 秒后再查一次。"
            )
        if record.status == "completed":
            return (
                f"绘图任务已完成：task_id={record.task_id}，类型={record.task_type}，"
                f"模型={record.model}，已发送 {record.sent_count} 张图片到当前聊天流。"
            )
        if record.status == "rejected":
            return f"绘图任务未通过审核：task_id={record.task_id}。{record.message}"
        return f"绘图任务失败：task_id={record.task_id}。{record.message}"

    def get_task_status_payload(self, stream_id: str, task_id: str = "") -> dict[str, Any]:
        """查询后台绘图任务状态。"""

        normalized_stream_id = stream_id.strip()
        normalized_task_id = task_id.strip()
        if not normalized_stream_id:
            return {"success": False, "message": "当前聊天流 ID 为空，无法查询绘图任务状态"}

        record = (
            self.task_store.get_task(normalized_task_id)
            if normalized_task_id
            else self.task_store.get_latest_task(normalized_stream_id)
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
                f"请直接回复用户“还在生成中”，并在 {max(next_check_after_seconds, 1)} 秒后再查。"
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

    async def _background_draw(
        self,
        *,
        task_id: str,
        prompt: str,
        stream_id: str,
        resolved_model: str,
        openai_compatibility_mode: str = "",
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
    ) -> None:
        """后台执行文生图。"""

        try:
            self.task_store.update_task(
                task_id,
                status="running",
                message="图片正在生成中",
            )
            self.ctx.logger.info(
                "后台文生图开始: stream_id=%s user_id=%s group_id=%s platform=%s model=%s openai_mode=%s prompt_preview=%s",
                stream_id,
                user_id,
                group_id,
                platform_name,
                resolved_model,
                openai_compatibility_mode,
                prompt[:120],
            )
            image_platform, provider_name = self.router.require_platform_for_model(
                resolved_model,
                openai_compatibility_mode,
            )
            image_bytes_list = await self.run_provider_call(image_platform.generate_images, prompt, resolved_model, 1)
            if not image_bytes_list:
                self.task_store.update_task(
                    task_id,
                    status="failed",
                    message="图片平台没有返回任何图片结果",
                )
                self.ctx.logger.warning("后台文生图无结果: stream_id=%s model=%s", stream_id, resolved_model)
                return

            reviewed_images, rejected_reasons = await self.filter_reviewed_images(prompt, image_bytes_list)
            if not reviewed_images:
                review_reason_text = "；".join(rejected_reasons) if rejected_reasons else "审核未通过"
                self.task_store.update_task(
                    task_id,
                    status="rejected",
                    message=review_reason_text,
                )
                self.ctx.logger.warning(
                    "后台文生图结果被全部拦截: stream_id=%s model=%s reasons=%s",
                    stream_id,
                    resolved_model,
                    review_reason_text,
                )
                await self.send_text_with_fallback(
                    text=f"图片生成完成了，但结果未通过审核，已拦截发送。{review_reason_text}",
                    stream_id=stream_id,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform_name,
                )
                return

            sent_count = await self.stream_service.send_generated_images_with_fallback(
                stream_id=stream_id,
                image_bytes_list=reviewed_images,
                user_id=user_id,
                group_id=group_id,
                platform=platform_name,
            )
            self.task_store.update_task(
                task_id,
                status="completed",
                message=f"图片已发送，数量={sent_count}",
                sent_count=sent_count,
            )
            self.ctx.logger.info(
                "后台图片生成完成: provider=%s model=%s count=%s",
                provider_name,
                resolved_model,
                sent_count,
            )
        except TimeoutError:
            timeout_seconds = self.resolve_request_timeout_seconds()
            self.task_store.update_task(
                task_id,
                status="failed",
                message=f"图片生成超时，超过 {timeout_seconds} 秒",
            )
            self.ctx.logger.warning("后台创建图片超时: timeout=%ss", timeout_seconds)
        except Exception as exc:
            self.task_store.update_task(
                task_id,
                status="failed",
                message=str(exc),
            )
            self.ctx.logger.error("后台创建图片失败: %s", exc, exc_info=True)

    async def _background_edit_image(
        self,
        *,
        task_id: str,
        prompt: str,
        stream_id: str,
        resolved_model: str,
        openai_compatibility_mode: str,
        source_image_bytes: bytes,
        matched_message_id: str,
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
    ) -> None:
        """后台执行图生图编辑。"""

        try:
            self.task_store.update_task(
                task_id,
                status="running",
                message="图片正在编辑中",
            )
            self.ctx.logger.info(
                "后台图生图开始: stream_id=%s user_id=%s group_id=%s platform=%s model=%s openai_mode=%s source_message_id=%s prompt_preview=%s",
                stream_id,
                user_id,
                group_id,
                platform_name,
                resolved_model,
                openai_compatibility_mode,
                matched_message_id,
                prompt[:120],
            )
            image_platform, provider_name = self.router.require_platform_for_model(
                resolved_model,
                openai_compatibility_mode,
            )
            image_bytes_list = await self.run_provider_call(
                image_platform.edit_images,
                prompt,
                resolved_model,
                source_image_bytes,
                1,
            )
            if not image_bytes_list:
                self.task_store.update_task(
                    task_id,
                    status="failed",
                    message="图片平台没有返回任何图片结果",
                )
                self.ctx.logger.warning(
                    "后台图生图无结果: stream_id=%s model=%s source_message_id=%s",
                    stream_id,
                    resolved_model,
                    matched_message_id,
                )
                return

            reviewed_images, rejected_reasons = await self.filter_reviewed_images(prompt, image_bytes_list)
            if not reviewed_images:
                review_reason_text = "；".join(rejected_reasons) if rejected_reasons else "审核未通过"
                self.task_store.update_task(
                    task_id,
                    status="rejected",
                    message=review_reason_text,
                )
                self.ctx.logger.warning(
                    "后台图生图结果被全部拦截: stream_id=%s model=%s source_message_id=%s reasons=%s",
                    stream_id,
                    resolved_model,
                    matched_message_id,
                    review_reason_text,
                )
                await self.send_text_with_fallback(
                    text=f"图片编辑完成了，但结果未通过审核，已拦截发送。{review_reason_text}",
                    stream_id=stream_id,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform_name,
                )
                return

            sent_count = await self.stream_service.send_generated_images_with_fallback(
                stream_id=stream_id,
                image_bytes_list=reviewed_images,
                user_id=user_id,
                group_id=group_id,
                platform=platform_name,
            )
            self.task_store.update_task(
                task_id,
                status="completed",
                message=f"图片已发送，数量={sent_count}",
                sent_count=sent_count,
            )
            self.ctx.logger.info(
                "后台图片编辑完成: provider=%s model=%s count=%s source_message_id=%s",
                provider_name,
                resolved_model,
                sent_count,
                matched_message_id,
            )
        except TimeoutError:
            timeout_seconds = self.resolve_request_timeout_seconds()
            self.task_store.update_task(
                task_id,
                status="failed",
                message=f"图片编辑超时，超过 {timeout_seconds} 秒",
            )
            self.ctx.logger.warning("后台编辑图片超时: timeout=%ss", timeout_seconds)
        except Exception as exc:
            self.task_store.update_task(
                task_id,
                status="failed",
                message=str(exc),
            )
            self.ctx.logger.error("后台编辑图片失败: %s", exc, exc_info=True)

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
        notify_start: bool = True,
    ) -> dict[str, Any]:
        """启动后台文生图。"""

        task_record = self.task_store.create_task(
            stream_id=stream_id,
            task_type="draw",
            prompt=prompt,
            model=resolved_model,
            provider=provider_name,
            message="任务已创建，等待后台执行",
        )
        background_task = asyncio.create_task(
            self._background_draw(
                task_id=task_record.task_id,
                prompt=prompt,
                stream_id=stream_id,
                resolved_model=resolved_model,
                openai_compatibility_mode=resolved_openai_mode,
                user_id=user_id,
                group_id=group_id,
                platform_name=platform_name,
            )
        )
        self.track_background_task(background_task)
        if notify_start:
            await self.send_text_with_fallback(
                text=f"开始生成图片了，当前模型是 {resolved_model}。这次会在后台慢慢跑，生成完成后我会直接把图片发出来。",
                stream_id=stream_id,
                user_id=user_id,
                group_id=group_id,
                platform=platform_name,
            )
        return {
            "success": True,
            "message": (
                f"已开始后台生成图片，task_id={task_record.task_id}。"
                "这是异步任务。当前不要立刻反复调用 draw_status；请先正常回复用户正在生成中，"
                f"至少等待 {self.STATUS_RECHECK_INTERVAL_SECONDS} 秒后再查询状态。"
            ),
            "provider": provider_name,
            "model": resolved_model,
            "openai_compatibility_mode": resolved_openai_mode,
            "timeout_seconds": self.resolve_request_timeout_seconds(),
            "task_id": task_record.task_id,
        }

    async def start_background_edit_request(
        self,
        *,
        prompt: str,
        stream_id: str,
        resolved_model: str,
        resolved_openai_mode: str,
        provider_name: str,
        source_image_bytes: bytes,
        matched_message_id: str,
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
    ) -> dict[str, Any]:
        """启动后台图生图。"""

        task_record = self.task_store.create_task(
            stream_id=stream_id,
            task_type="edit_image",
            prompt=prompt,
            model=resolved_model,
            provider=provider_name,
            message="任务已创建，等待后台执行",
        )
        background_task = asyncio.create_task(
            self._background_edit_image(
                task_id=task_record.task_id,
                prompt=prompt,
                stream_id=stream_id,
                resolved_model=resolved_model,
                openai_compatibility_mode=resolved_openai_mode,
                source_image_bytes=source_image_bytes,
                matched_message_id=matched_message_id,
                user_id=user_id,
                group_id=group_id,
                platform_name=platform_name,
            )
        )
        self.track_background_task(background_task)
        await self.send_text_with_fallback(
            text="开始后台编辑图片了，完成后我会直接把结果发出来。",
            stream_id=stream_id,
            user_id=user_id,
            group_id=group_id,
            platform=platform_name,
        )
        return {
            "success": True,
            "message": (
                f"已开始后台编辑图片，task_id={task_record.task_id}。"
                "这是异步任务。当前不要立刻反复调用 draw_status；请先正常回复用户正在处理中，"
                f"至少等待 {self.STATUS_RECHECK_INTERVAL_SECONDS} 秒后再查询状态。"
            ),
            "provider": provider_name,
            "model": resolved_model,
            "openai_compatibility_mode": resolved_openai_mode,
            "source_message_id": matched_message_id,
            "timeout_seconds": self.resolve_request_timeout_seconds(),
            "task_id": task_record.task_id,
        }
