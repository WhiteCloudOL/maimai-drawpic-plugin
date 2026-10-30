import re
import unicodedata

from ..moderation import DrawpicModerationService
from ...domain.errors import ProviderRequestError


class PromptReviewMixin:
    """PromptReviewMixin 的独立绘图职责。"""

    async def review_prompt_or_raise(self, prompt: str, *, task_id: str = "") -> None:
        """在提交绘图请求前审核提示词。"""

        if not self.moderation_service.is_prompt_review_enabled():
            return

        try:
            review_result = await self.moderation_service.review_prompt(prompt, task_id=task_id)
        except Exception as exc:
            self.ctx.logger.warning("提示词审核终止: task_id=%s error_type=%s", task_id, type(exc).__name__)
            raise
        if review_result.passed:
            self.ctx.logger.info("提示词审核通过: task_id=%s", task_id)
        else:
            self.ctx.logger.info("提示词审核未通过: task_id=%s", task_id)
        if not review_result.passed:
            reason_suffix = f"原因：{review_result.reason}" if review_result.reason else "原因：审核模型判定为不通过"
            raise ProviderRequestError(
                400, "content_policy_violation", f"提示词审核未通过，已拒绝本次绘图请求。{reason_suffix}"
            )

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
        *,
        task_id: str = "",
    ) -> tuple[list[bytes], list[str]]:
        """审核生成图片，并返回通过审核的图片列表。"""

        if not self.moderation_service.is_image_review_enabled():
            return image_bytes_list, []

        approved_images: list[bytes] = []
        rejected_reasons: list[str] = []
        for index, image_bytes in enumerate(image_bytes_list, start=1):
            try:
                review_result = await self.moderation_service.review_image(
                    prompt, image_bytes, task_id=task_id, image_index=index,
                )
            except Exception as exc:
                self.ctx.logger.warning(
                    "图片审核终止: task_id=%s image_index=%s error_type=%s", task_id, index, type(exc).__name__,
                )
                raise
            if review_result.passed:
                self.ctx.logger.info("图片审核通过: task_id=%s image_index=%s", task_id, index)
                approved_images.append(image_bytes)
                continue

            rejected_reason = review_result.reason or "审核模型判定为不通过"
            self.ctx.logger.info("图片审核未通过: task_id=%s image_index=%s", task_id, index)
            rejected_reasons.append(f"第 {index} 张：{rejected_reason}")

        return approved_images, rejected_reasons
