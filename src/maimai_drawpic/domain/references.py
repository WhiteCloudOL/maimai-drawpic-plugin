"""参考选项与图片用途；不包含工具调用或执行规划。"""

from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import List, Literal
import unicodedata


def normalize_tag(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


class ReferenceOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    self_reference: Literal["off", "auto", "required"] = "off"
    user_request: str = Field(default="", max_length=16000)
    self_reference_ids: List[str] = Field(default_factory=list, max_length=8)
    self_reference_tags: List[str] = Field(default_factory=list, max_length=32)
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


@dataclass(frozen=True)
class PreparedRequest:
    prompt: str
    negative_template: str
    images: List[bytes]
    urls: List[str]
    task_type: str
    style: str
    strict_reference_inputs: bool = False

