(() => {
  "use strict";
  const U = window.DrawpicUI,
    { e, $ } = U;
  let sequence = 0;
  const custom = "__workspace_custom__";
  function optionsHTML(choices, selected, labels = {}) {
    return choices
      .map(
        (value) =>
          `<option value="${e(value)}" ${value === selected ? "selected" : ""}>${e(labels[value] || U.formOptions.label(value))}</option>`,
      )
      .join("");
  }
  function choice(
    value,
    choices,
    { id, label, size = false, kind = "", allowCustom = true, forceCustom = false, labels = {}, placeholder = "填写服务要求的值…", customLabel = "自定义值…" } = {},
  ) {
    const known = !forceCustom && choices.includes(value),
      selected = known ? value : custom;
    const identity = id || `choice-${++sequence}`;
    const parts = size ? String(value).match(/^(\d+)[x*×](\d+)$/) : null;
    const legacySize = size && !known && value && !parts;
    const active = !known && !legacySize;
    const controls = size
      ? `<div class="dimension-inputs" data-custom-panel ${active ? "" : "hidden"}><label>宽度（px）<input data-width type="number" min="1" step="1" value="${e(parts?.[1] || "")}" ${active ? "required" : "disabled"}></label><span aria-hidden="true">×</span><label>高度（px）<input data-height type="number" min="1" step="1" value="${e(parts?.[2] || "")}" ${active ? "required" : "disabled"}></label></div>`
      : `<input data-custom-value aria-label="自定义${e(label || "参数值")}" value="${e(known ? "" : value)}" placeholder="${e(placeholder)}" autocomplete="off" ${active ? "required" : "hidden disabled"}>`;
    // 无法解析的旧尺寸仍作为独立选项保留，不打开空的宽高输入覆盖原值。
    const items = legacySize ? [value, ...choices] : choices;
    return `<div data-control="${size ? "dimension" : "choice"}" data-kind="${e(kind)}"><select id="${identity}" data-choice-select aria-label="${e(label || "参数值")}">${optionsHTML(items, legacySize ? value : selected, labels)}${allowCustom || !known ? `<option value="${custom}" ${selected === custom && !legacySize ? "selected" : ""}>${size ? "自定义宽高…" : e(customLabel)}</option>` : ""}</select>${controls}</div>`;
  }
  function read(node) {
    if (node.dataset.control === "tags") {
      commitTags(node);
      return [...node.querySelectorAll("[data-tag-value]")].map(input => input.value);
    }
    const selected = $("[data-choice-select]", node).value;
    if (node.dataset.control === "recognition-model")
      return selected === custom ? `model:${$("[data-custom-value]", node).value.trim()}` : "vlm";
    if (selected !== custom) return selected;
    if (node.dataset.control !== "dimension")
      return $("[data-custom-value]", node).value;
    const width = $("[data-width]", node).value,
      height = $("[data-height]", node).value;
    if (
      ![width, height].every(
        (value) =>
          /^\d+$/.test(value) && Number.isSafeInteger(+value) && +value > 0,
      )
    )
      throw new Error("自定义尺寸请填写有效的整数宽度和高度");
    return `${+width}${node.dataset.kind === "aliyun" ? "*" : "x"}${+height}`;
  }
  function tagHTML(value) {
    return `<span class="input-tag"><span>${e(value)}</span><input type="hidden" data-tag-value value="${e(value)}"><button type="button" data-remove-tag aria-label="移除${e(value)}">${U.icon("close")}</button></span>`;
  }
  function tags(value, { id, label, limit = 32, maxLength = 80 } = {}) {
    return `<div class="tag-input" data-control="tags" data-limit="${limit}" data-max-length="${maxLength}">${[...new Set(value)].map(tagHTML).join("")}<input id="${id}" data-tag-entry aria-label="${e(label)}" placeholder="输入后按回车添加" autocomplete="off" enterkeyhint="done"></div>`;
  }
  function commitTags(node) {
    const input = $("[data-tag-entry]", node), existing = [...node.querySelectorAll("[data-tag-value]")].map(item => item.value);
    const additions = input.value.split(/[,，\n]/).map(value => value.trim()).filter(Boolean);
    const values = [...new Set([...existing, ...additions])];
    if (values.length > Number(node.dataset.limit) || values.some(value => value.length > Number(node.dataset.maxLength))) {
      input.setCustomValidity(`最多 ${node.dataset.limit} 项，每项不超过 ${node.dataset.maxLength} 个字符`);
      input.reportValidity();
      throw new Error(input.validationMessage);
    }
    input.setCustomValidity("");
    for (const value of values.filter(value => !existing.includes(value))) input.insertAdjacentHTML("beforebegin", tagHTML(value));
    input.value = "";
    if (additions.length) node.dispatchEvent(new Event("input", { bubbles: true }));
  }
  function multi(key, choices, selected, id) {
    const values = [...new Set([...choices, ...selected])];
    return `<div class="choice-list" data-multiple="${e(key)}" id="${id}">${values.length ? values.map((value) => `<label class="choice-item"><input type="checkbox" data-choice-value value="${e(value)}" ${selected.includes(value) ? "checked" : ""}><span>${e(U.formOptions.label(value))}</span></label>`).join("") : '<p class="hint">暂无可选模型，请先添加并启用绘图平台。</p>'}</div>`;
  }
  function scalar(key, meta, value, id, options = {}) {
    const kind = options.kind;
    if (meta.type === "array" && ["self_keywords", "self_names", "tags"].includes(key))
      return tags(value || [], { id, label: meta.label, limit: meta.max_items || 32 });
    if (key === "material_model")
      return choice(value.replace(/^model:/, ""), ["vlm"], { id, label: "识别模型", labels: { vlm: "MaiBot 视觉模型" }, forceCustom: value !== "vlm",
        placeholder: "填写 MaiBot 中配置的模型名称", customLabel: "指定模型…" }).replace(
        "data-choice-select", `data-choice-select data-input="${e(key)}"`,
      ).replace('data-control="choice"', 'data-control="recognition-model"');
    if (meta.multiple) return multi(key, meta.choices || [], value || [], id);
    if (key === "request_retry_count" || key.endsWith("_review_retry_count"))
      return `<select id="${id}" data-input="${key}">${[0, 1, 2, 3, 4, 5].map((count) => `<option value="${count}" ${Number(value) === count ? "selected" : ""}>${count === 0 ? "不重试" : `${count} 次${count === Number(meta.default) ? "（默认）" : ""}`}</option>`).join("")}</select>`;
    if (U.formOptions.dimensionField(key, kind))
      return choice(value, [...(kind === "agnes" ? [] : [""]), ...U.formOptions.dimensions(kind)], {
        id,
        label: meta.label,
        size: true,
        kind,
      }).replace(
        "data-choice-select",
        `data-choice-select data-input="${e(key)}"`,
      );
    const choices = U.formOptions.choice(key, kind);
    if (choices)
      return choice(value, choices, { id, label: meta.label }).replace(
        "data-choice-select",
        `data-choice-select data-input="${e(key)}"`,
      );
    return null;
  }
  function bind(root) {
    root.addEventListener("keydown", event => {
      const input = event.target.closest("[data-tag-entry]");
      if (!input || event.isComposing || event.keyCode === 229 || event.ctrlKey || event.metaKey) return;
      if (["Enter", ",", "，"].includes(event.key)) {
        event.preventDefault();
        try { commitTags(input.parentElement); } catch { /* 保留未通过校验的输入。 */ }
      } else if (event.key === "Backspace" && !input.value) {
        input.previousElementSibling?.querySelector("[data-remove-tag]")?.click();
      }
    });
    root.addEventListener("input", event => {
      const input = event.target.closest("[data-tag-entry]");
      if (input) input.setCustomValidity("");
    });
    root.addEventListener("focusout", event => {
      const input = event.target.closest("[data-tag-entry]");
      if (input) { try { commitTags(input.parentElement); } catch { /* 保留未通过校验的输入。 */ } }
    });
    root.addEventListener("click", event => {
      const button = event.target.closest("[data-remove-tag]");
      if (!button) return;
      const node = button.closest('[data-control="tags"]');
      button.closest(".input-tag").remove();
      $("[data-tag-entry]", node).focus();
      node.dispatchEvent(new Event("input", { bubbles: true }));
    });
    root.addEventListener("change", (event) => {
      const select = event.target.closest("[data-choice-select]");
      if (!select) return;
      const node = select.closest("[data-control]");
      const panel = $("[data-custom-panel],[data-custom-value]", node);
      const active = select.value === custom;
      panel.hidden = !active;
      const inputs = panel.matches("input")
        ? [panel]
        : [...panel.querySelectorAll("input")];
      for (const input of inputs) {
        input.disabled = !active;
        input.required = active;
      }
      if (active) inputs[0]?.focus();
    });
  }
  U.formControls = { choice, multi, tags, read, scalar, bind, optionsHTML };
})();
