(() => {
  "use strict";
  const U = window.DrawpicUI,
    { state, $, e, icon, call, buttonAction, toast } = U;
  let mode = "draw",
    pollTimer,
    resultVersion = 0,
    queryFailed = false,
    submissionVersion = 0;
  // Unconfirmed immutable snapshots belong to requests, never to a DOM button.
  const submissions = new Map();
  const draft = {};
  function saveDraft() {
    for (const id of [
      "draw-prompt",
      "draw-model",
      "draw-style",
      "draw-negative",
      "draw-delivery",
      "chat-platform",
      "reference-self",
      "reference-tags",
      "reference-chat",
      "reference-web",
    ]) {
      const input = $("#" + id);
      if (input) draft[id] = input.type === "checkbox" ? input.checked : input.value;
    }
  }
  function modelOptions() {
    const placeholder = state.data.default_model_error
      ? '<option value="" selected>请选择平台实例 / 模型</option>'
      : "";
    return placeholder + state.data.models
      .filter((item) => item[mode])
      .map(
        (item) =>
          `<option value="${e(item.name)}" ${item.name === state.data.default_model ? "selected" : ""}>${e(item.name)} · ${e(item.provider)}</option>`,
      )
      .join("");
  }
  function bindSources() {
    const box = $("#source-list");
    if (!box) return;
    box.innerHTML = state.sources
      .map(
        (item, index) =>
          `<div class="source-item"><img src="${e(item.preview)}" alt="源图片 ${index + 1}"><button type="button" class="icon-button" data-source-index="${index}" aria-label="移除源图片 ${index + 1}">×</button></div>`,
      )
      .join("");
    box.querySelectorAll("[data-source-index]").forEach((button) => {
      button.onclick = () => {
        state.sources.splice(Number(button.dataset.sourceIndex), 1);
        state.requestId = null;
        bindSources();
      };
    });
  }
  async function upload(files) {
    if (state.sources.length + files.length > 8) {
      toast("最多选择 8 张源图");
      return;
    }
    const button = $("#source-button");
    button.disabled = true;
    try {
      for (const file of files) {
        const result = await call("upload", "source", {}, file, {
          onProgress: (percent) => {
            button.textContent = `上传中 ${Math.round(percent)}%`;
          },
        });
        state.sources.push(result);
        bindSources();
      }
      state.requestId = null;
    } catch (error) {
      U.error(error);
    } finally {
      button.disabled = false;
      button.innerHTML = `${icon("upload")}选择源图片`;
    }
  }
  async function updateResult() {
    clearTimeout(pollTimer);
    const taskId = state.lastTask, version = ++resultVersion;
    const pageVersion = state.renderVersion;
    const current = () => state.view === "studio" &&
      state.lastTask === taskId && version === resultVersion &&
      pageVersion === state.renderVersion;
    if (!taskId || !current()) return;
    let retry = false;
    try {
      const result = await call("query", "task", { task_id: taskId });
      if (!current()) return;
      const node = $("#studio-result");
      if (!node) return;
      if (result.images.length) {
        const preview = await call("query", "image", {
          task_id: result.task_id,
          index: 0,
        });
        if (!current()) return;
        node.innerHTML = `<img class="preview-image" src="${e(preview.data_url)}" alt="生成的图片"><div class="result-meta"><span class="pill ${e(result.status)}">${e(U.statusLabel(result.status))}</span><span class="pill">${e(preview.width)} × ${e(preview.height)}</span></div><p class="hint">${e(result.message)}</p><button id="studio-detail" class="button secondary wide" style="margin-top:16px">查看全部图片 ${icon("arrow")}</button>`;
        $("#studio-detail").onclick = () => U.openTask(result.task_id);
      } else {
        node.innerHTML = `<div class="placeholder-art">${icon(result.status === "running" ? "clock" : "images")}<span>${e(U.statusLabel(result.status))}</span><small>${e(result.message)}</small></div><div class="result-meta"><span class="pill">${e(result.model)}</span><span class="pill">${e(result.task_id)}</span></div>`;
      }
      queryFailed = false;
      retry = ["pending", "running"].includes(result.status);
    } catch (error) {
      if (!current()) return;
      retry = true;
      if (!queryFailed) U.error(error);
      queryFailed = true;
    } finally {
      if (retry && current()) pollTimer = setTimeout(() => {
        if (current()) updateResult().catch(U.error);
      }, 5000);
    }
  }
  function renderSubmissions() {
    if (state.view !== "studio") return;
    const node = $("#studio-submissions");
    if (!node) return;
    node.innerHTML = [...submissions.values()].map((entry) =>
      `<div class="hint">${e(entry.prompt.slice(0, 80))} · ${entry.pending ? "正在等待提交回执" : "提交未确认，请沿用原请求重试"}<button type="button" class="button secondary compact" data-retry-request="${e(entry.id)}" ${entry.pending ? "disabled" : ""}>恢复原提交</button></div>`,
    ).join("");
    node.querySelectorAll("[data-retry-request]").forEach((button) => {
      button.onclick = () => {
        const entry = [...submissions.values()].find((item) => item.id === button.dataset.retryRequest);
        if (entry) buttonAction(button, () => submitSnapshot(entry));
      };
    });
  }
  async function submitSnapshot(entry) {
    if (entry.pending) return;
    entry.pending = true;
    const version = ++submissionVersion;
    state.requestId = entry.id;
    renderSubmissions();
    try {
      const result = await call("action", "submit", { request_json: entry.json });
      if (submissions.get(entry.signature) === entry) submissions.delete(entry.signature);
      if (state.requestId === entry.id) state.requestId = null;
      // An older receipt cannot replace the task selected by a newer submission.
      if (version === submissionVersion) {
        state.lastTask = result.task_id;
        await updateResult();
      }
      toast("绘图任务已提交");
    } finally {
      entry.pending = false;
      renderSubmissions();
    }
  }
  U.views.studio = async (transition = null) => {
    clearTimeout(pollTimer);
    resultVersion++;
    if (!state.data.models.length) {
      $("#workspace-content").innerHTML = U.empty(
        "先添加一个绘图平台",
        state.data.default_model_error ||
          "平台和模型准备好之后，就可以在这里开始第一幅作品。",
        `<button id="first-platform" class="button">${icon("plus")}添加绘图平台</button>`,
      );
      $("#first-platform").onclick = () => U.navigate("platforms");
      return;
    }
    const refs = state.data.settings.general.references;
    const styles = state.data.settings.style;
    const inherited = state.data.presets.find(preset => preset.name === styles.default_style && preset.apply_to_image_edit);
    const defaultPreset = mode === "draw" ? styles.default_style : styles.default_image_edit_preset || inherited?.name;
    const presetCaption = mode === "edit_image" && !styles.image_edit_presets_enabled ? "图生图预设已关闭" : `自动匹配${defaultPreset ? ` · 默认：${defaultPreset}` : " · 未设置默认"}`;

    const presetOptions = state.data.presets
      .filter(item => item.enabled && (mode === "draw" ? item.preset_type === "text_to_image" : styles.image_edit_presets_enabled && (item.preset_type === "image_to_image" || item.apply_to_image_edit)))
      .map(item => `<option value="${e(item.name)}">${e(item.name)}</option>`).join("");
    const referenceControls = mode === "edit_image" ? `
      <details class="control-disclosure" id="reference-options">
        <summary><span>${icon("layers")}参考素材</span><span class="disclosure-note">按需使用 ${icon("chevron")}</span></summary>
        <div class="disclosure-body">
          <div class="field"><label for="reference-self">机器人自身</label><select id="reference-self" ${refs.self_reference_enabled ? "" : "disabled"}><option value="off">不使用自我参考</option><option value="auto" ${refs.self_reference_enabled ? "selected" : ""}>根据原始描述识别</option><option value="required">明确描绘机器人自身</option></select>${!refs.self_reference_enabled ? '<p class="hint">请先在“预设参考 → 自我参考”中开启。</p>' : ""}</div>
          <div class="field"><label for="reference-tags">参考图 tag <span class="label-optional">可选</span></label><input id="reference-tags" placeholder="例如：冬装，居家"><p class="hint">未命中 tag 时使用图库默认图。</p></div>
          <label class="reference-source-option"><span><strong>从聊天取材</strong><small>${refs.allow_chat_material_search ? `最多检查 ${e(refs.chat_material_search_limit)} 条近期消息` : "请先在“预设参考 → 素材来源”中开启"}</small></span><input id="reference-chat" type="checkbox" role="switch" class="toggle" ${refs.allow_chat_material_search ? "" : "disabled"}></label>
          <label class="reference-source-option"><span><strong>从网络取材</strong><small>${refs.allow_web_material_search ? "使用 MaiBot 的联网搜索服务" : "请先在“预设参考 → 素材来源”中开启"}</small></span><input id="reference-web" type="checkbox" role="switch" class="toggle" ${refs.allow_web_material_search ? "" : "disabled"}></label>

          <button type="button" class="button ghost compact" id="studio-references">管理预设参考 ${icon("arrow")}</button>
        </div>
      </details>` : "";
    $("#workspace-content").innerHTML = `
      <div class="studio-grid">
        <section class="panel studio-controls" aria-label="绘图设置">
          <div class="studio-heading"><div><span class="section-kicker">创作设置</span><h2>绘图设置</h2></div>${icon("sparkles")}</div>
          <div class="mode-switch" data-mode="${mode}" role="group" aria-label="绘图模式"><span class="mode-indicator" aria-hidden="true"></span><button id="mode-draw" aria-pressed="${mode === "draw"}" class="${mode === "draw" ? "active" : ""}">文生图</button><button id="mode-edit" aria-pressed="${mode === "edit_image"}" class="${mode === "edit_image" ? "active" : ""}">图生图</button></div>
          <form id="draw-form">
            <div class="field prompt-field"><div class="studio-label"><label for="draw-prompt">${mode === "draw" ? "画面描述" : "希望怎样修改画面？"}</label><span class="label-optional">主体 · 环境 · 光线</span></div><textarea id="draw-prompt" class="prompt-input" maxlength="16000" required placeholder="${mode === "draw" ? "例如：橘猫坐在窗边，午后阳光落在木地板上，柔和的水彩质感。" : "例如：保留人物和姿态，把背景换成傍晚的海边，使用柔和暖光。"}"></textarea></div>
            <div class="studio-models">
              <div class="field"><label for="draw-model">绘图模型</label><select id="draw-model" required${state.data.default_model_error ? ' aria-describedby="draw-model-error"' : ""}>${modelOptions()}</select>${state.data.default_model_error ? `<p id="draw-model-error" class="hint" role="status">${e(state.data.default_model_error)}。请选择完整的“平台实例 / 模型”名称；可在插件设置中更新默认模型。</p>` : ""}</div>
              <div class="field"><div class="studio-label"><label for="draw-style">绘图预设</label><button type="button" id="studio-presets" class="button ghost compact">管理 ${icon("arrow")}</button></div><select id="draw-style"><option value="">${e(presetCaption)}</option><option value="none">不使用预设</option>${presetOptions}</select><p class="hint" id="studio-preset-description" hidden></p></div>
            </div>
            ${mode === "edit_image" ? `<section class="studio-source"><div class="studio-label"><h3>参考图片</h3><span class="label-optional">最多 8 张，依模型支持</span></div><div class="upload-zone" id="upload-zone">${icon("upload")}<div><strong>拖放图片到这里</strong><small>也可从设备选择 PNG、JPG 或 WebP</small></div><button type="button" id="source-button" class="button secondary compact">选择图片</button><input type="file" id="source-file" accept="image/png,image/jpeg,image/webp" multiple hidden></div><div class="source-list" id="source-list"></div></section>` : ""}
            ${referenceControls}
            <details class="control-disclosure" id="negative-options"><summary><span>${icon("sliders")}反向提示词</span><span class="disclosure-note">可选 ${icon("chevron")}</span></summary><div class="disclosure-body"><div class="field"><label for="draw-negative">不希望出现的内容</label><textarea id="draw-negative" rows="3" maxlength="16000" placeholder="例如：模糊、水印、过度曝光"></textarea></div></div></details>
            <section class="studio-delivery"><div class="field"><label for="draw-delivery">结果处理</label><select id="draw-delivery"><option value="web">仅在工作台查看</option><option value="chat">同时发送到聊天</option></select></div><div id="delivery-fields" hidden><div class="field-row"><div class="field"><label for="chat-platform">聊天平台</label><input id="chat-platform" value="qq" maxlength="80"></div><div class="field stream-load"><button type="button" id="load-streams" class="button secondary wide">加载会话</button></div></div><div class="field"><label for="draw-stream">发送到</label><select id="draw-stream"><option value="">请先加载会话</option></select><p class="hint">发送到聊天时沿用该会话额度；仅在工作台查看不占聊天额度。</p></div></div></section>
            <div class="sticky-save studio-submit"><span class="hint">Ctrl / ⌘ + Enter</span><button type="submit" class="button" id="start-drawing">${icon("sparkles")}开始绘图</button></div>
          </form>
        </section>
        <aside class="studio-preview" aria-label="绘图结果">
          <section class="panel studio-canvas-panel"><div class="panel-header"><div><h2>创作结果</h2></div><button type="button" class="button ghost compact" id="studio-tasks">全部任务 ${icon("arrow")}</button></div><div id="studio-submissions" aria-live="polite"></div><div id="studio-result"><div class="placeholder-art studio-empty"><div class="empty-canvas" aria-hidden="true">${icon("images")}<span></span></div><span>暂无结果</span></div></div></section>
        </aside>
      </div>`;
    for (const [id, value] of Object.entries(draft)) {
      const input = $("#" + id);
      if (
        input &&
        (!input.options ||
          Array.from(input.options).some((option) => option.value === value))
      )
        if (input.type === "checkbox") input.checked = value;
        else input.value = value;
    }
    $("#delivery-fields").hidden = $("#draw-delivery").value !== "chat";
    function changeMode(next) {
      if (mode === next) return;
      saveDraft();
      state.requestId = null;
      const transform = getComputedStyle($(".mode-indicator")).transform;
      mode = next;
      U.views.studio({ transform }).catch(U.error);
    }
    $("#mode-draw").onclick = () => changeMode("draw");
    $("#mode-edit").onclick = () => changeMode("edit_image");
    U.motion.segmented($(".mode-switch"), transition?.transform);
    if (transition) U.motion.enter($("#draw-form"), 3);
    $("#draw-delivery").onchange = () => {
      $("#delivery-fields").hidden = $("#draw-delivery").value !== "chat";
    };
    if ($("#studio-references")) {
      $("#studio-references").onclick = () => { state.librarySection = "references"; U.navigate("library"); };
      const updateTags = () => { $("#reference-tags").disabled = $("#reference-self").value === "off"; };
      $("#reference-self").onchange = updateTags;
      updateTags();
    }
    $("#studio-tasks").onclick = () => U.navigate("tasks");
    const describePreset = () => {
      const selected = state.data.presets.find(item => item.name === $("#draw-style").value);
      $("#studio-preset-description").textContent = selected?.description || "";
      $("#studio-preset-description").hidden = !selected?.description;
    };
    $("#draw-style").onchange = describePreset;
    describePreset();
    $("#studio-presets").onclick = () => {
      state.librarySection = "style";
      U.navigate("library");
    };
    $("#load-streams").onclick = (event) =>
      buttonAction(event.currentTarget, async () => {
        const result = await call("query", "streams", {
          platform: $("#chat-platform").value.trim(),
        });
        $("#draw-stream").innerHTML =
          '<option value="">请选择真实会话</option>' +
          result.streams
            .map(
              (item) =>
                `<option value="${e(item.id)}">${e(item.name)}</option>`,
            )
            .join("");
        if (!result.streams.length) toast("这个平台暂无聊天会话");
      });
    if (mode === "edit_image") {
      $("#source-button").onclick = () => $("#source-file").click();
      $("#source-file").onchange = (event) =>
        upload(Array.from(event.target.files));
      bindSources();
      const zone = $("#upload-zone");
      zone.ondragover = (event) => {
        event.preventDefault();
        zone.classList.add("dragging");
      };
      zone.ondragleave = () => zone.classList.remove("dragging");
      zone.ondrop = (event) => {
        event.preventDefault();
        zone.classList.remove("dragging");
        upload(Array.from(event.dataTransfer.files));
      };
    }
    $("#draw-form").oninput = () => {
      state.requestId = null;
      saveDraft();
    };
    U.bindSubmit($("#draw-form"), { shortcutOnly: true });
    $("#draw-form").onsubmit = (event) => {
      event.preventDefault();
      buttonAction($("#start-drawing"), async () => {
        if (!$("#draw-model").value)
          throw new Error("当前没有支持这种任务的模型，请调整平台配置");
        const stream =
          $("#draw-delivery").value === "chat" ? $("#draw-stream").value : "";
        if ($("#draw-delivery").value === "chat" && !stream)
          throw new Error("请选择真实聊天会话");
        const request = {
          prompt: $("#draw-prompt").value,
          model: $("#draw-model").value,
          style: $("#draw-style").value,
          negative_prompt: $("#draw-negative").value,
          task_type: mode,
          stream_id: stream,
          source_ids:
            mode === "edit_image"
              ? state.sources.map((item) => item.source_id)
              : [],
        };
        if (mode === "edit_image") {
          const self = $("#reference-self").value;
          const sources = [$("#reference-chat").checked ? "chat" : "", $("#reference-web").checked ? "web" : ""].filter(Boolean);
          if (sources.includes("chat") && !stream) throw new Error("从聊天取材需要选择对应聊天会话，并明确将结果发送到该会话");
          request.reference_options_json = JSON.stringify({ self_reference: self,
            self_reference_tags: self === "off" ? [] : $("#reference-tags").value.split(/[,，]/).map(value => value.trim()).filter(Boolean),
            user_request: request.prompt, material_sources: sources });
        }
        const signature = JSON.stringify(request);
        let entry = submissions.get(signature);
        if (!entry) {
          const id = U.uid();
          entry = { signature, id, prompt: request.prompt,
            json: JSON.stringify({ ...request, request_id: id }), pending: false };
          submissions.set(signature, entry);
        }
        await submitSnapshot(entry);
      });
    };
    renderSubmissions();
    if (state.lastTask) await updateResult();
  };
})();
