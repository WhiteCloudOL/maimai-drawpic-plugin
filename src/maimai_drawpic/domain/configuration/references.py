"""用户显式开启的自我参考与素材来源设置。"""

from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator
from typing import List

from .styles import ReferenceBindingsSchema


class ReferenceConfig(PluginConfigBase):
    self_reference_enabled: bool = Field(default=False, description="允许识别并描绘机器人自身", json_schema_extra={"label": "启用自我参考"})
    self_names: List[str] = Field(default=["麦麦"], max_length=32, description="当前机器人的名称和别称，用于原始请求中的自身指向识别", json_schema_extra={"label": "机器人名称与别称"})
    self_reference_ids: List[str] = Field(default=[], max_length=8, description="明确选择的相容自我图片；留空时按 tag 选一张", json_schema_extra={"label": "自我参考图片"})
    multi_reference_confirmed: bool = Field(default=False, description="已通过对话框确认当前配置与多图合用方式；切换模型仍需自行核实", json_schema_extra={"label": "已确认多图参考"})
    allow_chat_material_search: bool = Field(default=False, description="允许从当前真实聊天流的有限近期记录中查找素材", json_schema_extra={"label": "允许聊天记录取材"})
    allow_web_material_search: bool = Field(default=False, description="允许通过宿主统一网络服务搜索缺少的素材", json_schema_extra={"label": "允许网络素材搜索"})

    @field_validator("self_names")
    @classmethod
    def validate_self_names(cls, names: List[str]) -> List[str]:
        if any(not name.strip() or len(name) > 80 for name in names):
            raise ValueError("机器人名称与别称必须是 1～80 个字符")
        return [name.strip() for name in names]


class ReferenceWorkspaceSchema(PluginConfigBase):
    """仅生成工作台表单字段，不新增持久配置节。"""

    references: ReferenceConfig = Field(default_factory=ReferenceConfig)
    bindings: ReferenceBindingsSchema = Field(default_factory=ReferenceBindingsSchema)

