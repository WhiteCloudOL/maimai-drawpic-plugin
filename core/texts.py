from __future__ import annotations

from .provider_router import ProviderRouter
from .task_store import DrawTaskRecord


def build_command_usage_text() -> str:
    """构建基础命令用法文本。"""

    return "\n".join(
        [
            "可用子命令",
            "/绘图 模型",
            "查看当前模型与可用模型；后接模型名可切换。",
            "",
            "/绘图 状态",
            "查看当前会话模型、兼容模式、额度与绘图任务。",
            "",
            "/绘图 兼容模式",
            "查看或设置 OpenAI 兼容模式，仅对 OpenAI 提供商生效。",
            "",
            "/绘图 文生图 <prompt>",
            "强制发起文生图，prompt 可包含空格；如果同条消息附带或引用图片，会提示改用图生图。",
            "",
            "/绘图 图生图 <prompt>",
            "强制发起图生图，需在同一条消息中附带或引用至少一张图片，支持多张。",
            "",
            "/绘图 添加/减少/设置 用户ID 次数",
            "管理员调整用户当前周期剩余绘图次数。",
        ]
    )


def build_model_text(router: ProviderRouter, session_preference: dict[str, str]) -> str:
    """构建模型列表文本。"""

    current_model = session_preference["model"] or router.resolve_default_model()
    current_provider = router.get_model_provider(current_model) or "unknown"
    provider_lines = [
        ("阿里百炼", router.get_aliyun_models()),
        ("OpenAI", router.get_openai_models()),
        ("Google", router.get_google_models()),
        ("智谱", router.get_zhipu_models()),
        ("火山引擎", router.get_volcengine_models()),
        ("硅基流动", router.get_siliconflow_models()),
        ("NovelAI / NovelAPI", router.get_novelai_models()),
    ]
    lines = [
        f"当前使用模型：{current_provider}：{current_model}",
        "后接模型名称即可切换当前会话模型。",
        "",
    ]
    for provider_name, models in provider_lines:
        models_text = "，".join(models) if models else "未配置"
        lines.append(f"{provider_name}：{models_text}")
    return "\n".join(lines)


def build_session_status_text(
    router: ProviderRouter,
    session_preference: dict[str, str],
    latest_task: DrawTaskRecord | None,
    *,
    quota_text: str,
) -> str:
    """构建当前会话的绘图状态文本。"""

    model_name = session_preference["model"] or router.resolve_default_model()
    provider_name = router.get_model_provider(model_name) or "unknown"
    lock_status = "已锁定" if session_preference["model"] else "未锁定，跟随默认模型"
    openai_mode_text = session_preference["openai_compatibility_mode"] or "未锁定，跟随模型配置"
    task_text = _format_task(latest_task)
    return "\n".join(
        [
            f"当前绘图模型：{provider_name}：{model_name}",
            f"会话模型状态：{lock_status}",
            f"OpenAI 兼容模式：{openai_mode_text}（仅对 OpenAI 提供商生效）",
            f"默认模型：{router.resolve_default_model()}",
            f"当前绘图任务：{task_text}",
            f"用户次数：{quota_text}",
        ]
    )


def build_compatible_mode_text(current_mode: str) -> str:
    """构建兼容模式说明。"""

    mode_text = current_mode.strip() or "未锁定，跟随模型配置"
    return "\n".join(
        [
            f"当前 OpenAI 兼容模式：{mode_text}",
            "该设置仅对 OpenAI 提供商生效。",
            "",
            "可选模式：",
            "auto：自动选择，推荐默认使用",
            "images_api：OpenAI 标准 Images API",
            "chat_completions：Chat Completion 返回图片",
            "novelai_images_api：旧版 NovelAI 风格 OpenAI 兼容接口",
            "",
            "不设置会话兼容模式时，会跟随当前模型所属实例的默认兼容模式。",
            "使用 /绘图 兼容模式 跟随 可清空会话设置。",
            "示例：/绘图 兼容模式 images_api",
        ]
    )


def build_quota_adjust_text(action_label: str, user_id: str, remaining: int) -> str:
    """构建次数调整结果文本。"""

    return f"已{action_label}用户 {user_id} 的当前周期剩余绘图次数。\n当前剩余：{remaining} 次"


def _format_task(record: DrawTaskRecord | None) -> str:
    if record is None:
        return "无"
    status_map: dict[str, str] = {
        "pending": "等待中",
        "running": "进行中",
        "completed": "已完成",
        "failed": "失败",
        "rejected": "审核拦截",
    }
    status_text = status_map.get(record.status, record.status)
    return f"{status_text}，task_id={record.task_id}，模型={record.model}，更新时间={record.updated_at:%m-%d %H:%M}"
