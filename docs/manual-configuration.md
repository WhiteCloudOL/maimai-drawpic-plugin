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
- `kind` 支持 `openai`、`agnes`、`google`、`zhipu`、`aliyun`、`volcengine`、`siliconflow`、`novelai`、`comfyui`。
- `config` 是该平台类型的字段，不能把另一种平台的参数混入。省略的已知字段会使用该平台默认值；已有文件通常已写出完整字段。
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

## 通用与风格示例

`workspace_settings.json` 顶层同时包含 `general` 和 `style`。以下是一份最小结构示例，未列出的通用字段沿用默认值：

```json
{
  "schema_version": 2,
  "revision": 1,
  "settings": {
    "general": {
      "default_model": "",
      "fallback_models": [],
      "request_retry_count": 1,
      "request_timeout_seconds": 150,
      "admin_user_ids": [],
      "prompt_review_enabled": false,
      "image_review_enabled": false
    },
    "style": {
      "default_style": "水彩",
      "presets": [
        {
          "name": "水彩",
          "enabled": true,
          "description": "柔和的透明水彩质感",
          "positive_prompt_template": "水彩，{prompt}",
          "negative_prompt_template": "水印，{negative_prompt}"
        }
      ]
    }
  }
}
```

常用字段：

- `default_model`：空字符串表示自动选择；指定时填写完整“平台名/模型名”。
- `fallback_models`：有顺序的模型名称列表，空列表表示不启用备选。
- `request_retry_count`：每模型额外重试次数，默认 1，可选 0～5；不是遇到任何失败都重新绘图。审核配置在界面中独立成标签页，文件中的字段仍在 `general` 下。
- `request_timeout_seconds`：单次平台尝试的超时预算，不是任务整体的永久等待时间。
- `admin_user_ids`：字符串列表，例如 `["12345678"]`；不同适配器的用户 ID 形式可能不同。
- `image_edit_unsupported_models`、`text_to_image_unsupported_models`：人工限制的模型列表；优先使用工作台中的完整模型名称。
- `presets`：风格模板列表。默认风格名称应对应一个已启用风格；保留 `{prompt}`、`{negative_prompt}` 来代入本次描述和反向词。

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
