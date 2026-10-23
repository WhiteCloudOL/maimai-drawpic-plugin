"""NovelAI 普通图片生成预设；不混入需要遮罩的 inpainting 专用模型。"""

# 官方未公开普通绘图模型目录接口，不能把文本模型接口当作图片目录。
# 2026-10-23 对照 https://docs.novelai.net/en/image/models/ 核对，V5 优先。
NOVELAI_DEFAULT_MODELS = (
    "nai-diffusion-5-full",
    "nai-diffusion-5-curated",
)
NOVELAI_PRESET_MODELS = NOVELAI_DEFAULT_MODELS + (
    "nai-diffusion-4-5-full",
    "nai-diffusion-4-5-curated",
    "nai-diffusion-4-full",
    "nai-diffusion-4-curated-preview",
    "nai-diffusion-3",
    "nai-diffusion-furry-3",
)
NOVELAI_PRESET_HINT = (
    "NovelAI 官方模型预设（2026-10-23 核对），不是在线接口结果；"
    "包含 V5、V4.5、V4、V3，实际权限以账号为准。可在同一列表中手动添加兼容服务的模型 ID。"
)
