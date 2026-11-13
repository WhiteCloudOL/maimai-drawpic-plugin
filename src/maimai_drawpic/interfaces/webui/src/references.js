(() => {
  "use strict";
  const U = window.DrawpicUI, { state, $, e, icon, call, toast } = U;
  const notice = "该配置会向绘图模型发送多张参考图。请确认所用服务商及具体模型支持多图参考。插件会校验图生图能力，但不自动探测多图兼容性；切换模型后请重新核实。";

  function confirmMultiple() {
    const dialog = document.createElement("dialog");
    dialog.className = "reference-confirm";
    const model = state.data?.settings.general.default_model || state.data?.default_model;
    dialog.innerHTML = `<div class="modal-header"><h2>确认多图参考能力</h2></div><div class="reference-dialog-body"><p>${e(notice)}</p>${model ? `<p class="hint">当前默认模型：${e(model)}</p>` : ""}<div class="modal-footer"><button type="button" class="button secondary" data-cancel>取消</button><button type="button" class="button" data-confirm>已确认支持</button></div></div>`;
    document.body.append(dialog);
    return new Promise((resolve) => {
      let accepted = false;
      $("[data-cancel]", dialog).onclick = () => dialog.close();
      $("[data-confirm]", dialog).onclick = () => { accepted = true; dialog.close(); };
      dialog.addEventListener("close", () => { dialog.remove(); resolve(accepted); }, { once: true });
      dialog.showModal();
    });
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
    let page = 0, version = 0;
    async function mutate(operation, item = {}, source = "") {
      const result = await call("action", "reference_update", {
        operation, revision: state.data.reference_assets.revision,
        asset_json: JSON.stringify(item), source_id: source,
      });
      state.data.reference_assets = result;
      refreshPickers();
      render();
    }
    function edit(item) {
      const dialog = document.createElement("dialog");
      dialog.className = "reference-confirm";
      dialog.innerHTML = `<form><div class="modal-header"><h2>编辑参考图片</h2></div><div class="reference-dialog-body"><div class="field"><label>图片名称<input name="name" value="${e(item.name)}" maxlength="80" required></label></div><div class="field"><label>Tag（逗号分隔）<input name="tags" value="${e(item.tags.join(", "))}"></label></div><div class="field"><label>替换图片（可选）<input name="replacement" type="file" accept="image/png,image/jpeg,image/webp"></label><p class="hint">替换后保留图片标识、默认项和预设引用；已经开始的任务仍使用读取的版本。</p></div><div class="modal-footer"><button type="button" class="button secondary" data-cancel>取消</button><button class="button" type="submit">保存图片信息</button></div></div></form>`;
      document.body.append(dialog);
      $("[data-cancel]", dialog).onclick = () => dialog.close();
      $("form", dialog).onsubmit = event => {
        event.preventDefault();
        U.buttonAction($("[type=submit]", dialog), async () => {
          const file = $('[name="replacement"]', dialog).files[0];
          const source = file ? (await call("upload", "source", {}, file)).source_id : "";
          await mutate("save", { asset_id: item.id, kind, name: $("[name=name]", dialog).value,
            tags: $("[name=tags]", dialog).value.split(/[,，]/).map(value => value.trim()).filter(Boolean) }, source);
          dialog.close();
        });
      };
      dialog.addEventListener("close", () => dialog.remove(), { once: true });
      dialog.showModal();
    }
    function render() {
      const current = ++version, entries = assets(kind), snapshot = state.data.reference_assets;
      page = Math.min(page, Math.max(0, Math.ceil(entries.length / 12) - 1));
      root.innerHTML = `<div class="reference-gallery-header"><h3>${kind === "self" ? "自我参考图库" : "图生图预设图片"}</h3><button type="button" class="button secondary compact" data-upload>${icon("upload")}上传图片</button><input data-file type="file" accept="image/png,image/jpeg,image/webp" hidden multiple></div><p class="hint">${kind === "self" ? "确认描绘机器人自身后才使用图库。Tag 未命中时使用默认图；已有图库不会自动开启功能。" : "先上传图片，再在图生图预设中选择图片及用途。文生图预设只保存文字模板。"}图片管理单独保存；设置开关与预设编辑仍通过“保存全部设置”生效。</p><div class="reference-gallery">${entries.slice(page * 12, page * 12 + 12).map(item => `<article class="reference-card" data-asset="${e(item.id)}"><div class="reference-thumbnail"><img alt="${e(item.name)}" loading="lazy" hidden><span class="hint" data-loading>正在读取预览</span></div><strong>${e(item.name)}</strong><div class="hint reference-tags">${e(item.tags.join(" · ") || "未设置 tag")}</div>${snapshot.default_reference_id === item.id ? '<span class="pill">默认自我参考</span>' : ""}<div class="reference-card-actions"><button type="button" class="button secondary compact" data-edit>编辑</button>${kind === "self" && snapshot.default_reference_id !== item.id ? '<button type="button" class="button secondary compact" data-default>设为默认</button>' : ""}<button type="button" class="icon-button" data-up aria-label="上移图片">↑</button><button type="button" class="icon-button" data-delete aria-label="删除图片">${icon("close")}</button></div></article>`).join("") || '<p class="muted">尚未上传参考图片。</p>'}</div>${entries.length > 12 ? '<div class="reference-paging"><button type="button" class="button secondary compact" data-prev>上一页</button><span data-page></span><button type="button" class="button secondary compact" data-next>下一页</button></div>' : ""}`;
      $("[data-upload]", root).onclick = () => $("[data-file]", root).click();
      $("[data-file]", root).onchange = event => U.buttonAction($("[data-upload]", root), async () => {
        for (const file of event.target.files) {
          const uploaded = await call("upload", "source", {}, file);
          await mutate("save", { name: file.name.slice(0, 80), kind, tags: [] }, uploaded.source_id);
        }
        toast("参考图片已保存");
      });
      if ($("[data-prev]", root)) {
        $("[data-page]", root).textContent = `${page + 1} / ${Math.ceil(entries.length / 12)}`;
        $("[data-prev]", root).disabled = page === 0;
        $("[data-next]", root).disabled = (page + 1) * 12 >= entries.length;
        $("[data-prev]", root).onclick = () => { page--; render(); };
        $("[data-next]", root).onclick = () => { page++; render(); };
      }
      root.querySelectorAll("[data-asset]").forEach(card => {
        const item = entries.find(entry => entry.id === card.dataset.asset);
        $("[data-edit]", card).onclick = () => edit(item);
        const run = (button, operation, values) => { button.onclick = () => U.buttonAction(button, () => mutate(operation, values)); };
        if ($("[data-default]", card)) run($("[data-default]", card), "default", { asset_id: item.id });
        const index = entries.findIndex(entry => entry.id === item.id);
        $("[data-up]", card).disabled = index === 0;
        run($("[data-up]", card), "move", { asset_id: item.id, position: snapshot.assets.findIndex(entry => entry.id === entries[Math.max(0, index - 1)].id) });
        run($("[data-delete]", card), "delete", { asset_id: item.id });
        call("query", "reference_image", { asset_id: item.id }).then(result => {
          if (current !== version || !card.isConnected) return;
          $("img", card).src = result.preview;
          $("img", card).hidden = false;
          $("[data-loading]", card).remove();
        }).catch(error => { if (current === version && card.isConnected) $("[data-loading]", card).textContent = error.message; });
      });
    }
    render();
  }

  function confirmButton(root) {
    const field = $('[data-field="multi_reference_confirmed"]', root);
    if (!field) return;
    field.hidden = true;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "button secondary compact";
    button.dataset.referenceConfirmation = "true";
    button.textContent = "确认与其他图片合用";
    button.onclick = async () => {
      if (await confirmMultiple()) {
        $('[data-input="multi_reference_confirmed"]', field).checked = true;
        field.dispatchEvent(new Event("input", { bubbles: true }));
        toast("已确认，保存全部设置后生效；切换模型后请重新核实");
      }
    };
    field.after(button);
  }

  function presetTypes(root) {
    const list = $('[data-array="presets"]', root);
    if (!list) return;
    let active = state.presetKind || "text_to_image", initialized = false;
    const toolbar = document.createElement("div");
    toolbar.className = "reference-preset-tabs";
    toolbar.innerHTML = '<button type="button" class="button secondary" data-kind="text_to_image">文生图预设</button><button type="button" class="button secondary" data-kind="image_to_image">图生图预设</button>';
    list.before(toolbar);
    function update() {
      state.presetKind = active;
      toolbar.querySelectorAll("button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.kind === active)));
      for (const row of [...list.children].filter(node => node.hasAttribute("data-array-object"))) {
        const type = $('[data-input="preset_type"]', row);
        if (!type) continue;
        if (!row.dataset.referenceBound) {
          row.dataset.referenceBound = "true";
          if (initialized && active === "image_to_image") type.value = active;
          confirmButton(row);
          type.addEventListener("change", () => {
            active = type.value;
            if (active === "image_to_image") $('[data-input="apply_to_image_edit"]', row).checked = false;
            update();
          });
        }
        row.hidden = type.value !== active;
        $('[data-field="apply_to_image_edit"]', row).hidden = type.value !== "text_to_image";
        const bindings = $('[data-field="reference_bindings"]', row);
        bindings.hidden = type.value !== "image_to_image" && !bindings.querySelector("[data-array-object]");
        $('[data-reference-confirmation]', row).hidden = type.value !== "image_to_image";
      }
      for (const key of ["image_edit_presets_enabled", "default_image_edit_preset"])
        $(`[data-field="${key}"]`, root).hidden = active !== "image_to_image";
      $('[data-field="default_style"]', root).hidden = active !== "text_to_image";
      const gallery = $(".reference-preset-gallery", root);
      if (gallery) gallery.hidden = active !== "image_to_image";
      initialized = true;
    }
    toolbar.querySelectorAll("button").forEach(button => { button.onclick = () => { active = button.dataset.kind; update(); }; });
    const observer = new MutationObserver(update);
    observer.observe(list, { childList: true, subtree: true });
    const reset = event => {
      if (event.detail.key !== "presets") return;
      observer.disconnect();
      toolbar.remove();
      root.removeEventListener("fieldreset", reset);
      presetTypes(root);
    };
    root.addEventListener("fieldreset", reset);
    update();
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

  U.referenceUI = { gallery, options, confirmButton, presetTypes, confirmSettings, confirmMultiple };
})();
