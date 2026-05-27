from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class PinkImageReplyRenderer:
    """把任意多行文本渲染为超级可爱的马卡龙少女心手帐风图片回复。"""

    def __init__(self) -> None:
        self.font_path = self._find_font_path()

    def render(self, title: str, body: str, *, max_width: int = 1100) -> bytes:
        """渲染标题与正文，返回 PNG 字节。"""

        normalized_title = title.strip()
        normalized_body = body.strip() or "无内容"
        # 考虑到顶部有徽章，标题字号可以稍微调整，拉开层次
        title_font, body_font = self._load_fonts(title_size=32, body_size=26)
        
        # 两侧留出足够宽裕的呼吸空间
        content_width = max_width - 220
        
        body_lines = self._wrap_text(normalized_body, body_font, content_width)
        title_lines = self._wrap_text(normalized_title, title_font, content_width) if normalized_title else []

        line_gap = 16
        title_gap = 26 if title_lines else 0
        body_line_height = self._line_height(body_font) + line_gap
        title_line_height = self._line_height(title_font) + 12
        text_height = len(title_lines) * title_line_height + title_gap + len(body_lines) * body_line_height
        
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
            
        # 绘制正文
        for line in body_lines:
            draw.text((x, y), line, fill="#665359", font=body_font)
            y += body_line_height

        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()

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