from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import base64
import re

from .config import DrawpicConfig
from .image_utils import detect_image_format


@dataclass(slots=True)
class ModerationResult:
    """审核结果。"""

    passed: bool
    reason: str
    raw_response: str


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

    async def review_prompt(self, prompt: str) -> ModerationResult:
        """审核用户提示词。"""

        if not self.is_prompt_review_enabled():
            return ModerationResult(passed=True, reason="", raw_response="SKIPPED")

        rendered_prompt = self._render_template(
            self.config.general.prompt_review_prompt,
            prompt,
        )
        response = await self.ctx.llm.generate(
            rendered_prompt,
            model="replyer",
            temperature=0.0,
            max_tokens=512,
        )
        return self._parse_review_response(self._extract_llm_response(response))

    async def review_image(self, prompt: str, image_bytes: bytes) -> ModerationResult:
        """审核生成图片。"""

        if not self.is_image_review_enabled():
            return ModerationResult(passed=True, reason="", raw_response="SKIPPED")

        rendered_prompt = self._render_template(
            self.config.general.image_review_prompt,
            prompt,
        )
        image_format = self._detect_image_format(image_bytes)
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        response = await self.ctx.llm.generate(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": rendered_prompt},
                        {
                            "type": "image",
                            "image_format": image_format,
                            "image_base64": image_base64,
                        },
                    ],
                }
            ],
            model="vlm",
            temperature=0.0,
            max_tokens=512,
        )
        return self._parse_review_response(self._extract_llm_response(response))

    @staticmethod
    def _extract_llm_response(response: dict[str, Any]) -> str:
        """从 SDK LLM 能力返回中提取文本响应。"""

        if not response.get("success", False):
            raise RuntimeError(str(response.get("error") or "审核模型调用失败"))
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
            raise RuntimeError("审核模型返回了空结果")

        conclusion_matches = list(
            DrawpicModerationService._REVIEW_CONCLUSION_PATTERN.finditer(normalized_response)
        )
        if len(conclusion_matches) != 1:
            raise RuntimeError(f"审核模型返回了无法识别的结果：{normalized_response}")

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
