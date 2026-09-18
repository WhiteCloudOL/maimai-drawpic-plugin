# AGENTS.md

## 本插件开发注意事项

- 本目录是独立插件仓库；提交、状态检查和 diff 优先使用 `git -C plugins/maimai-drawpic-plugin ...`。
- 不要修改 MaiBot 主程序代码来绕过插件问题；确实需要主程序改动时先说明原因并请求许可。
- 配置变更只改插件配置模板与配置模型；新增配置字段时同步提升 `config_version`。
- `models/` 只存放模型能力、任务约束与参数构造等纯定义；`providers/` 只存放平台鉴权、传输、轮询、响应解析和图片下载适配器，不要把模型注册表放入平台适配器目录。
- 强制绘图命令必须严格区分模式：`/绘图 文生图` 检测到同条消息或引用消息中有真实图片时要提示改用图生图；`/绘图 图生图` 找不到真实源图时要提示补充图片，不能降级为文生图。
- 后台任务提交层也必须校验图生图能力；不支持图生图的平台或模型要在创建 task 与扣额度前拒绝，并返回明确原因。
- 文生图/图生图能力判断统一走 `ProviderRouter` 的模型任务能力接口；不要在各入口散写 `provider != ...` 之类的分支。
- 某些平台整体不支持图生图时在路由层内置原因；具体模型优先自动识别，也允许通过 `[general].image_edit_unsupported_models` 与 `[general].text_to_image_unsupported_models` 人工覆盖，不要等上游接口报错。
- 日志要能定位任务链路：提交、开始执行、能力拒绝、审核失败、平台失败、发送成功至少包含 `task_id`、`task_type`、`provider`、`model`、`source_image_count` 等关键字段。
- 日志严禁输出 API Key、Authorization、完整 Base64、带查询参数的签名 URL；上游错误应保留 HTTP 状态、业务错误码、脱敏 URL、request_id 与耗时。
- 源图处理必须校验真实图片 Base64，同时保留适配器给出的原始 HTTP(S) URL；不要把图片描述文本当作源图传入。
- 智谱图片接口默认模型为 `glm-image`；请求必填字段为 `model`、`prompt`，可选字段为 `quality`、`size`、`watermark_enabled`、`user_id`，并保留 `extra_parameters` 供用户自定义。不要重新加入当前官方接口未声明的 `response_format` 或旧 `user` 字段。
- 智谱当前模型列表没有 Z-Image；插件中的 `z-image-turbo` 属于阿里百炼平台。维护智谱适配时不要误删或混用阿里百炼的 Z-Image 模型及参数。
- 阿里云支持范围为 Qwen Image、Z-Image、可灵图像和 Vidu 图像；当前明确不接入万象、创意工具、图像翻译与视频生成。变更范围时应同步更新模型注册表、能力测试和 README。
- 阿里云 `base_url` 必须来自配置且以 `/api/v1` 结尾；不要硬编码用户工作空间地址。可灵/Vidu 图生图必须使用适配器原图 URL，Qwen 默认保持 Base64。
- 文档与 README 要同步用户可见行为，尤其是命令语义、配置项、版本号和不支持图生图时的处理方式。
- `core/config.py` 新增或重命名配置节、配置字段时，必须同步维护 `core/config_i18n.py` 的英语、日语和韩语 Schema 文案，并运行配置 i18n 覆盖测试；简体中文保留为默认文案和回退语言。
- 提交前至少运行 AST/compileall 与 `git diff --check`；本插件通常可用 `PYTHONPYCACHEPREFIX=/private/tmp/maimai_drawpic_pycache python3 -m compileall -q plugins/maimai-drawpic-plugin` 避免写入用户缓存目录。
