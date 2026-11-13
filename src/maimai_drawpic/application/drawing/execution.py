from typing import Awaitable, Callable, Optional
import asyncio
import inspect

from ..chat import ImageDeliveryError, ImageDeliveryUnconfirmedError
from ...infrastructure.storage.retention import CacheCapacityError
from ...domain.errors import ProviderError
from ...domain.task_errors import TaskRequestError, provider_task_error, task_error
from ..references.service import ReferencePreparation
from .admission import update_task_owned


class ImageExecutionMixin:
    """ImageExecutionMixin 的独立绘图职责。"""

    async def _background_image_request(
        self,
        *,
        task_id: str,
        prompt: str,
        stream_id: str,
        resolved_model: str,
        openai_compatibility_mode: str = "",
        novelai_mode: str = "",
        novelai_artist_tags: str = "",
        request_negative_prompt: str = "",
        style_negative_prompt_template: str = "",
        source_image_bytes_list: list[bytes] | None = None,
        source_image_urls: list[str] | None = None,
        matched_message_id: str = "",
        user_id: str = "",
        group_id: str = "",
        platform_name: str = "qq",
        prompt_reviewed: bool = True,
        on_task_unsuccessful: Callable[[str, str, str], Awaitable[None] | None] | None = None,
        on_task_successful: Callable[[str, str, str], Awaitable[None] | None] | None = None,
        reference_preparation: Optional[ReferencePreparation] = None,
    ) -> None:
        """后台执行绘图任务，源图为空时文生图，存在源图时图生图。"""

        self._started_task_ids.add(task_id)
        notified = False
        delivery_started = False

        async def _update_terminal(**changes) -> None:
            await self.persist_terminal(task_id, **changes)

        async def _notify_task_unsuccessful(status: str, reason: str) -> None:
            nonlocal notified
            if notified:
                return
            notified = True
            reason = self.task_store.sanitize_message(reason)
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

        async def _notify_task_successful(status: str, reason: str) -> None:
            nonlocal notified
            if notified:
                return
            notified = True
            reason = self.task_store.sanitize_message(reason)
            if on_task_successful is None:
                return
            try:
                result = on_task_successful(task_id, status, reason)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                self.ctx.logger.error(
                    "绘图任务成功回调执行异常: task_id=%s status=%s reason=%s error=%s",
                    task_id,
                    status,
                    reason,
                    exc,
                    exc_info=True,
                )

        normalized_source_images = source_image_bytes_list or []
        normalized_source_urls = source_image_urls or [""] * len(normalized_source_images)
        is_image_edit = bool(normalized_source_images)
        task_type = "edit_image" if is_image_edit else "draw"
        running_message = "图片正在编辑中" if is_image_edit else "图片正在生成中"
        timeout_message = "图片编辑超时" if is_image_edit else "图片生成超时"
        try:
            if reference_preparation is not None:
                await update_task_owned(self.task_store, task_id, status="running", message="正在准备参考图片与预设")
                try:
                    async with asyncio.timeout(90):
                        prepared = await reference_preparation.prepare(task_id)
                except TimeoutError:
                    raise TaskRequestError("MATERIAL_PREPARATION_TIMEOUT", "参考素材准备超过 90 秒，请直接提供素材后重试") from None
                prompt = prepared.prompt
                style_negative_prompt_template = prepared.negative_template
                normalized_source_images, normalized_source_urls = prepared.images, prepared.urls
                task_type = prepared.task_type
                is_image_edit = task_type == "edit_image"
                running_message = "图片正在编辑中" if is_image_edit else "图片正在生成中"
                timeout_message = "图片编辑超时" if is_image_edit else "图片生成超时"
                self.router.validate_source_image_count(resolved_model, len(normalized_source_images))
                if normalized_source_images and any(not url for url in normalized_source_urls):
                    self.router.validate_local_source_images(resolved_model)
                await update_task_owned(self.task_store, task_id, status="running", message=running_message, task_type=task_type)
            if not prompt_reviewed:
                review_record = await update_task_owned(
                    self.task_store, task_id, status="running", message="正在审核提示词",
                )
                if review_record is None:
                    await _notify_task_unsuccessful("failed", "绘图任务已失效")
                    return
                await self.review_prompt_or_raise(prompt, task_id=task_id)
            running_record = await update_task_owned(
                self.task_store,
                task_id,
                status="running",
                message=running_message,
            )
            if running_record is None:
                # 任务记录已失效时结束执行，并通知调用方释放预留资源。
                self.ctx.logger.warning("绘图任务记录已失效，终止后台执行: task_id=%s task_type=%s", task_id, task_type)
                await _notify_task_unsuccessful("failed", "任务记录已失效")
                return
            primary_attempt = self._build_image_request_attempt(
                model=resolved_model,
                task_type=task_type,
                openai_compatibility_mode=openai_compatibility_mode,
                novelai_mode=novelai_mode,
                novelai_artist_tags=novelai_artist_tags,
            )
            await update_task_owned(
                self.task_store,
                task_id,
                status="running",
                message=running_message,
                model=primary_attempt.model,
                provider=primary_attempt.provider_name,
            )

            image_bytes_list, successful_attempt, attempt_errors = await self._execute_request_plan(
                primary_attempt=primary_attempt,
                primary_model=resolved_model,
                prompt=prompt,
                task_id=task_id,
                task_type=task_type,
                openai_compatibility_mode=openai_compatibility_mode,
                novelai_mode=novelai_mode,
                novelai_artist_tags=novelai_artist_tags,
                source_image_bytes_list=normalized_source_images,
                source_image_urls=normalized_source_urls,
                matched_message_id=matched_message_id,
                request_negative_prompt=request_negative_prompt,
                style_negative_prompt_template=style_negative_prompt_template,
            )

            if successful_attempt is None:
                failure_message = "；".join(attempt_errors) if attempt_errors else "图片平台没有返回任何图片结果"
                await _update_terminal(
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
                    self.router.config.general.fallback_models,
                    failure_message,
                )
                return

            await update_task_owned(
                self.task_store,
                task_id,
                status="running",
                message="图片已生成，正在审核结果",
                generated_count=len(image_bytes_list),
            )
            reviewed_images, rejected_reasons = await self.filter_reviewed_images(prompt, image_bytes_list, task_id=task_id)
            if not reviewed_images:
                review_reason_text = "；".join(rejected_reasons) if rejected_reasons else "审核未通过"
                if successful_attempt.is_fallback and attempt_errors:
                    review_reason_text = f"首选模型失败后使用备选模型生成，但图片审核未通过：{review_reason_text}"
                await _update_terminal(
                    status="rejected",
                    message=review_reason_text,
                    error=task_error("MODERATION_REJECTED", review_reason_text),
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

            result_count = 0
            await update_task_owned(
                self.task_store,
                task_id,
                status="running",
                message="图片已生成，正在保存结果",
                expected_delivery_count=len(reviewed_images) if stream_id else 0,
            )
            cache_message = ""
            if self.result_store is not None:
                try:
                    result_count = await asyncio.to_thread(self.result_store.save, task_id, reviewed_images)
                except CacheCapacityError as exc:
                    cache_message = f"；图片未缓存：{exc}，可在 MaiBot 插件配置页调整缓存上限"
                    self.ctx.logger.warning("绘图结果未缓存: task_id=%s reason=%s", task_id, exc)
                await update_task_owned(
                    self.task_store,
                    task_id,
                    status="running",
                    message="图片已生成",
                    result_count=result_count,
                )
            sent_count = 0
            if stream_id:
                delivery_started = True
                sent_count = await self.stream_service.send_generated_images_with_fallback(
                    stream_id=stream_id,
                    image_bytes_list=reviewed_images,
                    user_id=user_id,
                    group_id=group_id,
                    platform=platform_name,
                    task_id=task_id,
                    provider=successful_attempt.provider_name,
                    model=successful_attempt.model,
                    sync_to_maisaka_history=self.router.config.general.sync_generated_images_to_history,
                    task_type=task_type,
                    source_image_count=len(normalized_source_images),
                )
                delivery_started = False
            elif self.router.config.general.sync_generated_images_to_history:
                self.ctx.logger.debug(
                    "生成结果未投递，跳过会话历史同步: task_id=%s task_type=%s provider=%s model=%s "
                    "source_image_count=%s history_sync_requested=False",
                    task_id, task_type, successful_attempt.provider_name, successful_attempt.model,
                    len(normalized_source_images),
                )
            success_message = (
                f"图片已发送，数量={sent_count}" if stream_id else f"图片已生成，数量={len(reviewed_images)}"
            )
            if successful_attempt.is_fallback:
                action = "发送" if stream_id else "生成"
                success_message = f"首选模型失败，已使用生图备选模型{action}图片，数量={sent_count if stream_id else len(reviewed_images)}"
            success_message += cache_message
            await _update_terminal(
                status="completed",
                message=success_message,
                sent_count=sent_count,
                model=successful_attempt.model,
                provider=successful_attempt.provider_name,
            )
            await _notify_task_successful("completed", success_message)
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
            settled = self.task_store.get_task(task_id)
            if settled is not None and settled.status in {"completed", "failed", "rejected"}:
                # An owned terminal write can win the cancellation race. Preserve
                # the recorded outcome and settle according to that outcome.
                if settled.status == "completed":
                    await _notify_task_successful(settled.status, settled.message)
                else:
                    await _notify_task_unsuccessful(settled.status, settled.message)
            else:
                await _update_terminal(
                    status="failed",
                    message="任务已取消",
                    error=task_error("CANCELLED", "本地等待已取消，不代表上游撤单或停止计费"),
                    delivery_unconfirmed=delivery_started,
                )
                await _notify_task_unsuccessful("failed", "任务已取消")
            self.ctx.logger.warning(
                "绘图任务收到取消请求: task_id=%s task_type=%s model=%s", task_id, task_type, resolved_model
            )
            raise
        except TaskRequestError as exc:
            message = self.task_store.sanitize_message(str(exc))
            await _update_terminal(status="failed", message=message, error=task_error(exc.code, message))
            await _notify_task_unsuccessful("failed", message)
            self.ctx.logger.warning("参考准备失败: task_id=%s task_type=%s model=%s code=%s reason=%s",
                                    task_id, task_type, resolved_model, exc.code, message, exc_info=exc.__cause__ is not None)
        except ProviderError as exc:
            status = "rejected" if exc.rejected else "failed"
            message = self.task_store.sanitize_message(str(exc))
            await _update_terminal(
                status=status,
                message=message,
                error=provider_task_error(exc, message),
            )
            await _notify_task_unsuccessful(status, message)
            self.ctx.logger.warning("绘图请求已终止: task_id=%s status=%s reason=%s", task_id, status, message)
        except ImageDeliveryUnconfirmedError as exc:
            # Keep v1 terminal semantics while retaining the independent unknown
            # delivery outcome for v2, including partial confirmed sends.
            status = "completed" if exc.sent_count > 0 else "failed"
            await _update_terminal(
                status=status, message=str(exc), sent_count=exc.sent_count,
                delivery_unconfirmed=True,
                error=task_error("DELIVERY_UNCONFIRMED", str(exc)),
            )
            if exc.sent_count > 0:
                await _notify_task_successful(status, str(exc))
            else:
                await _notify_task_unsuccessful(status, str(exc))
            self.ctx.logger.warning("绘图任务投递结果待确认: task_id=%s sent_count=%s", task_id, exc.sent_count)
        except ImageDeliveryError as exc:
            if exc.sent_count <= 0:
                await _update_terminal(
                    status="failed",
                    message=str(exc),
                    error=task_error("DELIVERY_FAILED", str(exc)),
                )
                await _notify_task_unsuccessful("failed", str(exc))
                self.ctx.logger.error(
                    "绘图任务投递失败: task_id=%s task_type=%s model=%s error=%s",
                    task_id,
                    task_type,
                    resolved_model,
                    exc,
                )
                return

            partial_message = f"部分图片已发送，数量={exc.sent_count}；其余图片投递失败：{exc}"
            await _update_terminal(
                status="completed",
                message=partial_message,
                sent_count=exc.sent_count,
            )
            await _notify_task_successful("completed", partial_message)
            self.ctx.logger.warning(
                "绘图任务部分投递完成: task_id=%s task_type=%s model=%s sent_count=%s error=%s",
                task_id,
                task_type,
                resolved_model,
                exc.sent_count,
                exc,
            )
        except TimeoutError:
            timeout_seconds = self.resolve_request_timeout_seconds()
            await _update_terminal(
                status="failed",
                message=f"{timeout_message}，超过 {timeout_seconds} 秒",
                error=task_error("UPSTREAM_UNCONFIRMED", "本地等待超时，远端执行状态未确认"),
                delivery_unconfirmed=delivery_started,
            )
            await _notify_task_unsuccessful("failed", f"{timeout_message}，超过 {timeout_seconds} 秒")
            self.ctx.logger.error(
                "绘图任务失败: task_id=%s task_type=%s model=%s error=%s",
                task_id,
                task_type,
                resolved_model,
                f"{timeout_message}，超过 {timeout_seconds} 秒",
            )
        except Exception as exc:
            await _update_terminal(
                status="failed",
                message=str(exc),
                error=task_error("EXECUTION_FAILED", str(exc)),
                delivery_unconfirmed=delivery_started,
            )
            await _notify_task_unsuccessful("failed", str(exc))
            self.ctx.logger.error(
                "绘图任务失败: task_id=%s task_type=%s model=%s error=%s",
                task_id,
                task_type,
                resolved_model,
                exc,
                exc_info=True,
            )
        finally:
            if not notified:
                await _notify_task_unsuccessful("failed", "任务执行中断，未完成结算")
