(() => {
  "use strict";
  const U = window.DrawpicUI,
    { e, $, icon, state } = U;
  let sequence = 0;
  function localized(meta, key) {
    const language = window.maibot?.context?.language?.replace("-", "_");
    return meta.i18n?.[language]?.[key] || meta[key] || "";
  }
  function scalar(key, meta, value, id, values = {}) {
    const type = meta.type;
    if (key === "default_style") {
      const presets = (values.presets || []).filter(
        (item) => item.enabled && item.name.trim(),
      );
      return `<select id="${id}" data-input="${e(key)}"><option value="">不使用默认风格</option>${value && !presets.some((item) => item.name === value) ? `<option value="${e(value)}" selected>${e(value)}（未启用或不存在）</option>` : ""}${presets.map((item) => `<option value="${e(item.name)}" ${item.name === value ? "selected" : ""}>${e(item.name)}</option>`).join("")}</select>`;
    }

    if (key === "default_model") {
      const models = state.data.models;
      let selected = value;
      if (!models.some((item) => item.name === value)) {
        const matches = models.filter((item) => item.upstream_model === value);
        if (matches.length === 1) selected = matches[0].name;
        else if (
          value === state.data.settings.general.default_model &&
          matches.some((item) => item.name === state.data.default_model)
        )
          selected = state.data.default_model;
      }
      return `<select id="${id}" data-input="${e(key)}"><option value="">自动选择可用模型</option>${selected && !models.some((item) => item.name === selected) ? `<option value="${e(selected)}" selected>${e(selected)}（尚未匹配已启用平台）</option>` : ""}${models.map((item) => `<option value="${e(item.name)}" ${item.name === selected ? "selected" : ""}>${e(item.name)}</option>`).join("")}</select>`;
    }
    if (type === "boolean")
      return `<input id="${id}" type="checkbox" role="switch" class="toggle" data-input="${e(key)}" ${value ? "checked" : ""}>`;
    if (type === "select") {
      const selected = meta.multiple ? new Set(value || []) : new Set([value]);
      return `<select id="${id}" data-input="${e(key)}">${!meta.choices?.includes(value) ? `<option value="${e(value)}">${e(value) || "使用默认值"}</option>` : ""}${(meta.choices || []).map((item) => `<option value="${e(item)}" ${selected.has(item) ? "selected" : ""}>${e(U.formOptions.label(item))}</option>`).join("")}</select>`;
    }
    if (type === "integer" || type === "number")
      return `<input id="${id}" type="number" data-input="${e(key)}" value="${e(value)}" step="${meta.step || (type === "integer" ? 1 : "any")}" ${meta.min != null ? `min="${e(meta.min)}"` : ""} ${meta.max != null ? `max="${e(meta.max)}"` : ""}>`;
    const secret = key === "api_key" || key === "password";
    const multiline = /prompt|description|artist|extra_parameters/.test(key);
    if (multiline && !secret)
      return `<textarea id="${id}" rows="${meta.rows || 3}" data-input="${e(key)}" maxlength="16000">${e(value)}</textarea>`;
    const models = /^(default_model|fallback_model)$/.test(key);
    return `<input id="${id}" type="${secret ? "password" : "text"}" data-input="${e(key)}" value="${e(value)}" autocomplete="${secret ? "new-password" : "off"}" ${models ? 'list="workspace-models"' : ""} placeholder="${secret ? "留空保留已配置的密钥" : e(localized(meta, "placeholder"))}">`;
  }
  function row(value, keyvalue, ordered = false) {
    if (keyvalue) {
      const index = String(value).indexOf("=");
      const key = index < 0 ? String(value) : String(value).slice(0, index);
      const val = index < 0 ? "" : String(value).slice(index + 1);
      return `<div class="keyvalue-row" data-array-row><input aria-label="参数名称" data-key value="${e(key)}" placeholder="参数名称"><input aria-label="参数值" data-value value="${e(val)}" placeholder="参数值"><button type="button" class="icon-button" data-remove aria-label="移除参数">×</button></div>`;
    }
    if (ordered) {
      const options = state.data.models.map((model) => model.name);
      if (value && !options.includes(value)) options.unshift(value);
      return `<div class="array-row ordered-row" data-array-row><select data-value aria-label="备选模型"><option value="">请选择模型</option>${options.map((name) => `<option value="${e(name)}" ${name === value ? "selected" : ""}>${e(name)}</option>`).join("")}</select><button type="button" class="icon-button" data-move="up" aria-label="上移备选模型">↑</button><button type="button" class="icon-button" data-move="down" aria-label="下移备选模型">↓</button><button type="button" class="icon-button" data-remove aria-label="移除备选模型">×</button></div>`;
    }
    return `<div class="array-row" data-array-row><input data-value aria-label="列表项" value="${e(value)}"><button type="button" class="icon-button" data-remove aria-label="移除列表项">×</button></div>`;
  }
  function objectRow(meta, value, index) {
    return `<div class="array-object" data-array-object><div class="array-object-header"><span class="muted">${e(value.name || `第 ${index + 1} 项`)}</span><button type="button" class="button ghost compact" data-remove-object>移除</button></div>${fieldsHTML(meta.item_fields, value)}</div>`;
  }
  function fieldsHTML(fields, values, options = {}) {
    return (
      '<div class="form-grid">' +
      Object.entries(fields)
        .filter(
          ([key, meta]) =>
            !meta.hidden &&
            key !== "config_version" &&
            !(options.platform && key === "instances"),
        )
        .map(([key, meta]) => {
          const value = values[key] ?? structuredClone(meta.default);
          const id = `field-${++sequence}`;
          const hint = [
              meta.multiple
                ? `${localized(meta, "hint")} 直接勾选所需项目，无需按住 Ctrl 或 Shift。`
                : U.formOptions.hint(key) || localized(meta, "hint"),
              key === "default_model" && state.data.default_model_error
                ? `${state.data.default_model_error}。请选择完整的“平台实例 / 模型”名称后保存。`
                : "",
            ]
              .filter(Boolean)
              .join(" "),
            description = hint ? ` aria-describedby="${id}-hint"` : "";
          let control = U.formControls.scalar(key, meta, value, id, options);
          if (control)
            control = control.replace(`id="${id}"`, `id="${id}"${description}`);
          else if (meta.type === "array") {
            const keyvalue = /extra_parameters|overrides/.test(key);
            control = `<div data-array="${e(key)}" data-object="${meta.item_type === "object"}" data-keyvalue="${keyvalue}">${(value || []).map((item, index) => (meta.item_type === "object" ? objectRow(meta, item, index) : U.formCollections.row(key, item, options) || row(item, keyvalue, key === "fallback_models"))).join("")}<button type="button" class="button secondary compact" data-add-array>${icon("plus")}添加${meta.item_type === "object" ? "项目" : key === "model_size_overrides" || key === "model_endpoint_overrides" ? "模型覆盖" : key.includes("extra_parameters") ? "参数" : "一项"}</button></div>`;
          } else
            control = scalar(key, meta, value, id, values).replace(
              `id="${id}"`,
              `id="${id}"${description}`,
            );
          const full =
            meta.type === "array" ||
            meta.type === "boolean" ||
            meta.multiple ||
            /prompt|description/.test(key);
          const array = meta.type === "array",
            tag = array || meta.multiple ? "fieldset" : "div",
            label = e(localized(meta, "label") || key);
          return `<${tag} class="field ${meta.type === "boolean" ? "field-toggle" : ""} ${full ? "full" : ""}" data-field="${e(key)}"${tag === "fieldset" ? description : ""}>${tag === "fieldset" ? `<legend>${label}</legend>` : `<label for="${id}">${label}</label>`}${control}${hint ? `<p id="${id}-hint" class="hint">${e(hint)}</p>` : ""}</${tag}>`;
        })
        .join("") +
      "</div>"
    );
  }
  function read(fields, values, root, options = {}) {
    const result = structuredClone(values);
    for (const [key, meta] of Object.entries(fields)) {
      if (key === "config_version" || (options.platform && key === "instances"))
        continue;
      const field = Array.from(
        root.querySelectorAll(":scope > .form-grid > [data-field]"),
      ).find((n) => n.dataset.field === key);
      if (!field) continue;
      const multiple = $(":scope > [data-multiple]", field),
        control = $(":scope > [data-control]", field);
      if (multiple)
        result[key] = [...multiple.querySelectorAll("input:checked")].map(
          (input) => input.value,
        );
      else if (control) result[key] = U.formControls.read(control);
      else if (meta.type === "array") {
        const array = $("[data-array]", field);
        if (meta.item_type === "object")
          result[key] = Array.from(array.children)
            .filter((n) => n.hasAttribute("data-array-object"))
            .map((n) => read(meta.item_fields, {}, n));
        else
          result[key] = Array.from(array.children)
            .filter((n) => n.hasAttribute("data-array-row"))
            .map(
              (n) =>
                U.formCollections.readRow(key, n) ??
                (array.dataset.keyvalue === "true"
                  ? `${$("[data-key]", n).value.trim()}=${$("[data-value]", n).value}`
                  : $("[data-value]", n).value.trim()),
            )
            .filter((n) => n && !n.startsWith("="));
        U.formCollections.validateRows(array, result[key]);
      } else {
        const input = $("[data-input]", field);
        if (!input) continue;
        if (meta.type === "boolean") result[key] = input.checked;
        else if (meta.type === "integer" || meta.type === "number") {
          if (!input.value.trim())
            throw new Error(`${localized(meta, "label")}不能为空`);
          result[key] = Number(input.value);
        } else if (meta.multiple)
          result[key] = Array.from(input.selectedOptions, (n) => n.value);
        else result[key] = input.value;
      }
    }
    return result;
  }
  function refreshStyleChoices(root) {
    const select = $('[data-input="default_style"]', root);
    const list = $('[data-array="presets"]', root);
    if (!select || !list) return;
    const selected = select.value;
    const names = Array.from(list.children)
      .filter((node) => node.hasAttribute("data-array-object"))
      .map((node) => ({
        name: $('[data-input="name"]', node)?.value.trim() || "",
        enabled: $('[data-input="enabled"]', node)?.checked,
      }))
      .filter((item) => item.enabled && item.name);
    select.innerHTML =
      '<option value="">不使用默认风格</option>' +
      names
        .map(
          (item) =>
            `<option value="${e(item.name)}" ${item.name === selected ? "selected" : ""}>${e(item.name)}</option>`,
        )
        .join("");
    if (!names.some((item) => item.name === selected)) select.value = "";
  }
  function bind(root, fields, values, options = {}) {
    U.formControls.bind(root);
    U.formCollections.bind(root);
    root.addEventListener("input", () => refreshStyleChoices(root));
    root.onclick = (event) => {
      const move = event.target.closest("[data-move]");
      if (move) {
        const item = move.closest("[data-array-row]");
        const sibling =
          move.dataset.move === "up"
            ? item.previousElementSibling
            : item.nextElementSibling;
        if (sibling?.hasAttribute("data-array-row")) {
          if (move.dataset.move === "up")
            item.parentElement.insertBefore(item, sibling);
          else item.parentElement.insertBefore(sibling, item);
          state.dirty = true;
          const notice = $("[data-unsaved]", root);
          if (notice) notice.hidden = false;
        }
        return;
      }
      const remove = event.target.closest("[data-remove],[data-remove-object]");
      if (remove) {
        remove.closest("[data-array-row],[data-array-object]").remove();
        refreshStyleChoices(root);
        U.formCollections.refresh(root);
        state.dirty = true;
        const notice = $("[data-unsaved]", root);
        if (notice) notice.hidden = false;
        return;
      }
      const add = event.target.closest("[data-add-array]");
      if (!add) return;
      const array = add.parentElement;
      const key = array.dataset.array;
      // 嵌套对象字段可能属于列表子模型，通过所在表单逐级定位定义。
      let meta = fields[key];
      if (!meta) {
        for (const candidate of Object.values(fields)) {
          if (candidate.item_fields?.[key]) {
            meta = candidate.item_fields[key];
            break;
          }
        }
      }
      if (!meta) return;
      const html =
        meta.item_type === "object"
          ? objectRow(
              meta,
              {},
              array.querySelectorAll(":scope > [data-array-object]").length,
            )
          : U.formCollections.row(key, "", options) ||
            row(
              "",
              array.dataset.keyvalue === "true",
              key === "fallback_models",
            );
      add.insertAdjacentHTML("beforebegin", html);
      refreshStyleChoices(root);
      U.formCollections.refresh(root);
      state.dirty = true;
      const notice = $("[data-unsaved]", root);
      if (notice) notice.hidden = false;
    };
    U.bindDirty(root);
    return () => read(fields, values, root, options);
  }
  function appendArray(root, key, values, options = {}) {
    const array = $(`[data-array="${key}"]`, root), add = $("[data-add-array]", array);
    for (const value of values)
      add.insertAdjacentHTML("beforebegin", U.formCollections.row(key, value, options) || row(value, false));
    U.formCollections.refresh(root);
    array.dispatchEvent(new Event("input", { bubbles: true }));
  }
  U.forms = { html: fieldsHTML, bind, read, appendArray };
})();
