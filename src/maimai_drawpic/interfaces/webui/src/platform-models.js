(() => {
  "use strict";
  const U = window.DrawpicUI, { $, e, icon, call, state } = U;
  let sequence = 0;

  function picker(form, { kind, record, catalog, clearApiKey }) {
    const version = state.modalVersion;
    const fromPreset = !catalog.model_discovery && catalog.model_presets?.length > 0;
    const dialog = document.createElement("dialog");
    const titleId = `model-picker-${++sequence}`;
    dialog.className = "model-picker";
    dialog.setAttribute("aria-labelledby", titleId);
    dialog.innerHTML = `<div class="modal-header">
      <h2 id="${titleId}">选择 ${e(catalog.name)} 模型</h2>
      <button type="button" class="icon-button" data-close aria-label="关闭模型选择">${icon("close")}</button>
    </div>
    <div class="model-picker-content">
      <p class="hint">${fromPreset ? "从官方模型预设选择，勾选后加入同一模型列表；保存平台后生效。" : "从接口读取模型，勾选后加入草稿；保存平台后生效。"}</p>
      <div class="model-picker-filters">
        <input type="search" data-search aria-label="搜索模型" placeholder="搜索模型 ID 或名称…">
        <label class="inline-choice"${fromPreset ? " hidden" : ""}><input type="checkbox" role="switch" class="toggle" data-images-only>仅显示可能的绘图模型</label>
      </div>
      <div class="model-picker-results">
        <div class="model-picker-summary">
          <p class="hint" data-count aria-live="polite"></p>
          <p class="hint" data-status role="status" aria-live="polite">正在获取模型…</p>
        </div>
        <div class="model-picker-list" data-model-list role="group" aria-label="${fromPreset ? "预设模型" : "接口返回的模型"}" tabindex="0"></div>
      </div>
      <p class="hint model-picker-selection-hint">全选当前筛选结果；清空取消全部新勾选，已有模型保留。</p>
    </div>
    <div class="modal-footer model-picker-footer">
      <div class="model-picker-toolbar">
        <button type="button" class="button secondary compact" data-select-visible disabled>选择全部</button>
        <button type="button" class="button ghost compact" data-clear-selection disabled>清空选择</button>
      </div>
      <div class="model-picker-submit">
        <button type="button" class="button secondary" data-retry hidden>重新获取</button>
        <button type="button" class="button secondary" data-cancel>取消</button>
        <button type="button" class="button" data-apply disabled>添加所选模型</button>
      </div>
    </div>`;
    const existing = new Set(U.formCollections.models(form).map((model) => model.id));
    const selected = new Set();
    const list = $("[data-model-list]", dialog), status = $("[data-status]", dialog);
    $("[data-search]", dialog).classList.add("search-input");
    let models = [];
    const current = () => dialog.isConnected && dialog.open && form.isConnected && version === state.modalVersion;
    function visibleModels() {
      const query = $("[data-search]", dialog).value.trim().toLocaleLowerCase();
      return models.filter((model) =>
        (!$("[data-images-only]", dialog).checked || model.image_candidate) &&
        (!query || `${model.id} ${model.label}`.toLocaleLowerCase().includes(query)),
      );
    }
    function updateCount() {
      $("[data-count]", dialog).textContent = `显示 ${visibleModels().length} / ${models.length} 个 · 已选 ${selected.size} 个新模型`;
      $("[data-apply]", dialog).disabled = selected.size === 0;
      $("[data-select-visible]", dialog).disabled = !visibleModels().some((model) => !existing.has(model.id));
      $("[data-clear-selection]", dialog).disabled = selected.size === 0;
    }
    function renderList() {
      list.innerHTML = visibleModels().map((model) => {
        const added = existing.has(model.id);
        return `<label class="model-picker-item"><input type="checkbox" data-model-id="${e(model.id)}" ${added || selected.has(model.id) ? "checked" : ""} ${added ? "disabled" : ""}><span><strong>${e(model.label)}</strong>${model.label !== model.id ? `<small>${e(model.id)}</small>` : ""}${added ? '<small>已在当前模型列表中</small>' : ""}</span></label>`;
      }).join("") || '<p class="hint">没有匹配的模型，可修改搜索条件或关闭绘图模型筛选。</p>';
      updateCount();
    }
    async function load() {
      $("[data-retry]", dialog).hidden = true;
      list.setAttribute("aria-busy", "true");
      status.textContent = fromPreset ? "正在读取预设…" : "正在获取模型…";
      try {
        const config = { api_key: $('[data-input="api_key"]', form)?.value || "" };
        const base = $('[data-input="base_url"]', form);
        if (base) config.base_url = base.value;
        const result = fromPreset ? {
          models: catalog.model_presets.map((id) => ({ id, label: id, image_candidate: true })),
        } : await call("query", "provider_models", {
          provider_json: JSON.stringify({ id: record?.id || "", kind, config, clear_api_key: clearApiKey() }),
        });
        if (!current()) return;
        models = result.models;
        $("[data-images-only]", dialog).checked = models.some((model) => model.image_candidate);
        status.textContent = fromPreset ? catalog.model_presets_hint : models.length
          ? kind === "aliyun"
            ? "百炼在线目录，仅含插件已接入的图像模型，不代表账号已开通权限。"
            : "目录已在线获取；名称筛选不代表绘图能力或账号权限。"
          : "接口没有返回可导入的图片模型，请检查账号权限，或返回手动添加。";
        renderList();
      } catch (error) {
        if (current()) {
          status.textContent = error.message || String(error);
          $("[data-retry]", dialog).hidden = false;
        }
      } finally {
        if (current()) list.removeAttribute("aria-busy");
      }
    }
    $("[data-search]", dialog).oninput = renderList;
    $("[data-images-only]", dialog).onchange = renderList;
    list.onchange = (event) => {
      const input = event.target.closest("[data-model-id]");
      if (!input || input.disabled) return;
      if (input.checked) selected.add(input.dataset.modelId);
      else selected.delete(input.dataset.modelId);
      updateCount();
    };
    $("[data-select-visible]", dialog).onclick = () => {
      for (const model of visibleModels()) if (!existing.has(model.id)) selected.add(model.id);
      renderList();
    };
    $("[data-clear-selection]", dialog).onclick = () => { selected.clear(); renderList(); };
    $("[data-retry]", dialog).onclick = () => U.buttonAction($("[data-retry]", dialog), load);
    $("[data-apply]", dialog).onclick = () => {
      if (!current()) return;
      U.forms.appendArray(form, "models", [...selected], { platform: true, kind });
      U.toast(`已添加 ${selected.size} 个模型，保存平台后生效`);
      dialog.close();
    };
    const parent = $("#modal"), close = () => dialog.close();
    $("[data-close]", dialog).onclick = close;
    $("[data-cancel]", dialog).onclick = close;
    parent.addEventListener("close", close);
    dialog.addEventListener("close", () => {
      parent.removeEventListener("close", close);
      dialog.remove();
    }, { once: true });
    document.body.append(dialog);
    dialog.showModal();
    void load();
  }

  function bind(form, { kind, record, catalog }) {
    let pending = false, previousInput = "";
    const input = $('[data-input="api_key"]', form);
    const clearApiKey = () => pending;
    if (input) {
      const wrapper = document.createElement("div"), button = document.createElement("button");
      const hint = document.createElement("p");
      wrapper.className = "secret-input-row";
      input.replaceWith(wrapper);
      wrapper.append(input, button);
      button.type = "button";
      button.className = "button secondary compact";
      hint.className = "hint";
      hint.setAttribute("role", "status");
      wrapper.after(hint);
      function update() {
        button.textContent = pending ? "撤销清空" : "清空密钥";
        button.setAttribute("aria-pressed", String(pending));
        button.disabled = !pending && !record?.has_api_key && !input.value;
        input.placeholder = pending ? "保存后清空已保存的密钥" : record?.has_api_key ? "留空保留已保存的密钥" : "填写 API 密钥";
        hint.textContent = pending ? "已标记清空，保存平台后生效；也可以撤销或填写新密钥。" : "";
        hint.hidden = !pending;
      }
      button.onclick = () => {
        if (pending) {
          pending = false;
          input.value = previousInput;
        } else {
          previousInput = input.value;
          input.value = "";
          pending = Boolean(record?.has_api_key);
        }
        input.dispatchEvent(new Event("input", { bubbles: true }));
        update();
      };
      input.addEventListener("input", () => {
        if (input.value) pending = false;
        update();
      });
      update();
    }
    const field = $('[data-field="models"]', form);
    if (field) {
      const toolbar = document.createElement("div");
      toolbar.className = "collection-toolbar";
      if (catalog.model_discovery || catalog.model_presets?.length) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "button secondary compact";
        button.innerHTML = catalog.model_discovery
          ? `${icon("refresh")}从接口获取模型`
          : `${icon("plus")}从预设添加模型`;
        button.onclick = () => picker(form, { kind, record, catalog, clearApiKey });
        toolbar.append(button);
      } else {
        const hint = document.createElement("p");
        hint.className = "hint";
        hint.textContent = catalog.model_discovery_hint || "此平台请手动添加模型。";
        toolbar.append(hint);
      }
      $('[data-array="models"]', field).before(toolbar);
    }
    return { clearApiKey };
  }
  U.platformModels = { bind };
})();
