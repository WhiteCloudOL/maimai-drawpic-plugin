from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Literal, Sequence

from PIL import Image, ImageDraw, ImageFont


ReplyTextStyle = Literal["body", "muted"]


@dataclass(frozen=True, slots=True)
class ReplyTextSpan:
    """图片回复中具有独立视觉样式的一段文字。"""

    text: str
    style: ReplyTextStyle = "body"


class PinkImageReplyRenderer:
    """把任意多行文本渲染为超级可爱的马卡龙少女心手帐风图片回复。"""

    TITLE_FONT_SIZE = 32
    BODY_FONT_SIZE = 26
    MUTED_FONT_SIZE = 21
    BODY_TEXT_COLOR = "#665359"
    MUTED_TEXT_COLOR = "#9B8F93"

    def __init__(self) -> None:
        self.font_path = self._find_font_path()

    def render(self, title: str, body: str, *, max_width: int = 1100) -> bytes:
        """渲染标题与正文，返回 PNG 字节。"""

        normalized_body = body.strip() or "无内容"
        body_lines = [
            [ReplyTextSpan(raw_line)]
            for raw_line in normalized_body.splitlines()
        ]
        return self.render_rich(title, body_lines, max_width=max_width)

    def render_rich(
        self,
        title: str,
        body_lines: Sequence[Sequence[ReplyTextSpan]],
        *,
        max_width: int = 1100,
    ) -> bytes:
        """渲染可混合正文与弱化说明样式的多行图片回复。"""

        normalized_title = title.strip()
        normalized_lines = [list(line) for line in body_lines]
        if not normalized_lines:
            normalized_lines = [[ReplyTextSpan("无内容")]]

        # 考虑到顶部有徽章，标题字号可以稍微调整，拉开层次
        title_font, body_font = self._load_fonts(
            title_size=self.TITLE_FONT_SIZE,
            body_size=self.BODY_FONT_SIZE,
        )
        muted_font = self._load_font(self.MUTED_FONT_SIZE)
        body_fonts = {
            "body": body_font,
            "muted": muted_font,
        }

        # 两侧留出足够宽裕的呼吸空间
        content_width = max_width - 220

        wrapped_body_lines = self._wrap_rich_lines(
            normalized_lines,
            body_fonts,
            content_width,
        )
        title_lines = (
            self._wrap_text(normalized_title, title_font, content_width)
            if normalized_title
            else []
        )

        line_gap = 16
        title_gap = 26 if title_lines else 0
        title_line_height = self._line_height(title_font) + 12
        body_line_heights = [
            self._rich_line_height(line, body_fonts) + line_gap
            for line in wrapped_body_lines
        ]
        text_height = (
            len(title_lines) * title_line_height
            + title_gap
            + sum(body_line_heights)
        )

        margin = 48
        image_width = max_width
        image_height = max(340, text_height + 230)

        # 1. 基础背景 (极浅的草莓牛奶色)
        image = Image.new("RGB", (image_width, image_height), "#FFF5F8")
        draw = ImageDraw.Draw(image)
        
        # 2. 绘制错落有致的可爱波点背景
        self._draw_polka_dots(draw, image_width, image_height)
        
        # 3. 绘制主体卡片与装饰框架
        self._draw_decorated_frame(draw, image_width, image_height, margin)

        # 4. 绘制顶部的“麦麦绘图”专属徽章
        self._draw_header_badge(draw, image_width, margin, title_font)

        # 5. 文本坐标起始点 (为顶部徽章留出一点空间)
        x = 110
        y = 125
        
        # 绘制标题及前面的小爱心指示器
        if title_lines:
            self._draw_heart(draw, x - 25, y + 5, size=20, fill="#FF6B9E")
            for line in title_lines:
                draw.text((x, y), line, fill="#D64571", font=title_font)
                y += title_line_height
            y += title_gap

        # 绘制正文；弱化说明使用更小的灰色字号，并与正文按基线居中。
        for line, line_height in zip(
            wrapped_body_lines,
            body_line_heights,
            strict=True,
        ):
            cursor_x = x
            content_height = line_height - line_gap
            for span in line:
                font = body_fonts[span.style]
                color = (
                    self.MUTED_TEXT_COLOR
                    if span.style == "muted"
                    else self.BODY_TEXT_COLOR
                )
                span_height = self._line_height(font)
                span_y = y + max((content_height - span_height) // 2, 0)
                draw.text((cursor_x, span_y), span.text, fill=color, font=font)
                cursor_x += self._text_width(span.text, font)
            y += line_height

        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

    def _load_font(
        self,
        size: int,
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        if self.font_path:
            return ImageFont.truetype(self.font_path, size)
        return ImageFont.load_default()

    @classmethod
    def _wrap_rich_lines(
        cls,
        lines: Sequence[Sequence[ReplyTextSpan]],
        fonts: dict[ReplyTextStyle, ImageFont.FreeTypeFont | ImageFont.ImageFont],
        max_width: int,
    ) -> list[list[ReplyTextSpan]]:
        """按每段文字自身字体换行，同时保留段落样式。"""

        wrapped_lines: list[list[ReplyTextSpan]] = []
        for logical_line in lines:
            if not logical_line or not any(span.text for span in logical_line):
                wrapped_lines.append([ReplyTextSpan("")])
                continue

            current_line: list[ReplyTextSpan] = []
            current_width = 0
            for span in logical_line:
                font = fonts[span.style]
                for segment in cls._split_segments(span.text):
                    segment_width = cls._text_width(segment, font)
                    if current_line and current_width + segment_width > max_width:
                        wrapped_lines.append(current_line)
                        current_line = []
                        current_width = 0
                        segment = segment.lstrip()
                        segment_width = cls._text_width(segment, font)
                    if segment_width > max_width:
                        for part in cls._break_long_segment(segment, font, max_width):
                            part_width = cls._text_width(part, font)
                            if current_line and current_width + part_width > max_width:
                                wrapped_lines.append(current_line)
                                current_line = []
                                current_width = 0
                            cls._append_rich_span(current_line, part, span.style)
                            current_width += part_width
                        continue
                    cls._append_rich_span(current_line, segment, span.style)
                    current_width += segment_width
            wrapped_lines.append(current_line or [ReplyTextSpan("")])
        return wrapped_lines

    @staticmethod
    def _append_rich_span(
        line: list[ReplyTextSpan],
        text: str,
        style: ReplyTextStyle,
    ) -> None:
        if not text:
            return
        if line and line[-1].style == style:
            previous = line[-1]
            line[-1] = ReplyTextSpan(previous.text + text, style)
            return
        line.append(ReplyTextSpan(text, style))

    @classmethod
    def _rich_line_height(
        cls,
        line: Sequence[ReplyTextSpan],
        fonts: dict[ReplyTextStyle, ImageFont.FreeTypeFont | ImageFont.ImageFont],
    ) -> int:
        styles = {span.style for span in line} or {"body"}
        return max(cls._line_height(fonts[style]) for style in styles)

    @classmethod
    def _find_font_path(cls) -> str:
        plugin_font_paths = cls._plugin_font_paths()
        system_font_paths = cls._system_font_paths()
        candidates = plugin_font_paths + system_font_paths
        for path in candidates:
            if path.exists():
                return str(path)
        return ""

    @staticmethod
    def _plugin_font_paths() -> list[Path]:
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        return [
            assets_dir / "font.ttf",
        ]

    @staticmethod
    def _system_font_paths() -> list[Path]:
        return [
            Path("C:/Windows/Fonts/msyh.ttc"),
            Path("C:/Windows/Fonts/simhei.ttf"),
            Path("C:/Windows/Fonts/simsun.ttc"),
            Path("C:/Windows/Fonts/arial.ttf"),
        ]

    def _load_fonts(self, *, title_size: int, body_size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
        if self.font_path:
            return (
                ImageFont.truetype(self.font_path, title_size),
                ImageFont.truetype(self.font_path, body_size),
            )
        return ImageFont.load_default(), ImageFont.load_default()

    @staticmethod
    def _line_height(font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
        bbox = font.getbbox("麦Mai")
        return bbox[3] - bbox[1]

    @classmethod
    def _text_width(cls, text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
        bbox = font.getbbox(text)
        return bbox[2] - bbox[0]

    @classmethod
    def _wrap_text(
        cls,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        wrapped_lines: list[str] = []
        for raw_line in text.splitlines() or [""]:
            line = raw_line.rstrip()
            if not line:
                wrapped_lines.append("")
                continue
            wrapped_lines.extend(cls._wrap_line(line, font, max_width))
        return wrapped_lines

    @classmethod
    def _wrap_line(
        cls,
        line: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        segments = cls._split_segments(line)
        result: list[str] = []
        current = ""
        for segment in segments:
            candidate = f"{current}{segment}"
            if current and cls._text_width(candidate, font) > max_width:
                result.append(current.rstrip())
                current = segment.lstrip()
                continue
            if cls._text_width(segment, font) > max_width:
                if current:
                    result.append(current.rstrip())
                    current = ""
                broken = cls._break_long_segment(segment, font, max_width)
                result.extend(broken[:-1])
                current = broken[-1] if broken else ""
                continue
            current = candidate
        if current:
            result.append(current.rstrip())
        return result or [""]

    @staticmethod
    def _split_segments(line: str) -> list[str]:
        segments: list[str] = []
        current = ""
        for char in line:
            if char.isspace():
                current += char
                segments.append(current)
                current = ""
                continue
            if ord(char) > 127:
                if current:
                    segments.append(current)
                    current = ""
                segments.append(char)
                continue
            current += char
        if current:
            segments.append(current)
        return segments

    @classmethod
    def _break_long_segment(
        cls,
        segment: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        lines: list[str] = []
        current = ""
        for char in segment:
            candidate = f"{current}{char}"
            if current and cls._text_width(candidate, font) > max_width:
                lines.append(current)
                current = char
            else:
                current = candidate
        if current:
            lines.append(current)
        return lines

    @staticmethod
    def _draw_polka_dots(draw: ImageDraw.ImageDraw, width: int, height: int) -> None:
        """绘制交错的可爱婴儿粉波点背景"""
        dot_color = "#FFE6ED"
        spacing = 32
        radius = 3
        for y in range(0, height, spacing):
            # 奇数行错位，形成六边形交错排列
            offset = spacing // 2 if (y // spacing) % 2 == 1 else 0
            for x in range(0, width + spacing, spacing):
                cx, cy = x + offset, y
                draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=dot_color)

    def _draw_header_badge(self, draw: ImageDraw.ImageDraw, image_width: int, margin: int, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> None:
        """在正中央绘制『麦麦绘图』专属软萌徽章"""
        text = "麦麦绘图"
        badge_w = 200
        badge_h = 52
        badge_x = image_width // 2 - badge_w // 2
        badge_y = margin - 22  # 让徽章稍微向上凸出卡片边缘
        
        # 绘制徽章底座（带白色粗描边，像贴纸一样）
        draw.rounded_rectangle(
            (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
            radius=26,
            fill="#FF7DA3",
            outline="#FFFFFF",
            width=4
        )
        
        # 居中绘制文本
        tw = self._text_width(text, font)
        th = self._line_height(font)
        text_x = badge_x + (badge_w - tw) // 2
        # 根据字体可能会有基线偏移，适当微调 y 坐标使其视觉居中
        text_y = badge_y + (badge_h - th) // 2 - 3 
        draw.text((text_x, text_y), text, fill="#FFFFFF", font=font)
        
        # 徽章两侧加点小装饰
        self._draw_sparkle(draw, badge_x + 25, badge_y + 26, 12, fill="#FFF069")
        self._draw_sparkle(draw, badge_x + badge_w - 25, badge_y + 26, 12, fill="#FFF069")

    @staticmethod
    def _draw_decorated_frame(draw: ImageDraw.ImageDraw, width: int, height: int, margin: int) -> None:
        shadow_offset_x = 6
        shadow_offset_y = 10
        shadow_color = "#F4CED9"
        card_color = "#FFFFFF"
        line_color = "#FFB6C9"
        
        # 1. 柔和的卡片投影
        draw.rounded_rectangle(
            (margin + shadow_offset_x, margin + shadow_offset_y, width - margin + shadow_offset_x, height - margin + shadow_offset_y),
            radius=24,
            fill=shadow_color
        )
        
        # 2. 纯白主卡片
        draw.rounded_rectangle(
            (margin, margin, width - margin, height - margin),
            radius=24,
            fill=card_color
        )
        
        # 3. 内层精致的留空线条
        inner_m = margin + 20
        left, top, right, bottom = inner_m, inner_m, width - inner_m, height - inner_m
        gap = 26
        line_w = 2
        draw.line((left + gap, top, right - gap, top), fill=line_color, width=line_w)
        draw.line((left + gap, bottom, right - gap, bottom), fill=line_color, width=line_w)
        draw.line((left, top + gap, left, bottom - gap), fill=line_color, width=line_w)
        draw.line((right, top + gap, right, bottom - gap), fill=line_color, width=line_w)

        # 4. 绘制四周的星光氛围点缀
        PinkImageReplyRenderer._draw_sparkle(draw, left, top, 16, line_color)
        PinkImageReplyRenderer._draw_sparkle(draw, right, top, 16, line_color)
        PinkImageReplyRenderer._draw_sparkle(draw, left, bottom, 16, line_color)
        PinkImageReplyRenderer._draw_sparkle(draw, left + 40, bottom - 10, 10, "#FFF069") # 嫩黄星星
        PinkImageReplyRenderer._draw_sparkle(draw, right - 50, top + 15, 12, "#FFF069") 
        
        # 5. 右下角：超萌胖胖蝴蝶结
        PinkImageReplyRenderer._draw_cute_chunky_bow(draw, width - margin - 22, height - margin - 20)

    @staticmethod
    def _draw_sparkle(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, fill: str) -> None:
        """程序化绘制可爱的十字星光 ✨"""
        hw = size // 2
        qw = size // 4
        poly = [
            (cx, cy - hw), (cx + qw, cy - qw), (cx + hw, cy), (cx + qw, cy + qw),
            (cx, cy + hw), (cx - qw, cy + qw), (cx - hw, cy), (cx - qw, cy - qw)
        ]
        draw.polygon(poly, fill=fill)

    @staticmethod
    def _draw_heart(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, fill: str) -> None:
        """程序化绘制一个小爱心 💗"""
        r = size // 2
        draw.ellipse((cx - r, cy - r, cx, cy), fill=fill)
        draw.ellipse((cx, cy - r, cx + r, cy), fill=fill)
        draw.polygon([(cx - r, cy - r//2 + 1), (cx + r, cy - r//2 + 1), (cx, cy + r)], fill=fill)

    @staticmethod
    def _draw_cute_chunky_bow(draw: ImageDraw.ImageDraw, cx: int, cy: int) -> None:
        """带有白色贴纸描边的蝴蝶结"""
        main_color = "#FF84A7"  # 蝴蝶结亮粉色
        shadow_color = "#E8638B" # 内侧阴影色
        outline_color = "#FFFFFF" # 贴纸白边
        outline_w = 4
        
        # 为了实现完美的白边效果，我们先用白色画一圈稍微大一点的底，再在上面叠粉色
        # 1. 绘制飘带尾巴
        left_tail = [(cx - 8, cy + 8), (cx - 36, cy + 45), (cx - 20, cy + 38), (cx - 10, cy + 46)]
        right_tail = [(cx + 8, cy + 8), (cx + 36, cy + 45), (cx + 20, cy + 38), (cx + 10, cy + 46)]
        
        # 白底飘带
        draw.polygon(left_tail, fill=outline_color)
        draw.line(left_tail + [left_tail[0]], fill=outline_color, width=outline_w)
        draw.polygon(right_tail, fill=outline_color)
        draw.line(right_tail + [right_tail[0]], fill=outline_color, width=outline_w)
        # 粉色飘带
        draw.polygon(left_tail, fill=main_color)
        draw.polygon(right_tail, fill=main_color)
        
        # 2. 绘制蝴蝶结胖胖的主环
        # 白底环
        draw.ellipse((cx - 40, cy - 18, cx - 4, cy + 14), fill=outline_color, outline=outline_color, width=outline_w)
        draw.ellipse((cx + 4, cy - 18, cx + 40, cy + 14), fill=outline_color, outline=outline_color, width=outline_w)
        # 粉色环
        draw.ellipse((cx - 38, cy - 16, cx - 6, cy + 12), fill=main_color)
        draw.ellipse((cx + 6, cy - 16, cx + 38, cy + 12), fill=main_color)
        
        # 3. 蝴蝶结内侧褶皱的深色阴影 (小椭圆)
        draw.ellipse((cx - 32, cy - 6, cx - 12, cy + 4), fill=shadow_color)
        draw.ellipse((cx + 12, cy - 6, cx + 32, cy + 4), fill=shadow_color)
        
        # 4. 绘制中心圆滚滚的结
        # 白底中心结
        draw.rounded_rectangle((cx - 12, cy - 12, cx + 12, cy + 12), radius=10, fill=outline_color, outline=outline_color, width=outline_w)
        # 粉色中心结
        draw.rounded_rectangle((cx - 10, cy - 10, cx + 10, cy + 10), radius=8, fill=main_color)
