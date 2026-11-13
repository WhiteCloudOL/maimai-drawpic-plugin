"""MiniMax 官方图片平台配置。"""

from maibot_sdk import Field
from typing import List, Literal

from .common import NegativePromptConfig


class MiniMaxModelConfig(NegativePromptConfig):
    __ui_label__ = "MiniMax 配置"
    __ui_order__ = 12

    enabled: bool = Field(
        default=True,
        description="关闭后，该平台的模型将不可选。",
        json_schema_extra={"label":"启用 MiniMax","hint":"关闭后，该平台的模型将不可选。","order":0},
    )
    api_key: str = Field(
        default="",
        description="填写 MiniMax 按量 API Key；密钥不回显。",
        json_schema_extra={"label":"API 密钥","hint":"填写 MiniMax 按量 API Key；密钥不回显。","order":1,"input_type":"password"},
    )
    base_url: str = Field(
        default="https://api.minimax.cn/v1",
        description="以 /v1 结尾；国内默认 api.minimax.cn，国际站可按账户配置 api.minimax.io。",
        json_schema_extra={"label":"API 基础地址","hint":"以 /v1 结尾；国内默认 api.minimax.cn，国际站可按账户配置 api.minimax.io。","order":2},
    )
    models: List[str] = Field(
        default=["MiniMax-H3-Image"],
        description="H3 系列支持通用编辑；image-01 系列图生图是单人人物主体参考。",
        json_schema_extra={"label":"模型列表","hint":"H3 系列支持通用编辑；image-01 系列图生图是单人人物主体参考。","order":3},
    )
    size: str = Field(
        default="auto",
        description="auto 或 宽x高；H3 指定宽高时请清空宽高比及面积。image-01 自定义宽高须为 512～2048 的 8 的倍数。",
        json_schema_extra={"label":"输出尺寸","hint":"auto 或 宽x高；H3 指定宽高时请清空宽高比及面积。image-01 自定义宽高须为 512～2048 的 8 的倍数。","order":4},
    )
    model_size_overrides: List[str] = Field(
        default=[],
        description="每项为 模型ID=宽x高；使用当前实例的实际模型 ID。",
        json_schema_extra={"label":"按模型覆盖尺寸","hint":"每项为 模型ID=宽x高；使用当前实例的实际模型 ID。","order":5},
    )
    aspect_ratio: str = Field(
        default="",
        description="留空使用服务端默认；H3 支持 auto 或 X:Y（1:3～3:1），image-01 系列使用官方固定比例。",
        json_schema_extra={"label":"宽高比（可选）","hint":"留空使用服务端默认；H3 支持 auto 或 X:Y（1:3～3:1），image-01 系列使用官方固定比例。","order":6},
    )
    area: str = Field(
        default="",
        description="仅 H3 的 auto 尺寸生效，留空使用服务端默认 4K。",
        json_schema_extra={"label":"H3 面积档位","hint":"仅 H3 的 auto 尺寸生效，留空使用服务端默认 4K。","order":7},
    )
    n: int = Field(
        default=1, ge=1, le=10,
        description="H3 为 1～10，image-01 系列为 1～9；部分成功只保留成功图片，不补画失败项。",
        json_schema_extra={"label":"生成张数","hint":"H3 为 1～10，image-01 系列为 1～9；部分成功只保留成功图片，不补画失败项。","order":8},
    )
    response_format: Literal["url", "b64_json"] = Field(
        default="url",
        description="Base64 在 image-01 协议中自动映射为 base64；H3 流式只支持 URL。",
        json_schema_extra={"label":"返回格式","hint":"Base64 在 image-01 协议中自动映射为 base64；H3 流式只支持 URL。","order":9},
    )
    output_format: Literal["jpeg", "png", "webp"] = Field(
        default="jpeg",
        description="仅 H3；jpeg、png 或 webp。",
        json_schema_extra={"label":"H3 图片格式","hint":"仅 H3；jpeg、png 或 webp。","order":10},
    )
    output_compression: int = Field(
        default=95, ge=0, le=100,
        description="0～100，仅 H3 的 JPEG/WebP 生效，PNG 忽略此参数。",
        json_schema_extra={"label":"H3 压缩质量","hint":"0～100，仅 H3 的 JPEG/WebP 生效，PNG 忽略此参数。","order":11},
    )
    stream: bool = Field(
        default=False,
        description="仅 H3 且使用 URL 返回；按原图序号收集，流中断不重新生成。",
        json_schema_extra={"label":"H3 流式输出","hint":"仅 H3 且使用 URL 返回；按原图序号收集，流中断不重新生成。","order":12},
    )
    disable_prompt_enhanced: bool = Field(
        default=False,
        description="仅 H3 文生图；开启后必须指定宽高或固定比例。图像编辑始终增强，不接受此选项。",
        json_schema_extra={"label":"禁用 H3 提示词增强","hint":"仅 H3 文生图；开启后必须指定宽高或固定比例。图像编辑始终增强，不接受此选项。","order":13},
    )
    prompt_optimizer: bool = Field(
        default=False,
        description="仅 image-01 / image-01-live，默认关闭。",
        json_schema_extra={"label":"image-01 提示词优化","hint":"仅 image-01 / image-01-live，默认关闭。","order":14},
    )
    seed: int = Field(
        default=-1, ge=-1, le=9223372036854775807,
        description="仅 image-01 系列；-1 表示不传，0 是有效种子。H3 未声明 seed，不发送。",
        json_schema_extra={"label":"image-01 随机种子","hint":"仅 image-01 系列；-1 表示不传，0 是有效种子。H3 未声明 seed，不发送。","order":15},
    )
    style_type: str = Field(
        default="",
        description="仅 image-01-live，与插件全平台风格预设分别生效。",
        json_schema_extra={"label":"image-01-live 内置画风","hint":"仅 image-01-live，与插件全平台风格预设分别生效。","order":16},
    )
    style_weight: float = Field(
        default=0.8, gt=0, le=1,
        description="仅选择内置画风时生效，范围 (0, 1]。",
        json_schema_extra={"label":"image-01-live 画风权重","hint":"仅选择内置画风时生效，范围 (0, 1]。","order":17},
    )
    aigc_watermark: bool = Field(
        default=False,
        description="是否添加可见 AIGC 标识，不影响服务端隐式标识。",
        json_schema_extra={"label":"AIGC 可见水印","hint":"是否添加可见 AIGC 标识，不影响服务端隐式标识。","order":18},
    )
    request_timeout_seconds: int = Field(
        default=600, ge=600, le=1800,
        description="单位秒，至少 600；MiniMax 接口无幂等，超时和结果读取失败不重画。",
        json_schema_extra={"label":"MiniMax 请求超时","hint":"单位秒，至少 600；MiniMax 接口无幂等，超时和结果读取失败不重画。","order":19},
    )
    extra_parameters: List[str] = Field(
        default=[],
        description="按 名称=值 填写；不允许覆盖任务模型、提示词、源图或混用 H3/image-01 参数。",
        json_schema_extra={"label":"扩展参数","hint":"按 名称=值 填写；不允许覆盖任务模型、提示词、源图或混用 H3/image-01 参数。","order":20},
    )
    rewrite_prompt_to_english: bool = Field(
        default=False,
        description="默认关闭，开启后同时处理有效的反向词和风格内容。",
        json_schema_extra={"label":"英文提示词改写","hint":"默认关闭，开启后同时处理有效的反向词和风格内容。","order":21},
    )
