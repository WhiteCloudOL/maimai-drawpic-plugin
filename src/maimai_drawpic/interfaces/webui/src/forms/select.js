(() => {
  "use strict";
  const U = window.DrawpicUI, { e, icon } = U;
  const controls = new WeakMap();
  let sequence = 0, active = null;
  const panel = document.createElement("div");
  panel.className = "search-select-panel";
  panel.setAttribute("popover", "manual");
  panel.innerHTML = `<div class="select-search-row">${icon("search")}<input type="search" data-select-search autocomplete="off" spellcheck="false" placeholder="搜索选项…"></div><div class="select-options" role="listbox" id="select-options"></div><p class="select-status" role="status" aria-live="polite"></p>`;
  const search = panel.querySelector("input"), list = panel.querySelector("[role=listbox]"), status = panel.querySelector("[role=status]");
  search.setAttribute("aria-controls", list.id);

  function composing(event) {
    return event.isComposing || event.keyCode === 229;
  }
  function labelFor(select) {
    const explicit = select.getAttribute("aria-label");
    if (explicit) return explicit;
    return [...select.labels].map(label => {
      const copy = label.cloneNode(true);
      copy.querySelectorAll("select,.search-select").forEach(node => node.remove());
      return copy.textContent.trim();
    }).filter(Boolean).join(" ") || "选项";
  }
  function optionsFor(select) {
    return [...select.options].map((option, index) => {
      const group = option.parentElement.tagName === "OPTGROUP" ? option.parentElement : null;
      return { index, value: option.value, label: option.label, group: group?.label || "",
        disabled: option.disabled || Boolean(group?.disabled), hidden: option.hidden || Boolean(group?.hidden) };
    }).filter(option => !option.hidden);
  }
  function update(control) {
    const { select, trigger, text } = control;
    text.textContent = select.selectedOptions[0]?.label || "请选择…";
    trigger.title = text.textContent;
    trigger.disabled = select.matches(":disabled");
    trigger.setAttribute("aria-label", labelFor(select));
    trigger.setAttribute("aria-required", String(select.required));
    if (select.validity.valid) trigger.removeAttribute("aria-invalid");
    const description = select.getAttribute("aria-describedby");
    if (description) trigger.setAttribute("aria-describedby", description);
    else trigger.removeAttribute("aria-describedby");
    if (active?.control === control) {
      if (trigger.disabled || !select.isConnected) close(false);
      else renderOptions();
    }
  }
  function close(returnFocus = false) {
    if (!active) return;
    const { trigger } = active.control;
    active = null;
    trigger.setAttribute("aria-expanded", "false");
    search.removeAttribute("aria-activedescendant");
    if (panel.matches(":popover-open")) panel.hidePopover();
    if (returnFocus && trigger.isConnected && !trigger.disabled) trigger.focus({ preventScroll: true });
  }
  function position() {
    if (!active) return;
    const rect = active.control.trigger.getBoundingClientRect();
    const viewport = window.visualViewport;
    const top = viewport?.offsetTop || 0, bottom = top + (viewport?.height || innerHeight);
    // 软键盘可能遮住触发器；搜索仍有焦点时，将弹层约束到可视区域而不关闭。
    if ((rect.bottom < top || rect.top > bottom) && !panel.contains(document.activeElement)) { close(false); return; }
    const left = viewport?.offsetLeft || 0;
    const visibleWidth = Math.min(document.documentElement.clientWidth, viewport?.width || document.documentElement.clientWidth);
    const width = Math.min(Math.max(rect.width, 230), visibleWidth - 16);
    const below = bottom - rect.bottom - 8, above = rect.top - top - 8;
    const upwards = below < 220 && above > below;
    const height = Math.min(360, Math.max(0, bottom - top - 16), Math.max(100, (upwards ? above : below) - 8));
    panel.style.width = `${width}px`;
    panel.style.maxHeight = `${height}px`;
    panel.style.left = `${Math.max(left + 8, Math.min(rect.left, left + visibleWidth - width - 8))}px`;
    const desiredTop = upwards ? rect.top - panel.offsetHeight - 6 : rect.bottom + 6;
    panel.style.top = `${Math.max(top + 8, Math.min(desiredTop, bottom - panel.offsetHeight - 8))}px`;
  }
  function highlight(index, scroll = true) {
    if (!active) return;
    active.index = index;
    list.querySelectorAll("[data-select-index]").forEach(node => {
      node.dataset.active = String(Number(node.dataset.selectIndex) === index);
    });
    const item = list.querySelector(`[data-select-index="${index}"]`);
    if (item) {
      search.setAttribute("aria-activedescendant", item.id);
      if (scroll) item.scrollIntoView({ block: "nearest" });
    } else search.removeAttribute("aria-activedescendant");
  }
  function renderOptions() {
    const query = search.value.normalize("NFKC").toLocaleLowerCase().trim().split(/\s+/).filter(Boolean);
    active.options = optionsFor(active.control.select).filter(option => {
      const text = `${option.label} ${option.value} ${option.group}`.normalize("NFKC").toLocaleLowerCase();
      return query.every(term => text.includes(term));
    });
    let group = "";
    list.innerHTML = active.options.map(option => {
      const heading = option.group && option.group !== group ? `<div class="select-group" role="presentation">${e(option.group)}</div>` : "";
      group = option.group;
      const selected = option.index === active.control.select.selectedIndex;
      return `${heading}<button type="button" role="option" id="select-option-${option.index}" class="select-option" data-select-index="${option.index}" tabindex="-1" aria-selected="${selected}"${option.disabled ? ' disabled aria-disabled="true"' : ""}><span>${e(option.label || "未选择")}</span>${selected ? icon("check") : ""}</button>`;
    }).join("");
    status.textContent = active.options.length ? `${active.options.length} 个选项` : "没有匹配的选项";
    const enabled = active.options.filter(option => !option.disabled);
    const next = enabled.find(option => option.index === active.index)
      || enabled.find(option => option.index === active.control.select.selectedIndex) || enabled[0];
    highlight(next?.index ?? -1, false);
    position();
  }
  function open(control, query = "") {
    if (control.trigger.disabled) return;
    close(false);
    // 弹层属于当前模态框，并进入 top layer，保持可交互且不被滚动容器裁切。
    (control.select.closest("dialog") || document.body).append(panel);
    active = { control, options: [], index: control.select.selectedIndex };
    search.value = query;
    search.setAttribute("aria-label", `搜索${labelFor(control.select)}`);
    list.setAttribute("aria-label", `${labelFor(control.select)}选项`);
    control.trigger.setAttribute("aria-expanded", "true");
    renderOptions();
    panel.showPopover();
    position();
    search.focus({ preventScroll: true });
    if (!query) highlight(active.index);
  }
  function choose(index) {
    if (!active) return;
    const option = active.options.find(item => item.index === index);
    if (!option || option.disabled) return;
    const control = active.control, changed = control.select.selectedIndex !== index;
    control.select.selectedIndex = index;
    close(true);
    update(control);
    if (changed) {
      control.select.dispatchEvent(new Event("input", { bubbles: true }));
      control.select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }
  function enhance(select) {
    if (select.multiple || controls.has(select)) return;
    const focused = document.activeElement === select;
    const wrapper = document.createElement("div"), trigger = document.createElement("button");
    wrapper.className = "search-select";
    trigger.className = "select-trigger";
    trigger.type = "button";
    trigger.id = `select-trigger-${++sequence}`;
    trigger.setAttribute("role", "combobox");
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-controls", list.id);
    trigger.setAttribute("aria-expanded", "false");
    trigger.innerHTML = `<span class="select-label"></span>${icon("chevron")}`;
    // 原字段只保留取值、校验与事件契约，交互和展示由共享组件完成。
    select.replaceWith(wrapper);
    wrapper.append(select, trigger);
    select.hidden = true;
    select.tabIndex = -1;
    select.setAttribute("aria-hidden", "true");
    const control = { select, trigger, text: trigger.querySelector(".select-label") };
    controls.set(select, control);
    update(control);
    trigger.addEventListener("click", () => active?.control === control ? close(true) : open(control));
    trigger.addEventListener("keydown", event => {
      if (composing(event)) return;
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        open(control);
        const enabled = active.options.filter(option => !option.disabled);
        highlight((event.key === "End" || event.key === "ArrowUp" ? enabled.at(-1) : enabled[0])?.index ?? -1);
      } else if (event.key.length === 1 && event.key !== " " && !event.ctrlKey && !event.metaKey && !event.altKey) {
        event.preventDefault();
        open(control, event.key);
      }
    });
    select.addEventListener("invalid", event => {
      event.preventDefault();
      trigger.setAttribute("aria-invalid", "true");
      trigger.focus();
      U.toast(select.validationMessage);
    });
    if (focused) trigger.focus({ preventScroll: true });
  }
  function refresh(root = document) {
    const selects = [...root.querySelectorAll("select")];
    if (root.matches?.("select")) selects.unshift(root);
    selects.forEach(select => {
      enhance(select);
      const control = controls.get(select);
      if (control) update(control);
    });
  }
  search.addEventListener("input", () => {
    if (!active) return;
    active.index = -1;
    renderOptions();
  });
  search.addEventListener("keydown", event => {
    if (!active || composing(event)) return;
    const enabled = active.options.filter(option => !option.disabled);
    if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      const current = enabled.findIndex(option => option.index === active.index);
      const next = (current + (event.key === "ArrowDown" ? 1 : -1) + enabled.length) % enabled.length;
      highlight(enabled[next]?.index ?? -1);
    } else if (event.key === "Enter") {
      event.preventDefault();
      event.stopPropagation();
      choose(active.index);
    }
  });
  list.addEventListener("click", event => {
    const option = event.target.closest("[data-select-index]");
    if (option) choose(Number(option.dataset.selectIndex));
  });
  document.addEventListener("pointerdown", event => {
    if (active && !panel.contains(event.target) && !active.control.trigger.contains(event.target)) close(false);
  }, true);
  document.addEventListener("keydown", event => {
    if (!active || composing(event)) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    } else if (event.key === "Tab") close(true);
  }, true);
  document.addEventListener("close", event => {
    if (active?.control.select.closest("dialog") === event.target) close(false);
  }, true);
  document.addEventListener("click", event => {
    const label = event.target.closest("label[for]");
    if (label && !event.target.closest("button,input")) {
      const control = controls.get(document.getElementById(label.htmlFor));
      if (control) { event.preventDefault(); control.trigger.focus(); }
    }
  });
  for (const name of ["input", "change"]) document.addEventListener(name, event => {
    const control = controls.get(event.target);
    if (control) update(control);
  }, true);
  window.addEventListener("resize", position);
  document.addEventListener("scroll", position, true);
  window.visualViewport?.addEventListener("resize", position);
  window.visualViewport?.addEventListener("scroll", position);
  // 模型目录、风格、扩展参数等会动态更新选项或插入新控件。
  new MutationObserver(records => {
    if (active && !active.control.select.isConnected) close(false);
    const changed = new Set();
    for (const record of records) {
      const element = record.target.nodeType === Node.ELEMENT_NODE ? record.target : record.target.parentElement;
      const select = element?.closest("select");
      if (select) changed.add(select);
      for (const node of record.addedNodes) if (node.nodeType === Node.ELEMENT_NODE) {
        if (node.matches("select")) changed.add(node);
        node.querySelectorAll("select").forEach(item => changed.add(item));
      }
    }
    for (const select of changed) if (select.isConnected) {
      enhance(select);
      const control = controls.get(select);
      if (control) update(control);
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true,
    attributeFilter: ["disabled", "required", "label", "selected", "hidden", "aria-label", "aria-describedby"] });
  U.selects = { refresh, close };
  refresh();
})();
