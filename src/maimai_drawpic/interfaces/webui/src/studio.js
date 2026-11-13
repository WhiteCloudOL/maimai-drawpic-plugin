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
        node.innerHTML = `<img class="preview-image" src="${e(preview.data_url)}" alt="生成的图片"><div class="result-meta"><span class="pill ${e(result.status)}">${e(U.statusLabel(result.status))}</span><span class="pill">${e(preview.width)} × ${e(preview.height)}</span></div><p class="hint">${e(result.message)}</p><button id="studio-detail" class="button secondary wide" style="margin-top:16px">查看任务与全部图片 ${icon("arrow")}</button>`;
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
  U.views.studio = async (previousMode = null) => {
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
    const presetCaption = mode === "edit_image" && !styles.image_edit_presets_enabled ? "图生图预设已关闭" : `跟随当前模式默认预设${defaultPreset ? `（${defaultPreset}）` : "（未设置）"}`;

    const referenceControls = mode === "edit_image" ? `<fieldset class="reference-request"><legend>本次参考与素材</legend><div class="field"><label for="reference-self">机器人自身</label><select id="reference-self" ${refs.self_reference_enabled ? "" : "disabled"}><option value="off">不使用自我参考</option><option value="auto" ${refs.self_reference_enabled ? "selected" : ""}>根据本次原始描述识别</option><option value="required">明确描绘机器人自身</option></select></div><div class="field"><label for="reference-tags">自我参考 Tag（可选）</label><input id="reference-tags" placeholder="例如：冬装，居家"></div><label class="reference-source-option"><span>从当前选定聊天查找缺少的素材</span><input id="reference-chat" type="checkbox" role="switch" class="toggle" ${refs.allow_chat_material_search ? "" : "disabled"}></label><label class="reference-source-option"><span>联网查找缺少的素材</span><input id="reference-web" type="checkbox" role="switch" class="toggle" ${refs.allow_web_material_search ? "" : "disabled"}></label><p class="hint">自我图库、预设图或合格素材可提供真实源图。聊天取材需要在结果去向中选择对应会话；全局关闭的来源不可使用。</p><button type="button" class="button ghost compact" id="studio-references">管理参考与素材 ${icon("arrow")}</button></fieldset>` : "";
    $("#workspace-content").innerHTML =
      `<div class="studio-grid"><section class="panel"><div class="panel-header"><div class="section-label">${icon("sparkles")}<h2>创作新的画面</h2></div><span class="pill">后台执行</span></div><div class="mode-switch" data-mode="${mode}" role="group" aria-label="绘图模式"><span class="mode-indicator" aria-hidden="true"></span><button id="mode-draw" aria-pressed="${mode === "draw"}" class="${mode === "draw" ? "active" : ""}">文生图</button><button id="mode-edit" aria-pressed="${mode === "edit_image"}" class="${mode === "edit_image" ? "active" : ""}">图生图</button></div><form id="draw-form"><div class="field"><label for="draw-prompt">你想画什么？</label><textarea id="draw-prompt" class="prompt-input" maxlength="16000" required placeholder="描述主体、构图、光线和风格。例如：一只橘猫坐在窗边，午后阳光照进房间，水彩质感。"></textarea></div><div class="field-row"><div class="field"><label for="draw-model">绘图模型</label><select id="draw-model" required${state.data.default_model_error ? ' aria-describedby="draw-model-error"' : ""}>${modelOptions()}</select>${state.data.default_model_error ? `<p id="draw-model-error" class="hint" role="status">${e(state.data.default_model_error)}。请选择完整的“平台实例 / 模型”名称；可在偏好与预设中更新默认模型。</p>` : ""}</div><div class="field"><label for="draw-style">绘图预设</label><select id="draw-style"><option value="">${e(presetCaption)}</option><option value="none">不使用预设</option>${state.data.presets
        .filter((item) => item.enabled && (mode === "draw" ? item.preset_type === "text_to_image" : state.data.settings.style.image_edit_presets_enabled && (item.preset_type === "image_to_image" || item.apply_to_image_edit)))
        .map(
          (item) => `<option value="${e(item.name)}">${e(item.name)}</option>`,
        )
        .join(
          "",
        )}</select></div></div>${mode === "edit_image" ? `<div class="field"><label>源图片</label><div class="upload-zone" id="upload-zone">${icon("upload")}<p>拖放图片到这里，或选择文件</p><button type="button" id="source-button" class="button secondary compact">${icon("upload")}选择源图片</button><input type="file" id="source-file" accept="image/png,image/jpeg,image/webp" multiple hidden></div><div class="source-list" id="source-list"></div><p class="hint">上传真实源图；最终支持数量以模型为准。需要公网原图 URL 的模型不支持直接使用网页上传的本地图片。</p></div>` : ""}${referenceControls}<details><summary class="muted" style="cursor:pointer;margin-bottom:15px">反向提示词与发送选项</summary><div class="field"><label for="draw-negative">反向提示词</label><textarea id="draw-negative" rows="2" maxlength="16000" placeholder="不希望出现在画面中的内容"></textarea></div><div class="field"><label for="draw-delivery">结果去向</label><select id="draw-delivery"><option value="web">仅在工作台查看</option><option value="chat">同时发送到聊天</option></select></div><div id="delivery-fields" hidden><div class="field-row"><div class="field"><label for="chat-platform">聊天平台标识</label><input id="chat-platform" value="qq" maxlength="80"></div><div class="field"><label>&nbsp;</label><button type="button" id="load-streams" class="button secondary wide">加载聊天会话</button></div></div><div class="field"><label for="draw-stream">目标会话</label><select id="draw-stream"><option value="">请先加载会话</option></select><p class="hint">使用实际聊天流；发送到聊天时沿用群聊或私聊额度。网页专用任务由当前实例管理，不计入聊天额度。</p></div></div></details><div class="sticky-save"><span class="hint">模型校验 · 提示词与图片审核</span><button type="submit" class="button" id="start-drawing">${icon("sparkles")}开始绘图</button></div></form></section><aside class="stack"><section class="panel"><div class="panel-header"><h3>创作结果</h3>${icon("images")}</div><div id="studio-submissions" aria-live="polite"></div><div id="studio-result"><div class="placeholder-art">${icon("sparkles")}<span>想象，正在等待落笔</span><small>任务提交后，会在这里显示进度与生成图片。</small></div></div></section><div class="panel"><h3>让画面更接近你的想法</h3><p class="hint">描述具体的主体、环境和光线。试试绘图预设，把常用的画面语言保存下来。</p><button class="button ghost compact" id="studio-presets" style="margin-top:8px">管理预设 ${icon("arrow")}</button></div></aside></div>`;
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
      const previous = mode;
      mode = next;
      U.views.studio(previous).catch(U.error);
    }
    $("#mode-draw").onclick = () => changeMode("draw");
    $("#mode-edit").onclick = () => changeMode("edit_image");
    if (
      previousMode !== null &&
      !window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      $(".mode-indicator").animate(
        [
          {
            transform:
              previousMode === "edit_image"
                ? "translateX(100%)"
                : "translateX(0)",
          },
          {
            transform:
              mode === "edit_image" ? "translateX(100%)" : "translateX(0)",
          },
        ],
        { duration: 260, easing: "cubic-bezier(.2,.8,.2,1)" },
      );
    }
    $("#draw-delivery").onchange = () => {
      $("#delivery-fields").hidden = $("#draw-delivery").value !== "chat";
    };
    if ($("#studio-references")) {
      $("#studio-references").onclick = () => { state.settingsSection = "references"; U.navigate("settings"); };
      const updateTags = () => { $("#reference-tags").disabled = $("#reference-self").value === "off"; };
      $("#reference-self").onchange = updateTags;
      updateTags();
    }
    $("#studio-presets").onclick = () => {
      state.settingsSection = "style";
      U.navigate("settings");
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
    U.bindSubmit($("#draw-form"));
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
