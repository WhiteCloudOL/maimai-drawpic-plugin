<div align="center">

<img src="assets/icon.png" alt="麦麦绘图插件图标" width="128" height="128">

# 麦麦绘图

![Plugin Version](https://img.shields.io/badge/Plugin-2.2.1-informational.svg) ![MaiBot](https://img.shields.io/badge/MaiBot-1.3.19%E2%80%931.4.99-blue.svg) ![MaiBot Plugin SDK](https://img.shields.io/badge/Plugin%20SDK-2.20.0%E2%80%932.22.1-blueviolet.svg) ![License](https://img.shields.io/badge/License-AGPL--3.0-green.svg)

**❤️为 MaiBot 提供多平台聚合绘图能力，内置现代化 WebUI 工作台与聊天指令支持❤️**

</div>

- **双端交互支持**：支持聊天指令与可视化 WebUI 双向操作，自由输入提示词、上传参考图并切换画风预设
- **多平台灵活管理**：支持多平台及同平台多实例配置，密钥、地址、参数完全独立，支持首选模型与按序备用切换
- **任务看板与排查**：后台异步执行，支持随时切页查询进度、浏览原图与失败日志，大图生成无需死守页面
- **精细化控制与模板**：可视化配置群聊／私聊额度、内容审查规则与黑白名单，内置风格模板支持一键复用
- **开箱即用的联动 API**：提供统一的任务调用接口与独立 `DrawingClient` 实现，方便第三方插件快速接入，详见[插件联动](./docs/integration.md)

## 🩷 问题反馈&功能建议
| 方式 | 联系 |
| :--: | :--: |
| Github Issue | [跳转](https://github.com/WhiteCloudOL/maimai-drawpic-plugin/issues) |
| QQ群 | [637174573](https://qm.qq.com/q/3f2bdkDsyW) |


## ✨ 工作台预览

![麦麦绘图插件扩展WebUI](assets/previews/workspace-desktop.png)

<details>
<summary>📱 查看移动端预览</summary>

<img src="assets/previews/workspace-mobile.png" alt="麦麦绘图移动端工作台" width="390">

</details>

---

## ⚡ 快速导航
[安装说明](#-安装) · [快速上手](#-快速上手) · [支持平台](#-支持平台) · [聊天命令](#-聊天命令) · [配置与特性](#-配置与高级特性) · [常见问题](#-常见问题)


---

## 📦 安装

最低运行环境：**MaiBot 1.3.19、插件 SDK 2.20.0、Python 3.12**；可用版本范围以 [_manifest.json](_manifest.json) 为准。

> [!TIP]
> 无论哪种方式，升级旧版本前均建议先备份原插件目录与数据配置。详见 [升级与恢复指南](docs/configuration.md#升级迁移与冲突恢复)

### 方式一：源码安装
在 MaiBot 根目录下执行：
```bash
cd plugins
git clone https://github.com/WhiteCloudOL/maimai-drawpic-plugin.git
```
完成后重启 MaiBot 或重载插件，在 WebUI 扩展页面打开 **麦麦绘图** 即可。

### 方式二：插件市场安装(⭐推荐)
在 MaiBot 插件市场中直接搜索并安装，安装后可在插件管理中直接查看版本与更新。

---

## 🚀 快速上手

首次使用前，请准备好绘图服务的 API Key 与可用模型（ComfyUI 用户需准备好 API 格式工作流）。

1. **添加平台**：进入 WebUI **绘图平台 → 添加平台**，选择平台类型
2. **配置连接**：设置自定义平台名称（如“日常创作”），填入 API Key、服务地址与可用模型 ID，保存后即刻生效
3. **文生图测试**：切换至 **开始创作 → 文生图**，输入 Prompt，挑选模型并点击 **开始绘图**
4. **查看成果**：在创作区或 **绘图任务** 列表查看进度与原图。若需发送到群聊，展开表单底部的发送选项即可

> 图生图支持上传参考图并在提示词中描述修改点。若模型要求公网 URL，需先将源图托管至可访问的公网地址。[完整使用指南 →](docs/usage.md)

---

## 🎨 支持平台

各平台均支持添加多个命名实例，按需启用：

| 平台 | 文生图 / 图生图 | 特性与主要限制 |
| :--- | :--- | :--- |
| **OpenAI / 兼容接口** | 视模型支持 | 支持各类兼容 OpenAI 规范的中转站与直连 |
| **Google Gemini** | 视模型支持 | 支持的模型参考图数量有所不同 |
| **智谱 AI** | 文生图 | 默认内置模型 `glm-image` |
| **MiniMax** | 全部支持 | 默认 `MiniMax-H3-Image`；image-01 支持主体参考 |
| **阿里百炼** | 视模型支持 | 可灵/Vidu 等编辑类模型要求原图提供公网 URL |
| **火山引擎** | 视模型支持 | 适配 Seedream 体系模型与校验能力 |
| **硅基流动** | 视模型支持 | 生成与图像编辑模型通常独立区分 |
| **NovelAI / NovelAPI** | 全部支持 | 默认开启反向词与多角色处理；图生图参考图为 1 张 |
| **Agnes AI** | 全部支持 | Image 2.0 采用像素尺寸；2.1 / 2.5 支持 1K–4K 及常用比例 |
| **ComfyUI** | 视工作流支持 | **必须**导出并使用 API 格式工作流 JSON |

详细配置与各家额度限制请查阅 [各平台最小配置与限制说明](docs/platforms.md)

---

## 💬 聊天命令

可在聊天中直接使用快捷指令发起作画或调整状态：

```text
/绘图 帮助
/绘图 模型
/绘图 文生图 夜晚的海边灯塔，水彩插画
/绘图 图生图 保留主体，把背景改成樱花树林 [附带图片或回复原图]
/绘图 风格 水彩 一座森林小屋
/绘图 状态
```

> [!NOTE]
> 图生图需附带图片或引用含有图片的消息。更多高级用法（如反向词过滤、NAI 专用语法、额度限制、英文别名等）详见 [完整命令用法表](docs/usage.md#聊天命令)。

---

## ⚙️ 配置与高级特性

WebUI 偏好设置采用标签页分类，右下角统一保存修改，修改项支持单击撤回图标快速重置。

- **模型与预设覆盖**：支持按模型覆盖分辨率、OpenAI 兼容接口模式，并配置平台扩展参数；支持常用尺寸下拉与自定义宽高
- **风格模板**：模板中 `{prompt}` 与 `{negative_prompt}` 为占位符，支持一键注入固定画风，未指定风格时自动继承默认预设
- **会话历史同步**：可在「通用配置」开启 *生成图片同步到会话历史*，开启后发至聊天的图片可供视觉 Planner 查看
- **权限与审核**：内置提示词与图片双重审查，支持 `vlm` / `planner` / `replyer` 模型，支持分别设置群聊／私聊黑白名单
- **缓存与日志**：在 MaiBot 宿主插件配置页可限制图片缓存（默认 300MB）与日志容量（默认 10MB），重要生成图建议本地另存

配置与预设均存储为标准 UTF-8 JSON，高级玩法详见 [手动编辑配置指南](docs/manual-configuration.md)。

---

## ❓ 常见问题

- **模型列表下拉为空？**<br>
  检查该平台是否已开启胶囊开关，并确认填写的模型 ID 与账号实际开通的模型权限一致
- **图生图提示“能力校验不通过”？**<br>
  所选模型可能不支持多图输入，或部分国内平台要求参考图必须是公网 HTTP/HTTPS 直链
- **请求超时或任务状态未更新？**<br>
  工作台取消仅终止本地等待，上游执行与计费以服务商账单为准；可先前往服务商控制台核对任务
- **图片无法下载 / 报 IP 校验异常？**<br>
  使用 TUN/Fake-IP 代理或内网私有图床时，在「通用配置」开启 *忽略图片地址 IP 校验*
- **表单填写内容丢失？**<br>
  偏好设置切换分类会保留草稿；离开未保存的配置页会提示确认。已提交任务可在“绘图任务”中查询；提交回执未确认时使用“恢复原提交”找回原任务
- **ComfyUI 报错无法执行？**<br>
  使用 ComfyUI 菜单中的「导出（API 格式）」保存 JSON。默认放在 `MaiBot\data\plugins\maimai-drawpic-plugin\workflows`，文生图设置填写 `data/workflows/t2i.json`，图生图填写 `data/workflows/i2i.json`；`MaiBot` 为主程序根目录。详见 [ComfyUI 配置](docs/platforms.md#comfyui-本地工作流)

---

## 📚 完整文档与扩展

- **用户指南**：[完整使用指南](docs/usage.md) ｜ [平台接入配置](docs/platforms.md) ｜ [配置与数据迁移](docs/configuration.md)
- **开发者接入**：[插件联动与 DrawingClient](docs/integration.md) ｜ [独立客户端](clients/README.md)
- **适配器支持**：[官方 QQ 机器人与 SnowLuma 适配说明](docs/qq-adapters.md)

---

## 开源协议

采用 [AGPL-3.0](LICENSE) 协议发布
