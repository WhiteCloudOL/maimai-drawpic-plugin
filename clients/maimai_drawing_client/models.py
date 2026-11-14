# SPDX-FileCopyrightText: 2026 WhiteCloudOL
# SPDX-License-Identifier: MIT

"""客户端结果类型；不依赖绘图插件内部代码或第三方库。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Sequence, TypedDict, Union


class DrawingPreferences(TypedDict, total=False):
    """部分更新；省略字段保留原值，空字符串清除对应会话覆盖。"""

    model: str
    openai_compatibility_mode: str
    novelai_mode: str
    novelai_artist_tags: str


class DrawingReferenceOptions(TypedDict, total=False):
    """单次参考限制；不能打开服务端全局开关。"""

    self_reference: Literal["off", "auto", "required"]
    user_request: str
    self_reference_ids: List[str]
    self_reference_tags: List[str]
    material_sources: List[Literal["chat", "web"]]


class DrawingRequest(TypedDict, total=False):
    """提交选项；源图既可使用已有 Base64 文本，也可直接传入图片 bytes。"""

    model: str
    negative_prompt: str
    style: str
    task_type: Literal["draw", "edit_image"]
    stream_id: str
    source_images: Optional[Sequence[Union[str, bytes]]]
    reference_options: DrawingReferenceOptions
    openai_compatibility_mode: str
    novelai_mode: str
    novelai_artist_tags: Optional[str]


class DrawingTransportError(RuntimeError):
    """RPC 未获得可信业务响应，不代表未受理或绘图失败。"""

    def __init__(self, message: str, *, task_id: Optional[str] = None, request_id: str = "") -> None:
        super().__init__(message)
        self.task_id, self.request_id = task_id, request_id


def validate_error(error: Any, *, task_id: Optional[str] = None, request_id: str = "") -> None:
    if (
        not isinstance(error, dict)
        or not isinstance(error.get("code"), str)
        or not error["code"]
        or not isinstance(error.get("message"), str)
        or any(name in error and type(error[name]) is not bool for name in ("retry_query", "retry_submit"))
    ):
        raise DrawingTransportError("业务错误响应格式无效", task_id=task_id, request_id=request_id)


class DrawingError(RuntimeError):
    def __init__(self, error: Dict[str, Any], *, task_id: Optional[str] = None, request_id: str = "") -> None:
        validate_error(error, task_id=task_id, request_id=request_id)
        super().__init__(error["message"])
        self.code = error["code"]
        self.retry_query = bool(error.get("retry_query", False))
        self.retry_submit = bool(error.get("retry_submit", False))
        self.task_id, self.request_id = task_id, request_id


@dataclass(frozen=True)
class TaskHandle:
    task_id: Optional[str]
    request_id: str
    status: str = "pending"
    reused: bool = False
    error: Optional[DrawingError] = None


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes = field(repr=False)
    reference: Dict[str, Any]


@dataclass
class DrawingResult:
    task_id: Optional[str]
    request_id: str
    status: str
    images: List[GeneratedImage] = field(default_factory=list)
    image_references: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[DrawingError] = None
    wait_expired: bool = False
    generation_completed: bool = False
    results_readable: bool = False
    delivery: Dict[str, Any] = field(default_factory=dict)
    retry_after_ms: int = 3000
