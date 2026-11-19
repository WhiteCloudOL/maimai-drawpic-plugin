"""只在宿主已开始的规划请求中追加绘图提醒。"""

from copy import deepcopy
from typing import Any, Dict, List, Optional
import re


REMINDER_ID = "maimai-drawpic:drawing-reminder"
REMINDERS = {
    "zh-CN": (
        "[绘图提醒] 关键词只作提醒。结合上下文确认绘图意图，闲聊、否定和引用示例不触发。"
        "新图用 draw，明确接续或改图用 edit_image。遵循原有回复规则，同一任务只提交一次。"
    ),
    "en-US": (
        "[Drawing reminder] A keyword is a cue. Confirm the request in context and skip casual discussion, negation and quoted examples. "
        "Use draw for a new image and edit_image for an explicit continuation or edit. Follow the existing reply policy and submit each task once."
    ),
    "ja-JP": (
        "[描画の確認] キーワードは目安です。文脈で依頼か確認し、雑談・否定・引用例では描画しません。"
        "新規画像はdraw、明確な続きや編集はedit_imageを使います。従来の返信ルールに従い、同じタスクは一度だけ送信します。"
    ),
}
SELF_REFERENCE_REMINDERS = {
    "zh-CN": (
        "只画机器人的自画像或自拍时直接用自我图库，设 self_reference=required、material_sources=[]。"
        "只有缺额外素材才取材。"
    ),
    "en-US": (
        "For a self-portrait or selfie of the bot alone, use its gallery and set self_reference=required and material_sources=[]. "
        "Fetch references only when additional material is missing."
    ),
    "ja-JP": (
        "ボットだけの自画像や自撮りは参照ギャラリーを使い、self_reference=required、material_sources=[]を指定します。"
        "追加の参照素材が不足している場合だけ探します。"
    ),
}
_MESSAGE = re.compile(r"\A<message\b(?P<attributes>[^>]*)>\s*\n(?P<body>.*)", re.DOTALL)


def drawing_reminder_items(
    items: List[Dict[str, Any]], tool_definitions: List[Dict[str, Any]], keywords: List[str], *, locale: str = "zh-CN",
    self_reference_enabled: bool = False,
) -> Optional[List[Dict[str, Any]]]:
    """检查最新真实发言；保持历史前缀不变，在即时提示尾部插入稳定内容。"""
    if not keywords or not any(tool.get("function", {}).get("name") in {"draw", "edit_image"} for tool in tool_definitions):
        return None
    if any(item["meta"]["item_id"] == REMINDER_ID for item in items):
        return None

    latest = None
    body = ""
    for item in reversed(items):
        if item["item_type"] != "UserMessageItem":
            if item["item_type"] != "SystemMessageItem":
                break
            continue
        text = "".join(part["text"] for part in item["parts"] if part["type"] == "text")
        message = _MESSAGE.match(text)
        if message is None:
            continue
        if 'is_self_message="true"' in message["attributes"]:
            break
        latest = item
        body = message["body"].casefold()
        break
    if latest is None or not any(keyword.casefold() in body for keyword in keywords):
        return None

    reminder_text = REMINDERS[locale]
    if self_reference_enabled:
        reminder_text += " " + SELF_REFERENCE_REMINDERS[locale]
    reminder = {
        "item_type": "UserMessageItem",
        "meta": {**latest["meta"], "item_id": REMINDER_ID, "logical_turn_id": None},
        "parts": [{"type": "text", "text": reminder_text}],
    }
    result = deepcopy(items)
    # 保留宿主最终决策提示在末尾，新增内容不进入持久聊天历史。
    position = len(items) - 1 if items[-1] is not latest and items[-1]["item_type"] == "UserMessageItem" else len(items)
    result.insert(position, reminder)
    return result
