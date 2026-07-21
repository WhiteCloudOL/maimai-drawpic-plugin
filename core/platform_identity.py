"""识别聊天平台运行时身份。"""

import re


_QQ_PLATFORMS = frozenset({"qq", "qqguild"})
_QQ_OFFICIAL_OPENID_PATTERN = re.compile(r"[0-9A-Fa-f]{32}")


def is_qq_platform(platform: str) -> bool:
    """判断是否为 QQ 平台。"""

    return platform.strip().lower() in _QQ_PLATFORMS


def is_qq_identifier(identifier: str) -> bool:
    """接受 OneBot 数字 ID 或 QQ 官方 OpenID。"""

    normalized_identifier = identifier.strip()
    return normalized_identifier.isdigit() or _QQ_OFFICIAL_OPENID_PATTERN.fullmatch(normalized_identifier) is not None
