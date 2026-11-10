"""按真实会话的群号或用户 ID 检查插件访问权限。"""

from typing import Any, Dict

from ..domain.configuration.common import GeneralConfig


class ChatAccessDenied(PermissionError):
    """当前群聊或私聊被配置的访问规则拒绝。"""


def require_integration_api(config: GeneralConfig, logger: Any, operation: str) -> None:
    if not config.integration_api_enabled:
        logger.debug("插件联动 API 已关闭，拒绝调用: api=%s", operation)
        raise PermissionError("插件联动 API 已关闭，请在通用配置中开启")


def access_restricted(config: GeneralConfig) -> bool:
    return (
        config.group_access_mode == "whitelist"
        or config.private_access_mode == "whitelist"
        or bool(config.group_access_ids)
        or bool(config.private_access_ids)
    )


def require_chat_access(config: GeneralConfig, context: Dict[str, str], logger: Any) -> None:
    """群聊仅匹配群 ID，私聊仅匹配用户 ID；不匹配 session_id 或推算哈希。"""
    group_id, user_id = context.get("group_id", "").strip(), context.get("user_id", "").strip()
    if group_id:
        kind, target, mode, entries = "群聊", group_id, config.group_access_mode, config.group_access_ids
    elif user_id:
        kind, target, mode, entries = "私聊", user_id, config.private_access_mode, config.private_access_ids
    elif access_restricted(config):
        logger.warning("访问控制无法识别真实会话身份: stream_id=%s", context.get("stream_id", ""))
        raise ChatAccessDenied("无法确认当前群号或用户 ID，已拒绝访问绘图插件")
    else:
        return
    matched = target in entries
    if matched == (mode == "blacklist"):
        logger.debug(
            "访问控制拒绝: chat_type=%s mode=%s platform=%s target_id=%s stream_id=%s",
            kind, mode, context.get("platform", ""), target, context.get("stream_id", ""),
        )
        raise ChatAccessDenied(f"当前{kind}已被绘图插件的{'黑名单' if mode == 'blacklist' else '白名单'}规则限制")
