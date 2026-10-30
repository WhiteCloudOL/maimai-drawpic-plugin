"""绘图配置共享的枚举类型。"""

from typing import Literal

NovelAIModelId = Literal[
    "nai-diffusion-5-full",
    "nai-diffusion-5-curated",
    "nai-diffusion-4-5-full",
    "nai-diffusion-4-5-curated",
    "nai-diffusion-4-full",
    "nai-diffusion-4-curated-preview",
    "nai-diffusion-3",
    "nai-diffusion-furry-3",
]

QuotaPeriodMode = Literal["daily", "weekly", "monthly", "once"]

ReviewModelTask = Literal["replyer", "planner", "vlm"]

ProxyScheme = Literal["http", "https"]

CommandReplyMode = Literal["图片", "文本"]

ComfyUIPromptMode = Literal["single_prompt", "positive_negative"]

NovelAIMode = Literal["anime", "furry", "background"]

AliyunImageInputMode = Literal["auto", "base64", "url"]

AliyunPromptExtendMode = Literal["direct", "agent"]

AliyunKlingResultType = Literal["single", "series"]

VolcengineResponseFormat = Literal["url", "b64_json"]

VolcengineSequentialMode = Literal["disabled", "auto"]
