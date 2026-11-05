from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List
import re
import unicodedata

from .configuration.models import StyleConfig, StylePresetConfig


@dataclass(frozen=True, slots=True)
class ResolvedStylePrompt:
    """一次风格化绘图最终使用的正向与反向提示词。"""

    style_name: str
    positive_prompt: str
    negative_prompt: str
    negative_prompt_template: str = ""


@dataclass(frozen=True, slots=True)
class StylePresetDetail:
    """提供给用户和模型的风格名称与语义描述。"""

    name: str
    description: str


def merge_prompt_parts(parts: Iterable[str]) -> str:
    """按顺序合并非空提示词片段。"""

    return ", ".join(part.strip(" \t\r\n,") for part in parts if part.strip(" \t\r\n,"))


def deduplicate_negative_prompt(*parts: str) -> str:
    """按词条去重，保留首次顺序以及括号内的权重、转义和分隔符。"""

    terms: List[str] = []
    seen = set()
    closing = {"(": ")", "[": "]", "{": "}", "<": ">"}
    for part in parts:
        stack: List[str] = []
        start = 0
        escaped = False
        weighted = False
        for index, character in enumerate(part + ","):
            if escaped and index < len(part):
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            # NovelAI 的 1.5::tag, tag:: 也是一个整体，不能跨权重区间去重。
            if part[index:index + 2] == "::" and (index == 0 or part[index - 1] != ":"):
                weighted = not weighted
            if character in closing:
                stack.append(closing[character])
            elif stack and character == stack[-1]:
                stack.pop()
            if index == len(part) or (character in ",，;；\n" and not stack and not weighted):
                term = part[start:index].strip()
                normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", term)).casefold()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    terms.append(term)
                start = index + 1
    return ", ".join(terms)


class StylePromptResolver:
    """解析配置中的全平台绘图风格提示词模板。"""

    DEFAULT_STYLE_ALIASES = {"默认", "default"}
    NO_STYLE_ALIASES = {"无", "none", "原始", "plain"}

    def __init__(self, config: StyleConfig) -> None:
        self.config = config

    def get_style_names(self) -> list[str]:
        """返回已启用且名称唯一的风格列表。"""

        return [detail.name for detail in self.get_style_details()]

    def get_style_details(self) -> list[StylePresetDetail]:
        """返回已启用且名称唯一的风格名称与描述。"""

        details: list[StylePresetDetail] = []
        seen: set[str] = set()
        for preset in self.config.presets:
            normalized_name = preset.name.strip()
            lookup_name = normalized_name.casefold()
            if not preset.enabled or not normalized_name or lookup_name in seen:
                continue
            seen.add(lookup_name)
            details.append(
                StylePresetDetail(
                    name=normalized_name,
                    description=preset.description.strip(),
                )
            )
        return details

    def resolve(
        self,
        *,
        style_name: str,
        user_prompt: str,
        user_negative_prompt: str = "",
    ) -> ResolvedStylePrompt:
        """未指定时使用默认风格；显式选择无风格时保持原始描述。"""

        normalized_style_name = style_name.strip()
        if normalized_style_name.casefold() in self.NO_STYLE_ALIASES:
            return ResolvedStylePrompt(
                style_name="",
                positive_prompt=user_prompt.strip(),
                negative_prompt=user_negative_prompt.strip(),
            )
        if not normalized_style_name or normalized_style_name.casefold() in self.DEFAULT_STYLE_ALIASES:
            normalized_style_name = self.config.default_style.strip()
            if not normalized_style_name:
                return ResolvedStylePrompt(
                    style_name="",
                    positive_prompt=user_prompt.strip(),
                    negative_prompt=user_negative_prompt.strip(),
                )

        preset = self._find_preset(normalized_style_name)
        if preset is None:
            available_styles = "、".join(self.get_style_names()) or "未配置"
            raise ValueError(f"未找到绘图风格：{normalized_style_name}。可用风格：{available_styles}")

        positive_prompt = self._render_template(
            preset.positive_prompt_template,
            placeholder="{prompt}",
            user_text=user_prompt,
        )
        negative_prompt = self._render_template(
            preset.negative_prompt_template,
            placeholder="{negative_prompt}",
            user_text=user_negative_prompt,
        )
        return ResolvedStylePrompt(
            style_name=preset.name.strip(),
            positive_prompt=positive_prompt,
            negative_prompt=negative_prompt,
            negative_prompt_template=preset.negative_prompt_template,
        )

    def _find_preset(self, style_name: str) -> StylePresetConfig | None:
        lookup_name = style_name.strip().casefold()
        matches = [
            preset for preset in self.config.presets if preset.enabled and preset.name.strip().casefold() == lookup_name
        ]
        if len(matches) > 1:
            raise ValueError(f"绘图风格名称重复：{style_name}，请在插件配置中保留一个同名风格")
        return matches[0] if matches else None

    @classmethod
    def render_negative_prompt(cls, template: str, negative_prompt: str) -> str:
        """在实例过滤之后渲染风格反向词，保留独立的模板内容并去重。"""

        return deduplicate_negative_prompt(
            cls._render_template(template, placeholder="{negative_prompt}", user_text=negative_prompt)
        )

    @staticmethod
    def _render_template(template: str, *, placeholder: str, user_text: str) -> str:
        """渲染单个模板；不使用 format，以保留 NovelAI 的花括号权重语法。"""

        normalized_template = template.strip()
        normalized_user_text = user_text.strip()
        if placeholder in normalized_template:
            return normalized_template.replace(placeholder, normalized_user_text).strip(" \t\r\n,")
        return merge_prompt_parts((normalized_template, normalized_user_text))
