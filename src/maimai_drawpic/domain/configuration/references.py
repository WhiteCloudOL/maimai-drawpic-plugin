"""用户显式开启的自我参考与素材来源设置。"""

from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator
from typing import List

from .styles import ReferenceBindingsSchema


class ReferenceConfig(PluginConfigBase):
    self_reference_enabled: bool = Field(default=False, description="允许识别并描绘机器人自身", json_schema_extra={"label": "启用自我参考"})
    self_names: List[str] = Field(default=["麦麦"], max_length=32, description="当前机器人的名称和别称，用于原始请求中的自身指向识别", json_schema_extra={"label": "机器人称呼"})
    self_keywords: List[str] = Field(default=["画你自己", "你的自拍", "你的样子"], max_length=32, description="自动识别自身时的可选语义线索，不作为命中即触发的硬规则", json_schema_extra={"label": "自身指向关键词", "hint": "例如：你的自拍、画你自己。关键词仅辅助判断，仍会区分否定、引用和用户本人；不要只填“我”或“自拍”等泛词。留空时只依据原话和名称识别。"})
    self_reference_ids: List[str] = Field(default=[], max_length=8, description="明确选择的相容自我图片；留空时按 tag 选一张", json_schema_extra={"label": "自我参考图片", "hint": "留空时按图库 tag 选择一张，未命中则使用默认图；需要固定形象时再选择图片。"})
    multi_reference_confirmed: bool = Field(default=False, description="已通过对话框确认当前配置与多图合用方式；切换模型仍需自行核实", json_schema_extra={"label": "已确认多图参考"})
    material_model: str = Field(default="vlm", min_length=1, max_length=200, description="参考识别使用的 MaiBot 模型名称或模型任务名", json_schema_extra={"label": "识别模型", "hint": "建议选择快速多模态模型。"})
    allow_chat_material_search: bool = Field(default=False, description="允许从当前真实聊天流的有限近期记录中查找素材", json_schema_extra={"label": "允许聊天记录取材", "hint": "仅在继续改图、重新生成等明确接续前图的任务中查找。"})
    chat_material_search_limit: int = Field(default=50, ge=1, le=200, strict=True, description="每次任务最多检查的近期聊天消息条数", json_schema_extra={"label": "聊天记录搜索上限（条）", "hint": "推荐 50 条，可设 1～200 条。仅查找当前聊天最近 24 小时内的消息，最多选取 6 张候选图。"})
    allow_web_material_search: bool = Field(default=False, description="允许通过宿主统一网络服务搜索缺少的素材", json_schema_extra={"label": "允许网络素材搜索", "hint": "仅为具体角色、特定物件或明确的参考图请求搜索；服务商跟随 MaiBot 设置。"})

    @field_validator("self_names", "self_keywords")
    @classmethod
    def validate_identity_hints(cls, names: List[str]) -> List[str]:
        if any(not name.strip() or len(name) > 80 for name in names):
            raise ValueError("名称、别称和自身关键词必须是 1～80 个字符")
        return [name.strip() for name in names]

    @field_validator("material_model")
    @classmethod
    def validate_material_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("识别模型不能为空")
        return value.strip()


class ReferenceWorkspaceSchema(PluginConfigBase):
    """仅生成工作台表单字段，不新增持久配置节。"""

    references: ReferenceConfig = Field(default_factory=ReferenceConfig)
    bindings: ReferenceBindingsSchema = Field(default_factory=ReferenceBindingsSchema)

