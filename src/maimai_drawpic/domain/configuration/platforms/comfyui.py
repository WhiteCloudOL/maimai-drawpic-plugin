"""configuration/platforms/comfyui.py 的强类型配置定义。"""

from maibot_sdk import Field

from ..types import ComfyUIPromptMode

from .common import NegativePromptConfig


class ComfyUIModelConfig(NegativePromptConfig):
    """ComfyUI 本地工作流配置。"""

    __ui_label__ = "ComfyUI 配置"
    __ui_order__ = 11

    enabled: bool = Field(
        default=False,
        description="是否启用 ComfyUI 本地工作流提供商",
        json_schema_extra={
            "label": "启用 ComfyUI",
            "hint": "开启后，模型列表会提供统一模型名 comfyui；它会按任务类型自动选择文生图或图生图工作流",
            "order": -1,
        },
    )
    base_url: str = Field(
        default="http://127.0.0.1:8188",
        description="ComfyUI 服务地址",
        json_schema_extra={
            "label": "ComfyUI 地址",
            "hint": "默认 http://127.0.0.1:8188。可填写局域网地址，例如 http://192.168.1.14:8188；末尾 / 会自动忽略",
            "order": 0,
        },
    )
    t2i_workflow_path: str = Field(
        default="data/workflows/t2i.json",
        description="ComfyUI 文生图 API 工作流 JSON 路径",
        json_schema_extra={
            "label": "文生图工作流 JSON",
            "hint": "data/ 前缀映射到插件标准数据目录，默认 data/workflows/t2i.json；其他相对路径仍以插件目录为基准，也可填写绝对路径。必须是 ComfyUI 导出的 API 格式 JSON",
            "order": 1,
        },
    )
    i2i_workflow_path: str = Field(
        default="data/workflows/i2i.json",
        description="ComfyUI 图生图 API 工作流 JSON 路径",
        json_schema_extra={
            "label": "图生图工作流 JSON",
            "hint": "data/ 前缀映射到插件标准数据目录，默认 data/workflows/i2i.json；其他相对路径仍以插件目录为基准，也可填写绝对路径。必须含可读取上传图片的节点",
            "order": 2,
        },
    )
    t2i_prompt_mode: ComfyUIPromptMode = Field(
        default="positive_negative",
        description="文生图工作流的提示词写入方式",
        json_schema_extra={
            "label": "文生图提示词模式",
            "hint": "positive_negative=分别写入正向和反向节点；single_prompt=仅写入一个提示词节点",
            "options": ["positive_negative", "single_prompt"],
            "order": 3,
        },
    )
    i2i_prompt_mode: ComfyUIPromptMode = Field(
        default="positive_negative",
        description="图生图工作流的提示词写入方式",
        json_schema_extra={
            "label": "图生图提示词模式",
            "hint": "positive_negative=分别写入正向和反向节点；single_prompt=仅写入一个提示词节点",
            "options": ["positive_negative", "single_prompt"],
            "order": 4,
        },
    )
    prompt_input_name: str = Field(
        default="text",
        description="提示词节点的输入字段名",
        json_schema_extra={
            "label": "提示词输入字段名",
            "hint": "标准 CLIPTextEncode 节点为 text。若自定义节点输入字段不是 text，请填写实际字段名",
            "order": 5,
        },
    )
    t2i_prompt_node_id: str = Field(
        default="",
        description="文生图单提示词节点 ID，仅 single_prompt 模式使用",
        json_schema_extra={
            "label": "文生图单提示词节点 ID",
            "hint": "仅 t2i_prompt_mode=single_prompt 时必填。填写 API 工作流中的节点 ID，例如 3",
            "order": 6,
        },
    )
    t2i_positive_prompt_node_id: str = Field(
        default="",
        description="文生图正向提示词节点 ID，仅 positive_negative 模式使用",
        json_schema_extra={
            "label": "文生图正向提示词节点 ID",
            "hint": "仅 t2i_prompt_mode=positive_negative 时必填。填写 API 工作流中的节点 ID",
            "order": 7,
        },
    )
    t2i_negative_prompt_node_id: str = Field(
        default="",
        description="文生图反向提示词节点 ID，仅 positive_negative 模式使用",
        json_schema_extra={
            "label": "文生图反向提示词节点 ID",
            "hint": "仅 t2i_prompt_mode=positive_negative 时必填。填写 API 工作流中的节点 ID",
            "order": 8,
        },
    )
    t2i_negative_prompt: str = Field(
        default="",
        description="文生图反向提示词",
        json_schema_extra={
            "label": "文生图反向提示词",
            "hint": "仅正反提示词模式使用；内容会覆盖工作流中反向提示词节点的原始文本，留空表示传入空字符串",
            "input_type": "textarea",
            "order": 9,
        },
    )
    i2i_prompt_node_id: str = Field(
        default="",
        description="图生图单提示词节点 ID，仅 single_prompt 模式使用",
        json_schema_extra={
            "label": "图生图单提示词节点 ID",
            "hint": "仅 i2i_prompt_mode=single_prompt 时必填。填写 API 工作流中的节点 ID",
            "order": 10,
        },
    )
    i2i_positive_prompt_node_id: str = Field(
        default="",
        description="图生图正向提示词节点 ID，仅 positive_negative 模式使用",
        json_schema_extra={
            "label": "图生图正向提示词节点 ID",
            "hint": "仅 i2i_prompt_mode=positive_negative 时必填。填写 API 工作流中的节点 ID",
            "order": 11,
        },
    )
    i2i_negative_prompt_node_id: str = Field(
        default="",
        description="图生图反向提示词节点 ID，仅 positive_negative 模式使用",
        json_schema_extra={
            "label": "图生图反向提示词节点 ID",
            "hint": "仅 i2i_prompt_mode=positive_negative 时必填。填写 API 工作流中的节点 ID",
            "order": 12,
        },
    )
    i2i_negative_prompt: str = Field(
        default="",
        description="图生图反向提示词",
        json_schema_extra={
            "label": "图生图反向提示词",
            "hint": "仅正反提示词模式使用；内容会覆盖工作流中反向提示词节点的原始文本，留空表示传入空字符串",
            "input_type": "textarea",
            "order": 13,
        },
    )
    i2i_image_node_id: str = Field(
        default="",
        description="图生图源图读取节点 ID",
        json_schema_extra={
            "label": "图生图源图节点 ID",
            "hint": "填写 API 工作流中 LoadImage 或兼容节点的 ID。插件会先上传源图，再将文件名写入该节点",
            "order": 14,
        },
    )
    image_input_name: str = Field(
        default="image",
        description="图生图源图节点的输入字段名",
        json_schema_extra={
            "label": "图生图源图输入字段名",
            "hint": "标准 LoadImage 节点为 image。若自定义节点输入字段不同，请填写实际字段名",
            "order": 15,
        },
    )
    poll_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=10.0,
        description="ComfyUI 任务完成状态的轮询间隔（秒）",
        json_schema_extra={
            "label": "任务轮询间隔",
            "hint": "默认 1 秒。总超时仍使用 general.request_timeout_seconds",
            "order": 16,
        },
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="是否在调用 ComfyUI 前将提示词改写为英文",
        json_schema_extra={
            "label": "英文提示词改写",
            "hint": "Stable Diffusion、Flux 等英文提示词工作流可按需开启；中文提示词模型可保持关闭",
            "order": 17,
        },
    )
    seed: int = Field(
        default=-1,
        ge=-1,
        le=18_446_744_073_709_551_615,
        description="ComfyUI 采样种子。-1 表示每次生成随机种子，非负整数表示固定种子",
        json_schema_extra={
            "label": "ComfyUI 种子",
            "hint": "默认 -1，每次任务自动生成随机种子；填写非负整数后，文生图和图生图都会使用该固定种子",
            "order": 18,
        },
    )
    seed_input_name: str = Field(
        default="seed",
        description="采样节点中接收种子的输入字段名",
        json_schema_extra={
            "label": "种子输入字段名",
            "hint": "标准 KSampler 节点为 seed。自定义采样节点使用其他字段名时请按实际填写",
            "order": 19,
        },
    )
    t2i_seed_node_id: str = Field(
        default="",
        description="文生图种子节点 ID。留空时自动识别唯一包含 seed 输入的节点",
        json_schema_extra={
            "label": "文生图种子节点 ID",
            "hint": "留空会自动识别唯一的种子节点；工作流有多个种子节点时必须填写 API 工作流中的节点 ID",
            "order": 20,
        },
    )
    i2i_seed_node_id: str = Field(
        default="",
        description="图生图种子节点 ID。留空时自动识别唯一包含 seed 输入的节点",
        json_schema_extra={
            "label": "图生图种子节点 ID",
            "hint": "留空会自动识别唯一的种子节点；工作流有多个种子节点时必须填写 API 工作流中的节点 ID",
            "order": 21,
        },
    )
