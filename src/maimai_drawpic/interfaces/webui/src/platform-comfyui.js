(() => {
  "use strict";
  const U = window.DrawpicUI;
  function html(fields, values) {
    return U.forms.sections([
      { title: "连接设置", hint: "地址从 MaiBot 所在机器访问；工作流文件也需放在该机器上。", open: true,
        includes: key => ["base_url", "negative_prompt_enabled", "negative_prompt", "rewrite_prompt_to_english"].includes(key) },
      { title: "文生图工作流", hint: "使用 ComfyUI 导出的 API 格式 JSON；节点 ID 填 JSON 中的键，不填节点标题。", open: true,
        includes: key => key.startsWith("t2i_") },
      { title: "图生图工作流（可选）", hint: "只使用文生图时无需配置。图生图支持一个 LoadImage 源图节点。", open: Boolean(values.i2i_image_node_id),
        includes: key => key.startsWith("i2i_") || key === "image_input_name" },
      { title: "节点采样", hint: "标准文本字段为 text，种子字段为 seed；noise_seed 等自定义字段请按工作流填写。", open: false,
        includes: key => ["prompt_input_name", "seed", "seed_input_name", "poll_interval_seconds"].includes(key) },
    ], fields, values, { platform: true, kind: "comfyui" });
  }
  function bind(form) {
    const refresh = () => {
      for (const task of ["t2i", "i2i"]) {
        const single = U.$(`[data-input="${task}_prompt_mode"]`, form).value === "single_prompt";
        for (const suffix of ["prompt_node_id", "positive_prompt_node_id", "negative_prompt_node_id", "negative_prompt"])
          U.$(`[data-field="${task}_${suffix}"]`, form).hidden = suffix === "prompt_node_id" ? !single : single;
      }
    };
    form.addEventListener("change", refresh);
    form.addEventListener("fieldreset", refresh);
    refresh();
  }
  U.comfyuiForm = { html, bind };
})();
