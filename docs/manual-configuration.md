# 手动编辑插件配置

适合习惯使用文本编辑器、需要批量调整或备份配置的实例管理员。平台、通用设置和风格使用普通 **UTF-8 JSON 文件**，没有配置数据库；WebUI 与手动编辑修改的是同一份配置。

日常使用推荐工作台的下拉、勾选和宽高控件；本页说明不打开工作台时怎样编辑文件。平台能力与字段含义见[平台配置](platforms.md)，审核和缓存策略见[配置与数据](configuration.md)。

目录：[文件位置](#文件位置) · [编辑步骤](#编辑步骤) · [平台示例](#平台配置示例) · [通用与风格](#通用与风格示例) · [填写规则](#填写规则) · [恢复](#常见错误与恢复)

## 文件位置

路径以当前 MaiBot 实例授予的目录为准。常见默认位置如下：

| 文件 | 内容 |
| --- | --- |
| `data/plugins/maimai-drawpic-plugin/platforms.json` | 所有命名平台实例、连接信息、密钥与模型参数 |
| `data/plugins/maimai-drawpic-plugin/workspace_settings.json` | 通用参数、管理员、额度规则、审核与风格模板 |
| `data/plugins/maimai-drawpic-plugin/reference_assets/` | 持久参考图库索引和图片；由工作台管理，不属于临时图片缓存 |
| 插件目录内的 `config.toml` | 插件开关、代理、图片/日志/上传缓存容量 |

插件文件夹改名不会改变上面以插件 ID 命名的数据目录。先正常加载插件一次，让它创建配置；编辑已有文件比从零手写完整结构更方便。

任务、额度使用记录、迁移备份与临时图片是运行数据，不是平台配置入口。不要通过修改任务或额度记录来调整模型、平台参数。

## 编辑步骤

1. **结束正在修改配置的操作，并停止 MaiBot。** 也可在插件管理中卸载当前运行实例，确认已卸载后再编辑；不要仅把绘图开关设为关闭就开始改文件。
2. 将准备修改的两个 JSON 文件复制到安全位置备份。平台文件包含真实密钥，备份同样需要保护。
3. 使用文本编辑器，以 **UTF-8、无 BOM** 保存；只改需要调整的值。保留原文件的 `schema_version`、`revision` 与已有平台 `id`。
4. 重新启动 MaiBot，或重新加载插件，让插件校验并读取文件。**只刷新浏览器页面不会重新读取磁盘配置。**
5. 在工作台核对模型列表和参数，再发起新任务。手动修改不需要额外点击一次“保存平台”。

运行时的 WebUI 保存会检查外部修改，不会直接覆盖它；若提示“配置文件已在外部修改”，请先重新加载插件，再刷新工作台。不要为了跳过校验自行改修订号。

如果数据目录存在 `workspace_config_transaction.json`，说明有已提交配置等待同步。应先正常加载插件完成恢复，确认恢复完成后再停止并编辑；不要修改或删除这个内部事务文件。

## 平台配置示例

`platforms.json` 的顶层结构如下。此例用于展示格式；已有安装应保留自己的 ID、修订号和密钥，并按账号权限填写模型：

```json
{
  "schema_version": 1,
  "revision": 1,
  "providers": [
    {
      "id": "d13f4c4c267d4dcc889255d82ad20c01",
      "kind": "openai",
      "name": "日常创作",
      "config": {
        "enabled": true,
        "base_url": "https://api.openai.com/v1",
        "api_key": "在此填写自己的密钥",
        "models": ["gpt-image-2.5", "gpt-image-1"],
        "default_openai_compatibility_mode": "auto",
        "default_size": "1024x1024",
        "negative_prompt_enabled": false,
        "negative_prompt": "",
        "model_size_overrides": ["gpt-image-1=1024x1536"],
        "quality": "",
        "output_format": "",
        "extra_parameters": []
      }
    }
  ]
}
```

- `providers` 是平台实例列表；同一种 `kind` 可以出现多次，但名称须不区分大小写唯一，支持中英文且不能含空格。最多 40 个实例。
- `id` 是 32 位小写十六进制字符串。已有实例不要改；新建实例优先通过工作台生成 ID，再在文件中编辑。
- `kind` 支持 `openai`、`agnes`、`google`、`zhipu`、`minimax`、`aliyun`、`volcengine`、`siliconflow`、`novelai`、`comfyui`。
- `config` 是该平台类型的字段，不能把另一种平台的参数混入。省略的已知字段会使用该平台默认值；已有文件通常已写出完整字段。
- 每个实例的 `negative_prompt_enabled` 控制本次输入与默认反向词；开启后，`negative_prompt` 作为默认词追加并去重。NovelAI 默认开启，其余平台默认关闭。关闭时忽略调用方与默认反向词，风格预设自己的模板仍保留。启用 `rewrite_prompt_to_english` 的平台会在合并默认词和风格后改写最终反向词。
- ComfyUI 旧 `t2i_negative_prompt`、`i2i_negative_prompt` 继续按任务类型追加，与新的通用 `negative_prompt` 一起受实例开关控制。

ComfyUI 工作流文件默认放在 `MaiBot\data\plugins\maimai-drawpic-plugin\workflows`（`MaiBot` 为主程序根目录）。将文生图文件命名为 `t2i.json` 后，`t2i_workflow_path` 填写 `data/workflows/t2i.json`；图生图文件 `i2i.json` 对应 `i2i_workflow_path` 的 `data/workflows/i2i.json`。路径与文件位置对照见 [ComfyUI 平台说明](platforms.md#comfyui-本地工作流)。
- 模型列表仅填写真实模型 ID，不再使用 `别名=模型ID`；分辨率覆盖也使用真实模型 ID。
- NovelAI 同样只维护一个 `models` 列表，可混合官方预设与兼容服务自定义 ID；旧 `custom_models` 加载时合并去重，保存后移除此旧字段。
- 要在通用配置中指定模型，应使用工作台显示的完整名称，例如 `日常创作/gpt-image-2.5`。

平台名称参与完整模型引用。已有默认或备选模型引用时，建议在 WebUI 重命名平台，让插件一起更新相关引用；手动改名则必须同步检查通用配置中的模型引用。

### 按模型覆盖分辨率

文件中继续兼容现有的字符串列表，WebUI 会把这些条目显示成“模型下拉 + 尺寸选择”，不会要求用户在页面输入等号表达式。

```json
{
  "model_size_overrides": [
    "gpt-image-2.5=1024x1024",
    "gpt-image-1=1024x1536"
  ]
}
```

这是 `config` 内的**字段片段**，不是独立配置文件。OpenAI、硅基流动、NovelAI 常用 `宽x高`；百炼使用 `宽*高`，例如 `qwen-image-2.0=2048*2048`；火山引擎可使用支持的分辨率档位，例如 `模型ID=2K`。不要照搬到不支持对应尺寸的模型。

### 扩展参数的值类型

扩展参数中的 `negative_prompt`、`uc` 和 `v4_negative_prompt.caption.base_caption` 会作为旧版默认反向文本并入实例处理，受反向词开关、去重和英文改写控制，不再直接覆盖最终请求。实例关闭反向词时忽略这些内容。

NAI 兼容网关的旧版 UC 预设同样受实例反向词开关控制：关闭时不发送 `ucPreset`，包括扩展参数中的同名字段；开启时保留配置的 `uc_preset`，扩展参数中的 `ucPreset` 可覆盖该编号。官方 V3/V4/V5 模型不发送这个旧版字段。

NovelAI 实例支持 `v4_negative_prompt.caption.char_captions` 多角色反向词。开启实例反向词后，每个角色的 `char_caption` 分别去重，并按实例的英文改写设置处理；空角色占位、列表顺序、`centers` 坐标以及 `use_coords`、`use_order` 等标记会保留。全图默认词与风格词在 `base_caption` 中处理；不同角色之间分别保留词条。关闭实例反向词后忽略整个扩展反向结构，风格模板自己的全图反向内容继续生效。角色格式错误或改写失败时会报出角色序号，并在发送生成请求前终止任务。[NovelAI 字段结构](https://image.novelai.net/docs/index.html)

`extra_parameters` 以及百炼各模型族的 `*_extra_parameters` 只用于服务实际支持的扩展字段。以下仅展示类型写法，参数名为示意：

```json
{
  "extra_parameters": [
    "vendor_label=\"preview\"",
    "vendor_count=2",
    "vendor_enabled=false",
    "vendor_options={\"mode\":\"sample\"}"
  ]
}
```

对应文本、数字、布尔和 JSON 对象。**想传文本 `true` 或 `123` 时，值必须再带 JSON 双引号**，例如 `"vendor_label=\"123\""`；否则会被识别为布尔或数字。WebUI 的“文本”类型会处理这层引号，无需手动转义。

文件里的 `api_key` 是真实值：手动改成空字符串就会清空密钥。它不同于 WebUI 密钥框“留空保留”的交互规则。

### 硅基流动显式水印

硅基流动实例的 `config` 可填写以下**字段片段**，关闭 API 生成图上的显式「AI 生成」水印：

```json
{
  "watermark_enabled": false
}
```

默认是 `true`，已有配置未填写该字段时保持平台的默认水印行为。设置为 `false` 后，文生图和图生图均发送 HTTP 请求头 `X-Enable-Watermark: 0`；不是请求体参数，不能用 `extra_parameters` 代替。隐式水印仍保留；适用场景及最终输出标识要求见[硅基流动平台说明](platforms.md#硅基流动)。

### MiniMax 实例示例

在 `platforms.json` 的 `providers` 中添加平台时沿用已有记录的 ID 格式，实际操作推荐先通过工作台创建再编辑。以下仅展示 `config` 字段，密钥请自行填写，不使用任何共享测试密钥：

```json
{
  "enabled": true,
  "api_key": "填写自己的 MiniMax API Key",
  "base_url": "https://api.minimax.cn/v1",
  "models": ["MiniMax-H3-Image"],
  "size": "auto",
  "aspect_ratio": "",
  "area": "1K",
  "n": 1,
  "response_format": "url",
  "output_format": "jpeg",
  "output_compression": 95,
  "stream": false,
  "disable_prompt_enhanced": false,
  "aigc_watermark": false,
  "request_timeout_seconds": 600,
  "negative_prompt_enabled": false,
  "extra_parameters": []
}
```

此示例显式选择 1K；平台默认 `area` 为空，使用服务端默认 4K。H3、image-01 与 image-01-live 的字段差异、流式限制和其他参数见 [MiniMax 平台说明](platforms.md#minimax)。图片模型使用官方文档预设，不能通过仅返回文本模型的 `/v1/models` 获取。

## 通用与风格示例

`workspace_settings.json` 顶层同时包含 `general` 和 `style`。以下是一份最小结构示例，未列出的通用字段沿用默认值：

```json
{
  "schema_version": 2,
  "revision": 1,
  "settings": {
    "general": {
      "integration_api_enabled": true,
      "group_access_mode": "blacklist",
      "group_access_ids": [],
      "private_access_mode": "blacklist",
      "private_access_ids": [],
      "default_model": "",
      "fallback_models": [],
      "request_retry_count": 1,
      "request_timeout_seconds": 150,
      "skip_image_url_ip_check": false,
      "sync_generated_images_to_history": false,
      "admin_user_ids": [],
      "prompt_review_enabled": false,
      "prompt_review_model": "vlm",
      "prompt_review_timeout_seconds": 60,
      "prompt_review_retry_count": 2,
      "image_review_enabled": false,
      "image_review_model": "vlm",
      "image_review_timeout_seconds": 60,
      "image_review_retry_count": 2,
      "references": {
        "self_reference_enabled": false,
        "self_names": ["麦麦"],
        "self_reference_ids": [],
        "multi_reference_confirmed": false,
        "allow_chat_material_search": false,
        "allow_web_material_search": false
      }
    },
    "style": {
      "default_style": "水彩",
      "image_edit_presets_enabled": false,
      "default_image_edit_preset": "",
      "presets": [
        {
          "name": "水彩",
          "enabled": true,
          "description": "柔和的透明水彩质感",
          "preset_type": "text_to_image",
          "tags": ["水彩"],
          "apply_to_image_edit": false,
          "reference_bindings": [],
          "multi_reference_confirmed": false,
          "positive_prompt_template": "水彩，{prompt}",
          "negative_prompt_template": "水印，{negative_prompt}"
        }
      ]
    }
  }
}
```

常用字段：

- `integration_api_enabled`：默认 `true`，关闭后拒绝所有公开插件联动 API，工作台和聊天入口仍可使用；已受理任务继续执行。
- `group_access_mode`、`private_access_mode`：分别填 `blacklist`（默认）或 `whitelist`。空黑名单允许全部，空白名单禁止对应的群聊或私聊。
- `group_access_ids`、`private_access_ids`：分别填写群号和 QQ 号的字符串列表，如 `["123456789"]`；QQ 官方适配器填写对应群/用户 OpenID。无需会话哈希，私聊名单不影响群内成员。[完整规则](configuration.md#插件联动与黑白名单)。

- `sync_generated_images_to_history`：默认 `false`。开启后，成功投递到聊天的生成图通过 Host 同步到当前 MaiSaka 历史，视觉 Planner 可查看图片，文本 Planner 使用图片描述；可能增加视觉上下文与后台识图开销。未投递任务和命令回复卡片不请求同步，回执未知不重发。详见[同步范围与日志](configuration.md#生成图片与会话历史)。

- `default_model`：空字符串表示自动选择；指定时填写完整“平台名/模型名”。
- `fallback_models`：有顺序的模型名称列表，空列表表示不启用备选。
- `request_retry_count`：每模型额外重试次数，默认 1，可选 0～5；不是遇到任何失败都重新绘图。审核配置在界面中独立成标签页，文件中的字段仍在 `general` 下。
- `request_timeout_seconds`：单次平台尝试的超时预算，不是任务整体的永久等待时间。
- `skip_image_url_ip_check`：默认 `false`。仅在可信内网图床或 TUN/Fake-IP 等特殊 DNS 环境需要时设为 `true`；手动/系统代理会自动保留域名交由代理解析，详见[图片下载说明](configuration.md#请求与安全边界)。
- `prompt_review_model`、`image_review_model`：分别选择提示词和图片审核使用的宿主任务组，均默认 `vlm`，还可填 `replyer` 或 `planner`；图片审核必须使用支持图片输入的模型。
- `prompt_review_timeout_seconds`、`image_review_timeout_seconds`：分别控制两类审核单次尝试的最长等待时间，单位秒，均默认 60，范围 5～600；与图片生成超时独立，审核提前完成即继续。
- `prompt_review_retry_count`、`image_review_retry_count`：分别控制两类审核失败后额外重试的次数，默认 2，范围 0～5；0 表示关闭。明确拒绝或取消不重试，图片审核重试不重新生图。
- `admin_user_ids`：字符串列表，例如 `["12345678"]`；不同适配器的用户 ID 形式可能不同。
- `image_edit_unsupported_models`、`text_to_image_unsupported_models`：人工限制的模型列表；优先使用工作台中的完整模型名称。
- `presets`：绘图预设列表；保留 `{prompt}`、`{negative_prompt}` 来代入本次描述和反向词。旧预设缺少新字段时按文生图预设读取。
- `default_style`：默认文生图预设名称；应对应已启用的 `text_to_image` 预设。空字符串表示不设置默认项。
- `image_edit_presets_enabled`：图生图预设总开关，默认 `false`。关闭时新入口的图生图不使用任何预设；不影响图生图本身和自我参考。
- `default_image_edit_preset`：默认图生图预设名称；留空时，只有默认文生图预设已勾选 `apply_to_image_edit` 才可继承。
- `preset_type`：`text_to_image` 只能保存文字模板；`image_to_image` 可以绑定真实参考图片，不再使用 `apply_to_image_edit`。
- `apply_to_image_edit`：文生图预设是否也适用于图生图，默认 `false`；同时受图生图总开关控制。
- `tags`：用于固定匹配的 tag 列表。显式选择优先，其次 tag，最后当前模式的默认项；同次只使用一个预设。

### 参考与素材字段

`general.references` 是“偏好与预设 → 参考与素材”的持久设置。以上示例保留所有新功能关闭状态：

- `self_reference_enabled`：开启后才允许使用机器人自身图库；`self_names` 填当前机器人的名称、别称，供原始请求的自身指向识别使用。
- `self_reference_ids`：留空时按 tag 从自我图库选一张，无命中时使用默认图。指定单张可固定形象；多张应通过工作台选择和确认。
- `allow_chat_material_search`、`allow_web_material_search`：两个独立开关，默认均为 `false`。聊天只检索当前真实聊天流，网络通过宿主统一搜索服务获取真实候选后再识别。外部 v2 调用还须逐次选择来源，见 [API 文档](integration.md#参考与素材选项)。
- `multi_reference_confirmed`：记录管理员在工作台 dialog 中确认当前多图配置；不表示插件已经探测到模型支持多图，也不能绕过图生图能力与图片数量限制。不要通过手动设为 `true` 代替确认。

图生图预设的 `reference_bindings` 是图片用途列表，例如下方**字段片段**。`asset_id` 必须从工作台上传后的预设图片中选择，不是路径、URL 或 Base64：

```json
{
  "preset_type": "image_to_image",
  "apply_to_image_edit": false,
  "reference_bindings": [
    {
      "asset_id": "由工作台生成的图片ID",
      "role": "scene",
      "subject_id": "海边场景",
      "note": "继承夕阳和背景，不继承图中人物"
    }
  ],
  "multi_reference_confirmed": false
}
```

`role` 可填 `identity`、`clothing`、`scene`、`lighting`、`composition`、`base`。多图以及单张预设图与其他输入合用，需要在工作台确认服务商模型支持多图参考。更改图片组合后重新确认。

图库索引、默认图和图片版本由工作台原子写入。请通过图库上传、替换、排序、设默认和删除，不直接编辑 `reference_assets/index.json` 或替换其图片文件；直接改动可能使内容校验不匹配。图库图片不会随上传或生成缓存过期而自动删除，总上限为 100 张、128 MiB；备份时连同整个目录一起备份。

仅修改普通绘图设置时，保留原文件已有的审核模板、管理员及额度规则；不要把示例整体覆盖到正在使用的配置上。

## 填写规则

- JSON 字段名与文本必须用英文双引号。开关是 `true` / `false`，数字不加引号，列表使用 `[]`。
- 不支持注释、尾随逗号、重复字段、`NaN` 或 `Infinity`。多行提示词在字符串中写成 `\n`；使用支持 JSON 的编辑器更方便。
- 不增加未知字段；字段名区分大小写。平台 ID、类型、修订号和文件版本属于结构字段，不用手动递增来让修改生效。
- 除 JSON 文件结构外，参数范围仍由平台与插件校验；手动编辑不会绕过模型能力、源图限制或审核。
- 插件开关、代理和缓存容量继续写在 `config.toml` 的 `plugin` / `proxy` 节，或在 MaiBot 插件配置页修改；不要移进这两个 JSON 文件。

## 常见错误与恢复

- **加载提示 JSON 格式错误**：检查引号、转义、括号和尾随逗号。插件会保留原件，不会用空配置掩盖错误；可恢复刚才的备份后再加载。
- **提示未知字段或版本不受支持**：核对是否把字段放错平台，或误改了 `schema_version`。不要删除版本字段。
- **提示外部修改冲突**：停止 WebUI 保存，重新加载插件读取手动编辑的文件，再刷新页面。
- **提示与旧 TOML 冲突**：按[升级迁移与冲突恢复](configuration.md#升级迁移与冲突恢复)选择要保留的数据，先备份再处理，勿直接覆盖两边。
- **工作台能看到模型但绘图失败**：配置可读取不代表账号开通了该模型。检查模型权限、地址和尺寸支持范围，再查看脱敏日志。

相关文档：[平台配置](platforms.md) · [配置、审核与缓存](configuration.md) · [工作台使用](usage.md) · [返回 README](../README.md)。
