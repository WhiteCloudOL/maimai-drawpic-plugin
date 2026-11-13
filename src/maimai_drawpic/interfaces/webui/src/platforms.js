(() => {
  "use strict";
  const U = window.DrawpicUI,
    { state, $, e, icon, call, modal, closeModal, buttonAction, toast } = U;
  async function editor(kind, record = null, reset = false) {
    const catalog = state.data.catalog.find((item) => item.kind === kind);
    const baseName = catalog.default_name;
    let defaultName = baseName;
    let suffix = 2;
    while (
      state.data.providers.some(
        (item) =>
          item.id !== record?.id &&
          item.name.trim().toLocaleLowerCase() ===
          defaultName.toLocaleLowerCase(),
      )
    )
      defaultName = `${baseName}_${suffix++}`;
    const values = structuredClone(
      reset ? catalog.defaults : record?.config || catalog.defaults,
    );
    const fields = Object.fromEntries(
      Object.entries(state.data.schema.sections[kind].fields).filter(
        ([key]) => key !== "enabled",
      ),
    );
    // 启用状态由卡片独立管理，恢复参数默认也不能改变已有平台的状态。
    values.enabled = record ? record.config.enabled : true;
    delete values.instances;
    const fieldsHTML = kind === "comfyui" ? U.comfyuiForm.html(fields, values) : U.forms.html(fields, values, { platform: true, kind });
    const node = modal(
      record ? "编辑绘图平台" : "添加绘图平台",
      `<form id="provider-form"><div class="provider-form-body"><div class="field"><label for="provider-name">平台名称</label><input id="provider-name" maxlength="80" required pattern="[^\\s]+" aria-describedby="provider-name-hint" value="${e(record?.name || defaultName)}" placeholder="例如 OpenAI_Compatible、日常绘图、备用_API"><p class="hint" id="provider-name-hint">支持中文、英文，名称不能包含空格，可使用下划线 _。</p></div>${fieldsHTML}</div><div class="modal-footer provider-footer"><div class="provider-footer-reset"><button type="button" id="reset-provider" class="button secondary">${icon("refresh")}恢复默认参数</button><span data-unsaved class="unsaved" hidden>有未保存的修改</span></div><div class="provider-footer-actions"><button type="button" id="provider-back" class="button secondary">取消</button><button type="submit" class="button">${icon("check")}保存平台</button></div></div></form>`,
    );
    const form = $("#provider-form", node),
      read = U.forms.bind(form, fields, values, { platform: true, kind });
    if (kind === "comfyui") U.comfyuiForm.bind(form);
    const keyControls = U.platformModels.bind(form, { kind, record, catalog });
    const nameInput = $("#provider-name", form);
    const nameControls = document.createElement("div");
    const nameValue = document.createElement("div");
    const resetName = document.createElement("button");
    nameControls.className = "field-controls";
    nameValue.className = "field-control-value";
    resetName.type = "button";
    resetName.className = "icon-button field-reset";
    resetName.title = "恢复默认值";
    resetName.setAttribute("aria-label", "恢复平台名称的默认值");
    resetName.innerHTML = icon("reset");
    nameInput.replaceWith(nameControls);
    nameControls.append(nameValue, resetName);
    nameValue.append(nameInput);
    resetName.onclick = () => {
      nameInput.value = defaultName;
      nameInput.dispatchEvent(new Event("input", { bubbles: true }));
      toast("已恢复平台名称默认值，保存后生效");
    };
    nameInput.addEventListener("input", () => {
      nameInput.setCustomValidity(/\s/.test(nameInput.value) ? "平台名称不能包含空格，可使用下划线 _" : "");
      resetName.hidden = nameInput.value === defaultName;
    });
    resetName.hidden = nameInput.value === defaultName;
    const modalVersion = state.modalVersion,
      revision = state.data.revision;
    const current = () =>
      form.isConnected && modalVersion === state.modalVersion;
    let saving = false;
    $("#provider-back", node).onclick = () => {
      closeModal();
    };
    $("#reset-provider", node).onclick = () => {
      state.dirty = false;
      editor(kind, record, true).catch(U.error);
    };
    if (reset) {
      state.dirty = true;
      $("[data-unsaved]", form).hidden = false;
      toast("已恢复参数默认值，保存后生效；已有 API Key 保留");
    }
    U.bindSubmit(form);
    form.onsubmit = (event) => {
      event.preventDefault();
      if (saving || !current()) return;
      buttonAction($("[type=submit]", form), async () => {
        const config = read();
        delete config.instances;
        saving = true;
        form.inert = true;
        form.setAttribute("aria-busy", "true");
        try {
          const result = await call("action", "provider_save", {
            provider_json: JSON.stringify({
              id: record?.id || "",
              kind,
              name: $("#provider-name", form).value,
              config,
              clear_api_key: keyControls.clearApiKey(),
            }),
            revision,
          });
          // RPC 已确认提交，即使后续读取失败也不能把它当作保存失败重试。
          if (current()) state.dirty = false;
          let refreshError = null;
          try {
            await U.bootstrap();
            // 关闭或替换编辑器后，旧保存不能清除新草稿或关闭新弹窗。
            if (current()) {
              await closeModal(true);
              await U.render();
            }
          } catch (error) {
            refreshError = error;
            if (current()) await closeModal(true);
          }
          U.savedNotice(result, "平台已保存", refreshError);
        } finally {
          saving = false;
          if (current()) {
            form.inert = false;
            form.removeAttribute("aria-busy");
          }
        }
      });
    };
  }
  function addPlatform() {
    const node = modal(
      "选择绘图平台",
      `<div class="catalog-grid">${state.data.catalog
        .map((item) => {
          const added = false;
          return `<button class="catalog-option" data-kind="${e(item.kind)}" ${added ? "disabled" : ""}><span class="provider-icon">${e(item.name.slice(0, 1))}</span><span>${e(item.name)}<small>${added ? "已添加，可在平台卡片中编辑" : item.kind === "openai" ? "OpenAI、New API 等兼容服务" : "添加并配置模型"}</small></span></button>`;
        })
        .join("")}</div>`,
    );
    node.querySelectorAll("[data-kind]").forEach((button) => {
      button.onclick = () => editor(button.dataset.kind);
    });
  }
  U.views.platforms = async () => {
    const items = state.data.providers;
    const revision = state.data.revision;
    $("#workspace-content").innerHTML =
      `<div class="toolbar"><span class="muted">已添加 ${items.length} 个平台</span><button id="add-platform" class="button">${icon("plus")}添加平台</button></div><div class="card-grid">${items
        .map((item) => {
          const kind = state.data.catalog.find((c) => c.kind === item.kind);
          const models =
            item.config.models || (item.kind === "comfyui" ? ["comfyui"] : []);
          let host = item.config.base_url || "";
          try {
            host = new URL(host).host;
          } catch {
            /* 非 URL 的配置仍作为纯文本显示。 */
          }
          return `<article class="panel provider-card" data-provider="${e(item.id)}"><div class="provider-top"><span class="provider-icon">${e(kind.name.slice(0, 1))}</span><div class="provider-name"><h3>${e(item.name)}</h3><small>${e(kind.name)}</small></div><button type="button" class="provider-switch" data-toggle role="switch" aria-checked="${item.config.enabled}" aria-label="启用平台：${e(item.name)}"><span class="provider-switch-track" aria-hidden="true"></span></button></div><div class="provider-endpoint">${e(host || "使用平台默认地址")}</div><div class="provider-models">${models
            .slice(0, 4)
            .map((model) => `<span class="pill">${e(model)}</span>`)
            .join(
              "",
            )}${models.length > 4 ? `<span class="pill">+${models.length - 4}</span>` : ""}</div><p class="hint">${item.kind === "comfyui" ? "ComfyUI 工作流" : item.has_api_key ? "密钥已配置" : "尚未填写 API Key"}</p><div class="actions"><button class="button secondary compact" data-edit>编辑配置</button><button class="button ghost compact" data-delete>移除</button></div></article>`;
        })
        .join(
          "",
        )}<button class="add-card" id="add-platform-card"><span>${icon("plus")}<br>添加另一个平台</span></button></div>`;
    $("#add-platform").onclick = addPlatform;
    $("#add-platform-card").onclick = addPlatform;
    document.querySelectorAll("[data-provider]").forEach((card) => {
      const item = items.find((item) => item.id === card.dataset.provider);
      $("[data-toggle]", card).onclick = (event) => {
        const button = event.currentTarget;
        buttonAction(button, async () => {
          const enabled = !item.config.enabled;
          card.inert = true;
          button.setAttribute("aria-busy", "true");
          try {
            const result = await call("action", "provider_enabled", {
              provider_id: item.id,
              enabled,
              revision,
            });
            // 写入确认后更新状态；刷新失败也不能显示成保存失败或自动再次切换。
            item.config.enabled = enabled;
            button.setAttribute("aria-checked", String(enabled));
            let refreshError = null;
            try {
              await U.bootstrap();
              if (card.isConnected && state.view === "platforms") await U.render();
            } catch (error) {
              refreshError = error;
            }
            U.savedNotice(result, `平台已${enabled ? "启用" : "停用"}`, refreshError);
          } finally {
            card.inert = false;
            button.removeAttribute("aria-busy");
          }
        });
      };
      $("[data-edit]", card).onclick = () => editor(item.kind, item);
      $("[data-delete]", card).onclick = (event) =>
        buttonAction(event.currentTarget, async () => {
          const result = await call("action", "provider_delete", {
            provider_id: item.id,
            revision: state.data.revision,
          });
          let refreshError = null;
          try {
            await U.bootstrap();
            if (card.isConnected && state.view === "platforms")
              await U.render();
          } catch (error) {
            refreshError = error;
          }
          U.savedNotice(result, "平台已移除", refreshError);
        });
    });
  };
  U.addPlatform = addPlatform;
})();
