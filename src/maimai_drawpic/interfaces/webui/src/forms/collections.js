(() => {
  "use strict";
  const U = window.DrawpicUI,
    { $, e } = U;
  function split(value) {
    const text = String(value),
      index = text.indexOf("=");
    return index < 0
      ? [text, ""]
      : [text.slice(0, index), text.slice(index + 1)];
  }
  const remove =
    '<button type="button" class="icon-button" data-remove aria-label="移除此项">×</button>';
  function invalid(input, message) {
    input.setCustomValidity(message);
    input.dataset.configInvalid = "true";
    input.reportValidity();
    input.focus();
    throw new Error(message);
  }
  function parameterType(raw) {
    try {
      const value = JSON.parse(raw);
      if (typeof value === "number")
        return Number.isFinite(value) &&
          (!Number.isInteger(value) || Number.isSafeInteger(value))
          ? ["number", String(value)]
          : ["json", raw];
      if (typeof value === "boolean") return ["boolean", String(value)];
      if (typeof value === "string") return ["text", value];
      return ["json", raw];
    } catch {
      return ["text", raw];
    }
  }
  function parameterValue(type, value = "") {
    if (type === "boolean")
      return `<input type="checkbox" role="switch" class="toggle" data-param-value aria-label="参数开关" ${value !== "false" ? "checked" : ""}>`;
    if (type === "json")
      return `<textarea data-param-value aria-label="JSON 参数值" rows="3" spellcheck="false" placeholder='例如 {"enabled": true}…'>${e(value)}</textarea>`;
    return `<input data-param-value type="${type === "number" ? "number" : "text"}" ${type === "number" ? 'step="any"' : ""} aria-label="参数值" autocomplete="off" value="${e(value)}" placeholder="填写参数值…">`;
  }
  function row(key, value, options = {}) {
    if (key === "fallback_models" || key.endsWith("unsupported_models")) {
      const ordered = key === "fallback_models";
      const title = ordered ? "备选模型" : key === "image_edit_unsupported_models" ? "仅支持文生图的模型" : "仅支持图生图的模型";
      const choices = U.state.data.models.map((item) => item.name);
      if (value && !choices.includes(value)) choices.unshift(value);
      return `<div class="array-row ${ordered ? "ordered-row" : "model-choice-row"}" data-array-row><select data-value aria-label="${title}"><option value="">请选择模型</option>${choices.map((name) => `<option value="${e(name)}" ${name === value ? "selected" : ""}>${e(name)}</option>`).join("")}</select>${ordered ? '<button type="button" class="icon-button" data-move="up" aria-label="上移备选模型">↑</button><button type="button" class="icon-button" data-move="down" aria-label="下移备选模型">↓</button>' : ""}${remove}</div>`;
    }
    if (key === "models" || key === "custom_models") {
      return `<div class="model-editor-row" data-array-row data-model-row><input data-model-id aria-label="模型 ID" value="${e(value)}" placeholder="填写平台提供的真实模型 ID…" autocomplete="off" spellcheck="false">${remove}</div>`;
    }
    if (key === "model_size_overrides" || key === "model_endpoint_overrides") {
      const [model, raw] = split(value);
      const valueControl =
        key === "model_size_overrides"
          ? U.formControls.choice(
              raw,
              ["", ...U.formOptions.dimensions(options.kind)],
              { label: "模型分辨率", size: true, kind: options.kind },
            )
          : `<input data-value aria-label="此模型的接口地址" value="${e(raw)}" placeholder="完整 URL 或接口路径…" autocomplete="off">`;
      return `<div class="model-override-row" data-array-row data-model-override><label>绘图模型<select data-model-key aria-label="覆盖配置的模型"><option value="${e(model)}" selected>${e(model || "请先选择模型")}</option></select></label><div><span class="control-caption">${key === "model_size_overrides" ? "输出尺寸" : "接口地址"}</span>${valueControl}</div>${remove}</div>`;
    }
    if (key.includes("extra_parameters")) {
      const [name, raw] = split(value),
        [type, content] = parameterType(raw);
      return `<div class="parameter-editor-row" data-array-row data-parameter-row><label>参数名称<input data-key value="${e(name)}" autocomplete="off" spellcheck="false" placeholder="平台文档中的参数名…"></label><label>值类型<select data-param-type aria-label="参数值类型">${[
        ["text", "文本"],
        ["number", "数字"],
        ["boolean", "开关"],
        ["json", "JSON 对象 / 列表"],
      ]
        .map(
          ([kind, title]) =>
            `<option value="${kind}" ${kind === type ? "selected" : ""}>${title}</option>`,
        )
        .join(
          "",
        )}</select></label><div data-param-editor><span class="control-caption">参数值</span>${parameterValue(type, content)}</div>${remove}</div>`;
    }
    return null;
  }
  function readRow(key, node) {
    if (node.hasAttribute("data-model-row")) {
      const model = $("[data-model-id]", node).value.trim();
      if (model.includes("="))
        invalid($("[data-model-id]", node), "仅填写真实模型 ID，不支持别名=模型的写法");
      return model;
    }
    if (node.hasAttribute("data-model-override")) {
      const model = $("[data-model-key]", node).value;
      const control = $("[data-control]", node);
      const value = control
        ? U.formControls.read(control)
        : $("[data-value]", node).value.trim();
      if (!model && !value) return "";
      if (!model || !value)
        invalid(
          $("[data-model-key]", node),
          "模型覆盖项请同时选择模型并填写参数值；不需要的项目可移除",
        );
      return `${model}=${value}`;
    }
    if (node.hasAttribute("data-parameter-row")) {
      const name = $("[data-key]", node).value.trim(),
        input = $("[data-param-value]", node);
      if (!name && !input.value) return "";
      if (!name || name.includes("="))
        invalid(
          $("[data-key]", node),
          "额外参数请填写有效的参数名称，名称中不能包含等号",
        );
      const type = $("[data-param-type]", node).value;
      let value = input.value;
      if (type === "boolean") value = String(input.checked);
      else if (type === "text") value = JSON.stringify(value);
      else if (type === "number") {
        if (!value.trim() || !Number.isFinite(Number(value)))
          invalid(input, "数字参数请填写有效数值");
        if (
          Number.isInteger(Number(value)) &&
          !Number.isSafeInteger(Number(value))
        )
          invalid(
            input,
            "这个整数超出普通数字输入的精确范围，请改用 JSON 类型",
          );
        value = JSON.stringify(Number(value));
      } else if (type === "json") {
        try {
          JSON.parse(value, (_, item) => {
            if (typeof item === "number" && !Number.isFinite(item))
              throw new Error("非有限数字");
            return item;
          });
          // 校验后保留原 JSON 文本，避免浏览器把大整数重新编码成近似值。
          value = value.trim();
        } catch {
          invalid(
            input,
            "JSON 参数格式不正确，请检查引号、括号、逗号及数字范围",
          );
        }
      }
      return `${name}=${value}`;
    }
    return null;
  }
  function models(root) {
    const result = [];
    for (const key of ["models", "custom_models"]) {
      const multi = $(`[data-multiple="${key}"]`, root);
      if (multi)
        result.push(
          ...[...multi.querySelectorAll("input:checked")].map((input) => ({
            id: input.value,
            label: input.value,
          })),
        );
      const array = $(`[data-array="${key}"]`, root);
      if (!array) continue;
      for (const row of array.querySelectorAll(":scope > [data-array-row]")) {
        const model = row.hasAttribute("data-model-row")
          ? $("[data-model-id]", row).value.trim()
          : $("[data-value]", row).value.trim();
        if (model)
          result.push({
            id: model,
            label: model,
          });
      }
    }
    return result.filter(
      (item, index) =>
        result.findIndex((other) => other.id === item.id) === index,
    );
  }
  function refresh(root) {
    for (const input of root.querySelectorAll("[data-config-invalid]")) {
      input.setCustomValidity("");
      delete input.dataset.configInvalid;
    }
    const choices = models(root);
    for (const select of root.querySelectorAll("[data-model-key]")) {
      const value = select.value;
      const present = choices.some((item) => item.id === value);
      select.innerHTML =
        '<option value="">请选择本平台模型</option>' +
        (value && !present
          ? `<option value="${e(value)}">${e(value)}（未在当前平台配置，保留原值）</option>`
          : "") +
        choices
          .map(
            (item) => `<option value="${e(item.id)}">${e(item.label)}</option>`,
          )
          .join("");
      select.value = value;
    }
  }
  function validateRows(array, values) {
    const models = array.dataset.array === "fallback_models" || array.dataset.array.endsWith("unsupported_models");
    if (!models && !/overrides|extra_parameters/.test(array.dataset.array)) return;
    const names = models ? values : values.map((item) => split(item)[0]);
    if (new Set(names).size !== names.length)
      invalid(
        array.querySelector("[data-model-key],[data-key],[data-value]"),
        "同一配置列表不能重复设置相同的模型或参数名称",
      );
  }
  function bind(root) {
    root.addEventListener("input", () => refresh(root));
    root.addEventListener("change", (event) => {
      const input = event.target.closest("[data-param-type]");
      if (input)
        $(
          "[data-param-editor]",
          input.closest("[data-parameter-row]"),
        ).innerHTML =
          '<span class="control-caption">参数值</span>' +
          parameterValue(input.value);
      refresh(root);
    });
    refresh(root);
  }
  U.formCollections = { row, readRow, refresh, validateRows, bind, models };
})();
