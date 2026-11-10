"""MiniMax 官方图片模型及参数约束（核对于 2026-11-10）。"""

from typing import Any, Dict
from urllib.parse import urlsplit
import re

MINIMAX_MODELS = ("MiniMax-H3-Image", "MiniMax-H3-Image-Highspeed", "image-01", "image-01-live")
MINIMAX_PRESET_HINT = "来源：MiniMax 官方图片 API 文档，核对于 2026-11-10；不是在线模型目录，不代表账号已开通或余额充足。"
H3_MODELS = frozenset(MINIMAX_MODELS[:2])
LEGACY_RATIOS = {"1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"}


def normalize_minimax_base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("MiniMax base_url 必须是无账号、查询参数和片段的 HTTP(S) 基础地址")
    if not parsed.path:
        base += "/v1"
    elif not parsed.path.endswith("/v1"):
        raise ValueError("MiniMax base_url 应以 /v1 结尾，不填写具体生成端点")
    return base


def max_reference_images(model: str) -> int:
    return 16 if model in H3_MODELS else 1


def build_minimax_payload(values: Dict[str, Any], prompt: str, model: str, *, edit: bool, n: int = 1) -> Dict[str, Any]:
    if model not in MINIMAX_MODELS:
        raise ValueError(f"未接入的 MiniMax 图片模型：{model}")
    h3 = model in H3_MODELS
    prompt = prompt.strip()
    if not prompt or len(prompt) > (32000 if h3 else 1500):
        raise ValueError(f"MiniMax {model} 提示词应为 1～{32000 if h3 else 1500} 个字符")
    count = values["n"] if n == 1 else n
    if type(count) is not int or not 1 <= count <= (10 if h3 else 9):
        raise ValueError(f"MiniMax {model} 单次张数应为 1～{10 if h3 else 9}")
    payload = {"model": model, "prompt": prompt, "n": count, "response_format": values["response_format"], "aigc_watermark": values["aigc_watermark"]}
    size = values["size"].strip() or "auto"
    size = values["model_size_overrides"].get(model, size)
    ratio = values["aspect_ratio"].strip()
    if h3:
        payload.update(size=size, output_format=values["output_format"], output_compression=values["output_compression"], stream=values["stream"])
        if ratio:
            payload["aspect_ratio"] = ratio
        if values["area"]:
            payload["area"] = values["area"]
        if not edit:
            payload["disable_prompt_enhanced"] = values["disable_prompt_enhanced"]
        elif values["disable_prompt_enhanced"]:
            raise ValueError("MiniMax H3 图像编辑始终开启 Prompt 增强，请关闭“禁用 H3 提示词增强”")
    else:
        payload["response_format"] = "base64" if values["response_format"] == "b64_json" else "url"
        payload["prompt_optimizer"] = values["prompt_optimizer"]
        if values["seed"] >= 0:
            payload["seed"] = values["seed"]
        if ratio and ratio != "auto":
            payload["aspect_ratio"] = ratio
        if size != "auto":
            match = re.fullmatch(r"([0-9]+)x([0-9]+)", size)
            if not match:
                raise ValueError("MiniMax 尺寸格式应为 auto 或 宽x高")
            payload.update(width=int(match[1]), height=int(match[2]))
        if values["style_type"]:
            if model != "image-01-live":
                raise ValueError("MiniMax 内置画风只适用于 image-01-live")
            payload["style"] = {"style_type": values["style_type"], "style_weight": values["style_weight"]}
        if values["stream"]:
            raise ValueError("image-01 系列没有接入流式接口，请关闭流式输出")
    extras = values["extra_parameters"]
    if extras.keys() & {"model", "prompt", "images", "subject_reference", "image", "mask", "negative_prompt"}:
        raise ValueError("MiniMax 扩展参数不能覆盖模型、提示词、源图或添加未支持的 mask/negative_prompt 字段")
    forbidden = {"seed", "prompt_optimizer", "style", "width", "height"} if h3 else {"size", "area", "output_format", "output_compression", "disable_prompt_enhanced", "stream"}
    if extras.keys() & forbidden:
        raise ValueError(f"MiniMax {model} 扩展参数包含另一协议的字段：{', '.join(sorted(extras.keys() & forbidden))}")
    payload.update(extras)
    validate_minimax_payload(payload, h3=h3, edit=edit)
    return payload


def validate_minimax_payload(payload: Dict[str, Any], *, h3: bool, edit: bool) -> None:
    if type(payload["n"]) is not int or not 1 <= payload["n"] <= (10 if h3 else 9):
        raise ValueError("MiniMax 生成张数超出模型限制")
    if payload["response_format"] not in ({"url", "b64_json"} if h3 else {"url", "base64"}):
        raise ValueError("MiniMax 返回格式与当前模型协议不匹配")
    if h3:
        size = payload["size"]
        if size == "auto":
            area = payload.get("area", "4K")
            if area not in {"1K", "2K", "4K"}:
                raise ValueError("H3 面积档位应为 1K、2K 或 4K")
            pixels = {"1K": 1024 ** 2, "2K": 2048 ** 2, "4K": 4096 ** 2}[area]
            ratio = payload.get("aspect_ratio", "auto")
            if ratio != "auto":
                match = re.fullmatch(r"([0-9]{1,3}):([0-9]{1,3})", ratio)
                if not match or not all(1 <= int(x) <= 300 for x in match.groups()) or not 1 / 3 <= int(match[1]) / int(match[2]) <= 3:
                    raise ValueError("H3 宽高比应为 auto 或 1～300 的整数 X:Y，比例在 1:3～3:1")
            elif payload.get("disable_prompt_enhanced"):
                raise ValueError("关闭 H3 提示词增强时必须指定宽高或固定宽高比")
        else:
            if "aspect_ratio" in payload or "area" in payload:
                raise ValueError("H3 指定宽高时不能同时设置宽高比或面积档位")
            match = re.fullmatch(r"([0-9]+)x([0-9]+)", size)
            if not match:
                raise ValueError("H3 尺寸格式应为 auto 或 宽x高")
            width, height = map(int, match.groups())
            pixels = width * height
            if not height or not 655360 <= pixels <= 20000000 or not 1 / 3 <= width / height <= 3:
                raise ValueError("H3 输出面积应为 655360～20000000 像素，宽高比在 1:3～3:1")
        if payload["output_format"] not in {"png", "jpeg", "jpg", "webp"} or type(payload["output_compression"]) is not int or not 0 <= payload["output_compression"] <= 100:
            raise ValueError("H3 输出格式或压缩质量不合法")
        if type(payload["stream"]) is not bool or type(payload.get("disable_prompt_enhanced", False)) is not bool:
            raise ValueError("H3 流式输出和提示词增强参数必须为布尔值")
        if edit and "disable_prompt_enhanced" in payload:
            raise ValueError("H3 编辑接口不接受 disable_prompt_enhanced")
        if payload["response_format"] == "b64_json":
            if payload["stream"]:
                raise ValueError("H3 流式输出只支持 URL 返回")
            maximum = 20000000 if payload["output_format"] == "png" else 80000000
            if payload["n"] * pixels > maximum:
                raise ValueError("H3 Base64 总输出面积超限，请减少张数、面积或使用 URL 返回")
        if payload["n"] * pixels > 67108864:
            raise ValueError("本插件单任务合计最多 67108864 像素，请减少 H3 张数或输出面积")
    else:
        ratio = payload.get("aspect_ratio")
        if ratio is not None and (ratio not in LEGACY_RATIOS or payload["model"] == "image-01-live" and ratio == "21:9"):
            raise ValueError("image-01 系列宽高比不合法；image-01-live 不支持 21:9")
        if "width" in payload or "height" in payload:
            if ratio or payload["model"] == "image-01-live":
                raise ValueError("image-01 自定义宽高不能同时设置宽高比，也不适用于 image-01-live")
            if any(type(payload.get(key)) is not int or not 512 <= payload[key] <= 2048 or payload[key] % 8 for key in ("width", "height")):
                raise ValueError("image-01 宽高需同时设置为 512～2048 内的 8 的倍数")
        if "seed" in payload and (type(payload["seed"]) is not int or not 0 <= payload["seed"] < 2 ** 63):
            raise ValueError("MiniMax seed 应为非负 int64 整数")
        if type(payload["prompt_optimizer"]) is not bool:
            raise ValueError("MiniMax prompt_optimizer 必须为布尔值")
        if "style" in payload:
            style = payload["style"]
            if payload["model"] != "image-01-live" or not isinstance(style, dict) or style.get("style_type") not in {"漫画", "元气", "中世纪", "水彩"}:
                raise ValueError("MiniMax 内置画风仅支持 image-01-live 的漫画、元气、中世纪、水彩")
            weight = style.get("style_weight", 0.8)
            if type(weight) not in (int, float) or not 0 < weight <= 1:
                raise ValueError("MiniMax 画风权重应在 (0, 1] 范围内")
    if type(payload["aigc_watermark"]) is not bool:
        raise ValueError("MiniMax 水印参数必须为布尔值")
