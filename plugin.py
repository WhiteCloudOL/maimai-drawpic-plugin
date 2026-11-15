"""麦麦绘图插件：组合组件并向 Runner 提供工厂入口。"""

from .src.maimai_drawpic.interfaces.api.drawing import DrawingAPIMixin
from .src.maimai_drawpic.interfaces.api.webui import WebUIAPIMixin
from .src.maimai_drawpic.application.plugin import DrawpicRuntime
from .src.maimai_drawpic.application.preferences import PreferenceMixin
from .src.maimai_drawpic.application.quotas import QuotaMixin
from .src.maimai_drawpic.interfaces.chat.context import ContextMixin
from .src.maimai_drawpic.interfaces.hooks import HookMixin
from .src.maimai_drawpic.interfaces.chat.replies import ReplyMixin
from .src.maimai_drawpic.application.submissions import RequestMixin
from .src.maimai_drawpic.interfaces.tools.drawing import DrawingToolMixin
from .src.maimai_drawpic.interfaces.tools.styles import StyleToolMixin
from .src.maimai_drawpic.interfaces.tools.status import StatusToolMixin
from .src.maimai_drawpic.interfaces.commands.images import ImageCommandMixin
from .src.maimai_drawpic.interfaces.commands.styles import StyleCommandMixin
from .src.maimai_drawpic.interfaces.commands.novelai import NovelAICommandMixin
from .src.maimai_drawpic.interfaces.commands.dispatcher import CommandMixin


class DrawpicPlugin(
    WebUIAPIMixin,
    DrawingAPIMixin,
    CommandMixin,
    ImageCommandMixin,
    StyleCommandMixin,
    NovelAICommandMixin,
    PreferenceMixin,
    QuotaMixin,
    DrawingToolMixin,
    StyleToolMixin,
    StatusToolMixin,
    HookMixin,
    ContextMixin,
    ReplyMixin,
    RequestMixin,
    DrawpicRuntime,
):
    """聚合命令、工具、生命周期和工作台接口。"""


def create_plugin() -> DrawpicPlugin:
    """供 MaiBot Runner 创建插件实例。"""
    return DrawpicPlugin()
