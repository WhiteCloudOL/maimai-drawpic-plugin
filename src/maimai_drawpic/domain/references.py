"""参考选项与图片用途；不包含工具调用或执行规划。"""

from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import List, Literal
import unicodedata


def normalize_tag(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


class ReferenceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    self_reference: Literal["off", "auto", "required"] = Field(
        default="off",
        description=(
            "仅填写小写字符串 off、auto、required。required：画面明确包含机器人自身，包括与其他人物合照；"
            "off：明确不包含机器人自身，或本次不使用自我图库；auto：无法确定是否包含机器人自身，必须同时提供 user_request 用户原话。"
            "这是主体判断，不是 tag 匹配；未命中 tag 时使用默认自我图，不自动变成 off。"
            "不要填写 true/false、yes/no、机器人名字或 tag，也不要仅凭‘自拍’认定主体。全局开关关闭时不能启用。"
        ),
        examples=["off", "required", "auto"],
    )
    user_request: str = Field(
        default="", max_length=16000,
        description=("本次用户原始绘图请求，直接复制用户原话；不能用改写后的 prompt、图片描述或编造的请求代替。"
                     "self_reference=auto 或 material_sources 非空时必填；明确使用 required 且不取材时可省略。"),
        examples=["画你穿冬装在海边的样子"],
    )
    self_reference_ids: List[str] = Field(
        default_factory=list, max_length=8,
        description="明确选择的自我图库图片 ID，优先于 tag；仅用于选图，不判断是否描绘机器人。self_reference=off 时不要传入。",
    )
    self_reference_tags: List[str] = Field(
        default_factory=list, max_length=32,
        description="自我图片的选图标签，例如冬装；不用于判断人物身份。未指定图片 ID 时按 tag/原话选图，未命中使用默认图。self_reference=off 时不要传入。",
    )
    reference_ids: List[str] = Field(default_factory=list, max_length=8)
    multi_reference_confirmed: bool = False
    material_sources: List[Literal["chat", "web"]] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def validate_selection(self) -> "ReferenceOptions":
        if len(set(self.material_sources)) != len(self.material_sources):
            raise ValueError("素材来源不能重复")
        if self.self_reference == "off" and (self.self_reference_ids or self.self_reference_tags):
            raise ValueError("指定自身选图条件时必须启用本次自我参考")
        if (self.self_reference == "auto" or self.material_sources) and not self.user_request.strip():
            raise ValueError("自身识别或素材搜索必须提供用户原始请求 user_request")
        if any(not value.strip() or len(value) > 80 for value in self.self_reference_tags):
            raise ValueError("参考 tag 必须是 1～80 个字符")
        self.self_reference_ids = list(dict.fromkeys(self.self_reference_ids))
        self.reference_ids = list(dict.fromkeys(self.reference_ids))
        self.self_reference_tags = list(dict.fromkeys(normalize_tag(value) for value in self.self_reference_tags))
        self.material_sources = [value for value in ("chat", "web") if value in self.material_sources]
        return self


@dataclass(frozen=True)
class ReferenceImage:
    raw: bytes
    source: str
    role: str = "base"
    subject: str = ""
    url: str = ""
    asset_id: str = ""
    version: str = ""
    note: str = ""
    description: str = ""


@dataclass(frozen=True)
class PreparedRequest:
    prompt: str
    negative_template: str
    images: List[bytes]
    urls: List[str]
    task_type: str
    style: str
    strict_reference_inputs: bool = False

