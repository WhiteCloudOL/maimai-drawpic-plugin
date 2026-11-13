(() => {
  "use strict";
  const U = window.DrawpicUI,
    { state, $, e, icon, call, buttonAction, toast } = U;
  const sections = { style: "绘图预设", references: "自我参考", materials: "素材来源", general: "运行设置", review: "内容审核", access: "权限额度" };
  const sectionIcons = { style: "sparkles", references: "images", materials: "search", general: "sliders", review: "eye", access: "layers" };
  const sourceSection = name => ["review", "access", "references", "materials"].includes(name) ? "general" : name;
  const reviewField = key => /^(prompt|image)_review_/.test(key);
  const accessField = key => /^(group|private)_access_/.test(key) || /quota/.test(key) || ["admin_user_ids", "permission_enabled"].includes(key);
  const belongsToSection = (name, key) => name === "style" ||
    (name === "references" ? key === "references" : key !== "references") &&
    (name === "review" ? reviewField(key) : name === "access" ? accessField(key) : !reviewField(key) && !accessField(key));

  function fieldGroups(name, fields, values) {
    const used = new Set();
    const group = (title, match, collapsed = false) => {
      const selected = Object.fromEntries(Object.entries(fields).filter(([key]) => !used.has(key) && match(key)));
      Object.keys(selected).forEach(key => used.add(key));
      if (!Object.keys(selected).length) return "";
      const content = U.forms.html(selected, values);
      return collapsed
        ? `<details class="settings-card settings-disclosure"><summary><span>${e(title)}</span>${icon("chevron")}</summary><div class="settings-card-body">${content}</div></details>`
        : `<section class="settings-card"><div class="settings-card-heading"><h3>${e(title)}</h3></div>${content}</section>`;
    };
    let html = "";
    if (name === "general") {
      html += group("默认任务", key => ["default_model", "fallback_model", "fallback_models", "request_retry_count", "request_timeout_seconds"].includes(key));
      html += group("聊天回传", key => ["command_reply_mode", "sync_generated_images_to_history", "failure_reason_enabled"].includes(key));
      html += group("插件联动", key => key === "integration_api_enabled");
      html += group("高级设置", key => /unsupported_models$/.test(key) || key === "skip_image_url_ip_check", true);
    } else if (name === "review") {
      html += group("提示词审核", key => key.startsWith("prompt_review_"));
      html += group("生成图片审核", key => key.startsWith("image_review_"));
    } else if (name === "access") {
      html += group("群聊访问", key => key.startsWith("group_access_"));
      html += group("私聊访问", key => key.startsWith("private_access_"));
      html += group("使用额度", key => /quota/.test(key));
      html += group("管理员", key => ["permission_enabled", "admin_user_ids"].includes(key));
    }
    html += group("其他设置", () => true);
    return html;
  }

  function referenceFields(fields, values) {
    const pick = keys => Object.fromEntries(Object.entries(fields).filter(([key]) => keys.includes(key)));
    return `<section class="settings-card"><div class="settings-card-heading"><h3>自身识别</h3></div>${U.forms.html(pick(["self_reference_enabled", "self_names"]), values)}<details class="recognition-hints"><summary>自定义识别线索 ${icon("chevron")}</summary>${U.forms.html(pick(["self_keywords"]), values)}</details></section>
      <section class="settings-card reference-library-card"><div data-self-gallery></div></section>
      <details class="settings-card settings-disclosure"><summary><span>固定参考组合</span><span class="disclosure-note">可选 ${icon("chevron")}</span></summary><div class="settings-card-body">${U.forms.html(pick(["self_reference_ids", "multi_reference_confirmed"]), values)}</div></details>`;
  }
  function materialFields(fields, values) {
    return `<section class="settings-card">${U.forms.html(fields, values)}</section>`;
  }
  async function showSettings(view) {
    const keys = view === "library" ? ["style", "references", "materials"] : ["general", "review", "access"];
    const preferred = view === "library" ? state.librarySection : state.settingsSection;
    let selected = keys.includes(preferred) ? preferred : keys[0];
    const revision = state.data.revision;
    const working = structuredClone(state.data.settings), baseline = working;
    const readers = {};
    const save = $("#save-settings");
    const navigation = (keys, caption) => `<span class="settings-nav-caption" aria-hidden="true">${caption}</span>${keys.map(name => `<button id="settings-tab-${name}" class="settings-tab" data-section="${name}" role="tab" aria-controls="settings-panel-${name}">${icon(sectionIcons[name])}<span>${e(sections[name])}</span>${icon("chevron")}</button>`).join("")}`;
    $("#workspace-content").innerHTML = `<div class="settings-layout"><nav class="settings-tabs" role="tablist" aria-label="配置分类">${navigation(keys, view === "library" ? "创作资源" : "运行管理")}</nav><section class="settings-workspace"><div class="settings-page-heading"><h2 id="settings-heading"></h2><button type="button" id="reset-settings" class="button secondary compact">${icon("reset")}恢复本类默认</button></div><form id="settings-form"></form></section></div>`;
    const form = $("#settings-form");
    let requiresRefresh = false;
    function renderSection(name, values) {
      const panel = document.createElement("section");
      panel.id = `settings-panel-${name}`;
      panel.dataset.settingsPanel = name;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", `settings-tab-${name}`);
      panel.hidden = name !== selected;
      const materialField = key => key.startsWith("allow_") || ["chat_material_search_limit", "material_model"].includes(key);
      const fields = ["references", "materials"].includes(name) ? Object.fromEntries(Object.entries(state.data.reference_fields).filter(([key]) => name === "materials" ? materialField(key) : !materialField(key))) : Object.fromEntries(
        Object.entries(state.data.schema.sections[sourceSection(name)].fields)
          .filter(([key]) => belongsToSection(name, key)),
      );
      if (name === "references") {
        values = values.references;
        panel.innerHTML = referenceFields(fields, values);
      } else if (name === "materials") {
        values = values.references;
        panel.innerHTML = materialFields(fields, values);
      } else panel.innerHTML = name === "style" ? U.forms.html(fields, values) : fieldGroups(name, fields, values);
      const old = $(`#${panel.id}`, form);
      if (old) old.replaceWith(panel);
      else form.append(panel);
      const read = U.forms.bind(panel, fields, values);
      // 各分类只读取所属字段，再合并为同一份持久配置。
      readers[name] = () => {
        const result = read();
        return Object.fromEntries(Object.keys(fields).map((key) => [key, result[key]]));
      };
      if (name === "references") {
        U.referenceUI.confirmButton(panel);
        U.referenceUI.gallery($("[data-self-gallery]", panel), "self");
      } else if (name === "style") {
        U.referenceUI.presetTypes(panel);
      }
    }
    for (const name of keys)
      renderSection(name, structuredClone(working[sourceSection(name)]));
    function activate(name, reveal = false) {
      const changed = selected !== name;
      selected = name;
      if (view === "library") state.librarySection = name;
      else state.settingsSection = name;
      $("#settings-heading").textContent = sections[name];
      for (const tab of document.querySelectorAll("[data-section]")) {
        const active = tab.dataset.section === name;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
      }
      for (const panel of form.children)
        panel.hidden = panel.dataset.settingsPanel !== name;
      if (changed) U.motion.enter($(`#settings-panel-${name}`, form));
      if (reveal) $("#settings-heading").scrollIntoView({ block: "start", behavior: "instant" });
    }
    const tabs = [...document.querySelectorAll("[data-section]")];
    for (const [index, tab] of tabs.entries()) {
      tab.onclick = () => activate(tab.dataset.section, true);
      tab.onkeydown = (event) => {
        let target;
        if (["ArrowRight", "ArrowDown"].includes(event.key))
          target = (index + 1) % tabs.length;
        else if (["ArrowLeft", "ArrowUp"].includes(event.key))
          target = (index + tabs.length - 1) % tabs.length;
        else if (event.key === "Home") target = 0;
        else if (event.key === "End") target = tabs.length - 1;
        else return;
        event.preventDefault();
        tabs[target].focus();
        activate(tabs[target].dataset.section, true);
      };
    }
    const updateNotice = () => {
      $("#settings-unsaved").hidden = !state.dirty;
    };
    form.addEventListener("input", updateNotice);
    form.addEventListener("click", updateNotice);
    $("#reset-settings").onclick = () => {
      renderSection(selected, structuredClone(state.data.defaults[sourceSection(selected)]));
      state.dirty = true;
      updateNotice();
      toast("已恢复当前分类默认值，其他分类草稿保留，保存后生效");
    };
    const submitAll = () => {
      const invalid = form.querySelector(":invalid");
      if (invalid) {
        activate(invalid.closest("[data-settings-panel]").dataset.settingsPanel);
        U.referenceUI.revealPreset?.(invalid);
        let parent = invalid.parentElement;
        while (parent && parent !== form) {
          if (parent.tagName === "DETAILS") parent.open = true;
          parent = parent.parentElement;
        }
      }
      U.submitForm(form);
    };
    save.onclick = submitAll;
    form.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || event.isComposing) return;
      if (event.ctrlKey || event.metaKey) {
        event.preventDefault();
        submitAll();
      } else if (event.target.tagName === "INPUT") {
        event.preventDefault();
      }
    });
    const readSettings = () => {
      const all = structuredClone(working);
      for (const name of ["general", "review", "access"]) if (readers[name]) Object.assign(all.general, readers[name]());
      for (const name of ["references", "materials"]) if (readers[name]) Object.assign(all.general.references, readers[name]());
      if (readers.style) all.style = readers.style();
      return all;
    };
    form.onsubmit = (event) => {
      event.preventDefault();
      if (form.inert || requiresRefresh || save.disabled) return;
      buttonAction(save, async () => {
        const all = readSettings();
        if (view === "library" && !(await U.referenceUI.confirmSettings(all, baseline))) {
          renderSection("references", { references: all.general.references });
          renderSection("materials", { references: all.general.references });
          renderSection("style", all.style);
          state.dirty = true;
          updateNotice();
          return;
        }
        if (view === "library") {
          $('[data-input="multi_reference_confirmed"]', $("#settings-panel-references")).checked = all.general.references.multi_reference_confirmed;
          const presetRows = $('[data-array="presets"]', $("#settings-panel-style"));
          [...presetRows.children].filter(node => node.hasAttribute("data-array-object")).forEach((row, index) => {
            $('[data-input="multi_reference_confirmed"]', row).checked = all.style.presets[index].multi_reference_confirmed;
          });
        }
        form.inert = true;
        $("#reset-settings").disabled = true;
        try {
          const result = await call("action", "settings_save", {
            config_json: JSON.stringify(all),
            revision,
          });
          if (form.isConnected) {
            state.dirty = false;
            updateNotice();
          }
          let refreshError = null;
          try {
            await U.bootstrap();
            if (form.isConnected && state.view === view) await U.render();
          } catch (error) {
            refreshError = error;
            requiresRefresh = true;
          }
          U.savedNotice(result, "全部设置已保存", refreshError);
        } finally {
          if (form.isConnected) {
            form.inert = requiresRefresh;
            $("#reset-settings").disabled = requiresRefresh;
          }
        }
      }).finally(() => {
        if (form.isConnected && requiresRefresh) save.disabled = true;
      });
    };
    activate(selected);
    updateNotice();
  }
  U.views.settings = () => showSettings("settings");
  U.views.library = () => showSettings("library");
})();
