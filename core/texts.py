from .provider_router import ProviderRouter


def build_session_status_text(router: ProviderRouter, session_preference: dict[str, str]) -> str:
    """构建当前会话的绘图状态文本。"""

    model_name = session_preference["model"]
    provider_name = router.get_model_provider(model_name) or "unknown"
    lines = [
        f"当前绘图模型：{model_name}",
        f"当前提供商：{provider_name}",
        f"当前 OpenAI 兼容模式：{session_preference['openai_compatibility_mode']}",
        f"默认模型：{router.resolve_default_model()}",
    ]
    return "\n".join(lines)


def build_draw_help_text(router: ProviderRouter) -> str:
    """构建 /绘图 命令帮助文本。"""

    openai_models = "、".join(router.get_openai_models()) or "未配置"
    google_models = "、".join(router.get_google_models()) or "未配置"
    return (
        "/绘图 帮助\n"
        "/绘图 状态\n"
        "/绘图 模型 模型名\n"
        "/绘图 兼容模式 images_api|chat_completions\n"
        "/绘图 这里直接写提示词\n"
        f"OpenAI 模型：{openai_models}\n"
        f"Google 模型：{google_models}"
    )
