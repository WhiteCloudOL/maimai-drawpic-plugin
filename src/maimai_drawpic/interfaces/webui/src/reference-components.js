(() => {
  "use strict";
  const U = window.DrawpicUI, { state, $, e, icon, call } = U;
  const views = new Map();
  function observe(root, render) {
    for (const element of views.keys()) if (!element.isConnected) views.delete(element);
    views.set(root, render);
  }
  function refresh() {
    U.referenceUI.refreshPickers();
    for (const [root, render] of views) {
      if (root.isConnected) render();
      else views.delete(root);
    }
  }
  async function update(operation, item = {}, source = "") {
    const snapshot = await call("action", "reference_update", {
      operation, revision: state.data.reference_assets.revision,
      asset_json: JSON.stringify(item), source_id: source,
    });
    state.data.reference_assets = snapshot;
    refresh();
    return snapshot;
  }
  function toolbar({ kind, beforeUpload = () => {}, onAsset = () => {}, onChoose = null }) {
    const root = document.createElement("div");
    root.className = "reference-upload-toolbar";
    root.innerHTML = `<button type="button" class="button secondary compact" data-upload>${icon("upload")}上传图片</button>${onChoose ? `<button type="button" class="button ghost compact" data-choose>${icon("images")}选择已有图片</button>` : ""}<input type="file" accept="image/png,image/jpeg,image/webp" multiple hidden>`;
    const input = $('input', root), button = $('[data-upload]', root);
    button.onclick = () => input.click();
    if (onChoose) $('[data-choose]', root).onclick = onChoose;
    input.onchange = () => U.buttonAction(button, async () => {
      const files = Array.from(input.files);
      try {
        beforeUpload(files);
        for (const file of files) {
          const upload = await call("upload", "source", {}, file);
          const snapshot = await update("save", { kind, name: file.name.slice(0, 80), tags: [], prompt: "" }, upload.source_id);
          onAsset(snapshot.assets.at(-1));
        }
        if (files.length) U.toast("图片已上传");
      } finally { input.value = ""; }
    });
    return root;
  }
  function card(item, { onEdit, onOpen = onEdit, onRemove = null, onDefault = null, onUp = null, isDefault = false, actionLabel = "编辑", prompt = item.prompt || "" } = {}) {
    const root = document.createElement("article");
    root.className = "reference-card";
    root.dataset.asset = item.id;
    root.innerHTML = `<button type="button" class="reference-card-open" aria-label="${e(actionLabel)}参考图片：${e(item.name)}"><div class="reference-thumbnail"><img alt="" hidden><span class="hint" data-loading>正在读取预览</span></div><strong>${e(item.name)}</strong>${prompt ? `<span class="reference-prompt">${e(prompt)}</span>` : ""}${item.kind === "self" && item.tags.length ? `<span class="hint reference-tags">${e(item.tags.join(" · "))}</span>` : ""}</button>${isDefault ? '<span class="pill">默认自我参考</span>' : ""}<div class="reference-card-actions"><button type="button" class="button secondary compact" data-edit>${e(actionLabel)}</button>${onDefault ? '<button type="button" class="button secondary compact" data-default>设为默认</button>' : ""}${onUp ? '<button type="button" class="icon-button" data-up aria-label="上移图片">↑</button>' : ""}${onRemove ? `<button type="button" class="icon-button" data-remove-image aria-label="移除图片">${icon("close")}</button>` : ""}</div>`;
    $('.reference-card-open', root).onclick = onOpen;
    $('[data-edit]', root).onclick = onEdit;
    if (onRemove) $('[data-remove-image]', root).onclick = onRemove;
    if (onDefault) $('[data-default]', root).onclick = onDefault;
    if (onUp) $('[data-up]', root).onclick = onUp;
    call("query", "reference_image", { asset_id: item.id }).then(result => {
      if (!root.isConnected) return;
      $('img', root).src = result.preview;
      $('img', root).hidden = false;
      $('[data-loading]', root).hidden = true;
    }).catch(error => { if (root.isConnected) $('[data-loading]', root).textContent = error.message; });
    return root;
  }
  function editor(item, { prompt = item.prompt || "", onSaved = () => {} } = {}) {
    const dialog = document.createElement("dialog");
    dialog.className = "reference-confirm reference-image-editor";
    dialog.setAttribute("aria-label", "编辑参考图片");
    const fields = {
      prompt: { type: "string", default: "", label: "参考提示词（可选）", input_type: "textarea", rows: 3, hint: "填写希望保留的特征，也可以留空。" },
      name: { type: "string", default: "", label: "图片名称" },
      ...(item.kind === "self" ? { tags: { type: "string", default: "", label: "Tag（逗号分隔）" } } : {}),
    };
    const values = { prompt, name: item.name, ...(item.kind === "self" ? { tags: item.tags.join(", ") } : {}) };
    const metadata = Object.fromEntries(Object.entries(fields).filter(([key]) => key !== "prompt"));
    dialog.innerHTML = `<form><div class="modal-header"><h2>编辑参考图片</h2><button type="button" class="icon-button" data-close aria-label="关闭弹窗">${icon("close")}</button></div><div class="reference-dialog-body"><div class="reference-editor-preview"></div><button type="button" class="button secondary compact" data-replace>${icon("upload")}替换图片</button><input type="file" accept="image/png,image/jpeg,image/webp" hidden data-file>${U.forms.html({ prompt: fields.prompt }, values)}<details class="reference-image-info"><summary>图片信息 ${icon("chevron")}</summary>${U.forms.html(metadata, values)}</details><div class="modal-footer"><button type="button" class="button secondary" data-cancel>取消</button><button type="submit" class="button">保存图片</button></div></div></form>`;
    document.body.append(dialog);
    const form = $('form', dialog), read = U.forms.bind(form, fields, values, { trackDirty: false });
    const file = $('[data-file]', dialog), preview = $('.reference-editor-preview', dialog);
    $('[data-input="prompt"]', form).maxLength = 500;
    $('[data-input="name"]', form).required = true;
    $('[data-input="name"]', form).maxLength = 80;
    let localUrl = "";
    call("query", "reference_image", { asset_id: item.id }).then(result => {
      if (dialog.isConnected && !file.files.length) preview.innerHTML = `<img src="${e(result.preview)}" alt="参考图片预览">`;
    }).catch(error => { if (dialog.isConnected && !file.files.length) preview.textContent = error.message; });
    $('[data-replace]', dialog).onclick = () => file.click();
    file.onchange = () => {
      if (localUrl) URL.revokeObjectURL(localUrl);
      localUrl = file.files.length ? URL.createObjectURL(file.files[0]) : "";
      if (localUrl) preview.innerHTML = `<img src="${e(localUrl)}" alt="替换图片预览">`;
    };
    $('[data-close]', dialog).onclick = $('[data-cancel]', dialog).onclick = () => dialog.close();
    form.onsubmit = event => {
      event.preventDefault();
      U.buttonAction($('[type="submit"]', form), async () => {
        const value = read();
        form.inert = true;
        try {
          const upload = file.files.length ? await call("upload", "source", {}, file.files[0]) : null;
          const snapshot = await update("save", { asset_id: item.id, kind: item.kind, name: value.name, prompt: value.prompt,
            tags: item.kind === "self" ? value.tags.split(/[,，]/).map(tag => tag.trim()).filter(Boolean) : item.tags }, upload?.source_id || "");
          onSaved(snapshot.assets.find(asset => asset.id === item.id));
          dialog.close();
          U.toast("图片已保存");
        } finally { form.inert = false; }
      });
    };
    dialog.addEventListener("close", () => { if (localUrl) URL.revokeObjectURL(localUrl); dialog.remove(); }, { once: true });
    U.bindSubmit(form, { shortcutOnly: true });
    dialog.showModal();
    U.selects.refresh(dialog);
  }
  U.referenceComponents = { observe, refresh, update, toolbar, card, editor };
})();
