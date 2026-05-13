from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

import base64

from PIL import Image as PILImage

from src.services.llm_service import LLMServiceClient

from .config import DrawpicConfig


@dataclass(slots=True)
class ModerationResult:
    """审核结果。"""

    passed: bool
    reason: str
    raw_response: str


class DrawpicModerationService:
    """负责提示词与生成图片审核。"""

    def __init__(self, config: DrawpicConfig) -> None:
        self.config = config
        self._prompt_reviewer = LLMServiceClient(
            task_name="replyer",
            request_type="drawpic.prompt_review",
        )
        self._image_reviewer = LLMServiceClient(
            task_name="vlm",
            request_type="drawpic.image_review",
        )

    def is_prompt_review_enabled(self) -> bool:
        """是否启用提示词审核。"""

        return bool(self.config.prompt_review.enabled)

    def is_image_review_enabled(self) -> bool:
        """是否启用图片审核。"""

        return bool(self.config.image_review.enabled)

    async def review_prompt(self, prompt: str) -> ModerationResult:
        """审核用户提示词。"""

        if not self.is_prompt_review_enabled():
            return ModerationResult(passed=True, reason="", raw_response="SKIPPED")

        rendered_prompt = self._render_template(
            self.config.prompt_review.review_prompt,
            prompt,
        )
        response = await self._prompt_reviewer.generate_response(rendered_prompt)
        return self._parse_review_response(response.response)

    async def review_image(self, prompt: str, image_bytes: bytes) -> ModerationResult:
        """审核生成图片。"""

        if not self.is_image_review_enabled():
            return ModerationResult(passed=True, reason="", raw_response="SKIPPED")

        rendered_prompt = self._render_template(
            self.config.image_review.review_prompt,
            prompt,
        )
        image_format = self._detect_image_format(image_bytes)
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        response = await self._image_reviewer.generate_response_for_image(
            rendered_prompt,
            image_base64,
            image_format,
        )
        return self._parse_review_response(response.response)

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

        with PILImage.open(BytesIO(image_bytes)) as image:
            format_name = str(image.format or "").strip().lower()
        if format_name in {"jpg", "jpeg", "png", "webp", "gif"}:
            return format_name
        return "png"

    @staticmethod
    def _parse_review_response(raw_response: str | None) -> ModerationResult:
        """解析模型返回的审核结论。"""

        normalized_response = str(raw_response or "").strip()
        if not normalized_response:
            raise RuntimeError("审核模型返回了空结果")

        upper_response = normalized_response.upper()
        first_line = normalized_response.splitlines()[0].strip().upper()

        if "REJECT" in first_line or "REJECT" in upper_response or "结论：REJECT" in normalized_response:
            return ModerationResult(
                passed=False,
                reason=DrawpicModerationService._extract_reason(normalized_response, default_reason="审核未通过"),
                raw_response=normalized_response,
            )
        if "PASS" in first_line or "PASS" in upper_response or "结论：PASS" in normalized_response:
            return ModerationResult(
                passed=True,
                reason=DrawpicModerationService._extract_reason(normalized_response),
                raw_response=normalized_response,
            )
        raise RuntimeError(f"审核模型返回了无法识别的结果：{normalized_response}")

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
