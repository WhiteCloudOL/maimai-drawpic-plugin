"""阿里云百炼图像模型能力注册与请求参数构造。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


AliyunModelFamily = Literal["qwen", "zimage", "kling", "vidu", "legacy"]
AliyunImageInputMode = Literal["auto", "base64", "url"]
AliyunTaskType = Literal["draw", "edit_image"]

DEFAULT_ALIYUN_MODELS: tuple[str, ...] = (
    "qwen-image-3.0-pro",
    "qwen-image-3.0",
    "qwen-image-2.0-pro",
    "qwen-image-2.0-pro-2026-06-22",
    "qwen-image-2.0-pro-2026-04-22",
    "qwen-image-2.0-pro-2026-03-03",
    "qwen-image-2.0",
    "qwen-image-2.0-2026-03-03",
    "qwen-image-max",
    "qwen-image-max-2025-12-30",
    "qwen-image-plus",
    "qwen-image-plus-2026-01-09",
    "qwen-image",
    "qwen-image-edit-max",
    "qwen-image-edit-max-2026-01-16",
    "qwen-image-edit-plus",
    "qwen-image-edit-plus-2025-12-15",
    "qwen-image-edit-plus-2025-10-30",
    "qwen-image-edit",
    "z-image-turbo",
    "kling/kling-v3-image-generation",
    "kling/kling-v3-omni-image-generation",
    "vidu/vidu-image_reference2image",
    "vidu/vidu-image-pro_reference2image",
    "vidu/vidu-image-lite_reference2image",
    "vidu/viduq3-fast_reference2image",
    "vidu/viduq2-pro_reference2image",
    "vidu/viduq2-fast_reference2image",
)


@dataclass(frozen=True, slots=True)
class AliyunModelProfile:
    """单个阿里云模型的任务与协议能力。"""

    model: str
    family: AliyunModelFamily
    supports_draw: bool
    supports_edit: bool
    max_input_images: int
    max_output_images: int
    is_async: bool
    supported_input_modes: frozenset[str]


@dataclass(frozen=True, slots=True)
class AliyunRequestOptions:
    """构造阿里云请求参数所需的已校验配置。"""

    default_size: str
    model_size_overrides: dict[str, str]
    negative_prompt: str
    prompt_extend: bool
    qwen_prompt_extend_mode: str
    qwen_enable_thinking: bool
    zimage_prompt_extend: bool
    seed: int
    watermark: bool
    max_images: int
    kling_aspect_ratio: str
    kling_resolution: str
    kling_result_type: str
    kling_series_amount: int
    qwen_extra_parameters: dict[str, Any]
    zimage_extra_parameters: dict[str, Any]
    kling_extra_parameters: dict[str, Any]
    vidu_extra_parameters: dict[str, Any]
    legacy_extra_parameters: dict[str, Any]


def _profile(
    model: str,
    family: AliyunModelFamily,
    supports_draw: bool,
    supports_edit: bool,
    max_input_images: int,
    max_output_images: int,
    is_async: bool,
    supported_input_modes: frozenset[str],
) -> AliyunModelProfile:
    return AliyunModelProfile(
        model=model,
        family=family,
        supports_draw=supports_draw,
        supports_edit=supports_edit,
        max_input_images=max_input_images,
        max_output_images=max_output_images,
        is_async=is_async,
        supported_input_modes=supported_input_modes,
    )


def resolve_aliyun_model_profile(model: str) -> AliyunModelProfile:
    """按模型 ID 识别能力，未知模型保持旧同步协议兼容。"""

    normalized_model = model.strip().lower()
    base64_or_url = frozenset({"base64", "url"})

    if normalized_model.startswith(("qwen-image-3.0", "qwen-image-2.0")):
        return _profile(model, "qwen", True, True, 3, 6, False, base64_or_url)
    if normalized_model.startswith("qwen-image-edit"):
        max_outputs = 1 if normalized_model == "qwen-image-edit" else 6
        return _profile(model, "qwen", False, True, 3, max_outputs, False, base64_or_url)
    if normalized_model == "qwen-image" or normalized_model.startswith(
        ("qwen-image-max", "qwen-image-plus")
    ):
        return _profile(model, "qwen", True, False, 0, 1, False, base64_or_url)
    if normalized_model.startswith("z-image"):
        return _profile(model, "zimage", True, False, 0, 1, False, base64_or_url)
    if normalized_model.startswith("kling/"):
        is_omni = "omni" in normalized_model
        return _profile(
            model,
            "kling",
            True,
            True,
            10 if is_omni else 1,
            9,
            True,
            frozenset({"url"}),
        )
    if normalized_model.startswith("vidu/"):
        return _profile(model, "vidu", True, True, 14, 1, True, frozenset({"url"}))
    return _profile(model, "legacy", True, True, 8, 6, False, frozenset({"base64"}))


def resolve_aliyun_image_input_mode(
    profile: AliyunModelProfile,
    configured_mode: str,
) -> str:
    """解析源图输入形式，并拒绝模型不支持的显式选择。"""

    normalized_mode = configured_mode.strip().lower()
    if normalized_mode not in {"auto", "base64", "url"}:
        raise ValueError(
            f"阿里云图片输入模式 {configured_mode!r} 无效，只能使用 auto、base64 或 url"
        )
    if normalized_mode == "auto":
        return "base64" if "base64" in profile.supported_input_modes else "url"
    if normalized_mode not in profile.supported_input_modes:
        display_mode = "Base64" if normalized_mode == "base64" else "URL"
        raise ValueError(f"阿里云模型 {profile.model} 不支持 {display_mode} 图片输入")
    return normalized_mode


def validate_aliyun_task(
    model: str,
    task_type: str,
    image_count: int,
    configured_input_mode: str,
) -> str:
    """在发起付费请求前校验任务能力、图片数量和输入形式。"""

    profile = resolve_aliyun_model_profile(model)
    if task_type not in {"draw", "edit_image"}:
        raise ValueError(f"不支持的阿里云绘图任务类型：{task_type}")
    if task_type == "draw":
        if not profile.supports_draw:
            raise ValueError(f"阿里云模型 {model} 不支持文生图")
        if image_count != 0:
            raise ValueError("文生图任务不应包含源图片")
        return resolve_aliyun_image_input_mode(profile, configured_input_mode)

    if not profile.supports_edit:
        raise ValueError(f"阿里云模型 {model} 不支持图生图")
    if image_count < 1:
        raise ValueError(f"阿里云模型 {model} 的图生图任务至少需要 1 张源图片")
    if image_count > profile.max_input_images:
        raise ValueError(
            f"阿里云模型 {model} 的图生图任务最多接收 "
            f"{profile.max_input_images} 张源图片"
        )
    return resolve_aliyun_image_input_mode(profile, configured_input_mode)


def _resolved_size(model: str, options: AliyunRequestOptions) -> str:
    return options.model_size_overrides.get(model, options.default_size)


def _validated_count(n: int, maximum: int) -> int:
    if n < 1:
        raise ValueError("生成图片数量必须大于 0")
    return min(n, maximum)


def _build_qwen_parameters(
    model: str,
    task_type: str,
    n: int,
    options: AliyunRequestOptions,
    profile: AliyunModelProfile,
) -> dict[str, Any]:
    if (
        task_type == "edit_image"
        and model.lower().startswith("qwen-image-3.0")
        and options.qwen_prompt_extend_mode == "agent"
    ):
        raise ValueError("千问 3.0 图生图不支持 agent 提示词改写模式")

    parameters: dict[str, Any] = {
        "n": _validated_count(n, min(options.max_images, profile.max_output_images)),
        "watermark": options.watermark,
        "negative_prompt": options.negative_prompt,
    }
    if model.lower() != "qwen-image-edit":
        parameters["prompt_extend"] = options.prompt_extend
        if model.lower().startswith("qwen-image-3.0"):
            parameters["prompt_extend_mode"] = options.qwen_prompt_extend_mode
            parameters["enable_thinking"] = options.qwen_enable_thinking
        parameters["size"] = _resolved_size(model, options)
    parameters["seed"] = options.seed
    parameters.update(options.qwen_extra_parameters)
    return parameters


def _build_kling_parameters(
    model: str,
    n: int,
    options: AliyunRequestOptions,
    profile: AliyunModelProfile,
) -> dict[str, Any]:
    is_omni = "omni" in model.lower()
    allowed_resolutions = {"1k", "2k", "4k"} if is_omni else {"1k", "2k"}
    if options.kling_resolution.lower() not in allowed_resolutions:
        raise ValueError(f"可灵模型 {model} 不支持分辨率 {options.kling_resolution}")
    if options.kling_aspect_ratio not in {"16:9", "9:16", "1:1"}:
        raise ValueError(f"可灵模型 {model} 不支持宽高比 {options.kling_aspect_ratio}")

    parameters: dict[str, Any] = {}
    if is_omni:
        if options.kling_result_type not in {"single", "series"}:
            raise ValueError("可灵 Omni result_type 只能为 single 或 series")
        parameters["result_type"] = options.kling_result_type
        if options.kling_result_type == "series":
            if not 2 <= options.kling_series_amount <= 9:
                raise ValueError("可灵 Omni 组图数量必须为 2 至 9")
            parameters["series_amount"] = options.kling_series_amount
        else:
            parameters["n"] = _validated_count(
                n,
                min(options.max_images, profile.max_output_images),
            )
    else:
        parameters["n"] = _validated_count(
            n,
            min(options.max_images, profile.max_output_images),
        )
    parameters["aspect_ratio"] = options.kling_aspect_ratio
    parameters["resolution"] = options.kling_resolution.lower()
    parameters["watermark"] = options.watermark
    parameters.update(options.kling_extra_parameters)
    return parameters


def build_aliyun_parameters(
    model: str,
    task_type: str,
    n: int,
    options: AliyunRequestOptions,
) -> dict[str, Any]:
    """构造仅属于当前模型族的请求参数。"""

    profile = resolve_aliyun_model_profile(model)
    if task_type not in {"draw", "edit_image"}:
        raise ValueError(f"不支持的阿里云绘图任务类型：{task_type}")
    if options.max_images < 1:
        raise ValueError("阿里云 max_images 必须大于 0")

    if profile.family == "qwen":
        return _build_qwen_parameters(model, task_type, n, options, profile)
    if profile.family == "zimage":
        parameters = {
            "size": _resolved_size(model, options),
            "prompt_extend": options.zimage_prompt_extend,
            "seed": options.seed,
        }
        parameters.update(options.zimage_extra_parameters)
        return parameters
    if profile.family == "kling":
        return _build_kling_parameters(model, n, options, profile)
    if profile.family == "vidu":
        parameters = {
            "size": _resolved_size(model, options),
            "n": 1,
            "seed": options.seed,
            "watermark": options.watermark,
        }
        parameters.update(options.vidu_extra_parameters)
        return parameters

    parameters = {
        "n": _validated_count(n, min(options.max_images, profile.max_output_images)),
        "watermark": options.watermark,
        "negative_prompt": options.negative_prompt,
        "prompt_extend": options.prompt_extend,
        "size": _resolved_size(model, options),
        "seed": options.seed,
    }
    parameters.update(options.legacy_extra_parameters)
    return parameters
