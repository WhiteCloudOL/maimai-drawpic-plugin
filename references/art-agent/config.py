"""绘图编排层 · 配置模型

只做三件事：判定通道、取参考图、把请求转给下游插件。
🔴 本插件**不接任何模型端点**，所以不会新增生图费用。
"""

from typing import List

from maibot_sdk import Field, PluginConfigBase


class PluginSection(PluginConfigBase):
    """插件开关"""

    __ui_label__ = "插件"
    __ui_order__ = 0

    name: str = Field(default="art_orchestrator", description="插件名称")
    version: str = Field(default="0.2.0", description="插件版本")
    config_version: str = Field(default="1.0.0", description="配置版本")
    enabled: bool = Field(default=True, description="是否启用")


class LanesSection(PluginConfigBase):
    """三条通道开关"""

    __ui_label__ = "通道"
    __ui_order__ = 1

    self_lane: bool = Field(
        default=True,
        description="她自己出镜 → 图生图引擎（人物形象图+可选会话图，按引擎计价）",
    )
    illustration: bool = Field(
        default=True,
        description="纯插画 → maimai-drawpic 的 draw（不单独计费）",
    )
    reference: bool = Field(
        default=True,
        description="参考图改编 → maimai-drawpic 的 edit_image（不单独计费）",
    )
    cast: bool = Field(
        default=True,
        description="画面里全是别人（不含她自己）→ 按每个角色的参考图出图（按引擎计价）",
    )


class LimitsSection(PluginConfigBase):
    """额度与超时"""

    __ui_label__ = "额度"
    __ui_order__ = 2

    daily_self_max: int = Field(
        default=2,
        ge=0,
        le=100,
        description="self 通道（画她自己）每日出图上限。0 = 不限",
    )
    daily_reference_max: int = Field(
        default=3,
        ge=0,
        le=100,
        description="reference 通道（带参考图生成）每日出图上限。0 = 不限",
    )
    submit_timeout_seconds: float = Field(
        default=20.0,
        gt=1.0,
        le=60.0,
        description="提交下游任务的最长等待（秒）。只等受理，不等出图",
    )
    daily_cast_max: int = Field(
        default=2,
        ge=0,
        le=100,
        description="cast 通道（画别人，不含她自己）每日出图上限。0 = 不限",
    )
    max_companions: int = Field(
        default=3,
        ge=1,
        le=4,
        description="多人合照时除她自己外最多再画几个角色（每多一人多一次搜图与审核）",
    )
    refs_per_subject: int = Field(
        default=2,
        ge=1,
        le=3,
        description=(
            "每个角色最多用几张搜来的参考图（不同角度/全身与细节）。"
            "一次只出一张图，多张参考图是为了让模型看清侧面、背面和细节；"
            "1 = 只用一张立绘（最省）"
        ),
    )


class ReferenceSection(PluginConfigBase):
    """参考图来源"""

    __ui_label__ = "参考图"
    __ui_order__ = 3

    chat_recent_fallback: bool = Field(
        default=True,
        description="当前消息没有图时，是否回退到最近 20 条里唯一一张图",
    )
    download_max_bytes: int = Field(
        default=8 * 1024 * 1024,
        ge=1024 * 100,
        le=64 * 1024 * 1024,
        description="外链参考图体积上限（字节）",
    )
    download_timeout_seconds: float = Field(
        default=20.0,
        gt=1.0,
        le=120.0,
        description="外链参考图下载超时（秒）",
    )
    allowed_hosts: List[str] = Field(
        default_factory=list,
        description="只允许这些域名。留空 = 允许任意公网 http/https",
    )


class SelfChannelSection(PluginConfigBase):
    """self 通道判定词"""

    __ui_label__ = "她自己判定"
    __ui_order__ = 4

    keywords: List[str] = Field(
        default_factory=lambda: [
            "自拍",
            "画你",
            "画她自己",
            "你的样子",
            "你穿",
            "你的照片",
            "来张你的",
            "你的自画像",
            "selfie",
        ],
        description="命中且未要求参考图时走 self 通道。宁窄勿宽：误判多花钱，漏判只是走 按引擎计价插画",
    )


class IntentSection(PluginConfigBase):
    """意图判别（LLM 优先，关键词兜底）"""

    __ui_label__ = "意图判别"
    __ui_order__ = 5

    use_llm: bool = Field(
        default=True,
        description="画图请求先让内部小模型判通道，失败再回退关键词规则",
    )
    model_task: str = Field(
        default="utils",
        description="判别用的宿主任务名。utils 走 deepseek-flash，按模型计价，计入 llm_usage 账本",
    )
    timeout_seconds: float = Field(
        default=12.0,
        gt=1.0,
        le=60.0,
        description="判别超时（秒）。超时不重试，直接回退关键词规则",
    )
    prompt: str = Field(
        default=(
            "你是绘图意图判别器。根据用户请求判断走哪条绘图通道、画面里有哪些人物，只输出 JSON。\n"
            "\n"
            "四条通道：\n"
            "- self：画面里有她自己（主角色本人）。包括自画像、自拍、「画你/画你自己/你的样子/你穿……」，"
            "以及「照着这张图画你自己」——即使带图，目标仍是把她自己画进画面。\n"
            "- reference：用户给了一张图，要以图中的人/物/场景/风格为素材作画，但主角不是她自己。"
            "例如画图中的人物、改图、换背景、照着图画别的角色、模仿图中画风。\n"
            "- illustration：没有参考图，按文字描述画一幅画，与她本人无关；也包括她主动说要给你画点什么"
            "（「我给你画个小猫」「随手涂鸦」「画个简笔画」）。\n"
            "- cast：画面里全是具体已有的角色（有名字、有立绘），没有她自己。"
            "例如「画甘雨和刻晴打牌」「给我画个胡桃」「画刻晴和甘雨背靠背」。这些角色有固定形象，要搜参考图，不能当随手画。\n"
            "\n"
            "判定原则：\n"
            "1. 先看画面里有没有她：有她 → self；没有她 → 看有没有具名角色：有 → cast；没有 → 带图选 reference、无图选 illustration。\n"
            "2. 「画我和 X 一起 / 合照 / 合影」→ self，subjects 里把两个人都列出来。\n"
            "3. 出现「画你」类词时看整体语义：指她本人 → self；明确说画图中某人或别的角色，措辞再像也走 reference。\n"
            "4. 语义模糊拿不准：带图选 reference，无图选 illustration。\n"
            "5. 她说「随手画 / 涂鸦 / 给你画一个」属于她主动画的小画 → illustration（插画通道，水墨风）；"
            "但点名要画某个具体角色（「给你画个甘雨」）仍走 cast。\n"
            "6. 「画我和 X 一起」和「画 X 和 Y 一起」是两件事：前者 self，后者 cast。\n"
            "\n"
            "subjects：画面里每个主要人物一项，合照就写 2~4 项，按从左到右或主次排序。\n"
            "- who：人物名，她自己写「主角色」；\n"
            "- kind：她自己填 self，其他角色填 character；\n"
            "- query：其他角色填搜参考图的关键词，写法「角色名 立绘」，不要堆「服装」「全身」「设定图」"
            "——关键词越长命中越少；她自己留空。\n"
            "风景、物件、抽象画就输出空数组。\n"
            "\n"
            "relation：一句话写清人物之间的站位与动作（如「并排站着看向镜头」「她从后面搂着小鱼肩膀」），"
            "单人就留空。优先写具体姿势、谁在前谁在后、有没有肢体接触。\n"
            "layout：构图取景，三选一：portrait（竖构图，单人全身或半身）、landscape（横构图，两人以上横向排开或需要场景）、"
            "square（拿不准或单人特写）。两人以上默认 landscape。\n"
            "outfit_query：她一个人穿某角色的服装（cos）时填「角色名 立绘」；有 subjects 多人时留空。\n"
            "search_query：单人场景要出现某个已有角色/实物时填关键词；多人已写进 subjects 时留空。\n"
            "\n"
            '只输出：{"lane":"self","reason":"一句话理由","relation":"","subjects":[],'
            '"layout":"square","outfit_query":"","search_query":""}，'
            "lane 只能是 self / reference / illustration / cast。"
        ),
        description="LLM 判别提示词。改动即时生效（配置热重载），改坏会自动回退关键词规则",
    )


class ArkEngineSection(PluginConfigBase):
    """火山图生图引擎（Seedream）直连引擎"""

    __ui_label__ = "引擎 · 火山图生图引擎"
    __ui_order__ = 6

    enabled: bool = Field(default=True, description="是否启用这条引擎")
    base_url: str = Field(
        default="https://ark.cn-beijing.volces.com/api/v3",
        description="图生图引擎端点。地址已带 /vN 版本段，插件不会再多加一层 /v1",
    )
    api_key: str = Field(
        default="",
        description="留空则自动读取写真插件的 config.toml，不用重复填",
    )
    model: str = Field(
        default="doubao-seedream-5-0-flash-260915",
        description="主模型：按引擎计价，输入图不计费，支持单图与多图参考",
    )
    fallback_model: str = Field(
        default="doubao-seedream-4-0-20260415",
        description="兜底模型：仅当主模型被版权审核拦截时切换，按引擎计价",
    )
    max_references: int = Field(default=8, ge=1, le=10, description="单次最多参考图张数")
    price: float = Field(default=0.12, ge=0.0, le=10.0, description="主模型单价，仅用于统计")
    fallback_price: float = Field(default=0.20, ge=0.0, le=10.0, description="兜底模型单价，仅用于统计")
    request_timeout_seconds: float = Field(
        default=180.0, gt=10.0, le=600.0, description="单次出图最长等待（秒）"
    )


class SearchSection(PluginConfigBase):
    """联网搜参考图 + 视觉审核（agent 式：搜 → 看 → 选）

    只在「画面主语是具体已有的东西、且用户没给图」时启用；搜到的图先交给
    ``review_task`` 指定的视觉模型逐张打分，合格才作为参考图。全部失败就
    退回原有通道，不阻塞绘图。
    """

    __ui_label__ = "联网搜图"
    __ui_order__ = 13

    enabled: bool = Field(default=True, description="是否允许自动搜参考图")
    provider: str = Field(
        default="auto",
        description=(
            "数据源：auto = 先图片搜索、没结果再走 DeepSeek 网页搜索；"
            "image_search = 只用 360 图片搜索；ds_web = 只用 DeepSeek 网页搜索（对新角色更准）"
        ),
    )
    api_plugin: str = Field(
        default="example.image-search", description="提供候选接口的插件 id"
    )
    api_operation: str = Field(
        default="search_image_candidates", description="候选接口名（只返回链接，不下载）"
    )
    max_candidates: int = Field(
        default=6, ge=1, le=12, description="每轮取多少个候选链接"
    )
    max_review: int = Field(
        default=4, ge=1, le=6, description="每轮最多下载几张交给视觉模型审核"
    )
    review_task: str = Field(
        default="vlm",
        description="审核用的宿主模型任务名（必须是宿主已有的任务，如 vlm / utils）",
    )
    review_model: str = Field(
        default="deepseek-flash-vision",
        description="审核具体用哪个模型（直选，覆盖任务默认模型）。该模型已关闭思考",
    )
    review_max_tokens: int = Field(
        default=1200, ge=200, le=4000, description="审核输出上限；正文为空时会翻倍重试一次"
    )
    review_timeout_seconds: float = Field(
        default=25.0, gt=1.0, le=120.0, description="单次审核超时（秒）"
    )
    download_timeout_seconds: float = Field(
        default=12.0, gt=1.0, le=60.0, description="候选图下载超时（秒）"
    )
    download_max_bytes: int = Field(
        default=6 * 1024 * 1024,
        ge=1024 * 100,
        le=32 * 1024 * 1024,
        description="单张候选图体积上限（字节）",
    )
    min_score: int = Field(
        default=3, ge=0, le=5, description="审核通过的最低吻合度（0-5）"
    )
    min_edge: int = Field(
        default=500,
        ge=0,
        le=4000,
        description="候选图最短边门槛（像素），太小的资讯横幅对服装参考没价值",
    )
    ds_web_max_pages: int = Field(
        default=4,
        ge=1,
        le=8,
        description="ds_web 数据源最多抓几个网页（每个页面取前几张图）",
    )
    fallback_suffix: str = Field(
        default="全身",
        description="第一轮全部不合格时，第二轮在原关键词后面补的限定词；留空 = 不重试",
    )


class SelfPromptsSection(PluginConfigBase):
    """self 通道预设（从写真插件提取，可在 config.toml 直接编辑）

    拼装顺序：request → identity → style → avoid；带参考图时再补 ref_*_hint。
    """

    __ui_label__ = "自画像预设"
    __ui_order__ = 7

    identity: str = Field(
        default="出镜人物固定为主角色本人。【此处填写你自己角色的正面外貌设定，只写「是什么」，不写「不是什么」；身份一致性主要由人物基准参考图承载。参考实现里该段原为角色专属设定，已占位。】",
        description="人物固定身份特征：只写正面事实；否定句会被画面模型抓成画面元素",
    )
    style: str = Field(
        default=(
            "画风必须与人物参考图一致：精致的二次元动漫插画风格，全图（含手部、皮肤、衣物、家具、道具）"
            "统一为 2D 插画：清晰线稿、赛璐璐平涂上色，不要照片质感、真实皮肤纹理、真实织物细节或摄影景深虚化。"
            "画面任何时候都必须清晰可见：夜晚或暗光场景必须有灯光、屏幕光等光源照亮人物面部，"
            "严禁剪影、严禁逆光死黑、严禁画面过暗。构图自然生活化，避免商业海报排版与过度磨皮。"
        ),
        description="画风与画面质量约束（源自 photo_system 风格句）",
    )
    scene_hint: str = Field(
        default=(
            "画面里的人怎么站、什么表情、彼此怎么互动，你自己按这句请求的情境判断着写，写具体一点："
            "这一刻该是什么神态、手在做什么、看向谁，都替画面定下来。"
            "只交代「在哪、穿什么、做什么」是不够的，那样画出来的人会空着一张脸摆在那里。"
            "请求里已经写明了的，以请求为准。"
        ),
        description="开放式引导：动作、表情、互动交给模型自行按情境判断（2026-11-11 改）",
    )
    avoid: str = Field(
        default="",
        description=(
            "默认留空：Seedream 无独立负面词参数，负面清单会拼进 prompt 尾部并被画面模型当成画面元素。"
            "身份特征请写进 identity 的正面描述；不要往这里加「不要画活鸟」之类的句子。"
        ),
    )
    ref_person_hint: str = Field(
        default="参考图说明：本次参考图是人物形象基准，必须保持同一个人、同一画风。",
        description="只有人物形象参考图时的参考图说明",
    )
    ref_combo_hint: str = Field(
        default=(
            "参考图说明：第一张是「本次造型基准」，人物长相与服装都以它为准；"
            "最后一张是本次画面参考，姿势、构图与场景氛围按它来改，但服装不要被它带偏。"
        ),
        description="人物形象图 + 会话参考图时的参考图说明",
    )
    edit_hint: str = Field(
        default=(
            "这一版是在上一版成品上改：最后一张是上一版成品，以它当底图，"
            "人物长相、发型、服装、场景、光线和构图都保持原样，只改本次说明里提到的那部分；"
            "上一版如果有手部、比例、五官画歪的地方，顺手一起修正，没提到的不要动。"
        ),
        description="按上一版成品继续改图时的参考图说明，替代 ref_combo_hint",
    )
    ref_mood_hint: str = Field(
        default=(
            "参考图里标着「氛围参考」的图只取服装款式与整体气氛，"
            "它自带背景（场景、光影、道具）不要照搬。"
        ),
        description="传入 role:mood 氛围参考图时追加的说明",
    )
    outfit_hint: str = Field(
        default=(
            "参考图说明：第一张是「本次造型基准」，人物长相、发型、瞳色、体型以她为准；"
            "后面的都是同一套「服装参考」，可能有好几张（全身、侧背面、头饰与纹样细节），"
            "把它们的服装（剪裁、主色搭配、纹样、鞋靴、头饰、标志性道具）整体换到第一张的人物身上，"
            "并按她的体型调整穿着效果。多张服装参考是同一套衣服的不同角度，不要把它们当成几套不同的衣服。"
            "只取后面几张的服装，不要采用它们任何一张的脸、五官或发型；"
            "发色保留第一张的设定，可以佩戴服装参考里的头饰、尽量还原它的发型。"
        ),
        description="换装（cos 某角色的服装）时的参考图说明，替代 ref_combo_hint",
    )
    group_hint: str = Field(
        default=(
            "多人合照说明：参考图按顺序对应画面里的人物，同一位角色可能连着给好几张。"
            "每个人的长相、五官、发色、瞳色、体型只认自己名下的参考图，"
            "绝不要把两个人的脸、发型或服装混在一起，也不要让两个人长得像同一个人；服装各穿各的，不要互换。"
            "同一位角色名下的多张图是同一套外形和服装的不同角度、全身与细节，只用来把造型看全，"
            "画面里这个人仍然只出现一次，不要按参考图张数画成几个人。"
            "画面里每个角色都必须出现，但不要求人人正面站直：可以搂肩、拥抱、牵手、前后错位、"
            "一人侧身或背对镜头、互相遮挡一部分，按人物关系自然摆姿势；"
            "不要因为遮挡或角度就少画一个人。"
        ),
        description="多人合照（她 + 其他角色）时的参考图说明，优先于 outfit_hint / ref_combo_hint",
    )
    cast_hint: str = Field(
        default=(
            "角色参考图说明：参考图按顺序依次对应画面里的每个角色，同一位角色可能连着给好几张。"
            "每个角色的长相、五官、发色、瞳色、体型和服装只认自己名下的参考图，"
            "不要把不同角色的特征混在一起，也不要让他们长得像同一个人。"
            "同一位角色名下的多张图是同一套造型的不同角度和细节，只用来把外形看全，"
            "画面里这个人仍然只出现一次。"
            "画面里每个角色都必须出现，可以搂肩、并肩、前后错位、一人侧身或背对镜头、互相遮挡一部分，"
            "按人物关系自然摆姿势，不要因为遮挡或角度就少画一个人。"
        ),
        description="cast 通道（画面里全是别人、没有她自己）的参考图说明",
    )
    cast_avoid: str = Field(
        default="文字、水印、logo、重复人物、畸形手指、海报排版、真人照片质感",
        description="cast 通道负面词。⚠️ 不要加主角色专属的「汉服/古风/民族服饰」，原神角色本来就需要这些",
    )


class IllustrationSection(PluginConfigBase):
    """手绘画（聊天里的随手涂鸦）——固定插画通道 + 水墨风

    她随口说「给你画个小猫」这类请求不追求精细，走 drawpic（不单独计费），画风统一为
    写意水墨，与 ark 那条精致二次元（self / reference）明确分开。
    """

    __ui_label__ = "手绘画"
    __ui_order__ = 14

    enabled: bool = Field(default=True, description="插画通道是否拼水墨风格提示词")
    style: str = Field(
        default=(
            "画风固定为写意水墨小品：宣纸质感，墨色分出浓淡干湿，线条简练带笔锋，"
            "留白充足，可以少量淡彩点染；不要厚涂、不要赛璐璐平涂、不要 3D、不要照片写实。"
        ),
        description="插画通道固定追加的画风约束（插画通道专用）",
    )
    avoid: str = Field(
        default="厚涂、赛璐璐平涂、日系厚线稿、3D 渲染、照片写实、油画、水印、文字、logo",
        description="水墨风格的负面词，拼在 prompt 尾部（插画引擎无独立负面词参数）",
    )


class WardrobeSection(PluginConfigBase):
    """造型库：只定义月份→季节，具体衣服全部在图库标签里。

    加一套新衣服 = 传图 + 打 outfit:/season:/scene:/role: 标签，不改这里也不改提示词。
    """

    __ui_label__ = "造型库"
    __ui_order__ = 8

    enabled: bool = Field(default=True, description="按季节挑选造型基准图")
    winter_months: list[int] = Field(
        default=[11, 12, 1, 2, 3],
        description="算作冬季的月份（重叠时冬季优先）",
    )
    summer_months: list[int] = Field(
        default=[6, 7, 8, 9],
        description="算作夏季的月份；其余月份按春秋处理",
    )
    scene_keywords: dict[str, str] = Field(
        default={
            "home": "宿舍,家里,家中,在家,室内,房间,床上,被窝,沙发,客厅,桌子前,书桌",
            "outing": "出门,外面,街上,路上,散步,食堂,超市,图书馆,教室,上课",
        },
        description="场景词→scene 标签：当季有多套造型时按请求里的场景词挑对应 scene",
    )
    max_assets: int = Field(
        default=20,
        description="人物图库最多放几张（每套造型占 2~3 张）",
    )


class EnginesSection(PluginConfigBase):
    """通道 → 引擎 的映射

    能力声明是硬约束：不接受参考图的引擎永远不会拿到源图。
    宁可直接拒绝，也不把图塞给只会文生图的模型——那会静默丢图，
    接口照样返回成功，只是画出来的东西跟参考图毫无关系。
    """

    __ui_label__ = "引擎"
    __ui_order__ = 5

    self_engine: str = Field(
        default="ark",
        description="self 通道引擎：ark（人物形象图+可选会话图一起图生图）/ maitu（旧写真插件，只吃人物库）",
    )
    illustration_engine: str = Field(
        default="drawpic",
        description="illustration 通道引擎：drawpic（不单独计费，右下角带 AI 水印）/ ark（0.12，无水印）",
    )
    reference_engine: str = Field(
        default="ark",
        description="reference 通道引擎：只允许真正支持参考图的引擎（ark）",
    )
    ark: ArkEngineSection = Field(default_factory=ArkEngineSection)


class ArtAgentConfig(PluginConfigBase):
    """顶层配置"""

    plugin: PluginSection = Field(default_factory=PluginSection)
    lanes: LanesSection = Field(default_factory=LanesSection)
    limits: LimitsSection = Field(default_factory=LimitsSection)
    reference: ReferenceSection = Field(default_factory=ReferenceSection)
    self_channel: SelfChannelSection = Field(default_factory=SelfChannelSection)
    intent: IntentSection = Field(default_factory=IntentSection)
    self_prompts: SelfPromptsSection = Field(default_factory=SelfPromptsSection)
    search: SearchSection = Field(default_factory=SearchSection)
    illustration: IllustrationSection = Field(default_factory=IllustrationSection)
    wardrobe: WardrobeSection = Field(default_factory=WardrobeSection)
    engines: EnginesSection = Field(default_factory=EnginesSection)
