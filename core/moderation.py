from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import base64

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

        采用分层匹配策略，兼容审核模型可能附加的多行前置说明：
        1. 优先全文精确匹配 `结论：PASS` / `结论：REJECT`（含全角冒号）
        2. 退化到逐行查找首个包含 PASS / REJECT 的结论行
        3. 再退化到全文模糊匹配 PASS / REJECT
        4. 仍无法识别时抛出 RuntimeError，由调用方决定拒绝或放行
        """

        normalized_response = str(raw_response or "").strip()
        if not normalized_response:
            raise RuntimeError("审核模型返回了空结果")

        # 1) 全文精确匹配结论行（兼容全角/半角冒号）
        if "结论：REJECT" in normalized_response or "结论:REJECT" in normalized_response or "结论: REJECT" in normalized_response:
            return ModerationResult(
                passed=False,
                reason=DrawpicModerationService._extract_reason(normalized_response, default_reason="审核未通过"),
                raw_response=normalized_response,
            )
        if "结论：PASS" in normalized_response or "结论:PASS" in normalized_response or "结论: PASS" in normalized_response:
            return ModerationResult(
                passed=True,
                reason=DrawpicModerationService._extract_reason(normalized_response),
                raw_response=normalized_response,
            )

        # 2) 逐行查找首个包含明确 PASS / REJECT 关键词的行
        for raw_line in normalized_response.splitlines():
            normalized_line = raw_line.strip().upper()
            if not normalized_line:
                continue
            if "REJECT" in normalized_line:
                return ModerationResult(
                    passed=False,
                    reason=DrawpicModerationService._extract_reason(normalized_response, default_reason="审核未通过"),
                    raw_response=normalized_response,
                )
            if "PASS" in normalized_line:
                return ModerationResult(
                    passed=True,
                    reason=DrawpicModerationService._extract_reason(normalized_response),
                    raw_response=normalized_response,
                )

        # 3) 全文模糊兜底（模型可能把结论拼接在一段话中）
        upper_response = normalized_response.upper()
        if "REJECT" in upper_response:
            return ModerationResult(
                passed=False,
                reason=DrawpicModerationService._extract_reason(normalized_response, default_reason="审核未通过"),
                raw_response=normalized_response,
            )
        if "PASS" in upper_response:
            return ModerationResult(
                passed=True,
                reason=DrawpicModerationService._extract_reason(normalized_response),
                raw_response=normalized_response,
            )

        # 4) 无法识别
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
