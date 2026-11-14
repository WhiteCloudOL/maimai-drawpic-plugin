"""规划阶段触发、缓存前缀和具体模型路由，不调用收费模型。"""

from copy import deepcopy
from types import SimpleNamespace
import asyncio
import json

import pytest

from test_references import module
from test_workspace import make_plugin


def item(kind, text="", identity="message-1"):
    return {"item_type": kind, "meta": {"item_id": identity, "logical_turn_id": None, "timestamp": "2026-11-14T12:00:00"},
            "parts": [{"type": "text", "text": text}]}


def user(text, identity="message-1", attributes='user="用户"'):
    return item("UserMessageItem", f'<message msg_id="1" time="12:00:00" {attributes}>\n{text}\n</message>', identity)


TOOLS = [{"type": "function", "function": {"name": "draw"}}, {"type": "function", "function": {"name": "edit_image"}}]


@pytest.mark.parametrize("message,keywords,tools,expected", [
    ("发张自拍", ["自拍", "画"], TOOLS, True),
    ("帮我画只猫", ["自拍", "画"], TOOLS, True),
    ("DRAW a cat", ["draw"], TOOLS, True),
    ("下午好", ["自拍", "画"], TOOLS, False),
    ("画只猫", [], TOOLS, False),
    ("画只猫", ["画"], [], False),
    ("画只猫", ["画"], [{"function": {"name": "unrelated"}}], False),
])
def test_reminder_only_for_matching_current_user_and_available_tool(message, keywords, tools, expected):
    planner = module("application.references.planner")
    history = [item("SystemMessageItem", "固定系统提示词", "system"), user(message), item("UserMessageItem", "宿主最终提示", "tail")]
    original = deepcopy(history)
    result = planner.drawing_reminder_items(history, tools, keywords)
    assert (result is not None) is expected
    assert history == original
    if result is not None:
        assert result[:2] == history[:2] and result[-1] == history[-1]
        assert result[2]["meta"]["item_id"] == planner.REMINDER_ID
        assert planner.drawing_reminder_items(result, tools, keywords) is None


@pytest.mark.parametrize("after", [
    item("AssistantMessageItem", "已经回复", "assistant"),
    item("FunctionCallItem", "已提交画图", "call"),
    item("FunctionCallOutputItem", "任务已受理", "output"),
    user("机器人发言里的画", "self", 'user="麦麦" is_self_message="true"'),
    user("今天天气如何", "new"),
])
def test_reminder_does_not_reuse_keywords_from_old_turns_or_bot(after):
    planner = module("application.references.planner")
    history = [user("画一只猫"), after, item("UserMessageItem", "本轮即时提示", "tail")]
    assert planner.drawing_reminder_items(history, TOOLS, ["画"]) is None


def test_reminder_uses_stable_suffix_without_keyword_or_user_content():
    planner = module("application.references.planner")
    a = planner.drawing_reminder_items([user("画秘密角色A")], TOOLS, ["画"])
    b = planner.drawing_reminder_items([user("自拍")], TOOLS, ["自拍"])
    assert a[-1]["parts"] == b[-1]["parts"]
    assert "秘密角色A" not in a[-1]["parts"][0]["text"]
    for locale in ("zh-CN", "en-US", "ja-JP"):
        assert planner.drawing_reminder_items([user("画")], TOOLS, ["画"], locale=locale)[-1]["parts"]


def test_planner_hook_preserves_host_fields_without_starting_models_or_tasks(make_plugin):
    async def run():
        plugin = make_plugin(False)
        # 自我参考默认关闭，但绘图意图提醒可用。
        assert not plugin.config.general.references.self_reference_enabled
        args = dict(items=[user("画只猫")], tool_definitions=TOOLS, item_schema_version=1, session_id="real-session",
                    selected_history_count=1, built_message_count=1, selection_reason="宿主放行")
        result = await plugin.handle_drawing_keyword_reminder(**args)
        changed = result["modified_kwargs"]
        assert changed["session_id"] == "real-session" and changed["selection_reason"] == "宿主放行"
        assert changed["tool_definitions"] == TOOLS and changed["selected_history_count"] == 1
        assert result["action"] == "continue"
        plugin.config.general.references.self_keywords = []
        assert "modified_kwargs" not in await plugin.handle_drawing_keyword_reminder(**args)
    asyncio.run(run())


def test_planner_hook_respects_chat_access(make_plugin, monkeypatch):
    async def run():
        plugin = make_plugin(False)
        plugin.config.general.group_access_mode = "whitelist"
        plugin.config.general.group_access_ids = ["100"]
        async def existing(stream_id):
            assert stream_id == "real-session"
            return {"stream_id": stream_id, "group_id": "200", "user_id": "300", "platform": "qq"}
        monkeypatch.setattr(plugin, "_require_stream_service", lambda: SimpleNamespace(existing_stream_context=existing))
        result = await plugin.handle_drawing_keyword_reminder(
            items=[user("画只猫")], tool_definitions=TOOLS, item_schema_version=1, session_id="real-session")
        assert "modified_kwargs" not in result
    asyncio.run(run())


@pytest.mark.parametrize("model,expected", [
    ("vlm", {"task_name": "vlm"}),
    ("fast-vision", {"task_name": "vlm", "model_name": "fast-vision"}),
    ("planner", {"task_name": "vlm", "model_name": "planner"}),
    ("model:vlm", {"task_name": "vlm", "model_name": "vlm"}),
])
def test_recognition_routes_task_default_and_strict_configured_names(model, expected):
    async def run():
        from maibot_sdk.capabilities.llm import LLMCapability
        requests = []
        async def rpc(capability, **kwargs):
            assert capability == "llm.generate"
            requests.append(kwargs)
            return {"content": json.dumps({"subject": "other"})}
        llm = LLMCapability(SimpleNamespace(call_capability=rpc))
        recognizer = module("application.references.recognition").ReferenceRecognizer(SimpleNamespace(llm=llm), model)
        assert await recognizer.self_subject("画只猫", ["麦麦"]) == "other"
        route = {key: value for key, value in requests[0].items() if key in {"task_name", "model_name"}}
        assert route == expected and requests[0]["model"] == ""
    asyncio.run(run())
