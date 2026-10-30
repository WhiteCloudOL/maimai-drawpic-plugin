from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Union
import asyncio
import base64
import re

from ..domain.configuration.models import DrawpicConfig
from ..domain.configuration.types import ReviewModelTask
from ..infrastructure.http import sanitize_provider_text
from ..infrastructure.media.images import detect_image_format


@dataclass(slots=True)
class ModerationResult:
    """审核结果。"""

    passed: bool
    reason: str
    raw_response: str


class ReviewError(RuntimeError):
    """保留可定位的审核错误码，日志不需要输出完整模型响应。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class DrawpicModerationService:
    """负责提示词与生成图片审核。"""

    _REVIEW_CONCLUSION_PATTERN = re.compile(
        r"^\s*(?:结论|CONCLUSION)\s*[:：]\s*(PASS|REJECT)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    def __init__(self, config: DrawpicConfig, ctx: Any) -> None:
        self.config = config
        self.ctx = ctx

    def is_prompt_review_enabled(self) -> bool:
        """是否启用提示词审核。"""

        return bool(self.config.general.prompt_review_enabled)

    def is_image_review_enabled(self) -> bool:
        """是否启用图片审核。"""

        return bool(self.config.general.image_review_enabled)

    async def review_prompt(self, prompt: str, *, task_id: str = "") -> ModerationResult:
        """审核用户提示词。"""

        if not self.is_prompt_review_enabled():
            return ModerationResult(passed=True, reason="", raw_response="SKIPPED")

        rendered_prompt = self._render_template(
            self.config.general.prompt_review_prompt,
            prompt,
        )
        return await self._review(
            rendered_prompt,
            model=self.config.general.prompt_review_model,
            timeout_seconds=self.config.general.prompt_review_timeout_seconds,
            retry_count=self.config.general.prompt_review_retry_count,
            stage="提示词审核",
            task_id=task_id,
        )

    async def review_image(
        self, prompt: str, image_bytes: bytes, *, task_id: str = "", image_index: int = 0,
    ) -> ModerationResult:
        """审核生成图片。"""

        if not self.is_image_review_enabled():
            return ModerationResult(passed=True, reason="", raw_response="SKIPPED")

        rendered_prompt = self._render_template(
            self.config.general.image_review_prompt,
            prompt,
        )
        messages = await asyncio.to_thread(self._image_messages, rendered_prompt, image_bytes)
        return await self._review(
            messages,
            model=self.config.general.image_review_model,
            timeout_seconds=self.config.general.image_review_timeout_seconds,
            retry_count=self.config.general.image_review_retry_count,
            stage="图片审核",
            task_id=task_id,
            image_index=image_index,
        )

    async def _review(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        *,
        model: ReviewModelTask,
        timeout_seconds: int,
        retry_count: int,
        stage: str,
        task_id: str,
        image_index: int = 0,
    ) -> ModerationResult:
        """仅重试审核调用和解析失败；明确拒绝直接返回，取消立即向上传播。"""
        loop = asyncio.get_running_loop()
        total_attempts = retry_count + 1
        attempt = 0
        started = loop.time()
        try:
            for attempt in range(1, total_attempts + 1):
                started = loop.time()
                self.ctx.logger.info(
                    "审核请求开始: task_id=%s stage=%s image_index=%s model_task=%s attempt=%s total_attempts=%s timeout_seconds=%s",
                    task_id, stage, image_index, model, attempt, total_attempts, timeout_seconds,
                )
                try:
                    response = await self._generate_review(
                        prompt, model=model, timeout_seconds=timeout_seconds, stage=stage,
                    )
                    result = self._parse_review_response(self._extract_llm_response(response))
                except Exception as exc:
                    will_retry = attempt < total_attempts
                    code = exc.code if isinstance(exc, ReviewError) else type(exc).__name__
                    detail = str(exc) if isinstance(exc, ReviewError) else ""
                    self.ctx.logger.warning(
                        "审核请求失败: task_id=%s stage=%s image_index=%s model_task=%s attempt=%s total_attempts=%s "
                        "error_code=%s error_type=%s retrying=%s duration_ms=%s error=%s",
                        task_id, stage, image_index, model, attempt, total_attempts,
                        code, type(exc).__name__, will_retry, round((loop.time() - started) * 1000), detail,
                    )
                    if not will_retry:
                        raise
                    await asyncio.sleep(min(0.25 * attempt, 1.0))
                    continue
                self.ctx.logger.info(
                    "审核请求完成: task_id=%s stage=%s image_index=%s model_task=%s attempt=%s total_attempts=%s result=%s duration_ms=%s",
                    task_id, stage, image_index, model, attempt, total_attempts,
                    "PASS" if result.passed else "REJECT", round((loop.time() - started) * 1000),
                )
                return result
        except asyncio.CancelledError:
            self.ctx.logger.info(
                "审核已取消: task_id=%s stage=%s image_index=%s model_task=%s attempt=%s total_attempts=%s duration_ms=%s",
                task_id, stage, image_index, model, attempt, total_attempts,
                round((loop.time() - started) * 1000),
            )
            raise
        raise AssertionError("unreachable review retry state")

    async def _generate_review(
        self,
        prompt: Union[str, List[Dict[str, Any]]],
        *,
        model: ReviewModelTask,
        timeout_seconds: int,
        stage: str,
    ) -> Dict[str, Any]:
        """同时覆盖 Runner RPC 和本地等待；超时或取消后的结果不能重新放行。"""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        try:
            async with asyncio.timeout_at(deadline):
                response = await self.ctx.llm.generate(
                    prompt,
                    model=model,
                    temperature=0.0,
                    max_tokens=512,
                    rpc_timeout_ms=timeout_seconds * 1000,
                )
            # 即使下游吞掉取消并返回 PASS，也不得接受已经过期的审核结果。
            if loop.time() >= deadline:
                raise TimeoutError
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError
            return response
        except TimeoutError:
            raise ReviewError("REVIEW_TIMEOUT", f"{stage}等待超时，超过 {timeout_seconds} 秒，未通过审核") from None

    @classmethod
    def _image_messages(cls, rendered_prompt: str, image_bytes: bytes) -> List[Dict[str, Any]]:
        """在线程内读取图片格式并编码，不占用 Runner 事件循环。"""
        image_format = cls._detect_image_format(image_bytes)
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": rendered_prompt},
                    {"type": "image", "image_format": image_format, "image_base64": image_base64},
                ],
            }
        ]

    @staticmethod
    def _extract_llm_response(response: dict[str, Any]) -> str:
        """从 SDK LLM 能力返回中提取文本响应。"""

        if not response.get("success", False):
            raise ReviewError("MODEL_CALL_FAILED", sanitize_provider_text(response.get("error") or "审核模型调用失败"))
        return str(response.get("response") or response.get("content") or "").strip()

    @staticmethod
    def _render_template(template: str, user_prompt: str) -> str:
        """渲染审核提示模板。"""

        normalized_template = str(template or "").strip()
        if not normalized_template:
            raise ValueError("审核提示词不能为空")
        return normalized_template.replace("{user_prompt}", user_prompt)

    @staticmethod
    def _detect_image_format(image_bytes: bytes) -> str:
        """根据图片字节推断格式。"""

        return detect_image_format(image_bytes)

    @staticmethod
    def _parse_review_response(raw_response: str | None) -> ModerationResult:
        """解析模型返回的审核结论。

        仅接受独立、结构化的 PASS / REJECT 结论行，避免否定句中的关键词造成误判。
        """

        normalized_response = str(raw_response or "").strip()
        if not normalized_response:
            raise ReviewError("EMPTY_RESPONSE", "审核模型返回了空结果")

        conclusion_matches = list(DrawpicModerationService._REVIEW_CONCLUSION_PATTERN.finditer(normalized_response))
        if len(conclusion_matches) != 1:
            raise ReviewError("INVALID_RESPONSE", "审核模型返回了无法识别的结果：需要唯一的 PASS 或 REJECT 结论行")

        conclusion_match = conclusion_matches[0]
        conclusion = conclusion_match.group(1).upper()
        if conclusion == "REJECT":
            return ModerationResult(
                passed=False,
                reason=DrawpicModerationService._extract_reason(normalized_response, default_reason="审核未通过"),
                raw_response=normalized_response,
            )
        return ModerationResult(
            passed=True,
            reason=DrawpicModerationService._extract_reason(normalized_response),
            raw_response=normalized_response,
        )

    @staticmethod
    def _extract_reason(response_text: str, default_reason: str = "") -> str:
        """从审核响应中提取原因。"""

        for line in response_text.splitlines():
            normalized_line = line.strip()
            if normalized_line.startswith("原因："):
                return normalized_line.removeprefix("原因：").strip()
            if normalized_line.lower().startswith("reason:"):
                return normalized_line[7:].strip()
        return default_reason
