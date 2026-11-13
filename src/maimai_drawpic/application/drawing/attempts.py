"""按配置顺序执行模型尝试，并在单个模型内进行有界重试。"""

from typing import List, Optional, Tuple
import aiohttp

from ...domain.errors import ProviderError, ProviderOutcomeUnknown, ProviderRequestError, ProviderResultError, ProviderSubmittedError
from .types import ImageRequestAttempt
from .admission import update_task_owned
from ...domain.task_errors import provider_task_error


class RequestAttemptRunnerMixin:
    async def _execute_request_plan(
        self,
        *,
        primary_attempt: ImageRequestAttempt,
        primary_model: str,
        prompt: str,
        task_id: str,
        task_type: str,
        openai_compatibility_mode: str,
        novelai_mode: str,
        novelai_artist_tags: str,
        source_image_bytes_list: List[bytes],
        source_image_urls: List[str],
        matched_message_id: str,
        request_negative_prompt: str,
        style_negative_prompt_template: str = "",
        strict_reference_inputs: bool = False,
    ) -> Tuple[List[bytes], Optional[ImageRequestAttempt], List[str]]:
        # 模式参数只携带调用方/会话的显式覆盖；空值由每个备选实例自行解析默认值。
        errors: List[str] = []
        failure = None
        seen = set()
        models = [primary_model, *self.router.resolve_fallback_models(primary_model)]
        retry_count = self.router.config.general.request_retry_count
        for position, model in enumerate(models):
            attempt = (
                primary_attempt
                if position == 0
                else self._build_fallback_image_request_attempt(
                    primary_model=primary_model,
                    primary_effective_model=primary_attempt.model,
                    task_type=task_type,
                    openai_compatibility_mode=openai_compatibility_mode,
                    novelai_mode=novelai_mode,
                    novelai_artist_tags=novelai_artist_tags,
                    fallback_model=model,
                )
            )
            if attempt is None or attempt.model in seen:
                continue
            seen.add(attempt.model)
            try:
                self.router.validate_source_image_count(attempt.model, len(source_image_bytes_list))
            except ValueError as exc:
                errors.append(self._format_attempt_error(attempt, str(exc)))
                self.ctx.logger.warning("备选模型源图数量校验拒绝: task_id=%s model=%s reason=%s", task_id, model, exc)
                continue
            for retry in range(retry_count + 1):
                await update_task_owned(
                    self.task_store,
                    task_id,
                    status="running",
                    model=attempt.model,
                    provider=attempt.provider_name,
                    message=f"{'备选' if position else '首选'}模型 {attempt.model}，第 {retry + 1}/{retry_count + 1} 次尝试",
                )
                try:
                    images = await self._run_image_request_attempt(
                        attempt=attempt,
                        prompt=prompt,
                        task_id=task_id,
                        task_type=task_type,
                        source_image_bytes_list=source_image_bytes_list,
                        source_image_urls=source_image_urls,
                        matched_message_id=matched_message_id,
                        request_negative_prompt=request_negative_prompt,
                        style_negative_prompt_template=style_negative_prompt_template,
                    )
                    if not images:
                        raise ProviderResultError("已收到图片平台响应，但没有可用图片；未重新提交生成")
                    self.ctx.logger.info(
                        "模型尝试成功: task_id=%s task_type=%s provider=%s model=%s attempt=%s source_image_count=%s",
                        task_id,
                        task_type,
                        attempt.provider_name,
                        attempt.model,
                        retry + 1,
                        len(source_image_bytes_list),
                    )
                    return images, attempt, errors
                except Exception as exc:
                    if isinstance(exc, ProviderError):
                        failure = exc
                    elif isinstance(exc, (TimeoutError, aiohttp.ClientConnectionError)):
                        failure = ProviderOutcomeUnknown(
                            "图片请求超时或连接中断，远端受理状态不确定，未自动重绘；请先检查提供商记录"
                        )
                    else:
                        # 未分类异常不代表请求未受理；禁止根据错误字符串猜测可重绘。
                        failure = ProviderError(str(exc) or type(exc).__name__)
                    reason = self.task_store.sanitize_message(str(failure))
                    if failure.outcome_unknown and not isinstance(
                        failure, (ProviderOutcomeUnknown, ProviderSubmittedError)
                    ):
                        reason = "远端受理状态不确定，未自动重绘；" + reason
                    if failure.rejected:
                        raise failure from None
                errors.append(self._format_attempt_error(attempt, reason))
                self.ctx.logger.warning(
                    "模型尝试失败: task_id=%s task_type=%s provider=%s model=%s attempt=%s retry_limit=%s reason=%s",
                    task_id,
                    task_type,
                    attempt.provider_name,
                    attempt.model,
                    retry + 1,
                    retry_count,
                    reason,
                )
                if not failure.retryable:
                    break
            input_rejected = strict_reference_inputs and isinstance(failure, ProviderRequestError) and 400 <= failure.status < 500 and not failure.retryable
            if not failure.allow_fallback or input_rejected:
                await update_task_owned(
                    self.task_store,
                    task_id,
                    status="failed",
                    message=reason,
                    error=provider_task_error(failure, reason),
                )
                return [], None, errors
        if failure is not None:
            await update_task_owned(
                self.task_store,
                task_id,
                status="failed",
                message=reason,
                error=provider_task_error(failure, reason),
            )
        return [], None, errors
