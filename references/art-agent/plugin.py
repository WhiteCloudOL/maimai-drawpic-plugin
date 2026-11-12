"""绘图编排层（参考实现） · 主入口

一个工具 `draw`，三条通道，每条挂一个可配置的引擎：

| 通道 | 默认引擎 | 费用 | 说明 |
|---|---|---|---|
| self | ark | 按引擎计价 | 本地人物形象图 + 可选会话参考图，一起喂图生图引擎 |
| illustration | drawpic | 0（带水印） | 纯文生图；可改配成 ark |
| reference | ark | 按引擎计价 | 真图生图 |

## 为什么要这一层

底下插件各自注册了工具，Planner 面对 4 个形状相近的选项（draw / edit_image /
generate_photo / generate_scene_photo），实测选错过（要自画像走了水墨插画）。这里把它们
收成一个入口，对外只留 `draw`。通道判定 v0.6 起由插件内部 LLM 判别
（提示词在 config.toml [intent].prompt，走 utils 任务，按模型计价），失败自动回退关键词规则。

## 引擎能力是硬约束

reference 通道只接受声明支持参考图的引擎。硅基的可图收下源图后会**静默丢弃**，
接口照样 200，画出来却与参考图无关——所以它只能待在被标记为不支持参考图的位置。

## 直连与兜底

ark 引擎自己发请求，才能认出「输出被版权过滤」这种只有图生图引擎会返回的错误，
并只在**这一种情况**下换 4.0 重试；超时、限流、鉴权失败都不重试（换模型也救不回来）。
直连是同步出图，所以扔后台跑，立即回执，出图后自己发到聊天。

## 边界

- 参考图只认一张（多图接口留着，等有需求再放）。
- 外链下载先做公网校验，禁私网/回环/组播。
- 下游异步任务「提交即返回」；ark 返回 running，完成与否看日志。
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import ipaddress
import inspect
import json
import os
import re
import socket
import time
from typing import Any, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import httpx

from maibot_sdk import API, MaiBotPlugin, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from .config import ArtAgentConfig
from . import search_ref
from .vendor.maimai_drawing_client import DrawingClient, DrawingError

MAITU_PLUGIN = "maitu.photo-studio"
DRAWPIC_PLUGIN = "maimai-drawpic-plugin"

#: self 通道单张成本（图生图引擎 Seedream），只用于控制台估算，不参与扣费
SELF_COST = 0.12

#: WebUI 允许逐项回写的配置（其余字段只读，避免误改判定词顺序等）
EDITABLE_FIELDS = {
    # 通道开关（cast 是 v1.1.11 控制台里列了、后端却漏放行的一项）
    ("lanes", "self_lane"): "bool",
    ("lanes", "cast"): "bool",
    ("lanes", "illustration"): "bool",
    ("lanes", "reference"): "bool",
    # 额度与限制
    ("limits", "daily_self_max"): "int",
    ("limits", "daily_cast_max"): "int",
    ("limits", "daily_reference_max"): "int",
    ("limits", "max_companions"): "int",
    ("limits", "refs_per_subject"): "int",
    ("limits", "submit_timeout_seconds"): "float",
    # 参考图、判定词与判路
    ("reference", "chat_recent_fallback"): "bool",
    ("reference", "allowed_hosts"): "list",
    ("reference", "download_timeout_seconds"): "float",
    ("self_channel", "keywords"): "list",
    ("intent", "use_llm"): "bool",
    ("intent", "model_task"): "str",
    ("intent", "timeout_seconds"): "float",
    # 引擎选择
    ("engines", "self_engine"): "str",
    ("engines", "illustration_engine"): "str",
    ("engines", "reference_engine"): "str",
    # 画面预设（身份主要由参考图承载，改文字时别堆否定词）
    ("self_prompts", "identity"): "str",
    ("self_prompts", "style"): "str",
    ("self_prompts", "scene_hint"): "str",
    ("self_prompts", "avoid"): "str",
    ("self_prompts", "edit_hint"): "str",
    ("illustration", "enabled"): "bool",
    ("illustration", "style"): "str",
    # 联网搜图
    ("search", "enabled"): "bool",
    ("search", "min_score"): "int",
    ("search", "max_candidates"): "int",
    ("search", "review_model"): "str",
}

_IMAGE_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


class ArtAgentError(RuntimeError):
    """可以原样说给用户听的失败原因。"""


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _decode_base64_image(value: str) -> Optional[bytes]:
    encoded = (value or "").strip()
    if not encoded:
        return None
    if encoded.startswith("data:"):
        match = re.match(r"^data:image/[^;,]+;base64,(.*)$", encoded, flags=re.I | re.S)
        if match is None:
            return None
        encoded = match.group(1)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error):
        return None
    return data or None


def _mai_root() -> str:
    """MaiBot 实例根目录（插件在 <root>/plugins/<plugin>/plugin.py）。"""

    try:
        return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    except Exception:
        return ""


def _image_cache_dirs() -> List[str]:
    """本机图片缓存目录候选（按顺序找）。

    🔴 2026-11-11 18:3x：库里存的图片段只有 ``{"type":"image","data":"[图片：描述]","hash":...}``，
    **没有 base64**。所以不管走不走 ``get_by_id`` 回查，只要宿主没补二进制就取不到图。
    但图片本体一直在磁盘上：``data/images/<hash>.jpeg``（a-memorix 另存一份 .jpg）。
    按 hash 读文件是这里唯一不依赖宿主的取法。
    """

    root = _mai_root()
    if not root:
        return []
    return [
        os.path.join(root, "data", "images"),
        os.path.join(root, "data", "a-memorix", "images", "assets"),
    ]


def _segments_from_db(message_id: str) -> List[Any]:
    """只读查库，按消息 ID 取消息段。

    ``get_by_id`` 能不能带回图片段要看宿主心情（还有归一化形态的坑），
    但原始段一定在库里的 ``raw_content``（msgpack）。这里只读、不写、不复制库文件。
    """

    token = (message_id or "").strip()
    root = _mai_root()
    if not token or not root:
        return []
    path = os.path.join(root, "data", "MaiBot.db")
    if not os.path.isfile(path):
        return []
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute(
                "SELECT raw_content FROM mai_messages WHERE message_id = ? LIMIT 1", (token,)
            ).fetchone()
        finally:
            con.close()
    except Exception:
        return []
    raw = row[0] if row else None
    if not raw:
        return []
    if isinstance(raw, (bytes, bytearray)):
        try:
            import msgpack

            parsed = msgpack.unpackb(bytes(raw), raw=False)
        except Exception:
            return []
    else:
        try:
            parsed = json.loads(str(raw))
        except Exception:
            return []
    return parsed if isinstance(parsed, list) else []



def _image_by_hash(digest: str) -> bytes:
    """按图片 hash 去本地缓存目录读原图；找不到返回 b""。"""

    token = (digest or "").strip()
    if len(token) < 16 or not re.fullmatch(r"[0-9a-fA-F]+", token):
        return b""
    for base in _image_cache_dirs():
        if not os.path.isdir(base):
            continue
        for suffix in (".jpeg", ".jpg", ".png", ".webp", ".gif"):
            path = os.path.join(base, token + suffix)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "rb") as handle:
                    data = handle.read()
            except OSError:
                continue
            if data and _looks_like_image(data):
                return data
    return b""


def extract_message_images(message: Any) -> List[bytes]:
    """从一条消息里取出图片 bytes（与写真插件同源的取法）。

    优先用段里自带的 base64；没有就按段里的 ``hash`` 去本地图片缓存读文件。
    后者是常态——聊天历史归一时图片段只留描述和 hash。
    """

    if not isinstance(message, Mapping):
        return []
    segments: List[Any] = []
    for key in ("raw_message", "segments", "message_segments", "content"):
        value = message.get(key)
        if isinstance(value, list):
            segments.extend(value)
    images: List[bytes] = []
    for segment in segments:
        if not isinstance(segment, Mapping):
            continue
        segment_type = str(segment.get("type") or segment.get("content_type") or "").casefold()
        if segment_type not in {"image", "picture", "photo"}:
            continue
        encoded = _first_text(
            segment.get("binary_data_base64"),
            segment.get("base64"),
            segment.get("data_base64"),
        )
        if not encoded:
            data = segment.get("data")
            if isinstance(data, str) and data.startswith("data:image/"):
                encoded = data
        image = _decode_base64_image(encoded)
        if not image:
            image = _image_by_hash(
                _first_text(segment.get("hash"), segment.get("file_hash"), segment.get("sha256"))
            )
        if image:
            images.append(image)
    return images


def reply_message_id(message: Any) -> str:
    """取「被回复那条消息」的 ID。"""

    if not isinstance(message, Mapping):
        return ""
    direct = _first_text(message.get("reply_to"), message.get("quoted_message_id"))
    if direct:
        return direct
    for key in ("raw_message", "segments", "message_segments"):
        segments = message.get(key)
        if not isinstance(segments, list):
            continue
        for segment in segments:
            if not isinstance(segment, Mapping):
                continue
            if str(segment.get("type") or "").casefold() != "reply":
                continue
            raw_data = segment.get("data")
            # 🔴 NapCat 的 reply 段是 {"type":"reply","data":"627472789"}，
            # data 直接就是被引用的消息号，不是字典。只认字典会让引用永远取不到，
            # 静默退到 recent 兜底（2026-11-11 16:37 实测）。
            if isinstance(raw_data, str) and raw_data.strip():
                return raw_data.strip()
            data = _mapping(raw_data)
            found = _first_text(data.get("target_message_id"), data.get("message_id"), data.get("id"))
            if found:
                return found
    return ""


def _unwrap_message(payload: Any) -> Any:
    """把 ``message.get_by_id`` 的返回值统一成消息字典。

    🔴 2026-11-11 18:10 实测：SDK 命中 ``_CAPABILITY_RESULT_KEYS`` 时会**直接返回消息字典**
    （顶层就有 message_id / raw_message），不再包一层 ``{"message": …}``。
    旧写法 ``payload.get("message")`` 在这种形态下拿到 None，`_hydrate_message` 静默失效、
    `_images_by_id` 恒返回空 —— 表现就是「用户明明引用了图，日志却记 ref= 空，
    然后 reference 通道无图降级成插画通道」。两种形态都必须认。
    """

    if not isinstance(payload, Mapping):
        return None
    if "success" in payload and not payload.get("success"):
        return None
    inner = payload.get("message")
    if isinstance(inner, Mapping):
        return inner
    if payload.get("message_id") or payload.get("raw_message") is not None:
        return payload
    return None



def _iter_json_objects(text: str):
    """按花括号配对切出文本里所有顶层 JSON 对象。

    不能用 ``\\{[^{}]*\\}`` 这种正则——判路输出里 ``subjects`` 是嵌套结构，
    正则只会捞到最内层的 ``{"who": "小鱼"}``，整段就解析失败了。
    这里按深度扫描并跳过字符串内部（含转义），能正确拿到整个对象。
    """

    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    yield text[start : i + 1]
                    start = -1


_MULTI_HINTS = (
    "和", "与", "跟", "一起", "合照", "合影", "同框",
    "俩人", "两人", "三人", "你俩", "我俩", "还有", "带着",
)


def _looks_multi(text: str) -> bool:
    """粗判请求里是不是有多个人。只用于「要不要补跑一次判路拿 subjects」，
    判错了最多多花一次 utils（按模型计价），不影响画面，所以宁可放宽。"""

    lowered = (text or "").strip()
    if not lowered:
        return False
    return any(hint in lowered for hint in _MULTI_HINTS)


def _parse_intent_json(raw: str) -> Tuple[str, str, dict]:
    """从 LLM 回复里提取通道、理由、搜索关键词与多主体清单。

    返回 ``(lane, reason, extras)``；extras 里的 ``outfit_query`` / ``search_query``
    为空字符串时表示不需要联网搜图。容忍代码块围栏、前后解释文字，以及
    ``subjects`` 这种嵌套结构。
    """
    if not raw:
        return "", "", {}
    blobs: List[str] = []
    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fence:
        blobs.append(fence.group(1))
    blobs.extend(_iter_json_objects(raw))
    blobs.append(raw)
    for text in blobs:
        try:
            data = json.loads(text)
        except Exception:
            continue
        if isinstance(data, dict):
            lane = str(data.get("lane") or "").strip().casefold()
            reason = str(data.get("reason") or "").strip()
            if lane in {"self", "reference", "illustration", "cast"}:
                return lane, reason, _search_extras(data)
    match = re.search(
        r'"lane"\s*:\s*"(self|reference|illustration|cast)"', raw, re.I
    )
    if match:
        return match.group(1).casefold(), "", {}
    return "", "", {}


def _search_extras(data: Mapping) -> dict:
    """取出判路输出里的搜索关键词与多主体清单，做长度与格式清洗。

    ``subjects`` 允许两种写法：完整对象 ``{who, kind, query}``，或光一个名字字符串
    （后者按「其他角色」处理，自动补「角色名 立绘」）。解析失败一律退化成空列表，
    调用方看到空列表就走原来的单主体逻辑。
    """

    def _clean(key: str) -> str:
        value = str(data.get(key) or "").strip()
        value = re.sub(r"\s+", " ", value)
        # 模型常用「/」「-」「无」当占位表示「这项没有」。以前会原样拿去搜，
        # 真的为「一个斜杠」跑一轮搜图；统一清成空字符串。
        if value.casefold() in {"/", "-", "—", "无", "none", "null", "空", "n/a"}:
            return ""
        return value[:60]

    subjects: List[dict] = []
    raw_subjects = data.get("subjects")
    if isinstance(raw_subjects, list):
        for item in raw_subjects:
            if isinstance(item, Mapping):
                who = str(item.get("who") or "").strip()[:20]
                kind = str(item.get("kind") or "").strip().casefold()
                query = str(item.get("query") or "").strip()[:60]
            elif isinstance(item, str):
                who = item.strip()[:20]
                kind, query = "character", ""
            else:
                continue
            if not who:
                continue
            # 她自己只认这几个写法。「我」不在此列——用户说「我」指他自己，
            # 那是真人、没有立绘可搜，不能用她的形象图顶上去。
            if who in {"主角色", "她自己", "你"}:
                kind = "self"
            elif kind not in {"self", "character"}:
                kind = "character"
            if kind == "character" and not query:
                query = f"{who} 立绘"
            item_out = {"who": who, "kind": kind, "query": query}
            if any(s["who"] == who for s in subjects):
                continue
            subjects.append(item_out)

    layout = str(data.get("layout") or "").strip().casefold()
    if layout not in {"portrait", "landscape", "square"}:
        layout = "square"

    return {
        "outfit_query": _clean("outfit_query"),
        "search_query": _clean("search_query"),
        "subjects": subjects,
        "relation": str(data.get("relation") or "").strip()[:120],
        "layout": layout,
    }

# 第一人称在场信号：判定规则的最后一道兜底（LLM 判别失败 / 无图降级复核时才会用到）。
# 只认「我(们) … 穿/和/跟/与」，不认单独的「我」——「给我画个小猫」不该算画她自己。
_SELF_PRESENCE = re.compile(
    # 我穿 / 我和她 / 我们一起
    r"我(?:们)?[^，。；]{0,6}(?:穿|和|跟|与)"
    # 把我也画上 / 把我画进去（「把这张改成水墨」不该命中）
    r"|把我(?:也)?[^，。；]{0,3}(?:画|加|放|带)"
    r"|(?:加|带|算)上我"
    r"|我也(?:在|要|想|去)"
    # 画咱俩 / 你俩 / 我俩
    r"|咱(?:们)?俩|我俩|你俩"
)


def _looks_like_image(data: bytes) -> bool:
    if any(data.startswith(magic) for magic, _ in _IMAGE_MAGIC):
        return True
    # WebP 不是固定开头，要看 RIFF....WEBP
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


def _media_type(data: bytes) -> str:
    for magic, media in _IMAGE_MAGIC:
        if data.startswith(magic):
            return media
    return "image/jpeg"


def _ts_of(value: str) -> int:
    """把 'YYYY-MM-DDTHH:MM:SS' 解析成时间戳；解析不了返回 0。"""

    try:
        return int(time.mktime(time.strptime(value[:19], "%Y-%m-%dT%H:%M:%S")))
    except (ValueError, TypeError, OverflowError):
        return 0


def _make_thumbnail(data: bytes, max_edge: int = 240) -> Optional[bytes]:
    """生成小尺寸 JPEG 缩略图；没有 Pillow 或图片解不开时返回 None。

    WebUI 响应超过 512 KiB 会被宿主整个拒掉（502），所以列表接口绝不能带原图 base64。
    """

    try:
        from io import BytesIO

        from PIL import Image, ImageOps

        with Image.open(BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((max_edge, max_edge))
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")
            out = BytesIO()
            img.save(out, "JPEG", quality=70)
            return out.getvalue()
    except Exception:
        return None


class ArtOrchestratorPlugin(MaiBotPlugin):
    """绘图调度的唯一入口。"""

    config_model = ArtAgentConfig

    def __init__(self) -> None:
        super().__init__()
        self._plugin_dir = os.path.dirname(os.path.abspath(__file__))
        # 直连引擎是同步出图，扔后台跑，免得把 Planner 那一轮卡住
        self._bg_tasks: set = set()
        # 同一句话刚提交过的记录（stream|prompt → 时间戳），用来挡重复调用
        self._draw_calls: dict = {}

    # ---------------- 生命周期 ----------------

    async def on_load(self) -> None:
        cfg = self._cfg()
        self.ctx.logger.info(
            "绘图编排层 v%s 已加载（启用=%s，引擎 self=%s/cast=ark/illustration=%s/reference=%s，"
            "ark 主=%s 兜底=%s，额度 self=%s/cast=%s/reference=%s）",
            cfg.plugin.version,
            cfg.plugin.enabled,
            cfg.engines.self_engine,
            cfg.engines.illustration_engine,
            cfg.engines.reference_engine,
            cfg.engines.ark.model,
            cfg.engines.ark.fallback_model,
            cfg.limits.daily_self_max or "不限",
            cfg.limits.daily_cast_max or "不限",
            cfg.limits.daily_reference_max or "不限",
        )

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        del config_data, version
        self.ctx.logger.info("绘图编排层配置更新: scope=%s", scope)

    async def on_unload(self) -> None:
        for task in list(self._bg_tasks):
            task.cancel()
        self._bg_tasks.clear()
        self.ctx.logger.info("绘图编排层已卸载")

    # ---------------- 基础 ----------------

    def _cfg(self) -> ArtAgentConfig:
        return self.config  # type: ignore[return-value]

    def _data_dir(self) -> str:
        try:
            base = str(self.ctx.paths.data_dir)
        except Exception:
            base = os.path.join(self._plugin_dir, "data")
        os.makedirs(base, exist_ok=True)
        return base

    # ---------------- 额度（按通道分开算） ----------------

    def _quota_file(self, name: str = "self") -> str:
        return os.path.join(self._data_dir(), f"{name}_quota.json")

    def _quota_state(self, name: str = "self") -> dict:
        today = time.strftime("%Y-%m-%d")
        try:
            with open(self._quota_file(name), "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except Exception:
            state = {}
        if not isinstance(state, dict) or state.get("date") != today:
            state = {"date": today, "count": 0}
        return state

    def _consume_quota(self, name: str, limit: int) -> Tuple[bool, int, int]:
        """扣一次额度。返回（是否允许，已用，上限）。上限 <= 0 = 不限。"""

        limit = int(limit or 0)
        if limit <= 0:
            return True, 0, 0
        state = self._quota_state(name)
        used = int(state.get("count") or 0)
        if used >= limit:
            return False, used, limit
        state["count"] = used + 1
        try:
            with open(self._quota_file(name), "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False)
        except Exception as exc:  # 记账失败不阻断出图
            self.ctx.logger.warning("%s 额度写入失败: %s", name, exc)
        return True, used + 1, limit

    def _consume_self_quota(self) -> Tuple[bool, int, int]:
        return self._consume_quota("self", int(self._cfg().limits.daily_self_max or 0))

    def _consume_reference_quota(self) -> Tuple[bool, int, int]:
        return self._consume_quota("reference", int(self._cfg().limits.daily_reference_max or 0))

    def _refund_quota(self, name: str, limit: int) -> None:
        """退回一次额度（出图失败时用）。

        额度在「提交成功」时就扣了，但提交成功不等于画出来了：引擎 500、审核
        拒绝、图片下载超时都会让这次白花。不退回的话 self 一天只有 2 张，
        一次失败就废掉半天（2026-11-11 19:0x 补）。
        """

        limit = int(limit or 0)
        if limit <= 0 or not name:
            return
        state = self._quota_state(name)
        used = int(state.get("count") or 0)
        if used <= 0:
            return
        state["count"] = used - 1
        try:
            with open(self._quota_file(name), "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False)
        except Exception as exc:
            self.ctx.logger.warning("%s 额度回退失败: %s", name, exc)
        else:
            self.ctx.logger.info("额度已退回: %s %s -> %s", name, used, used - 1)

    def _check_quota(self, name: str, limit: int) -> Tuple[bool, int, int]:
        """只查不扣。先检查、提交成功后再扣，失败就不占额度。"""

        limit = int(limit or 0)
        if limit <= 0:
            return True, 0, 0
        used = int(self._quota_state(name).get("count") or 0)
        return used < limit, used, limit

    # ---------------- 绘制记录（供 WebUI 控制台） ----------------

    def _history_file(self) -> str:
        return os.path.join(self._data_dir(), "history.jsonl")

    def _history_entries(self) -> List[dict]:
        """读全部历史；坏行跳过，不让一条脏数据废掉整个控制台。"""

        rows: List[dict] = []
        try:
            with open(self._history_file(), "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(item, dict):
                        rows.append(item)
        except FileNotFoundError:
            return []
        except Exception as exc:
            self.ctx.logger.warning("读取绘制记录失败: %s", exc)
        return rows

    def _rotate_history(self, path: str, keep: int = 400) -> None:
        try:
            if os.path.getsize(path) <= 400 * 1024:
                return
            with open(path, "r", encoding="utf-8") as handle:
                lines = [line for line in handle if line.strip()]
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                handle.writelines(lines[-keep:])
        except Exception as exc:
            self.ctx.logger.warning("绘制记录轮转失败: %s", exc)

    def _record(self, info: Mapping[str, Any], result: Mapping[str, Any], elapsed_ms: int) -> None:
        entry = {
            "ts": int(time.time()),
            "lane": str(info.get("lane") or ""),
            "reference": str(info.get("reference") or "none"),
            "size": str(info.get("size") or ""),
            "ok": bool(result.get("success")),
            "status": str(result.get("status") or ""),
            "task_id": str(result.get("task_id") or ""),
            "prompt": str(info.get("prompt") or "")[:160],
            "note": str(result.get("message") or "")[:200],
            "elapsed_ms": max(0, int(elapsed_ms)),
            "source": str(info.get("source") or "chat"),
        }
        path = self._history_file()
        try:
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._rotate_history(path)
        except Exception as exc:
            self.ctx.logger.warning("写入绘制记录失败: %s", exc)

    @staticmethod
    def _day_of(item: Mapping[str, Any]) -> str:
        try:
            return time.strftime("%Y-%m-%d", time.localtime(int(item.get("ts") or 0)))
        except Exception:
            return ""

    def _lane_price(self, lane: str) -> float:
        """通道单价随引擎表走：ark 直连读引擎配置；maitu 写真按引擎计价；drawpic 插画不单独计费。"""

        cfg = self._cfg()
        name = {
            "self": cfg.engines.self_engine,
            "reference": cfg.engines.reference_engine,
            "illustration": cfg.engines.illustration_engine,
            "cast": "ark",
        }.get(lane, "")
        if str(name).strip().casefold() == "ark":
            return float(cfg.engines.ark.price or 0.0)
        if lane == "self":
            return SELF_COST  # maitu 写真价
        return 0.0

    def _stats(self, days: int = 7) -> dict:
        rows = self._history_entries()
        today = time.strftime("%Y-%m-%d")
        since = time.strftime("%Y-%m-%d", time.localtime(time.time() - max(0, days - 1) * 86400))

        def bucket(items: List[dict]) -> dict:
            lanes = {"self": 0, "cast": 0, "illustration": 0, "reference": 0}
            paid_self = 0
            cost = 0.0
            for item in items:
                lane = str(item.get("lane") or "")
                if lane in lanes:
                    lanes[lane] += 1
                if item.get("ok"):
                    cost += self._lane_price(lane)
                if item.get("ok") and lane == "self":
                    paid_self += 1
            return {
                "total": len(items),
                "lanes": lanes,
                "failed": sum(1 for item in items if not item.get("ok")),
                "paid_self": paid_self,
                "cost": round(cost, 3),
            }

        return {
            "today": bucket([item for item in rows if self._day_of(item) == today]),
            "week": bucket([item for item in rows if self._day_of(item) >= since]),
            "total_records": len(rows),
        }

    def _downstream(self, payload: Mapping[str, Any]) -> dict:
        """从组件列表里找下游插件；找不到不等于坏了，只标「未加载」。"""

        found = {
            MAITU_PLUGIN: {"loaded": False, "tools": [], "tool_total": 0, "tool_enabled": 0},
            DRAWPIC_PLUGIN: {"loaded": False, "tools": [], "tool_total": 0, "tool_enabled": 0},
        }
        for key, info in payload.items():
            text = str(key).casefold()
            if not isinstance(info, Mapping):
                continue
            comps = info.get("components")
            rows = [comp for comp in (comps if isinstance(comps, list) else []) if isinstance(comp, Mapping)]
            names = [str(comp.get("name") or comp.get("full_name") or "") for comp in rows]
            tools = [comp for comp in rows if str(comp.get("type") or "").casefold() == "tool"]
            stats = {
                "tools": names,
                "tool_total": len(tools),
                "tool_enabled": sum(1 for comp in tools if comp.get("enabled", True)),
            }
            if "maitu" in text or "photo-studio" in text:
                found[MAITU_PLUGIN] = {"loaded": True, **stats}
            elif "drawpic" in text:
                found[DRAWPIC_PLUGIN] = {"loaded": True, **stats}
        return found

    async def _component_payload(self) -> Mapping[str, Any]:
        try:
            raw = await self.ctx.component.get_all_plugins()
        except Exception as exc:
            self.ctx.logger.warning("读取组件列表失败: %s", exc)
            return {}
        if not isinstance(raw, Mapping) or raw.get("success") is False:
            return {}
        payload = raw.get("plugins") if isinstance(raw.get("plugins"), Mapping) else raw
        return payload if isinstance(payload, Mapping) else {}

    def _config_snapshot(self) -> dict:
        cfg = self._cfg()
        # key 可能是「自己填的」也可能是「从写真插件借的」，这里只回报最终能不能用
        try:
            self._ark_api_key()
            ark_key_ready = True
        except Exception:
            ark_key_ready = False
        return {
            "lanes": {
                "self_lane": bool(cfg.lanes.self_lane),
                "cast": bool(cfg.lanes.cast),
                "illustration": bool(cfg.lanes.illustration),
                "reference": bool(cfg.lanes.reference),
            },
            "limits": {
                "daily_self_max": int(cfg.limits.daily_self_max or 0),
                "daily_reference_max": int(cfg.limits.daily_reference_max or 0),
                "daily_cast_max": int(cfg.limits.daily_cast_max or 0),
                "max_companions": int(cfg.limits.max_companions or 0),
                "refs_per_subject": int(cfg.limits.refs_per_subject or 1),
                "submit_timeout_seconds": float(cfg.limits.submit_timeout_seconds or 20),
            },
            "reference": {
                "chat_recent_fallback": bool(cfg.reference.chat_recent_fallback),
                "allowed_hosts": list(cfg.reference.allowed_hosts or []),
                "download_max_bytes": int(cfg.reference.download_max_bytes or 0),
                "download_timeout_seconds": float(cfg.reference.download_timeout_seconds or 0),
            },
            "self_channel": {"keywords": list(cfg.self_channel.keywords or [])},
            "intent": {
                "use_llm": bool(cfg.intent.use_llm),
                "model_task": str(cfg.intent.model_task),
                "timeout_seconds": float(cfg.intent.timeout_seconds or 0),
            },
            "engines": {
                "self_engine": str(cfg.engines.self_engine),
                "illustration_engine": str(cfg.engines.illustration_engine),
                "reference_engine": str(cfg.engines.reference_engine),
                "ark": {
                    "enabled": bool(cfg.engines.ark.enabled),
                    "model": str(cfg.engines.ark.model),
                    "fallback_model": str(cfg.engines.ark.fallback_model),
                    # 绝不回传明文 key，只说「现在能不能用」
                    "has_api_key": ark_key_ready,
                    "max_references": int(cfg.engines.ark.max_references or 1),
                },
            },
            "self_prompts": {
                "identity": str(cfg.self_prompts.identity),
                "style": str(cfg.self_prompts.style),
                "scene_hint": str(cfg.self_prompts.scene_hint),
                "avoid": str(cfg.self_prompts.avoid),
                "edit_hint": str(cfg.self_prompts.edit_hint),
            },
            "illustration": {
                "enabled": bool(cfg.illustration.enabled),
                "style": str(cfg.illustration.style),
            },
            "search": {
                "enabled": bool(cfg.search.enabled),
                "min_score": int(cfg.search.min_score or 0),
                "max_candidates": int(cfg.search.max_candidates or 0),
                "review_model": str(cfg.search.review_model),
            },
        }

    # ---------------- 配置回写 ----------------

    def _config_path(self) -> str:
        return os.path.join(self._plugin_dir, "config.toml")

    def _persist_config(self, section: str, key: str, value: Any) -> None:
        """只改一个键，保留注释；没有 tomlkit 时宁可只在内存生效也不重写整份文件。"""

        try:
            import tomlkit
        except ImportError:
            self.ctx.logger.warning("缺少 tomlkit，配置只在本进程内生效")
            return
        path = self._config_path()
        with open(path, "r", encoding="utf-8") as handle:
            document = tomlkit.parse(handle.read())
        table = document.get(section)
        if not isinstance(table, dict):
            table = tomlkit.table()
            document[section] = table
        table[key] = value
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(tomlkit.dumps(document))

    @staticmethod
    def _coerce(kind: str, value: str) -> Any:
        text = (value or "").strip()
        if kind == "bool":
            return text.casefold() in {"1", "true", "yes", "on", "是", "开", "启用"}
        if kind == "int":
            number = int(float(text or "0"))
            if number < 0 or number > 10000:
                raise ValueError("数值需要在 0~10000 之间")
            return number
        if kind == "float":
            number = float(text or "0")
            if number < 0 or number > 10000:
                raise ValueError("数值需要在 0~10000 之间")
            return number
        if kind == "str":
            # 提示词类配置保留原文（含换行），不要 strip 掉排版
            return str(value or "")
        if kind == "list":
            parts = re.split(r"[,，;；\n]+", text)
            items: List[str] = []
            for part in parts:
                item = part.strip()
                if item and item not in items:
                    items.append(item)
            return items
        raise ValueError("未知的配置类型：%s" % kind)

    # ---------------- 会话上下文 ----------------

    def _runtime(self, kwargs: Mapping[str, Any]) -> Tuple[Mapping[str, Any], str, str]:
        message = _mapping(kwargs.get("message"))
        info = _mapping(message.get("message_info"))
        user_info = _mapping(info.get("user_info"))
        stream_id = _first_text(
            kwargs.get("stream_id"),
            kwargs.get("chat_id"),
            kwargs.get("session_id"),
            message.get("stream_id"),
            message.get("session_id"),
        )
        user_id = _first_text(user_info.get("user_id"), message.get("user_id"), kwargs.get("user_id"))
        return message, stream_id, user_id

    # ---------------- 取参考图 ----------------

    async def _images_by_id(self, stream_id: str, message_id: str) -> List[bytes]:
        """按消息 ID 取图，一条消息里有几张就返回几张。

        2026-11-11：原来只认「恰好一张」，引用一条多图消息会静默取不到、
        再退到 recent 兜底拿到别人或她自己刚发的图。引用是用户明确指定的，
        多图全收才和「本条消息附图」那条路一致；总量由 max_references 收口。
        """

        try:
            payload = await self.ctx.message.get_by_id(
                message_id, stream_id=stream_id, include_binary_data=True
            )
        except Exception as exc:
            # 取不到就算了，下面还有查库 + 按 hash 读图这条路，不能在这儿提前 return。
            self.ctx.logger.warning("按 ID 取图失败: %s", exc)
            payload = None
        message = _unwrap_message(payload)
        if not isinstance(message, Mapping):
            self.ctx.logger.warning(
                "按 ID 取图拿到的不是消息字典: %s", type(payload).__name__
            )
            message = {}
        images = extract_message_images(message)
        if images:
            return images
        # get_by_id 没带回二进制（图片段只有描述 + hash）⇒ 直接查库拿段，再按 hash 读原图。
        segments = _segments_from_db(message_id)
        if segments:
            images = extract_message_images({"raw_message": segments})
        if not images:
            self.ctx.logger.info(
                "按 ID 取图未命中: id=%s 段数=%d（库里有段但本地无图，或该消息不是图片）",
                message_id,
                len(segments),
            )
        return images

    @staticmethod
    def _row_user_id(message: Any) -> str:
        """取这条消息的发送者 QQ（埋在 message_info.user_info.user_id）。"""

        if not isinstance(message, Mapping):
            return ""
        info = message.get("message_info")
        if isinstance(info, Mapping):
            user = info.get("user_info")
            if isinstance(user, Mapping):
                return str(user.get("user_id") or "")
        return ""

    @classmethod
    def _row_is_self(cls, message: Any) -> bool:
        """这条消息是不是她自己发的。

        🔴 消息字典没有顶层 user_id，发送者在 message_info.user_info.user_id；
        与顶层 account_id（本实例 Bot 账号）相等即为自己发的。
        判据与 example.self-check 同源，那边已经真机验过。
        """

        user_id = cls._row_user_id(message)
        account = str(message.get("account_id") or "") if isinstance(message, Mapping) else ""
        return bool(user_id and account and user_id == account)

    async def _recent_image(
        self, stream_id: str, prefer_user: str = ""
    ) -> Optional[bytes]:
        """兜底参考图：最近一条带单图的消息。

        🔴 必须跳过她自己发的：她刚发出去的成品图也在会话里，重画一次就会被当成
        参考图，上一版画歪的地方反复继承（2026-11-11 10:32 合照越改越偏）。
        🔴 群聊里先找「本次请求同一个人发的图」：群里别人随手发的图更近，
        不加这层会拿别人的图当参考。
        """

        if not stream_id:
            return None
        try:
            payload = await self.ctx.call_capability(
                "message.get_recent", chat_id=stream_id, limit=20, include_binary_data=True
            )
        except Exception as exc:
            self.ctx.logger.warning("取最近消息失败: %s", exc)
            return None
        messages: List[Any] = []
        if isinstance(payload, list):
            messages = payload
        elif isinstance(payload, Mapping) and isinstance(payload.get("messages"), list):
            messages = list(payload["messages"])
        candidates = [m for m in reversed(messages) if not self._row_is_self(m)]
        skipped_self = len(messages) - len(candidates)

        def _first_image(pool: List[Any]) -> Optional[bytes]:
            for message in pool:
                images = extract_message_images(message)
                if len(images) == 1:
                    return images[0]
            return None

        picked: Optional[bytes] = None
        if prefer_user:
            same_sender = [m for m in candidates if self._row_user_id(m) == prefer_user]
            if same_sender:
                picked = _first_image(same_sender)
                if picked:
                    self.ctx.logger.info(
                        "参考图兜底取到发起人自己的图（跳过她自己 %d 条；候选 %d 条）",
                        skipped_self,
                        len(same_sender),
                    )
        if not picked:
            picked = _first_image(candidates)
            if picked:
                # 日志要分清「发起人确实没图」和「压根没拿到发起人 ID」，
                # 否则排查时会误判成「同一个人发过图却取不到」。
                if prefer_user:
                    self.ctx.logger.info(
                        "参考图兜底取到会话里的图（同发送者没有可用图；跳过她自己 %d 条）",
                        skipped_self,
                    )
                else:
                    self.ctx.logger.info(
                        "参考图兜底取到会话里的图（未拿到发起人 ID；跳过她自己 %d 条）",
                        skipped_self,
                    )
        if not picked and skipped_self:
            self.ctx.logger.info(
                "参考图兜底未命中：最近带图消息全是她自己发的（%d 条）", skipped_self
            )
        return picked

    # ---------------- 在上一版成品上继续改 ----------------

    _EDIT_PATTERNS = (
        re.compile(r"改(成|为|一下|掉|了)|换成|换掉|再改"),
        re.compile(r"上一张|上一版|刚才那张|刚那张|这张图|前一版"),
        re.compile(r"去掉|删掉|补上|加上|别(再)?画|不要(再)?[^，。]{0,8}(了|，)"),
    )
    # 「更…些 / 再…一点」这类弱信号单独判：整段画面描述也常带「更柔和一点」，
    # 那种是新图，不是改图。凡是自己带完整场景的（画一个/站在/穿着…）都不算。
    _EDIT_WEAK = re.compile(r"(更|再)[^，。]{0,10}(些|一点|点儿|点)")
    _FRESH_SCENE = re.compile(r"画(一个|一张|个|张)|插画|场景|背景是|站在|坐在|穿着|里头|走来")

    @classmethod
    def _looks_like_edit(cls, request: str) -> bool:
        """判断这句是不是「在她上一张成品上继续改」。

        真实场景（2026-11-11 16:52~16:56 连改三版）：她画完一张，对方接着说
        「改成两人并肩同向走」「表情更生动些」。这类话本身没有完整画面，只有
        改动点；当成新图从零重画等于重新猜，人、衣服、场景全变，越改越不像。

        只在句子短时成立；整段画面描述即便带「更」字也不算（见 _FRESH_SCENE）。
        另外调用侧还有一道闸：聊天里必须真有她自己刚发的一张图，才会走改图。
        """

        text = (request or "").strip()
        if not text:
            return False
        # 「改成…」开头是明确指令，后面跟的整段描述是改法本身，不是另一张画的设定。
        # 2026-11-11 18:08 那句 100+ 字就这么漏判，被当新图重画。
        head = re.sub(r"^(再|帮我|请|那|你)", "", text[:12])
        strong_head = bool(re.match(r"(改成|换成|改一下|再改|修改|调整|把)", head))
        if len(text) > (150 if strong_head else 80):
            return False
        if any(pattern.search(text) for pattern in cls._EDIT_PATTERNS):
            return True
        return bool(cls._EDIT_WEAK.search(text)) and not cls._FRESH_SCENE.search(text)

    async def _last_own_image(self, stream_id: str) -> Optional[bytes]:
        """她最近发出去的那张图，用作「在上一版上改」的底图。

        🔴 与 `_recent_image` 刻意相反：那边跳过她自己的图（防止把歪掉的成品
        反复当参考继承），这一路**只认**她的图——对方要改的就是那一张。
        """

        if not stream_id:
            return None
        try:
            payload = await self.ctx.call_capability(
                "message.get_recent", chat_id=stream_id, limit=20, include_binary_data=True
            )
        except Exception as exc:
            self.ctx.logger.warning("取上一版成品失败: %s", exc)
            return None
        messages: List[Any] = []
        if isinstance(payload, list):
            messages = payload
        elif isinstance(payload, Mapping) and isinstance(payload.get("messages"), list):
            messages = list(payload["messages"])
        for message in reversed(messages):
            if not self._row_is_self(message):
                continue
            images = extract_message_images(message)
            if len(images) == 1:
                return images[0]
        return None

    async def _hydrate_message(
        self, message: Mapping[str, Any], stream_id: str
    ) -> Mapping[str, Any]:
        """补齐触发消息的原始内容。

        🔴 2026-11-11 16:37 实测：工具调用拿到的 message 可能是精简版——
        没有 message_info，raw_message 里的图片段也没有 base64。结果引用取不到、
        本条附图也取不到，只能退到 recent 兜底（那次明明引用了设定图，日志却记成
        recent，还因为搜不到同伴参考整单拒画）。带 message_id 就回查一次主程序
        里的完整消息，代价是一次本地读取，只在字段缺的时候发生。
        """

        if not isinstance(message, Mapping):
            return message
        message_id = str(message.get("message_id") or "").strip()
        if not message_id or not stream_id:
            return message
        info = message.get("message_info")
        segments = (
            message.get("raw_message")
            or message.get("segments")
            or message.get("message_segments")
        )
        # 字段齐不代表能用：精简版的图片段里只有 VLM 描述和 hash、没有 base64，
        # 这种「看起来完整」的消息同样要回查（2026-11-11 18:10 引用图取不到的隐患）。
        missing_binary = False
        if isinstance(segments, list):
            for segment in segments:
                if not isinstance(segment, Mapping):
                    continue
                if str(segment.get("type") or "").casefold() not in {
                    "image", "picture", "photo"
                }:
                    continue
                if not any(
                    segment.get(k)
                    for k in ("binary_data_base64", "base64", "data_base64")
                ):
                    missing_binary = True
                    break
        if (
            isinstance(info, Mapping)
            and info
            and isinstance(segments, list)
            and segments
            and not missing_binary
        ):
            return message
        try:
            payload = await self.ctx.message.get_by_id(
                message_id, stream_id=stream_id, include_binary_data=True
            )
        except Exception as exc:
            self.ctx.logger.warning("回查触发消息失败: %s", exc)
            return message
        full = _unwrap_message(payload)
        if not isinstance(full, Mapping):
            return message
        merged = dict(message)
        for key, value in full.items():
            if key not in merged or merged.get(key) in (None, "", [], {}):
                merged[key] = value
        self.ctx.logger.info(
            "触发消息已回查补齐: message_info=%s segments=%d",
            bool(merged.get("message_info")),
            len(merged.get("raw_message") or []),
        )
        return merged

    async def _chat_image(
        self, message: Mapping[str, Any], stream_id: str
    ) -> Tuple[List[bytes], str]:
        """取聊天里的参考图，返回（图片列表, 来源）。

        🔴 顺序（设计约定）：引用 > 本条附图 > 最近兜底。
        引用是对方明确点出来「照这张」的，优先级高于随手附带的图；
        引用消息里有多张就全收下，同一角色/同一套衣服的多个角度一起喂，
        比只取一张更能把侧面和细节画对。上限交给 ``max_references`` 统一收口。
        """

        message = await self._hydrate_message(message, stream_id)

        replied = reply_message_id(message)
        if replied:
            images = await self._images_by_id(stream_id, replied)
            if images:
                return images, "reply"

        images = extract_message_images(message)
        if images:
            return images, "chat"

        if self._cfg().reference.chat_recent_fallback:
            image = await self._recent_image(
                stream_id, prefer_user=self._row_user_id(message)
            )
            if image:
                return [image], "recent"
        return [], ""

    # ---------------- 人物形象参考图（agent 自持） ----------------

    def _person_path(self) -> str:
        return os.path.join(self._data_dir(), "person_ref.img")

    def _gallery_dir(self) -> str:
        return os.path.join(self._data_dir(), "person_gallery")

    def _gallery_index_path(self) -> str:
        return os.path.join(self._gallery_dir(), "index.json")

    def _load_gallery(self) -> dict:
        """读图库索引；指向的文件已丢失的资产自动剔除。"""

        assets: List[dict] = []
        try:
            with open(self._gallery_index_path(), encoding="utf-8") as handle:
                raw = json.load(handle)
            items = raw.get("assets") if isinstance(raw, Mapping) else None
            if isinstance(items, list):
                assets = [a for a in items if isinstance(a, Mapping)]
        except (OSError, ValueError):
            assets = []
        cleaned: List[dict] = []
        for item in assets:
            filename = str(item.get("file") or "")
            if not filename:
                continue
            fpath = os.path.join(self._gallery_dir(), filename)
            if not (os.path.isfile(fpath) and os.path.getsize(fpath) > 0):
                continue
            cleaned.append(
                {
                    "id": str(item.get("id") or ""),
                    "name": str(item.get("name") or "人物参考图")[:60],
                    "tags": [
                        str(tag).strip()[:30]
                        for tag in (item.get("tags") or [])
                        if str(tag).strip()
                    ][:12],
                    "file": filename,
                    "primary": bool(item.get("primary")),
                    "added_at": str(item.get("added_at") or ""),
                    "updated_at": str(item.get("updated_at") or ""),
                }
            )
        return {"version": 1, "assets": cleaned}

    def _save_gallery(self, index: Mapping[str, Any]) -> None:
        os.makedirs(self._gallery_dir(), exist_ok=True)
        tmp = self._gallery_index_path() + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(index, handle, ensure_ascii=False, indent=1)
        os.replace(tmp, self._gallery_index_path())

    def _gallery_add(
        self, data: bytes, name: str, tags: List[str], *, make_primary: bool = False
    ) -> dict:
        """往图库加一张图，返回资产条目。第一张自动成为主形象。"""

        index = self._load_gallery()
        assets = index["assets"]
        try:
            limit = max(int(self._cfg().wardrobe.max_assets or 10), 1)
        except Exception:
            limit = 10
        if len(assets) >= limit:
            raise ArtAgentError(f"图库最多放 {limit} 张，先删掉几张再传")
        asset_id = "p" + time.strftime("%Y%m%d%H%M%S") + format(int(time.time() * 1000) % 1000, "03d")
        filename = asset_id + ".img"
        os.makedirs(self._gallery_dir(), exist_ok=True)
        with open(os.path.join(self._gallery_dir(), filename), "wb") as handle:
            handle.write(data)
        thumb = _make_thumbnail(data)
        if thumb:
            with open(os.path.join(self._gallery_dir(), asset_id + ".thumb.jpg"), "wb") as handle:
                handle.write(thumb)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        asset = {
            "id": asset_id,
            "name": (name or "").strip()[:60] or "人物参考图",
            "tags": [t.strip()[:30] for t in tags if t.strip()][:12],
            "file": filename,
            "primary": bool(make_primary) or not any(a.get("primary") for a in assets),
            "added_at": now,
            "updated_at": now,
        }
        if asset["primary"]:
            for a in assets:
                a["primary"] = False
        assets.append(asset)
        self._save_gallery(index)
        return asset

    def _person_image(self) -> Optional[bytes]:
        """主形象的图片字节（向后兼容入口）。"""

        for asset in self._load_gallery()["assets"]:
            if asset["primary"]:
                fpath = os.path.join(self._gallery_dir(), asset["file"])
                try:
                    with open(fpath, "rb") as handle:
                        return handle.read()
                except OSError:
                    return None
        return None

    def _person_images(self, *, with_bytes: bool = True) -> List[dict]:
        """图库全部资产，主形象排最前，其余按更新时间倒序。

        with_bytes=False 只回元数据（选造型用），不把几十张原图读进内存；
        选完再由调用方对选中的几张补 bytes。
        """

        assets = [dict(a) for a in self._load_gallery()["assets"]]
        assets.sort(
            key=lambda a: (
                not a.get("primary"),
                -_ts_of(a.get("updated_at") or a.get("added_at") or ""),
            )
        )
        out: List[dict] = []
        for asset in assets:
            fpath = os.path.join(self._gallery_dir(), asset["file"])
            if not with_bytes:
                if not os.path.exists(fpath):
                    continue
                out.append(asset)
                continue
            try:
                with open(fpath, "rb") as handle:
                    asset["bytes"] = handle.read()
            except OSError:
                continue
            out.append(asset)
        return out

    def _attach_bytes(self, assets: List[dict]) -> List[dict]:
        """给选中的资产补上图片字节；读不到的整张丢掉，不留半残条目。"""

        out: List[dict] = []
        for asset in assets:
            fpath = os.path.join(self._gallery_dir(), asset["file"])
            try:
                with open(fpath, "rb") as handle:
                    asset["bytes"] = handle.read()
            except OSError:
                continue
            out.append(asset)
        return out

    # ---------------- 造型库（多套衣服 / 换装） ----------------

    @staticmethod
    def _tag_map(tags: Sequence[str]) -> dict:
        """把 ["season:winter", "role:base"] 解析成 {"season": "winter", "role": "base"}。

        同名键只取第一个，避免标签写重了互相覆盖。
        """

        out: dict = {}
        for raw in tags or []:
            text = str(raw).strip()
            if ":" not in text:
                continue
            key, _, value = text.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key and value and key not in out:
                out[key] = value
        return out

    def _current_season(self) -> str:
        """按月份判断当前季节；造型库关掉时返回空串（表示不按季节挑）。"""

        cfg = self._cfg().wardrobe
        if not cfg.enabled:
            return ""
        month = time.localtime().tm_mon
        if month in (cfg.winter_months or []):
            return "winter"
        if month in (cfg.summer_months or []):
            return "summer"
        return "spring_autumn"

    def _pick_person_assets(self, request: str) -> List[dict]:
        """挑一套造型的参考图：点名 > 当季（有场景词再按 scene 细分）> primary 兜底。

        图库里可以同时躺多套衣服，但一次只喂一套——否则模型会把两套衣服揉在一起。
        一套造型用 outfit:<id> 标签归组；没写 outfit 的图各自成组（兼容旧资产）。
        """

        assets = self._person_images(with_bytes=False)
        if not assets:
            return []

        groups: dict = {}
        for asset in assets:
            meta = self._tag_map(asset.get("tags") or [])
            key = meta.get("outfit") or f"__single__{asset.get('id') or id(asset)}"
            groups.setdefault(key, []).append(asset)

        rank = {"base": 0, "full": 1, "detail": 2, "mood": 3}

        def ordered(group: List[dict]) -> List[dict]:
            return sorted(
                group,
                key=lambda a: rank.get(self._tag_map(a.get("tags") or []).get("role", ""), 9),
            )

        def finish(group: List[dict]) -> List[dict]:
            """选完造型再读图：图库再大也只为选中的 2~4 张花内存。"""
            return self._attach_bytes(ordered(group))

        # 1) 请求里点名：命中造型名或 theme（如「穿那套星空裙」）
        text = (request or "").lower()
        for group in groups.values():
            meta = self._tag_map(group[0].get("tags") or [])
            # 名字常写成「冬装·三视图」，用户只会说「冬装」，所以按分隔符再拆一遍；
            # 组内每张图的名字都参与匹配（同一套造型的几张图名字可能不同）。
            probes: List[str] = []
            for asset in group:
                name = str(asset.get("name") or "")
                probes.append(name)
                probes.extend(re.split(r"[·/、\s]+", name))
                # alias:开衫,百褶裙 —— 用户不会说「春秋装」，只会说衣服本身的名字。
                # WebUI 保存会把逗号串拆成多个独立标签（只有第一项带 alias: 前缀），
                # 所以 alias 值按一切分隔符拆开，裸标签项也直接当别名探针。
                for raw in asset.get("tags") or []:
                    tag = str(raw).strip()
                    key, _, value = tag.partition(":")
                    if key.lower() == "alias" and value:
                        probes.extend(re.split(r"[,，、\s]+", value))
                    elif ":" not in tag and len(tag) >= 2:
                        probes.append(tag)
            if meta.get("theme"):
                probes.append(meta["theme"])
            for probe in probes:
                probe = probe.strip().lower()
                if len(probe) >= 2 and probe in text:
                    return finish(group)

        # 2) 当季的日常款（special 造型不参与自动换季）
        #    同一季有多套日常款时，按请求里的场景词挑 scene：
        #    「宿舍里玩手机」→ scene:home，没有场景词就用图库里靠前的那套。
        season = self._current_season()
        if season:
            candidates: List[dict] = []
            for group in groups.values():
                meta = self._tag_map(group[0].get("tags") or [])
                if meta.get("season") != season:
                    continue
                if str(meta.get("style") or "daily").lower() == "special":
                    continue
                candidates.append((group, meta))

            if candidates:
                picked = candidates[0][0]
                if len(candidates) > 1:
                    for scene, words in (
                        self._cfg().wardrobe.scene_keywords or {}
                    ).items():
                        if any(w.strip() and w.strip() in text for w in words.split(",")):
                            match = next(
                                (g for g, m in candidates if m.get("scene") == scene),
                                None,
                            )
                            if match is not None:
                                picked = match
                                break
                return finish(picked)

        # 3) primary 兜底（再不行就取前两页，保持旧行为）
        for group in groups.values():
            if any(a.get("primary") for a in group):
                return finish(group)
        return finish(assets[:2])

    async def _ensure_person_migrated(self) -> None:
        """图库为空时迁移：先看旧版单图文件，再看写真插件图库；之后完全自治。"""

        if self._load_gallery()["assets"]:
            return
        data: Optional[bytes] = None
        source = ""
        legacy_path = self._person_path()
        if os.path.isfile(legacy_path) and os.path.getsize(legacy_path) > 0:
            try:
                with open(legacy_path, "rb") as handle:
                    data = handle.read()
                source = "旧版单图"
            except OSError:
                data = None
        if data is None:
            try:
                response = await self.ctx.api.call(
                    f"{MAITU_PLUGIN}.person_ref", version="1", operation="raw"
                )
            except Exception as exc:
                self.ctx.logger.info("人物形象参考图迁移跳过（写真插件未响应）: %s", exc)
                return
            if not isinstance(response, Mapping) or not response.get("success"):
                return
            raw = str(response.get("image_base64") or "").strip()
            if not raw:
                return
            try:
                data = base64.b64decode(raw, validate=True)
                source = "写真插件"
            except Exception:
                return
        if not data or not _looks_like_image(data):
            return
        try:
            asset = self._gallery_add(data, "人物形象", [])
        except ArtAgentError as exc:
            self.ctx.logger.warning("人物形象图迁移入图库失败: %s", exc)
            return
        self.ctx.logger.info(
            "人物形象参考图已迁移到图库（来源=%s）: id=%s bytes=%d",
            source,
            asset["id"],
            len(data),
        )

    async def _download_image(self, url: str) -> bytes:
        cfg = self._cfg().reference
        try:
            parsed = urlsplit(url)
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as exc:
            raise ArtAgentError("参考图链接格式不正确") from exc
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ArtAgentError("只支持 http/https 图片链接")
        if parsed.username or parsed.password:
            raise ArtAgentError("参考图链接里不能带账号密码")

        allowed = [str(host).strip().lower() for host in (cfg.allowed_hosts or []) if str(host).strip()]
        hostname = parsed.hostname.rstrip(".").casefold()
        if allowed and not any(hostname == host or hostname.endswith("." + host) for host in allowed):
            raise ArtAgentError(f"参考图域名不在白名单里：{hostname}")

        try:
            infos = await asyncio.to_thread(
                socket.getaddrinfo, hostname, port, type=socket.SOCK_STREAM
            )
        except OSError as exc:
            raise ArtAgentError("参考图链接解析不到地址") from exc
        addresses = {str(item[4][0]).split("%", 1)[0] for item in infos or [] if item and item[4]}
        if not addresses:
            raise ArtAgentError("参考图链接解析不到地址")
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address)
            except ValueError:
                raise ArtAgentError("参考图链接解析到了非法地址") from None
            if not ip.is_global or ip.is_multicast:
                raise ArtAgentError("参考图链接指向非公网地址，已拒绝")

        timeout = float(cfg.download_timeout_seconds or 20)
        limit = int(cfg.download_max_bytes or 8 * 1024 * 1024)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, max_redirects=3) as client:
                response = await client.get(url, headers={"Accept": "image/*"})
        except httpx.HTTPError as exc:
            raise ArtAgentError("参考图下载失败，链接可能已失效") from exc
        if response.status_code >= 400:
            raise ArtAgentError(f"参考图下载失败（HTTP {response.status_code}）")
        data = response.content or b""
        if not data:
            raise ArtAgentError("参考图是空的")
        if len(data) > limit:
            raise ArtAgentError("参考图太大，超过体积上限")
        if not _looks_like_image(data):
            raise ArtAgentError("这个链接不是图片")
        self.ctx.logger.info("参考图下载成功: bytes=%d type=%s", len(data), _media_type(data))
        return data

    # ---------------- 判定 ----------------

    def _decide_lane(self, mode: str, request: str, has_reference: bool) -> str:
        mode = (mode or "").strip().casefold()
        if mode in {"self", "illustration", "reference"}:
            return mode
        text = (request or "").casefold()
        # auto + 会话图 + 命中「画你」关键词 → self 组合（人物形象图 + 会话图一起喂），
        # 覆盖「照这张画你自己」这类没显式传 mode 的说法；不命中才走纯图生图。
        if has_reference:
            for keyword in self._cfg().self_channel.keywords or []:
                token = str(keyword or "").strip().casefold()
                if token and token in text:
                    return "self"
            return "reference"
        for keyword in self._cfg().self_channel.keywords or []:
            token = str(keyword or "").strip().casefold()
            if token and token in text:
                return "self"
        # 「我仍穿…」「我和她…」这类不在关键词表里的说法：LLM 判路失败或降级复核时
        # 全靠这一条，否则会掉进插画画成跟她无关的一张（2026-11-11 18:08）。
        if _SELF_PRESENCE.search(text):
            return "self"
        return "illustration"

    def _prefer_self_with_reference(
        self,
        lane: str,
        request: str,
        has_images: bool,
        reference_from: str,
        self_subjects: List[dict],
    ) -> Tuple[str, bool, bool]:
        """图生图里她自己也在画面时，改走 self 管线。

        返回 (lane, 是否从 reference 改过来的, 输入图是否可信)。

        「可信」= 这张图是对方这次明确要参考的那张。reply / chat / url 天然可信；
        recent 是自动从会话里翻出来的，只有在这种「本来就走图生图」的场景才可信
        ——那张图正是对方指定要照着画的，不是随手抓的旧图。
        """

        input_trusted = reference_from in {"reply", "chat", "url"}
        if not (
            lane == "reference"
            and has_images
            and (bool(self_subjects) or self._involves_self(request))
        ):
            return lane, False, input_trusted
        return "self", True, (input_trusted or reference_from == "recent")

    def _involves_self(self, request: str) -> bool:
        """这句请求的画面里有没有她本人（不依赖 planner 给的 mode）。

        「照着这张图画你和她」听起来是图生图，其实画面里是她 + 图里那位。reference
        通道只把那张图喂给模型、不给她的人物基准，画出来图里那位是对的、她自己
        是个凭空捏的路人（线上实测：图中角色画对了，主角色被画成了无关路人）。这个判断决定要不要把她的人物形象图一起喂进去。

        只认「画你/你穿/我穿/你和她…」这类明确把她画进画面的说法，
        以及「我(们)…穿/和/跟/与」——「给我画只小猫」不算。
        """

        text = (request or "").casefold()
        for keyword in self._cfg().self_channel.keywords or []:
            token = str(keyword or "").strip().casefold()
            if token and token in text:
                return True
        return bool(_SELF_PRESENCE.search(text))

    async def _decide_lane_llm(
        self, request: str, has_reference: bool
    ) -> Tuple[str, str, dict]:
        """内部 LLM 判通道。成功返回 (lane, reason, extras)；失败返回 ("", 原因, {})。

        走宿主 ctx.llm.generate（utils 任务），计入 llm_usage 账本；超时不重试。
        extras 里的两个搜索词供「联网搜参考图」使用，为空表示不搜。
        """
        intent = self._cfg().intent
        if not intent.use_llm:
            return "", "llm 判别已关闭", {}
        system = (intent.prompt or "").strip()
        if not system:
            return "", "判别提示词为空", {}
        user = (
            f"用户请求：{(request or '').strip()[:300] or '（空）'}\n"
            f"是否附带图片：{'有（来自本条消息、引用消息或链接）' if has_reference else '无'}"
        )
        call_kwargs: dict = {
            "prompt": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": 520,
        }
        try:
            if "task_name" in inspect.signature(self.ctx.llm.generate).parameters:
                call_kwargs.update({"model": "", "task_name": intent.model_task})
            else:
                call_kwargs["model"] = intent.model_task
        except Exception:
            # ctx.llm 缺失/签名异常都按旧契约处理，判别环节绝不能把 draw 炸穿
            call_kwargs["model"] = intent.model_task
        try:
            result = await asyncio.wait_for(
                self.ctx.llm.generate(**call_kwargs),
                timeout=float(intent.timeout_seconds or 12),
            )
        except asyncio.TimeoutError:
            self.ctx.logger.info("意图判别超时（%ss），回退关键词规则", intent.timeout_seconds)
            return "", "llm 判别超时", {}
        except Exception as exc:
            self.ctx.logger.warning("意图判别 LLM 调用失败，回退关键词规则: %s", exc)
            return "", f"llm 调用失败({type(exc).__name__})", {}
        if not isinstance(result, Mapping) or not result.get("success"):
            err = str(result.get("error") or "")[:80] if isinstance(result, Mapping) else "invalid_result"
            return "", f"llm 返回失败: {err}", {}
        raw = str(result.get("response") or "").strip()
        lane, reason, extras = _parse_intent_json(raw)
        if not lane:
            self.ctx.logger.info("意图判别输出无法解析: %s", raw[:80])
            return "", "llm 输出无法解析", {}
        return lane, reason or "llm 判别", extras

    async def _decide_lane_smart(
        self, mode: str, request: str, has_reference: bool
    ) -> Tuple[str, str, str, dict]:
        """综合判路，返回 (lane, reason, via, extras)。

        planner 显式指定通道时不靠 LLM 定 lane；但若开着联网搜图、又没有随请求
        带图，仍跑一次 LLM 只为取搜索关键词（换装需要「搜什么」这件事）。
        """
        m = (mode or "").strip().casefold()
        cfg = self._cfg()
        if m in {"self", "illustration", "reference", "cast"}:
            extras: dict = {}
            # 判路不只用来取搜索词，还负责给 subjects（画面里有哪几个人）。
            # 2026-11-09 20:13 的 cast 失败就是这里漏的：recent 自动抓到一张旧聊天图
            # → has_reference=True → 整个判路被跳过 → subjects 为空 → cast 把整段
            # 提示词当成人名去报「没找到参考图」。所以「已经带图」不能作为跳过理由：
            # cast 一律要名单；self 带图时只有像多人合照才补跑，单人自拍不多花这三分钱。
            want_subjects = cfg.search.enabled and (
                not has_reference
                or m == "cast"
                or (m == "self" and _looks_multi(request))
                # reference 带图时也判一次，而且不先用关键词猜「有没有她」：
                # 猜漏的说法（「把我也画上」「画咱俩」）会让 subjects 空 →
                # 不改走 self → 她又被画成路人的第二张脸。
                # 一次 utils 按模型计价、上限 12s，换掉画错人的 按引擎计价。
                or m == "reference"
            )
            if want_subjects:
                _, _, extras = await self._decide_lane_llm(request, has_reference)
            return m, "planner 显式指定了通道", "explicit", extras
        lane, reason, extras = await self._decide_lane_llm(request, has_reference)
        if lane:
            return lane, reason, "llm", extras
        lane_rule = self._decide_lane(mode, request, has_reference)
        if lane_rule == "self":
            rule_reason = "命中画她自己判定词"
        elif lane_rule == "reference":
            rule_reason = "带参考图且未命中判定词 → 图生图"
        else:
            rule_reason = "无参考图、未命中判定词 → 插画"
        full = f"关键词兜底（{reason}）：{rule_reason}" if reason else f"关键词兜底：{rule_reason}"
        return lane_rule, full, "keyword", {}

    # ---------------- 分发 ----------------

    def _compose_self_prompt(
        self,
        request: str,
        *,
        has_combo: bool,
        person_assets: Optional[List[dict]] = None,
        outfit: bool = False,
        outfit_count: int = 1,
        companions: Optional[List[str]] = None,
        companion_counts: Optional[List[int]] = None,
        relation: str = "",
        missing: Optional[List[str]] = None,
        has_scene: bool = False,
        only_people: Optional[List[str]] = None,
        edit_base: bool = False,
    ) -> str:
        """self 通道最终 prompt：request + 身份特征 + 画风约束 + 参考图说明 + 负面词。

        预设全部在 config.toml [self_prompts]，可直接编辑。
        person_assets 带标签时，告诉模型每张参考图展示的是什么（正脸/全身/服装…）。
        outfit=True 表示「换装」：最后一张是服装参考，用 outfit_hint 替代 ref_combo_hint，
        否则 identity 里「服装以基准图为准、不要把两张混着画」会把换装直接掐死。
        companions 非空表示多人合照：按「第 1 张她自己 + 后面依次是同伴」逐张点名，
        用 group_hint 替代上面所有单人提示词。
        """

        sp = self._cfg().self_prompts
        parts = [request.strip()]
        numbered_ref = False
        if sp.identity:
            parts.append(sp.identity)
        if sp.style:
            parts.append(sp.style)
        # 开放式引导（v1.1.6）：只说明「只交代在哪、穿什么会得到空脸」，具体神态、动作、
        # 互动怎么落地交给模型按情境判断——写死「不要面无表情 / 手要有事做」这类清单，
        # 等于用我的判断顶替它的判断，容易把所有图压成同一种笑法。
        if getattr(sp, "scene_hint", ""):
            parts.append(sp.scene_hint)
        if companions or missing:
            # 多人合照：参考图顺序 = 她自己 + 每个同伴（同一人的多张连续）+ 可选会话参考图，
            # 必须逐张点名，否则模型会把两张脸揉成一个人（单人版提示词全是为了防这个写的）。
            # 同伴一张参考都没搜到时也要走这里：得明确告诉模型「她没参考图」，不能静默丢人。
            counts = list(companion_counts or [])
            if len(counts) != len(companions or []):
                counts = [1] * len(companions or [])
            spans: List[str] = ["第1张是你自己的形象参考"]
            cursor = 2
            for name, count in zip(companions or [], counts):
                count = max(1, int(count or 1))
                if count == 1:
                    spans.append(f"第{cursor}张是「{name}」")
                else:
                    spans.append(
                        f"第{cursor}~{cursor + count - 1}张都是「{name}」"
                        f"（同一位的 {count} 张不同角度/全身与细节）"
                    )
                cursor += count
            if has_scene:
                scene_from = cursor
                if edit_base:
                    spans.append("最后一张是上一版成品（以它为底图改）")
                else:
                    spans.append(f"第{cursor}张起是对方给的参考图（怎么用看后面的说明）")
            parts.append("人物参考图说明：" + "；".join(spans) + "。")
            numbered_ref = True
            if edit_base:
                # 改图 + 合照：最后一张是上一版成品，不是场景图也不是人物设定稿。
                parts.append(getattr(sp, "edit_hint", "") or sp.ref_combo_hint)
            elif has_scene:
                # 🔴 不预设这张图是「场景图」：对方给的多半就是他想要的那个东西，
                # 硬按场景处理会把人物设定稿当废图（2026-11-11 10:31 合照失真）。
                # 也不反过来一律当人物：只想要背景/光线时同样会画错。
                # 判据交给「图的内容 + 用户这句话的语境」，两档都写清楚。
                parts.append(
                    f"第{scene_from}张起是对方给的参考图，先看清它是什么再决定怎么用："
                    "① 若它展示的是某个角色的形象（同一个人物的正面/侧面/背面、全身立绘、设定稿），"
                    "就把图里人物的长相、发型、发色、瞳色、五官和服装当作该角色的形象参考，"
                    "这张图要算作那个角色名下的参考图，"
                    "和前面按这个角色名搜来的参考图冲突时一律以这张为准，不要沿用搜来的泛化形象；"
                    "② 若它主要展示场景（房间、街道、风景、光线、色调），"
                    "就只取它的场景、光线、构图和姿势氛围，不要因为图里有人就往画面里多加角色。"
                    "按对方这句话的语境判断属于①还是②，不要自行假定成某一种。"
                )
            if sp.group_hint and companions:
                parts.append(sp.group_hint)
            if relation:
                parts.append(f"人物关系与站位：{relation}")
            if only_people:
                parts.append(
                    "本次画面里只出现这些人："
                    + "、".join(only_people)
                    + "；请求里多提的角色这次不画，不要凭空加人。"
                )
            if missing:
                parts.append(
                    "没有拿到「"
                    + "」「".join(missing)
                    + "」的参考图；画面里如果要她出现，按你的理解画，"
                    "但不要借用主角色的长相、发色和服装，也不要和别人混成同一张脸。"
                )
        elif has_combo:
            if edit_base:
                # 改上一版：服装、场景、光线都跟着上一版走，不能用 ref_combo_hint
                # 的「服装不要被它带偏」——那是给「拿场景图当参考」写的，会把改图打回基准装。
                hint = getattr(sp, "edit_hint", "") or sp.ref_combo_hint
            elif outfit:
                hint = sp.outfit_hint
            else:
                hint = sp.ref_combo_hint
            if hint:
                parts.append(hint)
        elif sp.ref_person_hint:
            parts.append(sp.ref_person_hint)
        if person_assets and not numbered_ref:
            # 合照分支已经按「第几张是谁」逐张点名了，这里不能再从第 1 张重新编号
            # （2026-11-11 19:11 合照同时拼了两套互相打架的编号）。
            role_label = {
                "base": "本次造型基准",
                "full": "同一造型全身",
                "detail": "同一造型细节",
                "mood": "氛围参考",
            }
            described: List[str] = []
            has_mood = False
            for i, asset in enumerate(person_assets):
                meta = self._tag_map(asset.get("tags") or [])
                role = str(meta.get("role") or "").lower()
                label = role_label.get(role)
                described.append(f"第{i + 1}张「{label}」" if label else f"第{i + 1}张")
                if role == "mood":
                    has_mood = True
            if outfit:
                start = len(person_assets) + 1
                count = max(1, int(outfit_count or 1))
                span = (
                    f"第{start}张"
                    if count == 1
                    else f"第{start}~{start + count - 1}张（同一套服装的 {count} 张）"
                )
                tail = f"；长相、发色、体型只认这些形象图，{span}是服装参考，只取衣服。"
            else:
                tail = "。长相与服装都以标着「本次造型基准」的那张为准。"
            parts.append("人物参考图说明：" + "；".join(described) + tail)
            if has_mood and sp.ref_mood_hint:
                parts.append(sp.ref_mood_hint)
        if sp.avoid:
            parts.append("画面避免出现：" + sp.avoid)
        return "\n".join(p for p in parts if p)

    def _compose_cast_prompt(
        self,
        request: str,
        *,
        names: List[str],
        counts: Optional[List[int]] = None,
        relation: str = "",
        missing: Optional[List[str]] = None,
        has_scene: bool = False,
        only_people: Optional[List[str]] = None,
    ) -> str:
        """cast 通道：画面里全是别人，不能套主角色的身份句和服饰负面词。"""

        sp = self._cfg().self_prompts
        parts = [request.strip()]
        if sp.style:
            parts.append(sp.style)
        # 同 self 通道：一句开放式引导，不按人数分支、也不列具体动作清单。
        if getattr(sp, "scene_hint", ""):
            parts.append(sp.scene_hint)
        spans: List[str] = []
        cursor = 1
        per = list(counts or [])
        if len(per) != len(names):
            per = [1] * len(names)
        for name, count in zip(names, per):
            count = max(1, int(count or 1))
            if count == 1:
                spans.append(f"第{cursor}张是「{name}」")
            else:
                spans.append(
                    f"第{cursor}~{cursor + count - 1}张都是「{name}」"
                    f"（同一位的 {count} 张不同角度/全身与细节）"
                )
            cursor += count
        if has_scene:
            scene_from = cursor
            spans.append(f"第{cursor}张起是对方给的参考图（怎么用看后面的说明）")
        if spans:
            parts.append("人物参考图说明：" + "；".join(spans) + "。")
        if has_scene:
            # 同 self 通道：不预设是场景图，按「图的内容 + 对方这句话」判断。
            parts.append(
                f"第{scene_from}张起是对方给的参考图，先看清它是什么再决定怎么用："
                "① 若它展示的是某个角色的形象（同一个人物的正面/侧面/背面、全身立绘、设定稿），"
                "就把图里人物的长相、发型、发色、瞳色、五官和服装当作该角色的形象参考，"
                "这张图要算作那个角色名下的参考图，"
                "和前面按这个角色名搜来的参考图冲突时一律以这张为准；"
                "② 若它主要展示场景（房间、街道、风景、光线、色调），"
                "就只取它的场景、光线、构图和姿势氛围，不要因为图里有人就多画角色。"
                "按对方这句话的语境判断属于①还是②，不要自行假定成某一种。"
            )
        if sp.cast_hint:
            parts.append(sp.cast_hint)
        if relation:
            parts.append(f"人物关系与站位：{relation}")
        if only_people:
            parts.append(
                "本次画面里只出现这些人："
                + "、".join(only_people)
                + "；请求里多提的角色这次不画，不要凭空加人。"
            )
        if missing:
            parts.append(
                "没有拿到「"
                + "」「".join(missing)
                + "」的参考图；如果画面里需要出现，按你的理解画，但不要和其他人混成同一张脸。"
            )
        if sp.cast_avoid:
            parts.append("画面避免出现：" + sp.cast_avoid)
        return "\n".join(p for p in parts if p)

    async def _search_reference(
        self,
        query: str,
        request: str,
        cfg: ArtAgentConfig,
        want: int = 1,
    ) -> dict:
        """搜参考图；任何异常都返回 ok=False，不打断绘图。

        ``want`` > 1 时返回同一角色的多张图（不同角度），用于把侧面/背面/细节喂全。
        """

        suffix = str(getattr(cfg.search, "fallback_suffix", "") or "").strip()
        extra = [word for word in suffix.split() if word and word not in query]
        fallback = f"{query} {' '.join(extra)}".strip() if extra else ""
        try:
            return await search_ref.resolve_reference(
                self.ctx,
                self.ctx.llm.generate,
                query=query,
                target=request,
                config=cfg.search,
                fallback_query=fallback,
                want=max(1, int(want or 1)),
            )
        except Exception as exc:  # noqa: BLE001
            self.ctx.logger.warning("绘图搜图异常: %s", exc)
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    async def _submit_self(self, request: str, stream_id: str, user_id: str, size: str) -> dict:
        response = await self.ctx.api.call(
            f"{MAITU_PLUGIN}.generate_photo",
            version="1",
            description=request,
            stream_id=stream_id,
            user_id=user_id,
            size=size,
        )
        if not isinstance(response, Mapping) or not response.get("success"):
            error = ""
            if isinstance(response, Mapping):
                error = str(response.get("error") or "")
            raise ArtAgentError(error or "写真插件拒绝了这次请求")
        result = _mapping(response.get("result"))
        return {
            "task_id": _first_text(result.get("task_id")),
            "status": _first_text(result.get("status"), "queued"),
        }

    async def _submit_drawing(
        self,
        task_type: str,
        prompt: str,
        stream_id: str,
        image: Optional[bytes],
        size: str,
    ) -> dict:
        client = DrawingClient(self.ctx.api, rpc_timeout=float(self._cfg().limits.submit_timeout_seconds or 20))
        kwargs: dict = {"task_type": task_type, "stream_id": stream_id}
        if image:
            kwargs["source_images"] = [image]
        handle = await client.submit(prompt, **kwargs)
        return {
            "task_id": _first_text(getattr(handle, "task_id", "")),
            "status": _first_text(getattr(handle, "status", ""), "queued"),
        }

    # ---------------- Ark 引擎（直连火山图生图引擎） ----------------

    def _ark_conf(self):
        return self._cfg().engines.ark

    def _ark_api_key(self) -> str:
        """优先用本插件填的 key；留空则读写真插件的，避免同一个 key 存两份。"""

        key = (self._ark_conf().api_key or "").strip()
        if key:
            return key
        cfg_path = os.path.join(
            os.path.dirname(self._plugin_dir), "maitu-photo-studio", "config.toml"
        )
        try:
            with open(cfg_path, "r", encoding="utf-8") as handle:
                matched = re.search(r'api_key\s*=\s*"([^"]+)"', handle.read())
            if matched and matched.group(1).strip():
                return matched.group(1).strip()
        except Exception as exc:
            self.ctx.logger.warning("读取写真插件的图生图引擎 key 失败: %s", exc)
        raise ArtAgentError("绘图引擎没有可用的 API Key，请在控制台填写")

    @staticmethod
    def _is_copyright_reject(text: str) -> bool:
        """只把版权/内容审核拦截当作「可以切兜底」的信号。

        超时、限流、鉴权失败都不重试——换模型也救不回来，只会多花一次钱。
        """

        lowered = (text or "").casefold()
        return any(
            token in lowered
            for token in ("sensitivecontent", "copyright", "policyviolation")
        )

    async def _ark_generate(
        self, prompt: str, images: Sequence[bytes], size: str
    ) -> Tuple[bytes, str, bool]:
        conf = self._ark_conf()
        key = self._ark_api_key()
        payload: dict = {
            "model": conf.model,
            "prompt": prompt,
            "size": (size or "").strip() or "1024x1024",
            "watermark": False,  # 明确关水印：图生图引擎默认不加，但别依赖默认值
            "response_format": "url",
            # 注意：不要加 sequential_image_generation——5.0 Flash 不认这个参数，直接 400；
            # 默认行为本来就是单张，组图风险靠 prompt 约束。
        }
        uris = [
            f"data:{_media_type(blob)};base64,{base64.b64encode(blob).decode('ascii')}"
            for blob in images
            if blob
        ]
        if uris:
            payload["image"] = uris[0] if len(uris) == 1 else uris
        endpoint = conf.base_url.rstrip("/") + "/images/generations"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        timeout = float(conf.request_timeout_seconds or 180)
        used_fallback = False

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if (
                response.status_code >= 400
                and payload["size"] != "1024x1024"
                and "size" in response.text.lower()
            ):
                # 比例不被接受时退回方图重试：构图差一点，总比整次失败强。
                self.ctx.logger.warning(
                    "尺寸 %s 被拒，退回 1024x1024: %s",
                    payload["size"],
                    response.text[:120],
                )
                payload["size"] = "1024x1024"
                response = await client.post(endpoint, json=payload, headers=headers)
            if response.status_code >= 400 and uris and self._is_copyright_reject(response.text):
                # 5.0 Flash 对知名 IP 的角色有输出侧版权过滤；4.0 更宽松。
                self.ctx.logger.warning(
                    "主模型被版权拦截，切兜底: %s -> %s", conf.model, conf.fallback_model
                )
                payload["model"] = conf.fallback_model
                response = await client.post(endpoint, json=payload, headers=headers)
                used_fallback = True
            if response.status_code >= 400:
                raise ArtAgentError(
                    f"绘图引擎返回 {response.status_code}: {response.text[:160]}"
                )
            data = response.json()
            item = (data.get("data") or [{}])[0]
            image_url = str(item.get("url") or "").strip()
            if not image_url:
                raise ArtAgentError("绘图引擎没有返回图片地址")
            image_response = await client.get(image_url)
            if image_response.status_code >= 400:
                raise ArtAgentError("图片下载失败")
            content = image_response.content
            if not content or not _looks_like_image(content):
                raise ArtAgentError("引擎返回的不是图片")
        return content, str(payload["model"]), used_fallback

    def _snapshot_prompt(self, task_id: str, prompt: str, info: Mapping[str, Any]) -> None:
        """把最终发给画面模型的原文落盘（2026-11-11 20:0x）。

        以前 history 只存 request 的前 160 字，identity/style/hint 全靠代码反推，
        出图不对时没法复现「到底发了什么」。这里只写文本、不写 base64，
        顺带统计身份名词与否定词密度：以后谁再往提示词里加一句「不要画活鸟」，
        日志里会直接告警，而不是等一张错图画出来才发现。
        """

        try:
            birds = prompt.count("鸟") + prompt.count("燕")
            negations = sum(prompt.count(w) for w in ("不要", "避免", "严禁", "禁止"))
            entry = {
                "ts": int(time.time()),
                "task_id": task_id,
                "lane": str(info.get("lane") or ""),
                "reference": str(info.get("reference") or "none"),
                "chars": len(prompt),
                "identity_noun": birds,
                "negation": negations,
                "final_prompt": prompt,
            }
            path = os.path.join(
                os.path.dirname(self._history_file()), "prompt_snapshot.jsonl"
            )
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._rotate_history(path, keep=200)
            if birds > 4 or negations > 18:
                self.ctx.logger.warning(
                    "最终提示词身份名词 %d 次 / 否定词 %d 次，偏高：task=%s",
                    birds, negations, task_id,
                )
        except Exception as exc:
            self.ctx.logger.warning("写入最终提示词快照失败: %s", exc)

    async def _submit_ark(
        self,
        prompt: str,
        stream_id: str,
        images: Sequence[bytes],
        size: str,
        info: Mapping[str, Any],
    ) -> dict:
        """直连引擎是同步出图，扔后台跑，立刻回执，避免卡住 Planner 这一轮。"""

        conf = self._ark_conf()
        if not conf.enabled:
            raise ArtAgentError("直连引擎关着，画不了")
        task_id = f"ark-{int(time.time() * 1000)}"
        self._snapshot_prompt(task_id, prompt, info)
        task = asyncio.create_task(
            self._ark_worker(task_id, prompt, stream_id, list(images), size, dict(info))
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return {"task_id": task_id, "status": "running"}

    async def _ark_worker(
        self,
        task_id: str,
        prompt: str,
        stream_id: str,
        images: Sequence[bytes],
        size: str,
        info: Mapping[str, Any],
    ) -> None:
        started = time.time()
        try:
            content, model, used_fallback = await self._ark_generate(prompt, images, size)
            await self.ctx.send.image(
                base64.b64encode(content).decode("ascii"),
                stream_id,
                # 和主动发言一致：她自己发的图必须进对话历史，否则下一轮接不上
                sync_to_maisaka_history=True,
                maisaka_source_kind="guided_reply",
            )
            self.ctx.logger.info(
                "直连出图已发送: task=%s model=%s fallback=%s bytes=%d",
                task_id, model, used_fallback, len(content),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.ctx.logger.error("直连出图失败: task=%s err=%s", task_id, exc)
            # 提交成功不等于画出来了：失败要把额度退回去，不然 self 一天 2 张
            # 撞上一次 500 就没得用了（2026-11-11 19:0x）。
            try:
                self._refund_quota(
                    str(info.get("quota") or ""), int(info.get("quota_limit") or 0)
                )
            except Exception:
                pass
            # 她那轮在提交成功时就 stop 了，这里不发一句话，对方就是干等一场。
            await self._notify_draw_failed(stream_id, exc)
            try:
                self._record(
                    dict(info),
                    {"success": False, "message": str(exc)},
                    int((time.time() - started) * 1000),
                )
            except Exception:
                pass

    async def _notify_draw_failed(self, stream_id: str, exc: Exception) -> None:
        """出图失败必须说一声，别让对方干等。

        文案里不提「额度」「接口」这类机制词，只说这次不算数、份儿还留着
        ——她本来就该像人一样解释，而不是报错。
        """

        reason = "这次没画出来，那边卡住了"
        text = str(exc or "")
        lowered = text.casefold()
        if "版权" in text or "copyright" in lowered or "1026" in text:
            reason = "这张被当成有版权的图拦下来了，画不了"
        elif "timed out" in lowered or "超时" in text or "timeout" in lowered:
            reason = "等太久，那边一直没画完"
        elif "下载" in text or "download" in lowered:
            reason = "图是画出来了，我这边没接住"
        line = f"{reason}。这次不算数，份儿还留着，等会儿再让我试一次。"
        try:
            await self.ctx.send.text(
                line,
                stream_id,
                sync_to_maisaka_history=True,
                maisaka_source_kind="guided_reply",
            )
        except Exception as send_exc:  # 通知失败不能盖掉原始失败
            self.ctx.logger.warning("出图失败通知没发出去: %s", send_exc)

    # ---------------- 重复调用闸 ----------------

    _DRAW_DEDUP_SECONDS = 45

    def _draw_recently_submitted(self, stream_id: str, prompt: str) -> bool:
        """同一会话、同一句话 45 秒内是否刚刚提交过。

        planner 在工具返回后仍可能再调一次（「反复发起绘图」的老毛病），那会起
        第二个后台任务：画两张、扣两次额度、群里刷两张几乎一样的图。提示词只能
        降低概率，这里给一道硬闸。只认**原样重复**，换个说法/加一句都不拦。

        🔴 只在提交成功后才记账：失败了（缺参考、额度满、引擎拒）必须能立刻重试。
        """

        if not stream_id:
            return False
        base = re.sub(r"\s+", "", prompt or "").casefold()
        last = self._draw_calls.get(f"{stream_id}|{base}", 0.0)
        return bool(last) and (time.time() - last) < self._DRAW_DEDUP_SECONDS

    def _mark_draw_submitted(self, stream_id: str, prompt: str) -> None:
        if not stream_id:
            return
        base = re.sub(r"\s+", "", prompt or "").casefold()
        now = time.time()
        if len(self._draw_calls) > 300:  # 顺手清过期项，别让字典无限长
            cutoff = now - self._DRAW_DEDUP_SECONDS * 4
            self._draw_calls = {
                key: ts for key, ts in self._draw_calls.items() if ts >= cutoff
            }
        self._draw_calls[f"{stream_id}|{base}"] = now

    # ---------------- 工具 ----------------

    @Tool(
        "draw",
        visibility="visible",
        brief_description=(
            "🔴 只用于「新画一张图」；只是想随机看一张现成二次元图（来张好看的图／来点图／美图／来张二次元图）时不要用本工具，改用 send_setu；想按主题搜现成图（甘雨的图／搜一下猫）改用 image_search。"
            "画图统一入口（自动判路：画我自己→self；画别人→cast；纯插画/随手画→illustration；"
            "带参考图改造→reference）。"
            "🔴 有参考图时（reference 用 chat 或 url，包括「照着聊天里的图画」）：request 只写「在参考图基础上改什么」"
            "——姿势、表情、动作、服装、场景变化，不要从头重新描述整张画面（模型以图为准，重述会打架）。"
            "没有参考图时 request 才写完整画面描述。画我自己时把「画你」「你的样子」这类词写进 request。"
            "🔴 request 要写出这一刻的样子：神态、动作、彼此怎么互动，你按情境自己判断该怎么写，写具体就行。"
            "只交代「在哪、穿什么、做什么」，画出来的人会空着一张脸。"
            "🔴 她的固定长相、发色瞳色和发饰由工具自动补齐，request 里只写这一刻的神态、动作、场景和衣服，"
            "不要重述身份特征（用户明确点名要画某个细节时照他说的写）——重复写会把装饰物放大成画面里的角色。"
            "想表达「不要…」时改成正面写你要的样子（写「两人各自看着前方」而不是「不要互相对视」），"
            "画面模型容易只抓住你否定的那个词。"
            "🔴 多人合照（画我和某角色一起 / 合影）：request 写清有谁、什么姿势和站位"
            "（并肩站着、她从后面搂着对方、面对面坐着、一个侧身一个正对镜头），2~4 个人名直接写，"
            "会自动给每个角色搜参考图，不用自己搜图、也不用交代参考图怎么用。"
            "🔴 画面里没有她自己、全是别的角色（画甘雨和刻晴打牌）：写清角色名、动作、场景，走 cast 通道自动搜参考图。"
            "🔴 万一某个角色搜不到参考图，工具会直接失败并点名缺谁（不会硬画）："
            "照着返回的 message 请对方发一张图，不要自己改写描述重试，也不要换别的绘图工具。"
            "🔴 对方只是在评价上一张、或者还没说清要画什么时，一般先回一句话问清楚，别先画一版试水；"
            "他说「改成…」「再…一点」这类话时，是在她上一张成品上继续改：直接把改动点写进 request，"
            "上一版成品会自动当底图，不用重述整张画面，也不用先画一版试水。"
            "🔴 一次只出一张图。想让画面里的人物被画准（尤其是侧面、背面、头饰细节），"
            "不用自己凑参考图——会自动给每个角色多找几张不同角度的图一起当参考，"
            "也可以在 request 里写清「要正面偏侧身」这类机位要求。"
            "🔴 一条消息里发多张图也可以：会全部当参考图用（同一套衣服的多个角度最好）。"
            "🔴 聊天里的手绘画（随手画、涂鸦、给你画个小猫）走插画通道、固定水墨风，"
            "不用在 request 里写画风，也不用动 mode。"
            "调用后立即返回任务号，出图会自动发进聊天——拿到结果直接 stop 结束本轮，不要 wait 等图、不要 reply 复述。"
            "照着聊天里的图画她自己时，人物形象图和那张图会自动一起用，不用额外处理。"
            "🔴 参考图取不取得到是工具内部的事：**照常调用就行**，别因为上一轮没找到图、或看到聊天里"
            "只有描述没有原图，就先跟对方说「我取不到」。要不要用图、用哪张，让工具自己判断。"
        ),
        detailed_description=(
            "需要**新画一张图**（画我自己、画别的角色、画插画、照着某张图改）时用这个工具，"
            "**不要直接调用下游绘图工具（generate_photo / styled_draw 等）**——它们已对 LLM 隐藏，直接调会绕过额度与判路。"
            "🔴 只想随机看一张**现成**二次元图不算画图：改用 send_setu，不要当成画我自己或立绘；"
            "想按具体主题找现成图（XX 的图／搜一下 XX）改用 image_search。"
            "它会自己判断四件事：①画我自己（有固定形象，走写真通道）；"
            "②画别的角色、画面里没有我（搜参考图走 cast）；"
            "③画一个场景/东西/风格，或她随手画的小画（走插画通道，固定水墨风）；"
            "④照着某张图改（走图生图）。"
            "「画我和某角色一起」归①，「画 X 和 Y 一起」归②，两种情况都会自动给每个角色找参考图。"
            "request 写完整画面描述：主体、场景、构图、光线、风格，还有人物这一刻的样子"
            "（神态、动作、彼此怎么互动，你按情境自行判断着写具体）——只写「并肩走着看晚霞」"
            "会得到两张没有表情的脸。"
            "想表达「不要…」时改成正面写你要的样子（要「两人各自看着前方」而不是「不要互相对视」），"
            "画面模型常常只抓住被否定的那个词。"
            "多人时把姿势和站位写具体（谁在前谁在后、有没有拥抱/搂肩/牵手、各自朝向），"
            "只写「并排站」会得到很僵的证件照。"
            "想要某个角度的画面就在 request 里说明（如「正面偏侧身」「背影」「低机位仰拍」），"
            "一次仍然只出一张。"
            "想画我自己时，把「自拍」「画你」「你的样子」「你穿…」这类词写进 request。"
            "有参考图时用 reference 指定来源：chat（聊天里的图，可多张）、url（链接）、none（不用图）。"
            "🔴 参考图能不能取到由工具判断，**不要凭上一轮的印象先拒绝**：上一条就算真的没找到图、"
            "或画成了别的风格，这一条照样正常调用，让它自己再找一次（被引用的、附带发的、图库里的都算数）。"
            "只有工具明确返回「没有可用参考图」时，才需要跟对方说明、请他补一张。"
            "🔴 只是评价上一张、或者对方还没说清要画什么时，一般先回一句话问清楚，别先画一版试水。"
            "🔴 要改上一张就直接写改动点（如「改成两人并肩走」「表情再生动些」「背景换成夜里」），"
            "上一版成品会自动当底图，不用重述整张画面，也不用先把改动重画成新图。"
            "工具立即返回任务号，出图由下游插件自己发到聊天。"
        ),
        parameters=[
            ToolParameterInfo(
                name="request",
                param_type=ToolParamType.STRING,
                description="画面描述。没参考图：写完整画面（主体、场景、构图）。有参考图：只写要在图上改什么（姿势/表情/动作/服装/场景），不要重述画面",
                required=True,
            ),
            ToolParameterInfo(
                name="mode",
                param_type=ToolParamType.STRING,
                description=(
                    "auto（默认，自动判定）/ self（画面里有她自己，包括她和参考图里的人一起）/ "
                    "cast（全是别人）/ illustration / "
                    "reference（只照这张图改，画面里没有她）"
                ),
                required=False,
                default="auto",
            ),
            ToolParameterInfo(
                name="reference",
                param_type=ToolParamType.STRING,
                description="auto（默认）/ chat（聊天里的图）/ url（链接）/ none（不用参考图）",
                required=False,
                default="auto",
            ),
            ToolParameterInfo(
                name="url",
                param_type=ToolParamType.STRING,
                description="参考图链接（reference=url 时必填）",
                required=False,
                default="",
            ),
            ToolParameterInfo(
                name="size",
                param_type=ToolParamType.STRING,
                description="图片尺寸，留空用插件默认；仅 self 通道生效",
                required=False,
                default="",
            ),
        ],
    )
    async def tool_draw(
        self,
        request: str,
        mode: str = "auto",
        reference: str = "auto",
        url: str = "",
        size: str = "",
        **kwargs: Any,
    ) -> dict:
        cfg = self._cfg()
        if not cfg.plugin.enabled:
            return {"success": False, "message": "绘图调度没开，先让我醒一醒"}

        prompt = (request or "").strip()
        if not prompt:
            return {"success": False, "message": "画面描述是空的，我不知道要画什么"}

        message, stream_id, user_id = self._runtime(kwargs)
        if self._draw_recently_submitted(stream_id, prompt):
            self.ctx.logger.info(
                "重复绘图请求已拦截（%ss 内同一句）: %s",
                self._DRAW_DEDUP_SECONDS,
                prompt[:24],
            )
            return {
                "success": True,
                "lane": "",
                "count": 0,
                "message": (
                    "这张刚提交过、正在画，等它发出来就行"
                    "（本轮请直接结束 stop，不要再调一次，也不要 wait）"
                ),
            }
        result = await self._execute(
            prompt, mode, reference, url, size, message, stream_id, user_id
        )
        if result.get("success"):
            self._mark_draw_submitted(stream_id, prompt)
        # P4（2026-11-08 协作者B建议）：失败别让 planner wait 等「下一次再试」——
        # 那条路曾造成「生图失败 → wait → 唤醒后对同一条消息二次 reply」的自激。
        if not result.get("success") and result.get("message"):
            result["message"] += "。请把失败原因告诉用户，然后本轮直接结束（stop），不要 wait，不要重试"
        return result

    # ---------------- 供其它插件调用的入口 ----------------

    @API("draw_image", version="1", public=True, description="供其它插件（空间说说等）调用：按统一判定画一张图并提交任务")
    async def api_draw_image(
        self,
        request: str = "",
        mode: str = "auto",
        reference: str = "none",
        url: str = "",
        size: str = "",
        stream_id: str = "",
        user_id: str = "",
        return_bytes: bool = False,
    ) -> dict:
        """其它插件没有消息上下文，所以默认不走聊天取图（reference=none）。"""

        cfg = self._cfg()
        if not cfg.plugin.enabled:
            return {"success": False, "result": "绘图调度没开"}
        prompt = (request or "").strip()
        if not prompt:
            return {"success": False, "result": "画面描述是空的"}
        # 同步出图（2026-11-09 art-agent contributors）：供随笔/说说配图直接取图片字节，
        # 不进聊天流、不占日额度，调用方自己过闸门后发空间。
        if return_bytes:
            return await self._draw_bytes(prompt, mode, size)
        if not (stream_id or "").strip():
            return {"success": False, "result": "缺少 stream_id"}

        try:
            result = await self._execute(
                prompt,
                mode,
                reference,
                url,
                size,
                {},
                stream_id.strip(),
                (user_id or "").strip(),
                source="plugin",
            )
        except Exception as exc:
            self.ctx.logger.error("外部插件调用绘图失败: %s", exc, exc_info=True)
            return {"success": False, "result": str(exc)}
        if not result.get("success"):
            return {"success": False, "result": str(result.get("message") or "绘图失败")}
        return {"success": True, "result": result}

    async def _draw_bytes(self, request: str, mode: str, size: str) -> dict:
        """同步出图：直接把图片字节交给调用方，不自动发 QQ、不扣聊天额度。

        self  = 带造型库参考图（画她本人，按当季/点名/primary 挑一套）；
        scene = 不带任何参考图（纯风景/静物）。
        两路都复用 _ark_generate（含主模型版权兜底），刻意不经过 _dispatch，
        因此不会创建 _ark_worker、不会 ctx.send.image、也不会占 self/reference 日额度。
        """
        cfg = self._cfg()
        if not cfg.engines.ark.enabled:
            return {"success": False, "result": "ark 引擎关着，画不了同步图"}
        lane = "scene" if (mode or "").strip().casefold() in {"scene", "illustration"} else "self"
        started = time.time()
        info = {"prompt": request, "lane": lane, "reference": "none", "source": "plugin:prose"}
        try:
            ref_images: List[bytes] = []
            outfit = ""
            prompt = request
            if lane == "self":
                await self._ensure_person_migrated()
                person_assets = self._pick_person_assets(request)
                tagged = [a for a in person_assets if a.get("tags")]
                if tagged:
                    person_assets = tagged
                max_ref = max(int(cfg.engines.ark.max_references or 1), 1)
                ref_images = [a["bytes"] for a in person_assets if a.get("bytes")][:max_ref]
                if not ref_images:
                    return {"success": False, "result": "造型图库里还没有可用的人物形象图"}
                outfit = str(self._tag_map(person_assets[0].get("tags") or []).get("outfit") or "")
                prompt = self._compose_self_prompt(request, has_combo=False, person_assets=person_assets)
            content, model, used_fallback = await self._ark_generate(prompt, ref_images, size)
        except Exception as exc:
            self.ctx.logger.error("同步出图失败: %s", exc, exc_info=True)
            return {"success": False, "result": str(exc)}
        result = {
            "success": True,
            "lane": lane,
            "engine": "ark",
            "task_id": f"sync-{int(started * 1000)}",
            "status": "done",
            "message": f"同步出图完成 lane={lane} model={model} fallback={used_fallback}",
        }
        try:
            self._record(info, result, int((time.time() - started) * 1000))
        except Exception as exc:
            self.ctx.logger.warning("同步出图记账失败: %s", exc)
        return {
            "success": True,
            "result": {
                "success": True,
                "image_b64": base64.b64encode(content).decode("ascii"),
                "lane": lane,
                "outfit": outfit,
                "model": model,
                "bytes": len(content),
            },
        }

    # ---------------- WebUI 控制台 API ----------------

    @staticmethod
    def _public_entry(item: Mapping[str, Any]) -> dict:
        ts = int(item.get("ts") or 0)
        return {
            "ts": ts,
            "time": time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "",
            "lane": str(item.get("lane") or ""),
            "reference": str(item.get("reference") or "none"),
            "ok": bool(item.get("ok")),
            "status": str(item.get("status") or ""),
            "task_id": str(item.get("task_id") or ""),
            "prompt": str(item.get("prompt") or ""),
            "note": str(item.get("note") or ""),
            "elapsed_ms": int(item.get("elapsed_ms") or 0),
            "source": str(item.get("source") or ""),
        }

    @API("webui_overview", version="1", public=False, description="绘图控制台概览：通道、额度、统计、下游与配置")
    async def webui_overview(self, operation: str = "status", args: Optional[dict] = None) -> dict:
        del operation, args
        try:
            return await self._overview_payload()
        except Exception as exc:
            # 宿主只会回一句「插件运行时调用失败」，不留痕就没法查
            self.ctx.logger.error("控制台概览生成失败: %s", exc, exc_info=True)
            return {"success": False, "error": f"概览生成失败：{exc}"}

    async def _overview_payload(self) -> dict:
        cfg = self._cfg()
        state = self._quota_state()
        limit = int(cfg.limits.daily_self_max or 0)
        ref_state = self._quota_state("reference")
        ref_limit = int(cfg.limits.daily_reference_max or 0)
        cast_state = self._quota_state("cast")
        cast_limit = int(cfg.limits.daily_cast_max or 0)
        stats = self._stats(7)
        today = stats["today"]["lanes"]
        downstream = self._downstream(await self._component_payload())
        recent = sorted(self._history_entries(), key=lambda item: int(item.get("ts") or 0))[-8:]

        lanes = {
            "self": {
                "label": "画她自己",
                "target": f"引擎 · {cfg.engines.self_engine}",
                "enabled": bool(cfg.lanes.self_lane),
                "price": self._lane_price("self"),
                "desc": "本地人物形象图，可与会话参考图组合出图",
                "today": today["self"],
            },
            "illustration": {
                "label": "画插画",
                "target": f"引擎 · {cfg.engines.illustration_engine}",
                "enabled": bool(cfg.lanes.illustration),
                "price": self._lane_price("illustration"),
                "desc": "场景、物件、画风，不涉及固定形象；手绘固定水墨",
                "today": today["illustration"],
            },
            "cast": {
                "label": "画别人",
                "target": "引擎 · ark",
                "enabled": bool(cfg.lanes.cast),
                "price": self._lane_price("cast"),
                "desc": "画面里全是别的角色，每人各搜一张参考图",
                "today": today["cast"],
            },
            "reference": {
                "label": "照着参考图改",
                "target": f"引擎 · {cfg.engines.reference_engine}",
                "enabled": bool(cfg.lanes.reference),
                "price": self._lane_price("reference"),
                "desc": "聊天图 / 外链图，真图生图",
                "today": today["reference"],
            },
        }
        return {
            "success": True,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version": str(cfg.plugin.version),
            "enabled": bool(cfg.plugin.enabled),
            "lanes": lanes,
            "quota": {
                "date": str(state.get("date") or ""),
                "used": int(state.get("count") or 0),
                "limit": limit,
                "unlimited": limit <= 0,
            },
            "reference_quota": {
                "date": str(ref_state.get("date") or ""),
                "used": int(ref_state.get("count") or 0),
                "limit": ref_limit,
                "unlimited": ref_limit <= 0,
            },
            "cast_quota": {
                "date": str(cast_state.get("date") or ""),
                "used": int(cast_state.get("count") or 0),
                "limit": cast_limit,
                "unlimited": cast_limit <= 0,
            },
            "engines": {
                "self": str(cfg.engines.self_engine),
                "cast": "ark",
                "illustration": str(cfg.engines.illustration_engine),
                "reference": str(cfg.engines.reference_engine),
                "ark_enabled": bool(cfg.engines.ark.enabled),
                "ark_model": str(cfg.engines.ark.model),
                "ark_fallback": str(cfg.engines.ark.fallback_model),
                "ark_price": float(cfg.engines.ark.price or 0.0),
                "ark_fallback_price": float(cfg.engines.ark.fallback_price or 0.0),
            },
            "stats": stats,
            "downstream": downstream,
            "config": self._config_snapshot(),
            "recent": [self._public_entry(item) for item in reversed(recent)],
            "history_total": int(stats["total_records"]),
        }

    @API("webui_history", version="1", public=False, description="绘图记录分页读取")
    async def webui_history(self, offset: int = 0, limit: int = 20, args: Optional[dict] = None) -> dict:
        del args
        rows = sorted(self._history_entries(), key=lambda item: int(item.get("ts") or 0))
        rows.reverse()  # 同一秒内的多条记录也要保持「后写在前」
        start = max(0, int(offset or 0))
        size = min(50, max(1, int(limit or 20)))
        return {
            "success": True,
            "total": len(rows),
            "offset": start,
            "items": [self._public_entry(item) for item in rows[start : start + size]],
        }

    @API("webui_config_save", version="1", public=False, description="控制台逐项修改配置：校验后写回 config.toml 并热生效")
    async def webui_config_save(
        self, section: str, key: str, value: str, args: Optional[dict] = None
    ) -> dict:
        del args
        section = str(section or "").strip()
        key = str(key or "").strip()
        kind = EDITABLE_FIELDS.get((section, key))
        if kind is None:
            return {"success": False, "error": f"{section}.{key} 不允许在控制台修改"}
        try:
            coerced = self._coerce(kind, value)
            draft = self.config.model_dump(mode="python")
            draft.setdefault(section, {})[key] = coerced
            new_cfg = ArtAgentConfig.model_validate(draft)
        except Exception as exc:
            return {"success": False, "error": f"值不合法：{str(exc)[:160]}"}
        try:
            self._persist_config(section, key, coerced)
        except Exception as exc:
            self.ctx.logger.error("配置落盘失败: %s", exc, exc_info=True)
            return {"success": False, "error": "写入 config.toml 失败，改动没有保存"}
        self.set_plugin_config(new_cfg.model_dump(mode="python"))
        try:
            await self.on_config_update(
                "self", new_cfg.model_dump(mode="python"), str(new_cfg.plugin.config_version)
            )
        except Exception as exc:
            self.ctx.logger.warning("配置热更新回调失败: %s", exc)
        self.ctx.logger.info("控制台修改配置 %s.%s = %r", section, key, coerced)
        return {"success": True, "applied": {"section": section, "key": key, "value": coerced}}

    @API(
        "webui_quota_reset",
        version="2",
        public=False,
        description="重置今日额度：lane=self / reference / cast / all（默认 all）",
    )
    async def webui_quota_reset(
        self, lane: str = "all", args: Optional[dict] = None
    ) -> dict:
        """按通道重置。空参 = 全清，兼容老控制台的调用方式。"""

        del args
        wanted = str(lane or "all").strip().casefold()
        lanes = ("self", "reference", "cast")
        if wanted in ("", "all", "*"):
            targets = lanes
        elif wanted in lanes:
            targets = (wanted,)
        else:
            return {"success": False, "error": f"不认识的通道：{lane}"}
        today = time.strftime("%Y-%m-%d")
        try:
            for name in targets:
                with open(
                    self._quota_file(name), "w", encoding="utf-8", newline="\n"
                ) as handle:
                    json.dump({"date": today, "count": 0}, handle, ensure_ascii=False)
        except Exception as exc:
            return {"success": False, "error": f"重置失败：{exc}"}
        self.ctx.logger.info("控制台重置今日额度（%s）", " + ".join(targets))
        return {"success": True, "date": today, "lanes": list(targets), "count": 0}

    @API("webui_selftest", version="1", public=False, description="重新检查下游插件是否在线")
    async def webui_selftest(self, args: Optional[dict] = None) -> dict:
        del args
        cfg = self._cfg()
        downstream = self._downstream(await self._component_payload())
        maitu_ok = bool(downstream[MAITU_PLUGIN]["loaded"])
        drawpic_ok = bool(downstream[DRAWPIC_PLUGIN]["loaded"])
        ark_cfg = self._cfg().engines.ark
        self_engine = str(self._cfg().engines.self_engine or "").strip().casefold()
        ref_engine = str(self._cfg().engines.reference_engine or "").strip().casefold()
        illu_engine = str(self._cfg().engines.illustration_engine or "").strip().casefold()
        ark_ok = bool(ark_cfg.enabled)
        gallery_count = len(self._load_gallery()["assets"])
        person_ok = gallery_count > 0
        checks = [
            {
                "name": "火山图生图引擎（ark）",
                "ok": ark_ok,
                "detail": (
                    f"已启用 · {ark_cfg.model}（self/reference 引擎）"
                    if ark_ok
                    else "未启用，self 与 reference 通道不可用"
                ),
            },
            {
                "name": "绘图插件（drawpic）",
                "ok": drawpic_ok,
                "detail": (
                    "已加载 · 提供插画通道" if drawpic_ok else "没有找到，插画通道不可用"
                )
                if illu_engine == "drawpic"
                else ("已加载（当前插画引擎不是它）" if drawpic_ok else "未加载（当前插画引擎不依赖它）"),
            },
            {
                "name": "人物形象图库",
                "ok": person_ok,
                "detail": f"已有 {gallery_count} 张（含主形象），画她自己可用"
                if person_ok
                else "空的，先在上方上传一张",
            },
            {
                "name": "写真插件（maitu）",
                "ok": maitu_ok,
                "detail": "可选 · 仅旧人物图迁移时用一次" if maitu_ok else "未加载，不影响（人物图已在本地）",
            },
        ]
        return {
            "success": True,
            "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "downstream": downstream,
            "checks": checks,
            "lanes_ready": {
                "self": bool(cfg.lanes.self_lane) and ark_ok and person_ok,
                "illustration": (drawpic_ok if illu_engine == "drawpic" else ark_ok)
                and bool(cfg.lanes.illustration),
                "reference": (ark_ok if ref_engine == "ark" else drawpic_ok)
                and bool(cfg.lanes.reference),
            },
        }

    @API("webui_preview", version="1", public=False, description="通道判定试算（关键词规则快算；实际执行时优先内部 LLM 判别）")
    async def webui_preview(
        self, request: str = "", has_reference: bool = False, args: Optional[dict] = None
    ) -> dict:
        del args
        text = (request or "").strip()
        lane = self._decide_lane("auto", text, bool(has_reference))
        hit = ""
        for keyword in self._cfg().self_channel.keywords or []:
            token = str(keyword or "").strip()
            if token and token.casefold() in text.casefold():
                hit = token
                break
        if has_reference:
            reason = "带了参考图 → 走图生图"
        elif hit:
            reason = f"命中判定词「{hit}」→ 画她自己"
        else:
            reason = "没有参考图、也没命中判定词 → 走插画"
        return {
            "success": True,
            "lane": lane,
            "keyword": hit,
            "price": self._lane_price(lane),
            "reason": reason,
        }

    @API("webui_person", version="1", public=False, description="人物形象图库列表（agent 本地持有，支持多图与标签）")
    async def webui_person(self, args: Optional[dict] = None) -> dict:
        del args
        index = self._load_gallery()
        assets_out = []
        for asset in index["assets"]:
            fpath = os.path.join(self._gallery_dir(), asset["file"])
            thumb_path = os.path.join(self._gallery_dir(), asset["id"] + ".thumb.jpg")
            thumb_data: Optional[bytes] = None
            try:
                with open(thumb_path, "rb") as handle:
                    thumb_data = handle.read()
            except OSError:
                thumb_data = None
            if not thumb_data:
                # 旧资产没有缩略图，现生成一份并落盘
                try:
                    with open(fpath, "rb") as handle:
                        original = handle.read()
                    thumb_data = _make_thumbnail(original)
                    if thumb_data:
                        with open(thumb_path, "wb") as handle:
                            handle.write(thumb_data)
                except OSError:
                    thumb_data = None
            if not thumb_data:
                continue
            assets_out.append(
                {
                    "id": asset["id"],
                    "name": asset["name"],
                    "tags": asset["tags"],
                    "primary": asset["primary"],
                    "added_at": asset["added_at"],
                    "updated_at": asset["updated_at"],
                    "size": os.path.getsize(fpath) if os.path.isfile(fpath) else 0,
                    "thumbnail": f"data:image/jpeg;base64,{base64.b64encode(thumb_data).decode('ascii')}",
                }
            )
        primary_id = next(
            (a["id"] for a in index["assets"] if a["primary"]), ""
        )
        return {
            "success": True,
            "assets": assets_out,
            "primary_id": primary_id,
            "person_version": f"gallery:{int(os.path.getmtime(self._gallery_index_path())) if os.path.isfile(self._gallery_index_path()) else 0}",
        }

    @API("webui_person_upload", version="1", public=False, description="上传新的人物形象图（可填名称与标签）")
    async def webui_person_upload(
        self, upload_id: str = "", request_id: str = "", name: str = "", tags: str = ""
    ) -> dict:
        del request_id
        upload_id = (upload_id or "").strip()
        if not upload_id:
            return {"success": False, "error": "缺少上传标识"}
        try:
            envelope = await self.ctx.webui.claim_upload(upload_id)
        except Exception as exc:
            self.ctx.logger.warning("领取上传失败: %s", exc)
            return {"success": False, "error": "领取上传失败，请重试"}
        if not isinstance(envelope, Mapping) or envelope.get("success") is False:
            return {"success": False, "error": "上传领取失败"}
        upload = envelope.get("upload") if isinstance(envelope.get("upload"), Mapping) else envelope
        path = str(upload.get("path") or "")
        if not path or not os.path.isfile(path):
            return {"success": False, "error": "上传文件不存在"}
        try:
            with open(path, "rb") as handle:
                data = handle.read()
        except OSError as exc:
            return {"success": False, "error": f"读取上传文件失败：{exc}"}
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        if not data:
            return {"success": False, "error": "图片是空的"}
        if len(data) > 8 * 1024 * 1024:
            return {"success": False, "error": "图片超过 8 MB"}
        if not _looks_like_image(data):
            return {"success": False, "error": "文件不是可识别的图片"}
        tag_list = [t for t in (tags or "").replace("，", ",").replace("、", ",").split(",") if t.strip()]
        try:
            asset = self._gallery_add(data, name or "", tag_list)
        except ArtAgentError as exc:
            return {"success": False, "error": str(exc)}
        except OSError as exc:
            self.ctx.logger.error("写入人物形象图失败: %s", exc, exc_info=True)
            return {"success": False, "error": f"写入失败：{exc}"}
        self.ctx.logger.info(
            "人物形象图已入库: id=%s name=%s tags=%s bytes=%d",
            asset["id"],
            asset["name"],
            asset["tags"],
            len(data),
        )
        return {
            "success": True,
            "asset_id": asset["id"],
            "primary": asset["primary"],
            "status": "saved",
        }

    @API("webui_person_update", version="1", public=False, description="改人物形象的名称、标签或设为主形象")
    async def webui_person_update(
        self, asset_id: str = "", name: str = "", tags: str = "", make_primary: bool = False
    ) -> dict:
        asset_id = (asset_id or "").strip()
        index = self._load_gallery()
        target = next((a for a in index["assets"] if a["id"] == asset_id), None)
        if target is None:
            return {"success": False, "error": "没有这张图"}
        if name is not None and str(name).strip():
            target["name"] = str(name).strip()[:60]
        if tags:
            target["tags"] = [
                t.strip()[:30] for t in str(tags).replace("，", ",").replace("、", ",").split(",") if t.strip()
            ][:12]
        if make_primary:
            for a in index["assets"]:
                a["primary"] = a["id"] == asset_id
        target["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            self._save_gallery(index)
        except OSError as exc:
            return {"success": False, "error": f"保存失败：{exc}"}
        self.ctx.logger.info(
            "人物形象图已更新: id=%s name=%s tags=%s primary=%s",
            target["id"],
            target["name"],
            target["tags"],
            target["primary"],
        )
        return {"success": True, "asset": {k: target[k] for k in ("id", "name", "tags", "primary")}}

    @API("webui_person_delete", version="1", public=False, description="删除人物形象图（控制台已做两步确认）")
    async def webui_person_delete(self, asset_id: str = "", confirm: str = "") -> dict:
        asset_id = (asset_id or "").strip()
        if confirm != asset_id:
            return {"success": False, "error": "确认字段不匹配"}
        index = self._load_gallery()
        target = next((a for a in index["assets"] if a["id"] == asset_id), None)
        if target is None:
            return {"success": True, "deleted": False}
        was_primary = bool(target["primary"])
        index["assets"] = [a for a in index["assets"] if a["id"] != asset_id]
        for suffix in (target["file"], asset_id + ".thumb.jpg"):
            try:
                os.remove(os.path.join(self._gallery_dir(), suffix))
            except OSError:
                pass
        if was_primary and index["assets"]:
            index["assets"][0]["primary"] = True
        try:
            self._save_gallery(index)
        except OSError as exc:
            return {"success": False, "error": f"保存索引失败：{exc}"}
        self.ctx.logger.info("人物形象图已删除: id=%s bytes=%d", target["id"], 0)
        return {"success": True, "deleted": True}

    # ---------------- 核心执行 ----------------

    @staticmethod
    def _who_list(names: Sequence[Any]) -> str:
        clean = [str(n).strip() for n in names if str(n or "").strip()]
        return "、".join(dict.fromkeys(clean))

    def _missing_reference(
        self,
        not_found: Sequence[Any] = (),
        no_room: Sequence[Any] = (),
        lane: str = "cast",
        subject: str = "",
    ) -> dict:
        """缺参考就整单不画（设计约定）。

        以前是「搜不到就降级成插画水墨」，画出来的人和要的人根本不是同一个，
        还白花一次搜图审核。现在改成明说没找到、要图，让用户补一张再来。
        本函数只构造拒绝结果，不扣额度（额度在提交成功后才扣）。
        """

        missing = self._who_list(not_found)
        crowded = self._who_list(no_room)
        subject = subject or ("合照" if lane == "self" else "这张图")
        if missing and crowded:
            lead = f"没找到「{missing}」的参考图，「{crowded}」也没分到位置，{subject}先不画了"
        elif missing:
            lead = f"没找到「{missing}」的参考图，{subject}先不画了"
        else:
            lead = f"「{crowded}」没分到参考图位置，{subject}先不画了"
        if crowded and not missing:
            tail = (
                "一次最多只能带 10 张参考图，人太多就分配不过来。"
                "减掉一位，或者直接给这几位的图，我照着重画。"
            )
        else:
            tail = (
                "画面里点到名字的角色，我都是照着她（他）的立绘画的，"
                "没有参考我只能瞎猜，画出来就是另一个人。"
                "你发一张图给我就行——直接在消息里发图，或者给个图片链接都可以，我照着重画。"
            )
        return {
            "success": False,
            "lane": lane,
            "missing": list(dict.fromkeys(str(n).strip() for n in not_found if str(n).strip())),
            "message": lead + "。" + tail + "这次没扣额度。",
        }

    async def _execute(
        self,
        prompt: str,
        mode: str,
        reference: str,
        url: str,
        size: str,
        message: Mapping[str, Any],
        stream_id: str,
        user_id: str,
        source: str = "chat",
    ) -> dict:
        """统一出口：计时 + 记账，真正的判定在 `_dispatch` 里。"""

        started = time.time()
        info: dict = {"prompt": prompt, "lane": "", "reference": "none", "source": source}
        try:
            result = await self._dispatch(
                prompt, mode, reference, url, size, message, stream_id, user_id, info
            )
        except Exception as exc:
            self.ctx.logger.error("绘图调度未捕获异常: %s", exc, exc_info=True)
            result = {"success": False, "message": "任务没提交成功，等会儿再试"}
        # 拒绝路径（缺参考图等）在 info 里还没写 lane，但结果里带了；
        # 补上，历史记录才能按通道统计失败，而不是一堆「未知」。
        if not info.get("lane") and isinstance(result, dict) and result.get("lane"):
            info["lane"] = result["lane"]
        try:
            self._record(info, result, int((time.time() - started) * 1000))
        except Exception as exc:  # 记账失败不能反过来弄丢已经提交的任务
            self.ctx.logger.warning("绘制记录失败: %s", exc)
        return result

    async def _dispatch(
        self,
        prompt: str,
        mode: str,
        reference: str,
        url: str,
        size: str,
        message: Mapping[str, Any],
        stream_id: str,
        user_id: str,
        info: dict,
    ) -> dict:
        cfg = self._cfg()
        if not stream_id:
            self.ctx.logger.warning("绘图调用缺少 stream_id，已拒绝")
            return {"success": False, "message": "这次调用没带聊天上下文，画不了"}

        reference_mode = (reference or "auto").strip().casefold()
        # 输入侧支持多张：一条消息里的多张图全部当参考图（同一角色的不同角度）。
        input_images: List[bytes] = []
        image: Optional[bytes] = None
        reference_from = "none"
        try:
            if reference_mode in {"auto", "url"} and (url or "").strip():
                one = await self._download_image(url.strip())
                input_images = [one] if one else []
                reference_from = "url"
            if not input_images and reference_mode in {"auto", "chat"}:
                input_images, reference_from = await self._chat_image(message, stream_id)
            image = input_images[0] if input_images else None
        except ArtAgentError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            self.ctx.logger.warning("参考图获取异常: %s", exc)
            input_images, image, reference_from = [], None, "none"

        # ---- 迭代改图：把上一版成品拿回来当底图 ----
        # 「改成两人并肩走」「表情再生动些」这类话只有在上一张的基础上改才有意义。
        # 之前一律当新图重画，等于从头猜一遍，人、衣服、场景全漂，还多一次生成调用。
        edit_base = False
        if reference_mode in {"auto", "chat"} and not input_images and self._looks_like_edit(prompt):
            previous_image = await self._last_own_image(stream_id)
            if previous_image is not None:
                input_images = [previous_image]
                image = previous_image
                reference_from = "previous"
                edit_base = True
                prompt = "在上一版成品上改：只改下面说的这一处，其余照原样保留。\n" + prompt
                self.ctx.logger.info("检测到改图指令，用上一版成品当底图")

        # cast 画的是具名角色，靠搜她们的立绘；自动抓来的旧聊天图跟这次画面无关，
        # 还会被当成「场景图」塞进参考里把画面带偏。用户主动发的（chat/reply/url）不算。
        if reference_from == "recent" and (mode or "").strip().casefold() == "cast":
            self.ctx.logger.info("cast 通道丢弃自动抓取的旧聊天图（与本次画面无关）")
            input_images, image, reference_from = [], None, "none"

        lane, lane_reason, lane_via, extras = await self._decide_lane_smart(
            mode, prompt, image is not None
        )
        # 判路自己认出 cast（mode=auto）时同样要丢掉那张自动抓的旧图，
        # 否则它会被当场景参考，画出来背景跟要的没关系。
        if lane == "cast" and reference_from == "recent":
            self.ctx.logger.info("cast 通道丢弃自动抓取的旧聊天图（与本次画面无关）")
            input_images, image, reference_from = [], None, "none"
        self.ctx.logger.info(
            "绘图判路: via=%s lane=%s reason=%s ref=%s q=%s/%s",
            lane_via,
            lane,
            lane_reason,
            reference_from,
            extras.get("outfit_query", ""),
            extras.get("search_query", ""),
        )
        info["lane"] = lane
        note = ""

        # ---- 主体归一化：lane 与 subjects 不一致时以 subjects 为准 ----
        # LLM 偶尔会把「画我和小鱼」判成 self 但 subjects 只写别人，或反过来。
        # 只在 subjects 非空时纠正，避免它偷懒不给 subjects 时把单人路径改坏。
        subjects = list(extras.get("subjects") or [])
        self_subjects = [s for s in subjects if s.get("kind") == "self"]
        mate_subjects = [
            s for s in subjects if s.get("kind") != "self" and s.get("who")
        ]
        if subjects and lane in {"self", "cast"}:
            if self_subjects and lane == "cast":
                self.ctx.logger.info("判路归一化: cast → self（subjects 里有她自己）")
                lane = "self"
            elif not self_subjects and mate_subjects and lane == "self":
                self.ctx.logger.info("判路归一化: self → cast（subjects 里只有别人）")
                lane = "cast"
            info["lane"] = lane

        # ---- 图生图 + 画面里有她自己 → 走 self 那套人物基准 ----
        # reference 通道只把「那张图」喂给模型，没有任何她的形象图；「照着参考图画你和她」
        # 于是画对了图里那位、把主角色画成凭空捏的路人（实测）。
        # 这里改成：她自己的人物基准当第 1 张，那张图当同伴参考——和合照同一条管线。
        # 纯图生图（「把这张图改成水墨」「背景换成晚上」）不含她自己，仍然走 reference。
        lane, self_from_reference, input_trusted = self._prefer_self_with_reference(
            lane, prompt, bool(input_images), reference_from, self_subjects
        )
        if self_from_reference:
            info["lane"] = lane
            note += "画面里有她自己，按她自己的人物基准画；"
            self.ctx.logger.info(
                "判路归一化: reference → self（画面里有她本人，共 %d 张输入图）",
                len(input_images),
            )
            if not mate_subjects:
                # 没解析出名字（图里是谁她也不知道）：给个占位名，图就是她的参考。
                # 标 from_input 让下面跳过搜图——「图中那位 立绘」搜不出东西，只会白花时间。
                mate_subjects = [
                    {
                        "who": "图中那位",
                        "kind": "character",
                        "query": "",
                        "from_input": True,
                    }
                ]
            elif len(mate_subjects) == 1:
                # 判路给了名字也只画一个人：那张图就是她的参考，直接绑上。
                # 别拿「鲸鱼少女 立绘」去搜——搜不到白等十几秒，搜到别的角色更糟（串脸）。
                mate_subjects[0]["from_input"] = True

        # 多人合照优先于换装：subjects 里只要有别人，就不能把那个人当成「服装参考」，
        # 否则会先搜一张「小鱼」当衣服，画面里只剩她一个人穿着小鱼的衣裳。
        # 带图时同样要搜同伴，否则「画我和小鱼在这张图里」会静默退化成只画她一个。
        multi_mode = lane == "self" and bool(mate_subjects)

        # 构图：判路给建议，工具显式传 size 时以工具为准。出图永远只有一张。
        layout = str(extras.get("layout") or "").strip().casefold()
        if not (size or "").strip():
            if lane == "illustration":
                # 插画走 drawpic（不单独计费），它的默认尺寸别乱改，改了容易 400。
                size = ""
            else:
                # 🔴 2026-11-11：Seedream 5.0 flash 按「张」计价 按引擎计价，
                # 1K / 1.5K / 2K 同价（官方定价页确认），以前一直写死 1024 级，
                # 等于白放着 2K 的细节点数不用。这里换成官方 2K 档的宽高像素。
                size = {
                    "portrait": "1776x2368",
                    "landscape": "2368x1776",
                    "square": "2048x2048",
                }.get(layout, "2048x2048")
        info["layout"] = layout or "default"
        info["size"] = str(size or "")

        # 额度见底就别再往下跑了：判路 + 搜图 + 视觉审核要 20~30 秒，最后照样被拒。
        # 真机 2026-11-11 16:56：自拍额度已经 2/2，她还是一次次重试，
        # 用户等半分钟只等到一句「明天再画」。这里只查不扣，真正的扣费仍在提交前。
        quota_probe = {
            "self": ("self", int(cfg.limits.daily_self_max or 0), "自拍"),
            "reference": ("reference", int(cfg.limits.daily_reference_max or 0), "照着图"),
            "cast": ("cast", int(cfg.limits.daily_cast_max or 0), "画别人"),
        }.get(lane)
        if lane == "reference" and not cfg.lanes.reference:
            # 参考图通道关着时后面会降级成插画通道，不能按 reference 额度提前拒。
            quota_probe = None
        if quota_probe:
            quota_name, quota_limit, quota_label = quota_probe
            allowed, used, limit = self._check_quota(quota_name, quota_limit)
            if not allowed:
                self.ctx.logger.info(
                    "%s 通道额度用尽（前置拦截）: used=%s limit=%s", quota_name, used, limit
                )
                info["lane"] = lane
                return {
                    "success": False,
                    "lane": lane,
                    "message": f"今天{quota_label}已经画了 {used} 张（上限 {limit}），明天再画吧",
                }

        # 联网搜参考图：搜 → 下载 → 视觉模型逐张审核 → 合格才用。
        # 放在 lane 降级之前，否则 reference 无图会先被改成 illustration。
        # cos 换装时要多搜几张：同一套衣服的正面、侧背面、头饰细节，
        # 只给一张正面立绘时模型画不出背面和配饰。
        outfit_mode = False
        if cfg.search.enabled and not input_images and not multi_mode and lane != "cast":
            query = ""
            if lane == "self":
                query = str(extras.get("outfit_query") or "").strip()
            elif lane == "reference":
                query = str(extras.get("search_query") or "").strip()
            if query:
                want = max(1, int(cfg.limits.refs_per_subject or 1)) if lane == "self" else 1
                found = await self._search_reference(query, prompt, cfg, want=want)
                if found.get("ok"):
                    found_images = [b for b in (found.get("images") or [found["image"]]) if b]
                    input_images = found_images
                    image = input_images[0]
                    reference_from = "search"
                    if lane == "self":
                        outfit_mode = True
                        note += (
                            f"检索到服装参考「{str(found.get('title') or '')[:18]}」"
                            f"（{len(input_images)} 张，吻合度 {found.get('score')}）；"
                        )
                    else:
                        note += (
                            f"检索到参考图「{str(found.get('title') or '')[:18]}」"
                            f"（吻合度 {found.get('score')}）；"
                        )
                    info["search"] = {
                        "query": found.get("query", ""),
                        "title": found.get("title", ""),
                        "score": found.get("score"),
                        "rounds": found.get("rounds"),
                        "reviewed": found.get("reviewed"),
                        "images": len(input_images),
                    }
                else:
                    self.ctx.logger.info(
                        "绘图搜图未采用（%s）: %s", query, str(found.get("error") or "")[:160]
                    )
                    if lane == "self":
                        # cos 换装没有服装参考就画不出这套衣服，硬画=一张普通自拍还扣额度。
                        name = str(extras.get("outfit_query") or "").split()[0]
                        return self._missing_reference(
                            [name or query], lane="self", subject="这张换装图"
                        )
                    note += "没搜到靠谱的参考图；"

        info["reference"] = reference_from

        if lane == "reference" and not input_images:
            # 🔴 2026-11-11 18:08 / 18:10 实测：planner 判了 reference，但图没取到，
            # 这里直接掉进插画通道——插画画的是「跟她无关的一幅画」，人和画风全不对。
            # 降级可以，但不能降错方向：先问一次判别模型「没有图的话这幅画跟她有没有关系」，
            # 判不出来再退回关键词规则。异常路径才会走到这里，多这一次调用可以忽略。
            fb_lane, fb_reason, _ = await self._decide_lane_llm(prompt, False)
            if fb_lane not in {"self", "cast", "illustration"}:
                fb_lane = self._decide_lane("auto", prompt, False)
            lane = fb_lane if fb_lane in {"self", "cast"} else "illustration"
            info["lane"] = lane
            note = (
                "没找到可用参考图，改成按人物形象画了；"
                if lane in {"self", "cast"}
                else "没找到可用参考图，改成直接画了；"
            )
            self.ctx.logger.info(
                "reference 无图降级: lane=%s reason=%s", lane, fb_reason or "规则复核"
            )

        # 额度：先按实际张数收敛，再一次性检查；提交成功后按实际张数扣。
        # 额度按「请求的来路」算，不按内部实现：对方说的是「照着这张图」，
        # 就该记在「照着图」的额度上，不能因为实现走了 self 管线就把额度从 10 缩到 2。
        quota_lane = "reference" if (self_from_reference and lane == "self") else lane
        quota_name = {"self": "self", "reference": "reference", "cast": "cast"}.get(quota_lane, "")
        quota_limit = {
            "self": cfg.limits.daily_self_max,
            "reference": cfg.limits.daily_reference_max,
            "cast": cfg.limits.daily_cast_max,
        }.get(quota_name, 0)
        # 后台 worker 失败时要按同一口径把额度退回去，得让它拿到扣在哪个口上。
        info["quota"] = quota_name
        info["quota_limit"] = int(quota_limit or 0)
        if lane == "self" and not cfg.lanes.self_lane:
            return {"success": False, "message": "写真通道我关掉了，这会儿画不了自己"}
        if lane == "cast" and not cfg.lanes.cast:
            return {"success": False, "message": "画别人的通道我关掉了"}
        if quota_name:
            allowed, used, limit = self._check_quota(quota_name, quota_limit)
            if not allowed:
                self.ctx.logger.info(
                    "%s 通道额度用尽: used=%s limit=%s", quota_name, used, limit
                )
                label = {"self": "自拍", "reference": "照着图", "cast": "画别人"}[quota_name]
                return {
                    "success": False,
                    "message": f"今天{label}已经画了 {used} 张（上限 {limit}），明天再画吧",
                }

        # 通道开关必须在这里把关：关掉 reference 却仍走 edit_image，
        # 或在 illustration 关着时静默画出来，都会让「开关」变成摆设。
        if lane == "reference" and not cfg.lanes.reference:
            lane = "illustration"
            info["lane"] = lane
            note += "参考图通道关着，改成直接画了；"
        if lane == "illustration" and not cfg.lanes.illustration:
            self.ctx.logger.warning("插画通道已关闭，拒绝本次请求")
            return {"success": False, "message": "插画通道我关掉了，这会儿画不了"}

        engine = ""
        try:
            if lane == "self":
                engine = (cfg.engines.self_engine or "ark").strip().casefold()
                if engine == "ark":
                    if not cfg.engines.ark.enabled:
                        return {"success": False, "message": "直连引擎关着，画不了"}
                    await self._ensure_person_migrated()
                    max_ref = max(int(cfg.engines.ark.max_references or 1), 1)
                    person_assets = self._pick_person_assets(prompt)
                    # 空标签图不喂：花 token 喂进去模型只能瞎猜（2026-11-08 协作者B建议）。
                    # 全都没标签时仍全喂，否则 self 通道直接残废。
                    tagged = [a for a in person_assets if a.get("tags")]
                    if tagged:
                        person_assets = tagged

                    # 多人合照：她自己 1 张基准 + 每个同伴各搜 1~N 张（N = refs_per_subject）。
                    # 带图时也要搜同伴——否则「画我和小鱼在这张图里」会静默退化成只画她一个。
                    # 搜图放在额度检查之后，被拒的请求不该白花搜索与审核的钱。
                    # 分配按两轮走：先每人保底 1 张（不让人凭空消失），再轮着补到 N 张
                    # （补的是同一角色的侧面/背面/细节）。否则第一个角色会把位置吃光。
                    companion_names: List[str] = []
                    companion_images: List[bytes] = []
                    consumed_input = False
                    companion_counts: List[int] = []
                    missing_names: List[str] = []
                    no_room_names: List[str] = []
                    mate_limit = max(0, int(cfg.limits.max_companions or 0))
                    mates = mate_subjects[:mate_limit]
                    truncated = len(mate_subjects) > len(mates)
                    per_subject = max(1, int(cfg.limits.refs_per_subject or 1))
                    # 参考图里那位没有名字，也不该拿去搜：这次给的图就是她的参考。
                    # 先摘出来直接绑定，剩下的人才走「搜立绘」。
                    from_input_mates = [m for m in mates if m.get("from_input")]
                    if from_input_mates:
                        mates = [m for m in mates if not m.get("from_input")]
                        if input_images:
                            for mate in from_input_mates:
                                companion_images.extend(input_images)
                                companion_names.append(str(mate.get("who") or "图中那位"))
                                companion_counts.append(len(input_images))
                            consumed_input = True
                            note += f"图中那位按你这次给的图算（{len(input_images)} 张）；"
                    if mates and cfg.search.enabled:
                        room = max_ref - 1 - len(input_images)
                        alloc: List[dict] = []
                        for mate in mates:
                            query = str(mate.get("query") or "").strip() or f"{mate['who']} 立绘"
                            found = await self._search_reference(
                                query, prompt, cfg, want=min(per_subject, max(1, room))
                            )
                            if found.get("ok"):
                                images = [
                                    b for b in (found.get("images") or [found["image"]]) if b
                                ]
                                alloc.append(
                                    {
                                        "who": str(mate["who"]),
                                        "images": images,
                                        "score": found.get("score"),
                                    }
                                )
                                note += (
                                    f"检索到「{mate['who']}」参考 {len(images)} 张"
                                    f"（{found.get('score')} 分）；"
                                )
                            else:
                                self.ctx.logger.info(
                                    "合照搜图未采用（%s）: %s",
                                    query,
                                    str(found.get("error") or "")[:120],
                                )
                                missing_names.append(str(mate["who"]))
                                note += f"没搜到「{mate['who']}」的靠谱参考；"
                        # 第一轮：每人 1 张
                        for item in alloc:
                            if len(companion_images) >= room:
                                break
                            companion_images.append(item["images"].pop(0))
                            companion_names.append(item["who"])
                            companion_counts.append(1)
                        # 第二轮：按顺序补到 per_subject 张
                        progressed = True
                        while len(companion_images) < room and progressed:
                            progressed = False
                            for index, item in enumerate(alloc):
                                if len(companion_images) >= room:
                                    break
                                if not item["images"] or companion_counts[index] >= per_subject:
                                    continue
                                companion_images.append(item["images"].pop(0))
                                companion_counts[index] += 1
                                progressed = True
                        # 位置真的不够时也要说清楚，不能让人物悄悄消失
                        for item in mates:
                            who = str(item["who"])
                            if who not in companion_names and who not in missing_names:
                                no_room_names.append(who)
                                note += f"参考图位置不够，没给「{who}」留图；"
                    elif mates:
                        missing_names.extend(str(item["who"]) for item in mates)
                        note += "搜图关着，同伴只能靠描述画；"

                    # 本次请求自己带了图（引用 / 附图 / 链接）时，搜不到别再拒画：
                    # 那张图多半就是这位的设定图，用它当她的参考，比让用户再发一张有用。
                    # input_trusted 的来历：reply/chat/url 天然可信；recent 只有在这种
                    # 情况才可信——判路本来是 reference、又从会话里翻到对方发的那张图
                    # （已跳过她自己发的），那是他明确要参考的图，不是随机旧图。
                    if (
                        missing_names
                        and input_images
                        and input_trusted
                    ):
                        name = missing_names[0]
                        companion_images.extend(input_images)
                        companion_names.extend([name] * len(input_images))
                        companion_counts.append(len(input_images))
                        note += f"没搜到「{name}」的独立参考，按你这次给的图算她；"
                        missing_names.remove(name)
                        consumed_input = True

                    # 缺一个就不画（设计约定）：少一个人不是画得糙，是画错人。
                    # 以前会带着「缺参考」继续提交，出来的是另一个人，还白扣一次额度。
                    if missing_names or no_room_names:
                        return self._missing_reference(
                            missing_names, no_room_names, lane="self"
                        )

                    if companion_names and not person_assets:
                        # 合照提示词里「第1张是你自己」是硬约束。她的形象图一张都
                        # 没有时，第1张就成了同伴，画出来同伴是主角、她本人凭空
                        # 消失（与「缺参考整单拒」同一套判断，别为了出图硬画）。
                        return {
                            "success": False,
                            "lane": "self",
                            "message": (
                                "图库里还没有我的人物形象图，合照画不出来——"
                                "先在控制台传一张我的形象图，再来叫我画。这次没扣额度。"
                            ),
                        }
                    if companion_names:
                        # 顺序即语义：第 1 张是她自己，后面按 subjects 顺序跟同伴（同一人连续），
                        # 最后是会话参考图。提示词里的「第 N 张是谁」靠这个顺序对齐。
                        ref_images = [a["bytes"] for a in person_assets[:1]] + companion_images
                        if not consumed_input:
                            ref_images.extend(input_images)
                        ref_images = ref_images[:max_ref]
                    else:
                        if outfit_mode:
                            # 换装只留一张人物基准：形象图里的原衣服会和服装参考打架
                            person_assets = person_assets[:1]
                        if input_images:
                            # 给输入图留位置（cos 时是整组服装参考）
                            person_assets = person_assets[: max(1, max_ref - len(input_images))]
                        ref_images = [a["bytes"] for a in person_assets]
                        ref_images.extend(input_images)
                        ref_images = ref_images[:max_ref]
                    if not ref_images:
                        return {
                            "success": False,
                            "message": "图库里还没有人物形象图，在控制台传一张再来",
                        }
                    if companion_names or missing_names:
                        if truncated:
                            note += f"人数超过上限，只画前 {len(mates)} 位同伴；"
                        note += (
                            f"合照共 {len(ref_images)} 张参考（你"
                            + (f" + {'、'.join(companion_names)}" if companion_names else "")
                            + "）；"
                        )
                        prompt = self._compose_self_prompt(
                            prompt,
                            has_combo=False,
                            companions=companion_names,
                            companion_counts=companion_counts,
                            relation=str(extras.get("relation") or ""),
                            missing=missing_names,
                            # 输入图已经被算作某位同伴的参考时不重复点名：
                            # 否则会多出一句「第 N 张起是对方给的参考图」，指着一张不存在的图。
                            has_scene=bool(input_images) and not consumed_input,
                            only_people=(
                                ["主角色"] + list(dict.fromkeys(companion_names)) if truncated else None
                            ),
                        )
                        info["subjects"] = ["主角色"] + list(dict.fromkeys(companion_names))
                    elif not input_images:
                        note += f"按人物形象出图（参考她的 {len(person_assets)} 张形象图）；"
                        prompt = self._compose_self_prompt(
                            prompt, has_combo=False, person_assets=person_assets
                        )
                    elif outfit_mode:
                        note += (
                            f"按服装参考换装（{len(input_images)} 张），长相仍以她的形象图为准；"
                        )
                        prompt = self._compose_self_prompt(
                            prompt,
                            has_combo=True,
                            person_assets=person_assets,
                            outfit=True,
                            outfit_count=len(input_images),
                        )
                    elif edit_base:
                        note += "按上一版成品继续改（底图＝她刚发出去的那张）；"
                        prompt = self._compose_self_prompt(
                            prompt,
                            has_combo=True,
                            person_assets=person_assets,
                            edit_base=True,
                        )
                    else:
                        note += "按你给的图改画面，人物形象保持不变；"
                        prompt = self._compose_self_prompt(
                            prompt, has_combo=True, person_assets=person_assets
                        )
                    result = await self._submit_ark(
                        prompt, stream_id, ref_images, size, info
                    )
                else:
                    result = await self._submit_self(prompt, stream_id, user_id, size)
            elif lane == "cast":
                # 画别人：每个角色各搜 1~N 张参考图，不掺她自己的形象图。
                engine = "ark"
                if not cfg.engines.ark.enabled:
                    return {"success": False, "message": "直连引擎关着，画不了别人的图"}
                max_ref = max(int(cfg.engines.ark.max_references or 1), 1)
                cast_limit = max(1, int(cfg.limits.max_companions or 1) + 1)
                cast_subjects = mate_subjects[:cast_limit]
                cast_truncated = len(mate_subjects) > len(cast_subjects)
                cast_names: List[str] = []
                cast_images: List[bytes] = []
                cast_counts: List[int] = []
                cast_missing: List[str] = []
                cast_no_room: List[str] = []
                per_subject = max(1, int(cfg.limits.refs_per_subject or 1))
                if cfg.search.enabled:
                    room = max_ref - len(input_images)
                    alloc: List[dict] = []
                    for item in cast_subjects:
                        query = str(item.get("query") or "").strip() or f"{item['who']} 立绘"
                        found = await self._search_reference(
                            query, prompt, cfg, want=min(per_subject, max(1, room))
                        )
                        if found.get("ok"):
                            images = [
                                b for b in (found.get("images") or [found["image"]]) if b
                            ]
                            alloc.append(
                                {
                                    "who": str(item["who"]),
                                    "images": images,
                                    "score": found.get("score"),
                                }
                            )
                            note += (
                                f"检索到「{item['who']}」参考 {len(images)} 张"
                                f"（{found.get('score')} 分）；"
                            )
                        else:
                            cast_missing.append(str(item["who"]))
                            note += f"没搜到「{item['who']}」的靠谱参考；"
                    # 先每人保底 1 张，再轮着补到 per_subject 张（同一个人的侧面/背面/细节）
                    for entry in alloc:
                        if len(cast_images) >= room:
                            break
                        cast_images.append(entry["images"].pop(0))
                        cast_names.append(entry["who"])
                        cast_counts.append(1)
                    progressed = True
                    while len(cast_images) < room and progressed:
                        progressed = False
                        for index, entry in enumerate(alloc):
                            if len(cast_images) >= room:
                                break
                            if not entry["images"] or cast_counts[index] >= per_subject:
                                continue
                            cast_images.append(entry["images"].pop(0))
                            cast_counts[index] += 1
                            progressed = True
                    for entry in alloc:
                        who = str(entry["who"])
                        if who not in cast_names and who not in cast_missing:
                            cast_no_room.append(who)
                            note += f"参考图位置不够，没给「{who}」留图；"
                else:
                    cast_missing.extend(str(item["who"]) for item in cast_subjects)
                    note += "搜图关着，只能靠描述画；"

                # 缺参考就不画（设计约定）：冷门角色搜不到时，
                # 以前会降级成插画水墨——画风不对、人也不对。现在直接要图。
                if cast_missing or cast_no_room:
                    return self._missing_reference(cast_missing, cast_no_room, lane="cast")

                if not cast_images:
                    # 连要画谁都没解析出来（判路没给 subjects），别再拿整段提示词
                    # 当人名去报「没找到参考图」——那句话又长又莫名其妙。
                    if not cast_subjects:
                        return {
                            "success": False,
                            "lane": "cast",
                            "message": (
                                "我没从这句话里认出具体要画哪几个角色。"
                                "把名字单独说一遍就行，比如「画胡桃和七七」，"
                                "我好去搜她们的立绘。这次没扣额度。"
                            ),
                        }
                    return self._missing_reference(
                        [str(item["who"]) for item in cast_subjects], lane="cast"
                    )
                else:
                    ref_images = list(cast_images)
                    ref_images.extend(input_images)
                    ref_images = ref_images[:max_ref]
                    if cast_truncated:
                        note += f"人数超过上限，只画前 {len(cast_subjects)} 位；"
                    prompt = self._compose_cast_prompt(
                        prompt,
                        names=cast_names,
                        counts=cast_counts,
                        relation=str(extras.get("relation") or ""),
                        missing=cast_missing,
                        has_scene=bool(input_images),
                        only_people=(cast_names if cast_truncated else None),
                    )
                    info["subjects"] = list(dict.fromkeys(cast_names))
                    if cast_missing:
                        info["missing"] = cast_missing
                        note += f"缺参考：{'、'.join(cast_missing)}；"
                    note += f"画了 {'、'.join(dict.fromkeys(cast_names))}；"
                    result = await self._submit_ark(
                        prompt, stream_id, ref_images, size, info
                    )
            elif lane == "reference":
                engine = (cfg.engines.reference_engine or "ark").strip().casefold()
                # 只认真正支持参考图的引擎。drawpic 的可图收下源图后静默丢弃，
                # 接口照样 200，画出来却跟参考图无关——宁可拒绝。
                if engine != "ark":
                    return {
                        "success": False,
                        "message": "参考图通道没有能用的引擎，这次先不画了",
                    }
                if not cfg.engines.ark.enabled:
                    return {"success": False, "message": "直连引擎关着，画不了参考图"}
                ref_cap = max(int(cfg.engines.ark.max_references or 1), 1)
                result = await self._submit_ark(
                    prompt, stream_id, input_images[:ref_cap], size, info
                )
            else:
                # 手绘画一次只出一张：随手画不需要多机位，插画通道也按张排队。
                engine = (cfg.engines.illustration_engine or "drawpic").strip().casefold()
                # 手绘画固定走插画通道 + 水墨风：她随口说「给你画个小猫」不是精细出图，
                # 拼风格句保证每次都是同一个调子，而不是跟着 request 的描述乱飘。
                illus = cfg.illustration
                if illus.enabled:
                    style_parts = [prompt]
                    if illus.style:
                        style_parts.append(illus.style)
                    if illus.avoid:
                        style_parts.append("画面避免出现：" + illus.avoid)
                    prompt = "\n".join(part for part in style_parts if part)
                    note += "插画通道·水墨；"
                if engine == "ark":
                    if not cfg.engines.ark.enabled:
                        return {"success": False, "message": "直连引擎关着，画不了"}
                    result = await self._submit_ark(prompt, stream_id, [], size, info)
                else:
                    result = await self._submit_drawing(
                        "draw", prompt, stream_id, None, size
                    )
        except DrawingError as exc:
            return {"success": False, "message": f"绘图插件拒绝了这次请求：{exc}"}
        except ArtAgentError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            self.ctx.logger.error("提交绘图任务失败: %s", exc, exc_info=True)
            return {"success": False, "message": "任务没提交成功，等会儿再试"}

        # 提交成功才占额度：失败或被拒不该白扣一次。一次只出一张，扣一份额度。
        if quota_name == "self":
            self._consume_quota("self", cfg.limits.daily_self_max)
        elif quota_name == "reference":
            self._consume_quota("reference", cfg.limits.daily_reference_max)
        elif quota_name == "cast":
            self._consume_quota("cast", cfg.limits.daily_cast_max)
        info["engine"] = engine

        self.ctx.logger.info(
            "绘图任务已提交: lane=%s engine=%s reference=%s task_id=%s status=%s",
            lane,
            engine,
            reference_from,
            result.get("task_id", ""),
            result.get("status", ""),
        )
        return {
            "success": True,
            "lane": lane,
            "engine": engine,
            "reference": reference_from,
            "task_id": result.get("task_id", ""),
            "status": result.get("status", ""),
            "count": 1,
            "message": (
                note + "任务已提交，出图后会自动发出来；本轮请直接结束（stop），"
                "不要 wait 等图，也不要再用 reply 提这条消息"
            ).strip(),
        }


def create_plugin() -> ArtOrchestratorPlugin:
    """Runner 通过此工厂函数实例化插件（缺了它插件会加载失败）。"""
    return ArtOrchestratorPlugin()


__all__ = ["ArtOrchestratorPlugin", "create_plugin"]
