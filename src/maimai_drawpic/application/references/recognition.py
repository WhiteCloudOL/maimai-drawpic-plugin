"""有界、无状态的主体与候选识别。"""

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Any, Dict, List, Literal, Optional
import asyncio
import base64
import json

from ...domain.references import ReferenceImage
from ...domain.task_errors import TaskRequestError
from ...infrastructure.media.images import detect_image_format
from .prompts import PROMPTS


class MaterialNeed(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    subject: str = Field(min_length=1, max_length=200)
    role: Literal["identity", "clothing", "object"]
    query: str = Field(min_length=1, max_length=100)
    kind: Literal["character", "user", "bot", "object"] = "character"


class MaterialNeeds(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    needs: List[MaterialNeed] = Field(max_length=3)


class ReferenceRecognizer:
    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx

    async def _json(self, prompt: str, image: Optional[ReferenceImage] = None) -> Dict[str, Any]:
        messages: Any = prompt
        if image is not None:
            def encode() -> List[Dict[str, Any]]:
                return [{"role": "user", "content": [{"type": "text", "text": prompt},
                        {"type": "image", "image_format": detect_image_format(image.raw),
                         "image_base64": base64.b64encode(image.raw).decode("ascii")}]}]
            messages = await asyncio.to_thread(encode)
        try:
            async with asyncio.timeout(20):
                response = await self.ctx.llm.generate(messages, model="vlm" if image is not None else "utils",
                                                     temperature=0.0, max_tokens=900, rpc_timeout_ms=20000)
            value = json.loads(response["content"])
            if not isinstance(value, dict):
                raise ValueError("识别结果必须为 JSON 对象")
            return value
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            raise TaskRequestError("REFERENCE_RECOGNITION_FAILED", f"参考素材识别失败（{type(exc).__name__}）") from exc

    async def self_subject(self, request: str, names: List[str]) -> str:
        value = await self._json(PROMPTS["zh-CN"]["self"].format(request=request, names=json.dumps(names, ensure_ascii=False)))
        if set(value) != {"subject"} or not isinstance(value["subject"], str) or value["subject"] not in {"self", "other", "uncertain"}:
            raise TaskRequestError("REFERENCE_RECOGNITION_FAILED", "自身识别返回了无效分类")
        return value["subject"]

    async def needs(self, request: str) -> List[MaterialNeed]:
        value = await self._json(PROMPTS["zh-CN"]["needs"].format(request=request))
        try:
            return MaterialNeeds.model_validate(value).needs
        except ValidationError as exc:
            raise TaskRequestError("REFERENCE_RECOGNITION_FAILED", "素材需求识别返回了无效结构") from exc

    async def matches(self, image: ReferenceImage, need: MaterialNeed) -> bool:
        value = await self._json(PROMPTS["zh-CN"]["match"].format(request=need.model_dump_json()), image)
        if set(value) != {"matches"} or type(value["matches"]) is not bool:
            raise TaskRequestError("REFERENCE_RECOGNITION_FAILED", "候选图片识别返回了无效匹配结果")
        return value["matches"]
