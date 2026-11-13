(() => {
  "use strict";
  const U = window.DrawpicUI,
    { state, $, call, buttonAction, toast } = U;
  const sections = { general: "通用配置", review: "审核配置", access: "黑白名单", style: "绘图预设", references: "参考与素材" };
  const sourceSection = (name) => ["review", "access", "references"].includes(name) ? "general" : name;
  const reviewField = (key) => /^(prompt|image)_review_/.test(key);
  const accessField = (key) => /^(group|private)_access_/.test(key);
  const belongsToSection = (name, key) => name === "style" ||
    (name === "references" ? key === "references" : key !== "references") &&
    (name === "review" ? reviewField(key) : name === "access" ? accessField(key) : !reviewField(key) && !accessField(key));
  U.views.settings = async () => {
    let selected = Object.hasOwn(sections, state.settingsSection)
      ? state.settingsSection
      : "general";
    const revision = state.data.revision;
    const readers = {};
    const save = $("#save-settings");
    $("#workspace-content").innerHTML =
      `<div class="settings-layout"><div class="settings-tabs" role="tablist" aria-label="配置分类">${Object.entries(
        sections,
      )
        .map(
          ([name, title]) =>
            `<button id="settings-tab-${name}" class="settings-tab" data-section="${name}" role="tab" aria-controls="settings-panel-${name}">${title}</button>`,
        )
        .join(
          "",
        )}</div><section class="panel"><div class="panel-header"><div><h2 id="settings-heading"></h2><p class="hint" id="settings-description"></p></div><button type="button" id="reset-settings" class="button secondary compact">恢复当前分类默认</button></div><form id="settings-form"></form></section></div>`;
    const form = $("#settings-form");
    let requiresRefresh = false;
    function renderSection(name, values) {
      const panel = document.createElement("section");
      panel.id = `settings-panel-${name}`;
      panel.dataset.settingsPanel = name;
      panel.setAttribute("role", "tabpanel");
      panel.setAttribute("aria-labelledby", `settings-tab-${name}`);
      panel.hidden = name !== selected;
      const fields = name === "references" ? state.data.reference_fields : Object.fromEntries(
        Object.entries(state.data.schema.sections[sourceSection(name)].fields)
          .filter(([key]) => belongsToSection(name, key)),
      );
      if (name === "references") {
        values = values.references;
        const selfFields = Object.fromEntries(Object.entries(fields).filter(([key]) => !key.startsWith("allow_")));
        const sourceFields = Object.fromEntries(Object.entries(fields).filter(([key]) => key.startsWith("allow_")));
        panel.innerHTML = `<h3>自我参考</h3><p class="hint">默认关闭。开启后依据用户原始请求识别是否描绘机器人；不明确时需要补充主体说明。填写当前机器人的名称及常用称呼。</p>${U.forms.html(selfFields, values)}<div data-self-gallery></div><h3 class="reference-source-title">素材来源</h3><p class="hint">两个来源独立开启。仅查找当前任务缺少的素材；用户本条附图与明确引用的图片不受这两个开关限制。</p>${U.forms.html(sourceFields, values)}`;
      } else panel.innerHTML = U.forms.html(fields, values);
      const old = $(`#${panel.id}`, form);
      if (old) old.replaceWith(panel);
      else form.append(panel);
      const read = U.forms.bind(panel, fields, values);
      // 通用、审核和黑白名单共享持久化配置，只读取当前分类的字段，避免覆盖其他分类草稿。
      readers[name] = () => {
        const result = read();
        return name === "references" ? { references: result } : Object.fromEntries(Object.keys(fields).map((key) => [key, result[key]]));
      };
      if (name === "references") {
        U.referenceUI.confirmButton(panel);
        U.referenceUI.gallery($("[data-self-gallery]", panel), "self");
      } else if (name === "style") {
        U.referenceUI.presetTypes(panel);
        const gallery = document.createElement("div");
        gallery.className = "reference-preset-gallery";
        gallery.hidden = true;
        panel.append(gallery);
        U.referenceUI.gallery(gallery, "preset");
      }
    }
    for (const name of Object.keys(sections))
      renderSection(name, structuredClone(state.data.settings[sourceSection(name)]));
    function activate(name, reveal = false) {
      selected = state.settingsSection = name;
      $("#settings-heading").textContent = sections[name];
      $("#settings-description").textContent =
        name === "style"
          ? "文生图和图生图分别选择预设。图生图预设默认关闭；文生图预设可逐条勾选同时应用到图生图。"
          : name === "review"
            ? "分别设置提示词审核和生成图片审核，使用 MaiBot 配置的审核模型。切换分类保留草稿。"
          : name === "access"
            ? "分别设置群聊和私聊的访问规则。填写群号、QQ 号或 QQ 官方 OpenID，无需会话哈希；保存后对新的命令、AI 工具和指定会话的任务生效。"
          : "切换分类会保留草稿，点击右下角“保存全部设置”统一保存。";
      for (const tab of document.querySelectorAll("[data-section]")) {
        const active = tab.dataset.section === name;
        tab.classList.toggle("active", active);
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
      }
      for (const panel of form.children)
        panel.hidden = panel.dataset.settingsPanel !== name;
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
      if (invalid)
        activate(
          invalid.closest("[data-settings-panel]").dataset.settingsPanel,
        );
      U.submitForm(form);
    };
    save.onclick = submitAll;
    form.addEventListener("keydown", (event) => {
      if (
        event.key === "Enter" &&
        event.target.tagName === "INPUT" &&
        !event.isComposing
      ) {
        event.preventDefault();
        submitAll();
      }
    });
    form.onsubmit = (event) => {
      event.preventDefault();
      if (form.inert || requiresRefresh || save.disabled) return;
      buttonAction(save, async () => {
        const all = {
          general: { ...state.data.settings.general, ...readers.general(), ...readers.review(), ...readers.access(), ...readers.references() },
          style: readers.style(),
        };
        if (!(await U.referenceUI.confirmSettings(all, state.data.settings))) {
          renderSection("references", { references: all.general.references });
          renderSection("style", all.style);
          state.dirty = true;
          updateNotice();
          return;
        }
        $('[data-input="multi_reference_confirmed"]', $("#settings-panel-references")).checked = all.general.references.multi_reference_confirmed;
        const presetRows = $('[data-array="presets"]', $("#settings-panel-style"));
        [...presetRows.children].filter(node => node.hasAttribute("data-array-object")).forEach((row, index) => {
          $('[data-input="multi_reference_confirmed"]', row).checked = all.style.presets[index].multi_reference_confirmed;
        });
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
            if (form.isConnected && state.view === "settings") await U.render();
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
  };
})();
