from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .config import StyleConfig, StylePresetConfig


@dataclass(frozen=True, slots=True)
class ResolvedStylePrompt:
    """一次风格化绘图最终使用的正向与反向提示词。"""

    style_name: str
    positive_prompt: str
    negative_prompt: str


def merge_prompt_parts(parts: Iterable[str]) -> str:
    """按顺序合并非空提示词片段。"""

    return ", ".join(part.strip(" \t\r\n,") for part in parts if part.strip(" \t\r\n,"))


class StylePromptResolver:
    """解析配置中的全平台绘图风格提示词模板。"""

    DEFAULT_STYLE_ALIASES = {"默认", "default"}
    NO_STYLE_ALIASES = {"无", "none", "原始", "plain"}

    def __init__(self, config: StyleConfig) -> None:
        self.config = config

    def get_style_names(self) -> list[str]:
        """返回已启用且名称唯一的风格列表。"""

        names: list[str] = []
        seen: set[str] = set()
        for preset in self.config.presets:
            normalized_name = preset.name.strip()
            lookup_name = normalized_name.casefold()
            if not preset.enabled or not normalized_name or lookup_name in seen:
                continue
            seen.add(lookup_name)
            names.append(normalized_name)
        return names

    def resolve(
        self,
        *,
        style_name: str,
        user_prompt: str,
        user_negative_prompt: str = "",
    ) -> ResolvedStylePrompt:
        """解析一个风格；未指定风格时保持普通绘图行为。"""

        normalized_style_name = style_name.strip()
        if normalized_style_name.casefold() in self.NO_STYLE_ALIASES or not normalized_style_name:
            return ResolvedStylePrompt(
                style_name="",
                positive_prompt=user_prompt.strip(),
                negative_prompt=user_negative_prompt.strip(),
            )
        if normalized_style_name.casefold() in self.DEFAULT_STYLE_ALIASES:
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
        )

    def _find_preset(self, style_name: str) -> StylePresetConfig | None:
        lookup_name = style_name.strip().casefold()
        matches = [
            preset
            for preset in self.config.presets
            if preset.enabled and preset.name.strip().casefold() == lookup_name
        ]
        if len(matches) > 1:
            raise ValueError(f"绘图风格名称重复：{style_name}，请在插件配置中保留一个同名风格")
        return matches[0] if matches else None

    @staticmethod
    def _render_template(template: str, *, placeholder: str, user_text: str) -> str:
        """渲染单个模板；不使用 format，以保留 NovelAI 的花括号权重语法。"""

        normalized_template = template.strip()
        normalized_user_text = user_text.strip()
        if placeholder in normalized_template:
            return normalized_template.replace(placeholder, normalized_user_text).strip(" \t\r\n,")
        return merge_prompt_parts((normalized_template, normalized_user_text))
