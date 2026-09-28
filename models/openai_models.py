"""OpenAI / New API 兼容模式与聊天绘图请求定义。"""

from typing import Any, Dict, List, Literal, Optional


OpenAICompatibilityMode = Literal["auto", "images_api", "chat_completions", "rinkoai"]
OPENAI_COMPATIBILITY_MODES = {"auto", "images_api", "chat_completions", "rinkoai"}


def normalize_openai_mode(mode: str) -> str:
    """删除的 NovelAI Images 模式迁移到 RinkoAI，聊天模式独立保留。"""

    normalized = mode.strip().lower()
    if normalized in {"novelai_images_api", "rinkoai兼容", "rinkoai 兼容"}:
        return "rinkoai"
    return normalized


def uses_newapi_image_chat(model: str) -> bool:
    """New API 的 Gemini 图片模型自动走聊天协议，其他模型保持 Images API。"""

    normalized = model.strip().lower()
    return normalized.startswith("gemini-") and "image" in normalized


def select_auto_modes(model: str, endpoint_types: Optional[List[str]]) -> List[str]:
    """优先使用 New API 模型元数据；缺少元数据时按已知模型系列排序。"""

    modes = (
        ["chat_completions", "images_api"]
        if uses_newapi_image_chat(model)
        else ["images_api", "chat_completions"]
    )
    if endpoint_types:
        supported = set(endpoint_types)
        modes = [
            mode for mode in modes
            if ("openai" if mode == "chat_completions" else "image-generation") in supported
        ]
        if not modes:
            raise ValueError(
                f"模型 {model} 公布的端点不支持 Images API 或 Chat Completion；"
                "请切换模型或使用对应原生平台配置"
            )
    return modes


def is_endpoint_unsupported(status: int, code: str, message: str) -> bool:
    """仅确定的路由错误允许切换端点，模型/鉴权/配额错误不能重试。"""

    normalized_code = code.strip().lower()
    if normalized_code in {"unsupported_endpoint", "route_not_found", "method_not_allowed", "not_implemented"}:
        return status in {400, 404, 405, 501}
    if normalized_code:
        return False
    normalized_message = message.strip().lower()
    if "model" in normalized_message or "模型" in normalized_message:
        return False
    if status in {405, 501}:
        return True
    return status == 404 and (
        normalized_message in {"404 page not found", "not found", "404 not found"}
        or "route not found" in normalized_message
        or "cannot post /" in normalized_message
    )


def build_newapi_chat_payload(
    prompt: str,
    model: str,
    n: int,
    extra_parameters: Dict[str, Any],
    source_image_data_urls: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """使用 New API 的标准 OpenAI 消息协议，不混发 Gemini 原生字段。"""

    content: Any = prompt
    if source_image_data_urls:
        content = [{"type": "text", "text": prompt}]
        content.extend(
            {"type": "image_url", "image_url": {"url": data_url}}
            for data_url in source_image_data_urls
        )
    payload = dict(extra_parameters)
    payload.pop("contents", None)
    payload.pop("n", None)
    payload.update({
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "stream": False,
    })
    if n > 1:
        payload["n"] = n
    return payload
