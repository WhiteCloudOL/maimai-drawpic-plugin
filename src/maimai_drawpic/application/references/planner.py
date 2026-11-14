"""只在宿主已开始的规划请求中追加绘图提醒。"""

from copy import deepcopy
from typing import Any, Dict, List, Optional
import re


REMINDER_ID = "maimai-drawpic:drawing-reminder"
REMINDERS = {
    "zh-CN": (
        "[绘图工具提醒] 本轮用户发言可能涉及绘图。请结合上下文判断是否真的请求生成或修改图片；"
        "普通聊天、否定或引用示例不应触发绘图。需要新图时考虑 draw，明确接续或修改已有图时考虑 edit_image，"
        "不要重复提交已处理的任务。请按原有回复规则决定回复、等待或调用当前可用工具，关键词不构成调用指令。"
        "若涉及机器人自身，请区分机器人、用户和其他角色，按语义填写 reference_options.self_reference；不确定时使用 auto。"
    ),
    "en-US": (
        "[Drawing tool reminder] The current user message may concern drawing. Use context to decide whether an image is "
        "actually requested; casual discussion, negation or quoted examples do not request drawing. Consider draw for a new "
        "image and edit_image for an explicit continuation or edit. Do not resubmit completed requests. Follow the existing "
        "reply policy when choosing to reply, wait or use an available tool; a keyword is not a tool instruction. Distinguish "
        "the bot, user and other characters when setting reference_options.self_reference; use auto when uncertain."
    ),
    "ja-JP": (
        "[描画ツールの確認] 今回のユーザー発言は描画に関係する可能性があります。文脈から画像生成・編集の依頼か判断し、"
        "雑談・否定・引用例では描画しないでください。新規画像はdraw、明確な続きや編集はedit_imageを検討し、"
        "処理済みの依頼を重複送信しないでください。返信・待機・利用可能ツールの選択は従来の返信ルールに従い、"
        "キーワードだけを呼び出し指示と解釈しないでください。reference_options.self_referenceはボット・ユーザー・他の人物を文意で区別し、"
        "不確かな場合はautoを使ってください。"
    ),
}
_MESSAGE = re.compile(r"\A<message\b(?P<attributes>[^>]*)>\s*\n(?P<body>.*)", re.DOTALL)


def drawing_reminder_items(
    items: List[Dict[str, Any]], tool_definitions: List[Dict[str, Any]], keywords: List[str], *, locale: str = "zh-CN",
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

    reminder = {
        "item_type": "UserMessageItem",
        "meta": {**latest["meta"], "item_id": REMINDER_ID, "logical_turn_id": None},
        "parts": [{"type": "text", "text": REMINDERS[locale]}],
    }
    result = deepcopy(items)
    # 保留宿主最终决策提示在末尾，新增内容不进入持久聊天历史。
    position = len(items) - 1 if items[-1] is not latest and items[-1]["item_type"] == "UserMessageItem" else len(items)
    result.insert(position, reminder)
    return result
