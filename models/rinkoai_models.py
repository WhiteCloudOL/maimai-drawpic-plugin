"""RinkoAI NAI 聊天绘图协议与适用范围（不执行网络请求）。"""

from typing import Any, Dict
from urllib.parse import urlsplit


RINKOAI_EDIT_UNSUPPORTED_REASON = (
    "RinkoAI 的 NAI 聊天绘图接口目前未验证支持图生图："
    "带源图的请求仍返回 generate 任务。请使用文生图或切换到支持图生图的平台。"
)


def is_rinkoai_nai_model(base_url: str, model: str) -> bool:
    """只匹配指定站点与 NAI 系列，不影响其他中转站或绘图模型。"""

    return (
        is_rinkoai_host(base_url)
        and model.strip().lower().startswith("nai-diffusion-")
    )


def is_rinkoai_host(base_url: str) -> bool:
    """RinkoAI 专用模式不接管其他站点。"""

    return urlsplit(base_url).hostname == "api.rinko.ai"


def build_rinkoai_payload(
    prompt: str,
    model: str,
    n: int,
    extra_parameters: Dict[str, Any],
) -> Dict[str, Any]:
    """构造已实测的非流式 NAI 文生图请求。"""

    if n != 1:
        raise ValueError("RinkoAI NAI 兼容模式当前仅支持单次生成一张图片")
    # 不混发 Gemini contents，也不把 Images API 的参数假定为 NAI 参数。
    # 保留扩展字段，但不允许扩展参数改变模型、消息或启用流式响应。
    payload = dict(extra_parameters)
    payload.update({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    })
    payload.pop("n", None)
    return payload
