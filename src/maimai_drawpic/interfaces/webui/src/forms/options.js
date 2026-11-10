(() => {
  "use strict";
  const U = window.DrawpicUI;
  const labels = {
    "": "使用平台默认（不传此参数）",
    auto: "自动",
    low: "低",
    medium: "中",
    high: "高",
    standard: "标准",
    hd: "高清",
    fast: "速度优先",
    transparent: "透明背景",
    opaque: "不透明背景",
    b64_json: "直接返回图片数据",
    url: "返回图片链接",
    disabled: "关闭",
    single: "单张图片",
    series: "连续分镜",
    direct: "直接改写",
    agent: "智能体改写",
    anime: "动漫",
    furry: "兽人",
    background: "背景画",
    images_api: "图片接口",
    chat_completions: "聊天绘图接口（New API）",
    rinkoai: "RinkoAI NAI 接口",
    single_prompt: "单提示词节点",
    positive_negative: "正反提示词分开",
    daily: "每天",
    weekly: "每周",
    monthly: "每月",
    once: "一次性",
    blacklist: "黑名单",
    whitelist: "白名单",
    base64: "直接传入图片数据",
    image_url: "使用原图链接",
    replyer: "回复任务组",
    planner: "规划任务组",
    vlm: "视觉任务组",
  };
  const presets = {
    minimax: {
      area: ["", "1K", "2K", "4K"],
      aspect_ratio: ["", "auto", "1:1", "16:9", "4:3", "3:2", "2:3", "3:4", "9:16", "21:9"],
      style_type: ["", "漫画", "元气", "中世纪", "水彩"],
    },
    openai: {
      quality: ["", "auto", "low", "medium", "high", "standard", "hd"],
      response_format: ["", "b64_json", "url"],
      output_format: ["", "png", "jpeg", "webp"],
      background: ["", "auto", "transparent", "opaque"],
      moderation: ["", "auto", "low"],
    },
    google: {
      aspect_ratio: [
        "",
        "1:1",
        "2:3",
        "3:2",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "21:9",
      ],
      image_size: ["", "512", "1K", "2K", "4K"],
    },
    zhipu: { quality: ["", "hd", "standard"] },
    volcengine: {
      output_format: ["", "png", "jpeg"],
      optimize_prompt_mode: ["", "standard", "fast"],
      background: ["", "opaque", "transparent"],
    },
    novelai: {
      sampler: ["k_euler_ancestral", "k_euler", "k_dpmpp_2m", "ddim"],
      noise_schedule: [
        "",
        "native",
        "karras",
        "exponential",
        "polyexponential",
      ],
      v4_noise_schedule: ["", "karras", "exponential", "polyexponential"],
    },
  };
  const dimensions = {
    agnes: ["1K", "2K", "3K", "4K", "1024x1024", "1024x768", "768x1024"],
    openai: ["1024x1024", "1024x1536", "1536x1024", "auto"],
    zhipu: ["1280x1280", "1024x1024", "768x1344", "1344x768"],
    aliyun: ["2048*2048", "1328*1328", "1024*1024", "1024*1536", "1536*1024"],
    volcengine: ["1K", "1.5K", "2K", "4K", "1024x1024", "2048x2048"],
    siliconflow: ["1024x1024", "768x1024", "1024x768", "512x512"],
    novelai: ["832x1216", "1216x832", "1024x1024", "768x1024", "1024x768"],
  };
  function label(value) {
    if (value === "") return labels[""];
    if (["daily", "weekly", "monthly", "once", "blacklist", "whitelist"].includes(value)) return labels[value];
    if (Object.hasOwn(labels, value)) return `${labels[value]} · ${value}`;
    const size = String(value).match(/^(\d+)[x*](\d+)$/);
    if (size)
      return `${size[1]} × ${size[2]} · ${+size[1] === +size[2] ? "方形" : +size[1] > +size[2] ? "横向" : "竖向"}`;
    return value;
  }
  U.formOptions = {
    label,
    choice: (key, kind) => presets[kind]?.[key],
    dimensions: (kind) => dimensions[kind] || [],
    dimensionField: (key, kind) =>
      kind !== "google" &&
      ["default_size", "size", "image_size"].includes(key) &&
      !!dimensions[kind],
    hint(key) {
      if (key === "model_size_overrides")
        return "选择当前平台已添加的模型，再选择常用尺寸或填写宽高。未单独设置的模型继续使用默认尺寸；不同模型的尺寸限制仍以平台说明为准。";
      if (key === "model_endpoint_overrides")
        return "从当前平台模型中选择，再填写该模型使用的接口地址。通常无需设置。";
      if (key.includes("extra_parameters"))
        return "仅在需要平台扩展参数时添加。分别填写名称、值类型和值；开关直接选择，复杂结构使用 JSON。";
      if (key === "models" || key === "custom_models")
        return "按账号实际权限填写模型 ID；可直接粘贴。下方的按模型覆盖选项会随本列表更新。";
      if (key.endsWith("unsupported_models"))
        return "按需添加模型，可选择多个；通过右侧 × 移除。人工限制优先于自动识别，已有未匹配的模型仍会保留。";
      return "";
    },
  };
})();
