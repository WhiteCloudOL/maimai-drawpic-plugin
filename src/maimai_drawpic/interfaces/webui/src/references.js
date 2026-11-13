(() => {
  "use strict";
  const U = window.DrawpicUI, { state, $, e, icon, call, toast } = U;
  const notice = "该配置会向绘图模型发送多张参考图。请确认所用服务商及具体模型支持多图参考。插件会校验图生图能力，但不自动探测多图兼容性；切换模型后请重新核实。";

  function confirmReferenceAction(title, message, detail, confirmText) {
    const dialog = document.createElement("dialog");
    dialog.className = "reference-confirm";
    dialog.setAttribute("aria-label", title);
    dialog.innerHTML = `<div class="modal-header"><h2>${e(title)}</h2></div><div class="reference-dialog-body"><p>${e(message)}</p>${detail ? `<p class="hint">${e(detail)}</p>` : ""}<div class="modal-footer"><button type="button" class="button secondary" data-cancel>取消</button><button type="button" class="button" data-confirm>${e(confirmText)}</button></div></div>`;
    document.body.append(dialog);
    return new Promise(resolve => {
      let accepted = false;
      $("[data-cancel]", dialog).onclick = () => dialog.close();
      $("[data-confirm]", dialog).onclick = () => { accepted = true; dialog.close(); };
      dialog.addEventListener("close", () => { dialog.remove(); resolve(accepted); }, { once: true });
      dialog.showModal();
    });
  }

  function confirmMultiple() {
    const model = state.data?.settings.general.default_model || state.data?.default_model;
    return confirmReferenceAction("确认多图参考能力", notice, model ? `当前默认模型：${model}` : "", "已确认支持");
  }

  function assets(kind) { return (state.data.reference_assets?.assets || []).filter(item => item.kind === kind); }
  function options(kind, selected) {
    const entries = assets(kind);
    return `<option value="">请选择参考图片</option>${selected && !entries.some(item => item.id === selected) ? `<option value="${e(selected)}" selected>图片不存在或用途不符</option>` : ""}` + entries.map(item => `<option value="${e(item.id)}" ${item.id === selected ? "selected" : ""}>${e(item.name)}${item.tags.length ? ` · ${e(item.tags.join(" / "))}` : ""}</option>`).join("");
  }
  function refreshPickers() {
    document.querySelectorAll("[data-reference-picker]").forEach(select => {
      const selected = select.value;
      select.innerHTML = options(select.dataset.referencePicker, selected);
    });
    U.selects.refresh(document);
  }

  function gallery(root, kind) {
    const C = U.referenceComponents;
    let page = 0, query = "";
    async function mutate(operation, item) {
      if (operation === "delete") {
        const name = state.data.reference_assets.assets.find(asset => asset.id === item.asset_id).name;
        if (!(await confirmReferenceAction("删除参考图片？", `将删除“${name}”。`, "删除后无法撤销。", "删除图片"))) return;
      }
      await C.update(operation, item);
    }
    function render() {
      const snapshot = state.data.reference_assets;
      const entries = assets(kind).filter(item => [item.name, ...item.tags].join(" ").toLocaleLowerCase().includes(query));
      page = Math.min(page, Math.max(0, Math.ceil(entries.length / 12) - 1));
      root.innerHTML = `<div class="reference-gallery-header"><h3>${kind === "self" ? "自我参考图库" : "参考图片"}</h3></div><div class="reference-gallery"></div>${entries.length > 12 ? '<div class="reference-paging"><button type="button" class="button secondary compact" data-prev>上一页</button><span data-page></span><button type="button" class="button secondary compact" data-next>下一页</button></div>' : ""}`;
      $('.reference-gallery-header', root).append(C.toolbar({ kind }));
      const grid = $('.reference-gallery', root);
      for (const item of entries.slice(page * 12, page * 12 + 12)) {
        const index = snapshot.assets.findIndex(entry => entry.id === item.id);
        grid.append(C.card(item, {
          onEdit: () => C.editor(item),
          onRemove: () => U.buttonAction($(`[data-asset="${item.id}"] [data-remove-image]`, root), () => mutate("delete", { asset_id: item.id })),
          isDefault: snapshot.default_reference_id === item.id,
          onDefault: kind === "self" && snapshot.default_reference_id !== item.id ? () => mutate("default", { asset_id: item.id }).catch(U.error) : null,
          onUp: index > 0 ? () => mutate("move", { asset_id: item.id, position: index - 1 }).catch(U.error) : null,
        }));
      }
      if (!entries.length) grid.innerHTML = '<p class="muted">尚未上传参考图片</p>';
      if ($('[data-prev]', root)) {
        $('[data-page]', root).textContent = `${page + 1} / ${Math.ceil(entries.length / 12)}`;
        $('[data-prev]', root).disabled = page === 0;
        $('[data-next]', root).disabled = (page + 1) * 12 >= entries.length;
        $('[data-prev]', root).onclick = () => { page--; render(); };
        $('[data-next]', root).onclick = () => { page++; render(); };
      }
    }
    C.observe(root, render);
    render();
    return { filter(value) { query = value.trim().toLocaleLowerCase(); page = 0; render(); } };
  }

  function confirmButton(root) {
    const field = $('[data-field="multi_reference_confirmed"]', root);
    if (!field) return;
    field.hidden = true;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button secondary compact";
    button.dataset.referenceConfirmation = "true";
    button.textContent = "确认多图参考";
    button.onclick = async () => {
      if (await confirmMultiple()) {
        $('[data-input="multi_reference_confirmed"]', field).checked = true;
        field.dispatchEvent(new Event("input", { bubbles: true }));
        toast("已确认，保存全部设置后生效；切换模型后请重新核实");
      }
    };
    field.after(button);
  }

  function presetImages(row) {
    const C = U.referenceComponents;
    const field = $('[data-field="reference_bindings"]', row), array = $('[data-array="reference_bindings"]', field);
    const add = $(':scope > [data-add-array]', array);
    field.classList.add("preset-reference-field");
    add.hidden = true;
    const bindings = () => [...array.children].filter(item => item.hasAttribute("data-array-object"));
    function appendBinding(id) {
      if (bindings().length >= 8) throw new Error("一个预设最多使用 8 张参考图");
      const previous = bindings();
      add.click();
      const binding = bindings().find(item => !previous.includes(item));
      $('[data-input="asset_id"]', binding).value = id;
      $('[data-input="role"]', binding).value = "base";
      binding.dispatchEvent(new Event("input", { bubbles: true }));
      return binding;
    }
    function chooseImage() {
      if (bindings().length >= 8) { U.error(new Error("一个预设最多使用 8 张参考图")); return; }
      const dialog = document.createElement("dialog");
      dialog.className = "reference-confirm reference-image-picker";
      dialog.setAttribute("aria-label", "选择参考图片");
      dialog.innerHTML = `<div class="modal-header"><h2>选择参考图片</h2><button type="button" class="icon-button" data-close aria-label="关闭弹窗">${icon("close")}</button></div><div class="reference-dialog-body"><div class="reference-gallery"></div></div>`;
      const grid = $('.reference-gallery', dialog);
      for (const item of assets("preset")) {
        const select = () => { if (row.isConnected) appendBinding(item.id); dialog.close(); };
        grid.append(C.card(item, { onEdit: select, actionLabel: "选择" }));
      }
      if (!assets("preset").length) grid.innerHTML = '<p class="hint">尚未上传参考图片</p>';
      document.body.append(dialog);
      $('[data-close]', dialog).onclick = () => dialog.close();
      dialog.addEventListener("close", () => dialog.remove(), { once: true });
      dialog.showModal();
    }
    const toolbar = C.toolbar({ kind: "preset", onChoose: chooseImage,
      beforeUpload(files) { if (bindings().length + files.length > 8) throw new Error("一个预设最多使用 8 张参考图"); },
      onAsset(item) { if (row.isConnected) appendBinding(item.id); },
    });
    $('.field-heading', field).after(toolbar);
    const management = document.createElement("details");
    management.className = "preset-asset-manager";
    management.innerHTML = `<summary>管理已上传图片 ${icon("chevron")}</summary><div data-preset-assets></div>`;
    field.append(management);
    management.ontoggle = () => { if (management.open) gallery($('[data-preset-assets]', management), "preset"); };
    function render() {
      for (const binding of bindings()) {
        binding.classList.add("reference-binding-row");
        $(':scope > .array-object-header', binding).hidden = true;
        $(':scope > .form-grid', binding).hidden = true;
        const id = $('[data-input="asset_id"]', binding).value;
        const item = assets("preset").find(asset => asset.id === id);
        const legacyPrompt = $('[data-input="note"]', binding).value;
        const signature = JSON.stringify([item, legacyPrompt]);
        if (binding.dataset.cardSignature === signature) continue;
        binding.dataset.cardSignature = signature;
        $('.reference-card', binding)?.remove();
        if (!item) { binding.append(Object.assign(document.createElement("p"), { textContent: "参考图片不可用" })); continue; }
        const prompt = [...new Set([item.prompt, legacyPrompt].filter(Boolean))].join(", ");
        binding.append(C.card(item, { prompt,
          onEdit: () => C.editor(item, { prompt, onSaved() {
            if (!binding.isConnected) return;
            const changed = $('[data-input="role"]', binding).value !== "base" || $('[data-input="subject_id"]', binding).value || $('[data-input="note"]', binding).value;
            $('[data-input="role"]', binding).value = "base";
            $('[data-input="subject_id"]', binding).value = "";
            $('[data-input="note"]', binding).value = "";
            if (changed) binding.dispatchEvent(new Event("input", { bubbles: true }));
          } }),
          onRemove: () => $('[data-remove-object]', binding).click(),
        }));
      }
    }
    array.addEventListener("input", render);
    array.addEventListener("change", render);
    new MutationObserver(render).observe(array, { childList: true });
    C.observe(field, render);
    render();
  }

  function presetTypes(root) {
    const list = $('[data-array="presets"]', root);
    if (!list) return;
    let active = state.presetKind || "text_to_image", selected = null, displayed = null;
    const origin = list.closest(".form-grid"), field = list.closest('[data-field="presets"]');
    const manager = document.createElement("div");
    manager.className = "preset-manager";
    manager.innerHTML = `<div class="preset-modebar"><div class="reference-preset-tabs" role="group" aria-label="预设类型"><button type="button" class="button secondary" data-kind="text_to_image">文生图预设</button><button type="button" class="button secondary" data-kind="image_to_image">图生图预设</button></div><span class="hint" data-preset-count></span></div><section class="settings-card preset-defaults"><div class="preset-default-description"><h3 data-default-title></h3></div><div data-preset-defaults></div></section><div class="preset-body"><aside class="settings-card preset-library"><div class="preset-library-heading"><h3>我的预设</h3><button type="button" class="icon-button" data-new-preset aria-label="新建预设" title="新建预设">${icon("plus")}</button></div><label class="preset-search">${icon("search")}<input type="search" data-preset-search placeholder="搜索名称或 tag" aria-label="搜索预设"></label><div class="preset-list" data-preset-list></div></aside><div class="preset-editor" data-preset-editor><div class="settings-card preset-empty" data-preset-empty hidden>${icon("layers")}<h3>还没有预设</h3><p class="hint">保存常用的画面风格，下次创作直接使用。</p><button type="button" class="button secondary" data-empty-new>${icon("plus")}新建预设</button></div></div></div>`;
    root.prepend(manager);
    const editor = $('[data-preset-editor]', manager), defaults = $('[data-preset-defaults]', manager);
    for (const key of ["image_edit_presets_enabled", "default_style", "default_image_edit_preset"]) {
      const item = $(`[data-field="${key}"]`, origin);
      if (item) defaults.append(item);
    }
    editor.append(field);
    origin.hidden = true;
    const search = $('[data-preset-search]', manager), navigation = $('[data-preset-list]', manager);
    const rows = () => [...list.children].filter(node => node.hasAttribute("data-array-object"));
    const input = (row, key) => $(`[data-input="${key}"]`, row);
    const value = (row, key) => input(row, key)?.value || "";
    const typeOf = row => value(row, "preset_type");

    function decorate(row) {
      if (row.dataset.referenceBound) return;
      row.dataset.referenceBound = "true";
      row.classList.add("preset-detail-card");
      const grid = $(":scope > .form-grid", row);
      const fields = [...grid.children];
      grid.className = "preset-field-sections";
      const section = (title, keys, name, advanced = false) => {
        const block = document.createElement(advanced ? "details" : "section");
        block.className = `preset-field-section ${name}`;
        block.innerHTML = advanced ? `<summary>${title}${icon("chevron")}</summary><div class="form-grid"></div>` : `<div class="preset-section-heading"><h3>${title}</h3></div><div class="form-grid"></div>`;
        const target = $(".form-grid", block);
        keys.map(key => fields.find(field => field.dataset.field === key)).filter(Boolean).forEach(field => target.append(field));
        grid.append(block);
      };
      section("预设信息", ["name", "enabled", "description", "tags", "apply_to_image_edit"], "preset-identity");
      section("参考图片", ["reference_bindings", "multi_reference_confirmed"], "preset-bindings");
      section("画面风格", ["positive_prompt_template", "negative_prompt_template"], "preset-prompts");
      section("预设类型", ["preset_type"], "preset-advanced", true);
      $('[data-remove-object]', row).innerHTML = `${icon("close")}移除预设`;
      confirmButton(row);
    }

    function choose(row, reveal = false) {
      selected = row;
      update();
      if (reveal && window.matchMedia("(max-width: 760px)").matches) row.scrollIntoView({ block: "start", behavior: "instant" });
    }
    function update() {
      state.presetKind = active;
      const all = rows();
      all.forEach(decorate);
      const query = search.value.trim().toLocaleLowerCase();
      const kindRows = all.filter(row => typeOf(row) === active);
      const matching = kindRows.filter(row => [value(row, "name"), value(row, "description"), ...row.querySelectorAll('[data-array="tags"] [data-value]')].map(item => typeof item === "string" ? item : item.value).join(" ").toLocaleLowerCase().includes(query));
      if (!matching.includes(selected)) selected = matching.find(row => value(row, "name") === state.presetSelection?.[active]) || matching[0] || null;
      state.presetSelection = { ...state.presetSelection, [active]: selected ? value(selected, "name") : "" };
      manager.querySelectorAll('[data-kind]').forEach(button => button.setAttribute("aria-pressed", String(button.dataset.kind === active)));
      U.motion.segmented($('.reference-preset-tabs', manager));
      $('[data-preset-count]', manager).textContent = `${kindRows.length} 个${active === "text_to_image" ? "文生图" : "图生图"}预设`;
      $('[data-default-title]', manager).textContent = active === "text_to_image" ? "文生图的默认选择" : "图生图默认设置";
      for (const key of ["image_edit_presets_enabled", "default_image_edit_preset"]) $(`[data-field="${key}"]`, defaults).hidden = active !== "image_to_image";
      $('[data-field="default_style"]', defaults).hidden = active !== "text_to_image";
      const defaultName = $(`[data-input="${active === "text_to_image" ? "default_style" : "default_image_edit_preset"}"]`, defaults).value;
      all.forEach(row => {
        row.hidden = row !== selected;
        if (row !== selected && $('.preset-asset-manager', row)) $('.preset-asset-manager', row).open = false;
        row.setAttribute("aria-label", value(row, "name") || "未命名预设");
        $(':scope > .array-object-header > .muted', row).textContent = value(row, "name") || "未命名预设";
        $('[data-field="apply_to_image_edit"]', row).hidden = typeOf(row) !== "text_to_image";
        $(".preset-bindings", row).hidden = typeOf(row) !== "image_to_image" && !$('[data-array="reference_bindings"] [data-array-object]', row);
        $('[data-reference-confirmation]', row).hidden = typeOf(row) !== "image_to_image";
      });
      if (selected && typeOf(selected) === "image_to_image" && !$('.reference-upload-toolbar', selected)) presetImages(selected);
      if (selected && selected !== displayed) U.motion.enter(selected, 3);
      displayed = selected;
      const focused = document.activeElement?.closest('[data-preset-index]');
      const focusedIndex = focused && navigation.contains(focused) ? focused.dataset.presetIndex : null;
      navigation.innerHTML = matching.map(row => `<button type="button" class="preset-list-item ${row === selected ? "active" : ""}" aria-pressed="${row === selected}" data-preset-index="${all.indexOf(row)}"><span class="preset-item-icon">${icon(active === "text_to_image" ? "sparkles" : "images")}</span><span><strong>${e(value(row, "name") || "未命名预设")}</strong><small>${e(value(row, "description") || "")}</small></span>${value(row, "name") === defaultName ? '<span class="preset-badge">默认</span>' : !input(row, "enabled").checked ? '<span class="preset-badge">停用</span>' : ""}</button>`).join("") || '<p class="hint preset-no-match">没有匹配的预设</p>';
      navigation.querySelectorAll('[data-preset-index]').forEach(button => { button.onclick = () => choose(all[Number(button.dataset.presetIndex)], true); });
      if (focusedIndex !== null) $(`[data-preset-index="${focusedIndex}"]`, navigation)?.focus({ preventScroll: true });
      const empty = $('[data-preset-empty]', manager);
      empty.hidden = Boolean(selected);
      $("h3", empty).textContent = query ? "没有匹配的预设" : "还没有这类预设";
      $("p", empty).textContent = query ? "试试其他名称或 tag，也可以清空搜索。" : "新建一个预设，保存常用的画面描述。";
    }
    function addPreset() {
      search.value = "";
      const before = rows();
      $(":scope > [data-add-array]", list).click();
      const added = rows().find(row => !before.includes(row));
      if (!added) return;
      input(added, "preset_type").value = active;
      let name = "新建预设", index = 2;
      const names = before.map(row => value(row, "name"));
      while (names.includes(name)) name = `新建预设 ${index++}`;
      input(added, "name").value = name;
      choose(added, true);
      input(added, "name").dispatchEvent(new Event("input", { bubbles: true }));
      input(added, "name").focus();
      input(added, "name").select();
    }
    $('[data-new-preset]', manager).onclick = addPreset;
    $('[data-empty-new]', manager).onclick = addPreset;
    manager.querySelectorAll('[data-kind]').forEach(button => { button.onclick = () => { active = button.dataset.kind; search.value = ""; selected = null; update(); }; });
    search.addEventListener("input", event => { event.stopPropagation(); update(); });
    search.addEventListener("keydown", event => { if (event.key === "Enter") { event.preventDefault(); event.stopPropagation(); } });
    const changed = event => {
      const row = event.target.closest('[data-array-object]');
      if (event.target.dataset.input === "preset_type" && row && row.parentElement === list) {
        active = event.target.value;
        if (active === "image_to_image") input(row, "apply_to_image_edit").checked = false;
        selected = row;
      }
      update();
    };
    root.addEventListener("input", changed);
    root.addEventListener("change", changed);
    const observer = new MutationObserver(update);
    observer.observe(list, { childList: true });
    const reset = event => {
      if (event.detail.key !== "presets") { update(); return; }
      observer.disconnect();
      root.removeEventListener("input", changed);
      root.removeEventListener("change", changed);
      root.removeEventListener("fieldreset", reset);
      for (const key of ["image_edit_presets_enabled", "default_style", "default_image_edit_preset", "presets"]) origin.append($(`[data-field="${key}"]`, manager));
      manager.remove();
      origin.hidden = false;
      presetTypes(root);
    };
    root.addEventListener("fieldreset", reset);
    root.addEventListener("revealpreset", event => {
      const row = rows().find(item => item.contains(event.target));
      if (row) { active = typeOf(row); search.value = ""; choose(row); }
    });
    update();
  }

  function revealPreset(input) {
    input.dispatchEvent(new Event("revealpreset", { bubbles: true }));
  }

  async function confirmSettings(all, previous) {
    const refs = all.general.references, old = previous.general.references;
    const changed = JSON.stringify(refs.self_reference_ids) !== JSON.stringify(old.self_reference_ids);
    const combination = refs.self_reference_enabled && (refs.allow_chat_material_search || refs.allow_web_material_search || all.style.image_edit_presets_enabled && all.style.presets.some(preset => preset.reference_bindings.length));
    const selfNeeds = (refs.self_reference_ids.length > 1 && changed) || ((refs.self_reference_ids.length > 1 || combination) && !refs.multi_reference_confirmed);
    const presets = all.style.presets.filter(preset => {
      const before = previous.style.presets.find(item => item.name === preset.name);
      return preset.reference_bindings.length > 1 && (!preset.multi_reference_confirmed || JSON.stringify(preset.reference_bindings) !== JSON.stringify(before?.reference_bindings));
    });
    if (!selfNeeds && !presets.length) return true;
    if (!(await confirmMultiple())) {
      if (selfNeeds) refs.self_reference_ids = [...old.self_reference_ids];
      for (const preset of presets) {
        const before = previous.style.presets.find(item => item.name === preset.name);
        preset.reference_bindings = structuredClone(before?.reference_bindings || preset.reference_bindings.slice(0, 1));
        preset.multi_reference_confirmed = before?.multi_reference_confirmed || false;
      }
      return false;
    }
    if (selfNeeds) refs.multi_reference_confirmed = true;
    presets.forEach(preset => { preset.multi_reference_confirmed = true; });
    return true;
  }

  U.referenceUI = { refreshPickers, gallery, options, confirmButton, presetTypes, revealPreset, confirmSettings, confirmMultiple };
})();
