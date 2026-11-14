// Run with: node --test tests/webui_regressions.cjs
// Dependency-free controller tests. Browser QA separately checks native inert,
// focus, layout, and actual DOM form semantics; this fixture models only seams.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = path.join(__dirname, '../src/maimai_drawpic/interfaces/webui/src');
const read = name => fs.readFileSync(path.join(source, name), 'utf8');
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const event = { preventDefault() {} };
const referenceDefaults = { self_reference_enabled: false, self_names: ['麦麦'], self_reference_ids: [], multi_reference_confirmed: false, allow_chat_material_search: false, chat_material_search_limit: 50, material_model: "vlm", allow_web_material_search: false };
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function node(values = {}) {
  return { value: '', textContent: '', innerHTML: '', checked: false,
    disabled: false, isConnected: true, inert: false, hidden: false,
    scrollTop: 0, clientHeight: 100, scrollHeight: 500, children: [],
    attrs: {}, listeners: {}, dataset: {},
    setAttribute(k, v) { this.attrs[k] = v; },
    removeAttribute(k) { delete this.attrs[k]; },
    addEventListener(k, fn) { this.listeners[k] = fn; },
    append(...nodes) { this.children.push(...nodes); },
    replaceWith() {},
    querySelectorAll() { return []; },
    classList: { toggle() {} }, contains() { return false; }, focus() {}, scrollIntoView() {}, ...values };
}
function harness(file, extra = {}) {
  const nodes = new Map();
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, node());
    return nodes.get(selector);
  };
  const errors = [], calls = [], actions = [], timers = new Map();
  let timerId = 0;
  const U = { state: { view: file, dirty: false, busy: 0, modalVersion: 0 },
    views: {}, $: get, e: String, icon: () => '', bindSubmit() {}, bindDirty() {},
    selects: { refresh() {} },
    motion: { enter() {}, loading() {}, segmented() {} },
    toast() {}, savedNotice() {}, error: e => errors.push(e),
    call(kind, name, args) {
      const d = deferred(); calls.push({ kind, name, args, ...d }); return d.promise;
    },
    buttonAction(button, operation) {
      button.disabled = true;
      const p = operation().catch(e => errors.push(e)).finally(() => {
        if (button.isConnected) button.disabled = false;
      });
      actions.push(p); return p;
    }, ...extra };
  const document = { hidden: false, querySelectorAll: () => [], createElement: () => node() };
  const context = vm.createContext({ window: { DrawpicUI: U }, document,
    structuredClone, URL, Blob, Uint8Array, atob, Date,
    setTimeout: (fn, delay) => { const id = ++timerId; timers.set(id, { fn, delay }); return id; },
    clearTimeout: id => timers.delete(id) });
  const run = name => vm.runInContext(read(name + '.js'), context, { filename: name + '.js' });
  if (file === 'forms') for (const name of ['forms/options', 'forms/controls', 'forms/collections']) run(name);
  run(file);
  return { U, nodes, get, calls, errors, actions, timers, context, document, run,
    tick: async delay => {
      const entry = [...timers].find(([, t]) => t.delay === delay);
      assert.ok(entry, `expected ${delay}ms timer`);
      timers.delete(entry[0]); entry[1].fn(); await flush();
    } };
}
const result = (lines, cursor = 'cursor', unchanged = false) => ({ lines, cursor, unchanged });
async function logs() {
  const h = harness('logs');
  h.get('#log-auto').checked = false;
  const opening = h.U.views.logs();
  h.calls[0].resolve(result(['initial'])); await opening;
  return h;
}
test('logs: a slow INFO query drains only the latest ERROR filter with auto refresh off', async () => {
  const h = await logs();
  h.get('#log-level').value = 'INFO'; h.get('#log-level').onchange();
  h.get('#log-level').value = 'WARNING'; h.get('#log-level').onchange();
  h.get('#log-level').value = 'ERROR'; h.get('#log-level').onchange();
  assert.equal(h.calls.length, 2);
  h.calls[1].resolve(result(['[INFO] stale'], 'old')); await flush();
  assert.equal(h.get('#log-output').textContent, 'initial');
  assert.equal(h.calls.length, 3);
  assert.equal(h.calls[2].args.level, 'ERROR');
  assert.equal(h.calls[2].args.cursor, '');
  h.calls[2].resolve(result(['[ERROR] latest'], 'new')); await flush();
  assert.equal(h.get('#log-output').textContent, '[ERROR] latest');
  assert.match(h.get('#log-status').textContent, /已更新/);
});
test('logs: task input invalidates an old response immediately, before debounce fires', async () => {
  const h = await logs();
  h.get('#log-level').value = 'INFO'; h.get('#log-level').onchange();
  h.get('#log-task').value = 'latest'; h.get('#log-task').oninput();
  h.calls[1].resolve(result(['stale'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'initial');
  await h.tick(300);
  assert.equal(h.calls[2].args.task_id, 'latest');
  h.calls[2].resolve(result(['new task'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'new task');
});
test('logs: task debounce during a slow request queues the latest task', async () => {
  const h = await logs();
  h.get('#log-filter').onsubmit(event);
  h.get('#log-task').value = 'demo00000003'; h.get('#log-task').oninput();
  await h.tick(300);
  h.calls[1].resolve(result(['stale'])); await flush();
  assert.equal(h.calls[2].args.task_id, 'demo00000003');
  h.calls[2].resolve(result(['latest task'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'latest task');
});
test('logs: old errors do not suppress queued filters; current errors allow retry', async () => {
  const h = await logs();
  h.get('#log-filter').onsubmit(event);
  h.get('#log-level').value = 'ERROR'; h.get('#log-level').onchange();
  h.calls[1].reject(Error('old error')); await flush();
  assert.equal(h.calls.length, 3); assert.equal(h.errors.length, 0);
  h.calls[2].reject(Error('current error')); await flush();
  assert.match(h.get('#log-status').textContent, /查询失败/);
  h.get('#log-filter').onsubmit(event);
  h.calls[3].resolve(result(['retried'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'retried');
});
test('logs: navigation and a newer render invalidate old responses', async () => {
  const h = await logs();
  h.get('#log-filter').onsubmit(event);
  const newer = h.U.views.logs();
  h.calls[1].resolve(result(['old render'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'initial');
  h.calls[2].resolve(result(['new render'])); await newer;
  h.get('#log-filter').onsubmit(event); h.U.state.view = 'tasks';
  h.calls[3].resolve(result(['wrong page'])); await flush();
  assert.equal(h.get('#log-output').textContent, 'new render');
});
test('logs: unchanged refresh preserves text and scrolled-up position', async () => {
  const h = await logs();
  h.get('#log-auto').checked = true;
  h.get('#log-output').scrollTop = 15;
  await h.tick(5000);
  assert.equal(h.calls[1].args.cursor, 'cursor');
  h.calls[1].resolve(result([], 'cursor', true)); await flush();
  assert.equal(h.get('#log-output').textContent, 'initial');
  assert.equal(h.get('#log-output').scrollTop, 15);
});
async function platform() {
  let h, renders = 0, closes = 0, boot = 0, form;
  const record = { id: 'one', kind: 'openai', name: 'one', config: { enabled: true } };
  h = harness('platforms', {
    forms: { html: () => '', bind: () => () => ({ enabled: true }) },
    platformModels: { bind: () => ({ clearApiKey: () => false }) },
    modal() { h.U.state.modalVersion++; form = node(); h.nodes.set('#provider-form', form); return node(); },
    closeModal() { closes++; form.isConnected = false; h.U.state.modalVersion++; },
    bootstrap: async () => { boot++; }, render: async () => { renders++; },
  });
  h.U.state.data = { revision: 9, catalog: [{ kind: 'openai', name: 'OpenAI', default_name: 'OpenAI_Compatible', defaults: {} }],
    providers: [record], schema: { sections: { openai: { fields: {} } } } };
  const card = node({ dataset: { provider: 'one' } });
  h.document.querySelectorAll = () => [card];
  await h.U.views.platforms();
  await h.get('[data-edit]').onclick();
  return { ...h, form, stats: () => ({ renders, closes, boot }) };
}
test('platform: save freezes all fields and rejects repeated submissions', async () => {
  const h = await platform();
  h.get('#provider-name').value = 'submitted'; h.U.state.dirty = true;
  h.form.onsubmit(event); h.form.onsubmit(event);
  assert.equal(h.form.inert, true); assert.equal(h.form.attrs['aria-busy'], 'true');
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].args.revision, 9);
  assert.equal(JSON.parse(h.calls[0].args.provider_json).name, 'submitted');
  h.calls[0].resolve({}); await flush();
  assert.equal(h.U.state.dirty, false); assert.equal(h.stats().closes, 1);
  assert.equal(h.stats().renders, 1);
});
test('platform: failed saves retain the draft and unfreeze the form', async () => {
  const h = await platform();
  h.get('#provider-name').value = 'keep draft'; h.U.state.dirty = true;
  h.form.onsubmit(event); await flush(); h.calls[0].reject(Error('conflict')); await flush();
  assert.equal(h.form.inert, false); assert.equal(h.form.attrs['aria-busy'], undefined);
  assert.equal(h.get('#provider-name').value, 'keep draft');
  assert.equal(h.U.state.dirty, true); assert.equal(h.stats().closes, 0);
  assert.equal(h.get('[type=submit]').disabled, false);
});
test('platform: an old save cannot close a replacement editor or clear its draft', async () => {
  const h = await platform();
  h.form.onsubmit(event);
  h.U.state.modalVersion++; h.U.state.dirty = true;
  h.calls[0].resolve({}); await flush();
  assert.equal(h.U.state.dirty, true); assert.equal(h.stats().closes, 0);
  assert.equal(h.stats().renders, 0); assert.equal(h.stats().boot, 1);
});
test('platform: detached forms cannot clear dirty state even with the same version', async () => {
  const h = await platform(); h.form.onsubmit(event);
  h.form.isConnected = false; h.U.state.dirty = true;
  h.calls[0].resolve({}); await flush();
  assert.equal(h.U.state.dirty, true); assert.equal(h.stats().closes, 0);
});
test('platform: durable-save warnings survive refresh errors without another save', async () => {
  const h = await platform();
  const notices = [];
  h.U.bootstrap = async () => { throw Error('read unavailable'); };
  h.U.savedNotice = (...args) => notices.push(args);
  h.U.state.dirty = true; h.form.onsubmit(event); await flush();
  const response = { saved: true, recovery_pending: true, warning: 'Saved; recovery pending' };
  h.calls[0].resolve(response); await flush();
  assert.equal(h.calls.length, 1); assert.equal(h.errors.length, 0);
  assert.equal(h.U.state.dirty, false); assert.equal(h.stats().closes, 1);
  assert.equal(h.stats().renders, 0); assert.equal(notices[0][0], response);
  assert.match(notices[0][2].message, /read unavailable/);
});
test('platform: delete warnings and read failures report a committed removal', async () => {
  const h = await platform(), notices = [];
  h.U.bootstrap = async () => { throw Error('read failed after removal'); };
  h.U.savedNotice = (...args) => notices.push(args);
  h.get('[data-delete]').onclick({ currentTarget: h.get('[data-delete]') });
  const response = { saved: true, runtime_refresh_pending: true, warning: 'pending' };
  h.calls[0].resolve(response); await flush();
  assert.equal(h.calls[0].name, 'provider_delete');
  assert.equal(h.errors.length, 0); assert.equal(notices[0][0], response);
  assert.equal(notices[0][1], '平台已移除'); assert.equal(h.stats().renders, 0);
});
test('platform: a completed deletion cannot rerender a newer settings draft', async () => {
  const h = await platform();
  h.get('[data-delete]').onclick({ currentTarget: h.get('[data-delete]') });
  h.U.state.view = 'settings'; h.U.state.dirty = true;
  h.calls[0].resolve({ saved: true }); await flush();
  assert.equal(h.stats().renders, 0); assert.equal(h.U.state.dirty, true);
});
async function settings(view = 'settings') {
  let h;
  const tabs = (view === 'library' ? ['style', 'references', 'materials'] : ['general', 'review', 'access']).map(section => node({ dataset: { section } }));
  h = harness('settings', {
    referenceUI: { gallery() {}, confirmButton() {}, presetTypes() {}, confirmSettings: async () => true },
    forms: { html: () => '', bind: (panel, fields, values) => {
      panel.fields = fields; panel.values = structuredClone(values); return () => structuredClone(panel.values);
    } },
    bootstrap: async () => {}, render: async () => {},
    submitForm: form => form.onsubmit(event),
  });
  h.U.state.data = { revision: 7, reference_fields: { self_reference_enabled: {}, self_reference_ids: {}, multi_reference_confirmed: {}, allow_chat_material_search: {}, chat_material_search_limit: {}, material_model: {}, allow_web_material_search: {} },
    schema: { sections: { general: { fields: { timeout: {}, prompt_review_enabled: {}, integration_api_enabled: {}, group_access_ids: {}, private_access_mode: {}, admin_user_ids: {}, group_default_quota: {} } }, style: { fields: { presets: {} } } } },
    settings: { general: { references: structuredClone(referenceDefaults), timeout: 150, prompt_review_enabled: false, integration_api_enabled: true, group_access_ids: [], private_access_mode: 'blacklist', admin_user_ids: [], group_default_quota: 10 }, style: { presets: [] } },
    defaults: { general: { references: structuredClone(referenceDefaults), timeout: 150, prompt_review_enabled: false, integration_api_enabled: true, group_access_ids: [], private_access_mode: 'blacklist', admin_user_ids: [], group_default_quota: 10 }, style: { presets: [] } } };
  const form = h.get('#settings-form');
  form.querySelector = () => null;
  form.append = panel => form.children.push(panel);
  h.U.$ = (selector, root) => selector.startsWith('#settings-panel-')
    ? form.children.find(p => '#' + p.id === selector) : h.get(selector);
  h.document.querySelectorAll = selector => selector === '[data-section]' ? tabs : [];
  // Controllers capture U.$ when loaded, so reload after installing the scoped seam.
  h.run('settings');
  h.U.state.view = view;
  await h.U.views[view]();
  return { ...h, form, tabs, panel: name => form.children.find(panel => panel.dataset.settingsPanel === name) };
}
test('settings: runtime drafts survive category changes and preserve creative configuration', async () => {
  const h = await settings();
  h.panel('general').values.timeout = 231;
  h.panel('review').values.prompt_review_enabled = true;
  h.panel('general').values.integration_api_enabled = false;
  h.panel('access').values.group_access_ids = ['123456'];
  h.panel('access').values.private_access_mode = 'whitelist';
  h.panel('access').values.admin_user_ids = ['10001'];
  h.panel('access').values.group_default_quota = 20;
  assert.deepEqual(Object.keys(h.panel('general').fields), ['timeout', 'integration_api_enabled']);
  assert.deepEqual(Object.keys(h.panel('access').fields), ['group_access_ids', 'private_access_mode', 'admin_user_ids', 'group_default_quota']);
  h.U.state.dirty = true;
  h.tabs[1].onclick(); h.tabs[2].onclick(); h.tabs[0].onclick();
  assert.equal(h.panel('general').values.timeout, 231);
  h.form.onsubmit(event); h.form.onsubmit(event);
  await flush();
  assert.equal(h.calls.length, 1); assert.equal(h.form.inert, true);
  const submitted = JSON.parse(h.calls[0].args.config_json);
  assert.equal(submitted.general.timeout, 231);
  assert.equal(submitted.general.references.allow_web_material_search, false);
  assert.equal(submitted.general.prompt_review_enabled, true);
  assert.equal(submitted.general.integration_api_enabled, false);
  assert.deepEqual(submitted.general.group_access_ids, ['123456']);
  assert.equal(submitted.general.private_access_mode, 'whitelist');
  assert.deepEqual(submitted.general.admin_user_ids, ['10001']);
  assert.equal(submitted.general.group_default_quota, 20);
  assert.deepEqual(submitted.style.presets, []);
  h.calls[0].resolve({ saved: true }); await flush();
  assert.equal(h.U.state.dirty, false);
});
test('creative: preset, self-reference and material drafts merge without overwriting one another', async () => {
  const h = await settings('library');
  h.panel('style').values.presets.push({ name: 'draft' });
  h.panel('references').values.self_reference_enabled = true;
  h.panel('materials').values.allow_web_material_search = true;
  h.panel('materials').values.chat_material_search_limit = 80;
  h.panel('materials').values.material_model = 'fast-vision';
  assert.ok(Object.hasOwn(h.panel('materials').fields, 'chat_material_search_limit'));
  assert.equal(Object.hasOwn(h.panel('references').fields, 'chat_material_search_limit'), false);
  h.tabs[1].onclick(); h.tabs[2].onclick(); h.tabs[0].onclick();
  h.U.state.dirty = true;
  h.form.onsubmit(event); await flush();
  const submitted = JSON.parse(h.calls[0].args.config_json);
  assert.equal(submitted.style.presets[0].name, 'draft');
  assert.equal(submitted.general.references.self_reference_enabled, true);
  assert.equal(submitted.general.references.allow_web_material_search, true);
  assert.equal(submitted.general.references.chat_material_search_limit, 80);
  assert.equal(submitted.general.references.material_model, 'fast-vision');
  assert.equal(submitted.general.timeout, 150);
  assert.deepEqual(submitted.general.admin_user_ids, []);
  h.calls[0].resolve({ saved: true }); await flush();
  assert.equal(h.U.state.dirty, false);
});

test('settings: failed saves retain both category drafts and allow editing', async () => {
  const h = await settings();
  h.panel('general').values.timeout = 245;
  h.panel('review').values.prompt_review_enabled = true; h.U.state.dirty = true;
  h.form.onsubmit(event); await flush(); h.calls[0].reject(Error('revision conflict')); await flush();
  assert.equal(h.panel('general').values.timeout, 245);
  assert.equal(h.panel('review').values.prompt_review_enabled, true);
  assert.equal(h.U.state.dirty, true); assert.equal(h.form.inert, false);
  assert.equal(h.get('#reset-settings').disabled, false);
});
test('settings: saved-but-unreadable state warns and prevents resubmission until refresh', async () => {
  const h = await settings(), notices = [];
  h.U.bootstrap = async () => { throw Error('bootstrap failed'); };
  h.U.savedNotice = (...args) => notices.push(args);
  h.U.state.dirty = true; h.form.onsubmit(event); await flush();
  const response = { saved: true, runtime_refresh_pending: true, warning: 'Runtime refresh pending' };
  h.calls[0].resolve(response); await flush();
  assert.equal(h.U.state.dirty, false); assert.equal(h.form.inert, true);
  assert.equal(h.get('#save-settings').disabled, true);
  assert.equal(h.get('#reset-settings').disabled, true);
  h.form.onsubmit(event); assert.equal(h.calls.length, 1);
  assert.equal(h.errors.length, 0); assert.equal(notices[0][0], response);
  assert.match(notices[0][2].message, /bootstrap failed/);
});
test('settings: stale completion leaves newer dirty state alone', async () => {
  const h = await settings(); h.form.onsubmit(event); await flush();
  h.form.isConnected = false; h.U.state.dirty = true;
  h.calls[0].resolve({ saved: true }); await flush();
  assert.equal(h.U.state.dirty, true);
});
test('task details: close/navigation/newer request before the first response keep it stale', async () => {
  let modals = 0;
  const h = harness('tasks', { modal: () => { modals++; return node(); } });
  for (const invalidate of [() => h.U.state.modalVersion++, () => h.U.state.view = 'logs']) {
    h.U.state.view = 'tasks'; const opening = h.U.openTask('old');
    invalidate(); h.calls.at(-1).resolve({}); await opening;
  }
  h.U.state.view = 'tasks'; const first = h.U.openTask('first');
  const second = h.U.openTask('second');
  h.calls.at(-2).resolve({}); await first;
  h.U.state.modalVersion++; h.calls.at(-1).resolve({}); await second;
  assert.equal(modals, 0);
});
test('forms: scalar hints link to controls and nested arrays have legends with unique IDs', () => {
  const h = harness('forms'); h.U.state.data = { models: [] };
  const html = h.U.forms.html({
    timeout: { type: 'integer', default: 150, label: 'Timeout', hint: 'Seconds' },
    presets: { type: 'array', item_type: 'object', default: [], label: 'Presets', hint: 'Templates',
      item_fields: { positive_prompt_template: { type: 'string', default: '', label: 'Prompt', hint: '{prompt}' } } },
  }, { presets: [{ positive_prompt_template: 'one' }, { positive_prompt_template: 'two' }] });
  assert.match(html, /<input id="(field-\d+)" aria-describedby="\1-hint"/);
  assert.match(html, /<fieldset[^>]*aria-describedby="field-\d+-hint"><legend class="field-heading">Presets<\/legend>/);
  assert.equal((html.match(/<textarea id="(field-\d+)" aria-describedby="\1-hint"/g) || []).length, 2);
  const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map(m => m[1]);
  assert.equal(ids.length, new Set(ids).size);
  for (const [, id] of html.matchAll(/(?:for|aria-describedby)="([^"]+)"/g)) assert.ok(ids.includes(id));
});
test('forms: credential defaults stay blank instead of inserting configuration placeholders', () => {
  const h = harness('forms');
  const html = h.U.forms.html({
    api_key: { type: 'string', label: 'API Key', default: 'your-placeholder-api-key' },
    password: { type: 'string', label: 'Password', default: 'your-placeholder-password' },
  }, {});
  assert.match(html, /data-input="api_key" value=""/);
  assert.match(html, /data-input="password" value=""/);
  assert.doesNotMatch(html, /your-placeholder-/);
});

test('forms: wrapped platform fields read edited values and exclude nested object names', () => {
  const h = harness('forms');
  const arrayField = node({ dataset: { field: 'presets' } });
  const nested = node({ dataset: { field: 'name' }, parentElement: { closest: () => arrayField } });
  const outer = node({ dataset: { field: 'name' }, parentElement: { closest: () => null } });
  const input = node({ value: 'changed-after-opening' });
  const root = node({ contains: n => n === arrayField,
    querySelectorAll: selector => selector === '[data-field]' ? [nested, outer] : [] });
  h.U.$ = selector => selector === '[data-input]' ? input : null;
  h.run('forms');
  const result = h.U.forms.read({ name: { type: 'string', label: 'Name' } }, { name: 'original' }, root);
  assert.equal(result.name, 'changed-after-opening');
  root.querySelectorAll = () => [];
  assert.throws(() => h.U.forms.read({ name: { type: 'string', label: 'Name' } }, {}, root), /未找到.*Name/);
});

test('forms: node IDs use single-line controls and uint64 seeds round-trip without Number rounding', () => {
  const h = harness('forms');
  const meta = { type: 'integer', label: 'Seed', default: -1, min: -1, max: '18446744073709551615' };
  const html = h.U.forms.html({ seed: meta, t2i_prompt_node_id: { type: 'string', label: 'Node' },
    prompt_input_name: { type: 'string', label: 'Field' } }, { seed: '18446744073709551615' });
  assert.match(html, /type="text" inputmode="numeric"[^>]*data-exact-integer/);
  assert.match(html, /<input[^>]*data-input="t2i_prompt_node_id"/);
  assert.match(html, /<input[^>]*data-input="prompt_input_name"/);
  const field = node({ dataset: { field: 'seed' }, parentElement: { closest: () => null } });
  const input = node({ value: '18446744073709551615', hasAttribute: name => name === 'data-exact-integer' });
  const root = node({ contains: () => false, querySelectorAll: () => [field] });
  h.U.$ = selector => selector === '[data-input]' ? input : null;
  h.run('forms');
  assert.equal(h.U.forms.read({ seed: meta }, {}, root).seed, '18446744073709551615');
  input.value = '18446744073709551616';
  assert.throws(() => h.U.forms.read({ seed: meta }, {}, root), /超出允许范围/);
  input.value = '0';
  assert.equal(h.U.forms.read({ seed: meta }, {}, root).seed, 0);
});

test('invalid default model: diagnostics remain linked to the configuration control', () => {
  const h = harness('forms');
  h.U.state.data = { models: [], default_model: '', default_model_error: 'Ambiguous model',
    settings: { general: { default_model: 'shared' } } };
  const html = h.U.forms.html({ default_model: { type: 'string', default: '', label: 'Default model' } },
    { default_model: 'shared' });
  assert.match(html, /<select id="(field-\d+)" aria-describedby="\1-hint"/);
  assert.match(html, /Ambiguous model/);
  assert.match(html, /请选择完整/);
  assert.match(read('studio.js'), /<option value="" selected>请选择平台实例 \/ 模型<\/option>/);
});
test('typed values retain zero, false, literal strings and exact JSON integers', () => {
  const h = harness('forms');
  const row = node({ hasAttribute: name => name === 'data-parameter-row' });
  h.get('[data-key]').value = 'value';
  const input = h.get('[data-param-value]');
  input.setCustomValidity = message => { input.error = message; };
  input.reportValidity = () => false;
  for (const [type, value, encoded, checked = false] of [
    ['number', '0', '0'], ['boolean', 'on', 'false'], ['boolean', 'on', 'true', true], ['text', '123', '"123"'],
    ['json', '{"id":9007199254740993}', '{"id":9007199254740993}'],
  ]) {
    h.get('[data-param-type]').value = type; input.value = value; input.checked = checked;
    assert.equal(h.U.formCollections.readRow('extra_parameters', row), `value=${encoded}`);
  }
  h.get('[data-param-type]').value = 'json'; input.value = '{"value":1e999}';
  assert.throws(() => h.U.formCollections.readRow('extra_parameters', row), /JSON 参数格式/);
  assert.match(input.error, /数字范围/);
});

test('dimensions use the platform separator and preserve nonstandard saved values', () => {
  const h = harness('forms');
  const control = node({ dataset: { control: 'dimension', kind: 'aliyun' } });
  h.get('[data-choice-select]').value = '__workspace_custom__';
  h.get('[data-width]').value = '2048'; h.get('[data-height]').value = '1024';
  assert.equal(h.U.formControls.read(control), '2048*1024');
  control.dataset.kind = 'openai';
  assert.equal(h.U.formControls.read(control), '2048x1024');
  h.get('[data-choice-select]').value = 'legacy-size-value';
  assert.equal(h.U.formControls.read(control), 'legacy-size-value');
});

test('light theme small text and selected foreground meet 4.5:1; dark colors stay covered', () => {
  const css = read('style.css');
  const contrast = (a, b) => {
    const luminance = hex => {
      const c = hex.slice(1).match(/../g).map(x => parseInt(x, 16) / 255)
        .map(x => x <= .04045 ? x / 12.92 : ((x + .055) / 1.055) ** 2.4);
      return c[0] * .2126 + c[1] * .7152 + c[2] * .0722;
    };
    const x = luminance(a), y = luminance(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05);
  };
  for (const block of [css.split('.dark')[0], css.split('.dark {')[1].split('}')[0]]) {
    const color = key => { let s = block.match(new RegExp(`--${key}: (#[a-f0-9]+);`))[1]; return s.length === 4 ? '#' + [...s.slice(1)].map(c => c+c).join('') : s; };
    for (const bg of ['surface', 'bg', 'soft']) assert.ok(contrast(color('muted'), color(bg)) >= 4.5);
    assert.ok(contrast(color('accent'), color('accent-soft')) >= 4.5);
  }
});
test('mode state, mobile save label and allowed animations stay explicit', () => {
  const studio = read('studio.js');
  assert.match(studio, /id="mode-draw" aria-pressed="\$\{mode === "draw"\}"/);
  assert.match(studio, /id="mode-edit" aria-pressed="\$\{mode === "edit_image"\}"/);
  assert.doesNotMatch(studio, /duration: 190|translateY\(-5px\)/);
  assert.match(read('index.html'), /class="action-tag" aria-hidden="true">保存全部设置<\/span>/);
});

test('submit: ordinary input Enter and IME never start a drawing in shortcut-only forms', () => {
  const source = read('app.js');
  const code = source.slice(source.indexOf('  function bindSubmit('), source.indexOf('  window.DrawpicUI ='));
  for (const [options, keys, tagName, expected] of [
    [{ shortcutOnly: true }, {}, 'INPUT', 0],
    [{ shortcutOnly: true }, {}, 'TEXTAREA', 0],
    [{ shortcutOnly: true }, { ctrlKey: true }, 'TEXTAREA', 1],
    [{ shortcutOnly: true }, { metaKey: true }, 'INPUT', 1],
    [{ shortcutOnly: true }, { ctrlKey: true, isComposing: true }, 'INPUT', 0],
    [{}, {}, 'INPUT', 1],
    [{}, { isComposing: true }, 'INPUT', 0],
    [{}, { defaultPrevented: true }, 'INPUT', 0],
  ]) {
    let submissions = 0, keydown;
    const form = { querySelectorAll: () => [], addEventListener: (_name, handler) => { keydown = handler; } };
    const bind = new Function('submitForm', code + ';return bindSubmit;')(() => { submissions++; });
    bind(form, options);
    keydown({ key: 'Enter', target: { tagName }, preventDefault() {}, ...keys });
    assert.equal(submissions, expected, JSON.stringify({ options, keys, tagName }));
  }
});

test('tag control: IME stays intact, Enter commits unique tags, limits preserve the pending draft', () => {
  const h = harness('forms');
  let values = ['自拍'], inputEvents = 0;
  const input = node({ value: '画,自拍，绘图', validationMessage: '',
    setCustomValidity(value) { this.validationMessage = value; }, reportValidity() {},
    insertAdjacentHTML(_position, html) { values.push(html.match(/data-tag-value value="([^"]*)"/)[1]); },
    closest: () => input });
  const control = node({ dataset: { control: 'tags', limit: '3', maxLength: '80' },
    dispatchEvent() { inputEvents++; }, querySelectorAll: () => values.map(value => ({ value })) });
  input.parentElement = control;
  h.nodes.set('[data-tag-entry]', input);
  const listeners = {};
  h.U.formControls.bind({ addEventListener(name, fn) { listeners[name] = fn; } });
  let prevented = 0;
  const key = { target: input, key: 'Enter', preventDefault() { prevented++; } };
  listeners.keydown({ ...key, isComposing: true });
  assert.equal(input.value, '画,自拍，绘图'); assert.equal(prevented, 0);
  listeners.keydown({ ...key, ctrlKey: true });
  assert.equal(prevented, 0);
  h.context.Event = class Event {};
  listeners.keydown(key);
  assert.deepEqual(values, ['自拍', '画', '绘图']); assert.equal(input.value, '');
  assert.equal(prevented, 1); assert.equal(inputEvents, 1);
  input.value = '多余项';
  assert.throws(() => h.U.formControls.read(control), /最多 3 项/);
  assert.equal(input.value, '多余项'); assert.deepEqual(values, ['自拍', '画', '绘图']);
  input.value = ''; values.pop(); input.value = '重绘';
  assert.deepEqual([...h.U.formControls.read(control)], ['自拍', '画', '重绘']);
});

test('recognition model control distinguishes the default task from a concrete model with the same name', () => {
  const h = harness('forms'), control = { dataset: { control: 'recognition-model' } };
  h.get('[data-choice-select]').value = '__workspace_custom__';
  h.get('[data-custom-value]').value = ' vlm ';
  assert.equal(h.U.formControls.read(control), 'model:vlm');
  h.get('[data-choice-select]').value = 'vlm';
  assert.equal(h.U.formControls.read(control), 'vlm');
});

// Use the actual production bridge queue: ordering bugs must not be tested with
// independently resolving RPC promises that the application cannot issue.
function fifoController(file = 'studio') {
  const state = { view: file, busy: 0, lastTask: null, sources: [],
    data: { models: [{ name: 'model', draw: true }], presets: [], default_model: 'model', settings: { general: { references: structuredClone(referenceDefaults) }, style: { default_style: '', image_edit_presets_enabled: false, default_image_edit_preset: '' } } },
    taskPage: 1, taskStatus: '', taskSearch: '' };
  const calls = [];
  const bridge = (name, args) => {
    const d = deferred(); calls.push({ name, args, ...d }); return d.promise;
  };
  const app = read('app.js');
  const callSource = app.slice(app.indexOf('  let queue = Promise.resolve()'), app.indexOf('  function toast('));
  const call = new Function('window', 'state', callSource + ';return call;')(
    { maibot: { ready: Promise.resolve(), query: bridge, action: bridge } }, state);
  let keys = 0;
  const h = harness(file, { state, call, statusLabel: String, uid: () => `request-key-${++keys}` });
  h.calls = calls;
  return h;
}
const taskSnapshot = (id, extra = {}) => ({ task_id: id, images: [], status: 'running',
  message: id, model: 'model', ...extra });
const taskList = active => ({ counts: { pending: 0, running: active, completed: 0, failed: 0, rejected: 0 },
  items: [], total: 0, page_size: 20 });
test('studio FIFO: late A receipt cannot clear queued B key; lost receipt reuses exact snapshot after rebuild', async () => {
  const h = fifoController();
  await h.U.views.studio();
  h.get('#draw-model').value = 'model'; h.get('#draw-prompt').value = 'A';
  h.get('#draw-form').onsubmit(event); await flush();
  h.get('#draw-prompt').value = 'B'; h.get('#draw-form').oninput();
  h.U.state.view = 'tasks'; h.U.state.view = 'studio'; await h.U.views.studio();
  h.get('#draw-form').onsubmit(event); await flush();
  assert.equal(h.calls.length, 1);
  assert.equal(h.U.state.requestId, 'request-key-2');
  h.calls[0].resolve({ task_id: 'A' }); await flush();
  assert.equal(h.U.state.requestId, 'request-key-2');
  assert.equal(h.U.state.lastTask, null);
  const original = h.calls[1].args.request_json;
  h.calls[1].reject(Error('B accepted but receipt lost')); await flush();
  await h.U.views.studio();
  assert.match(h.get('#studio-submissions').innerHTML, /恢复原提交/);
  h.get('#draw-form').onsubmit(event); await flush();
  assert.equal(h.calls[2].args.request_json, original);
  h.calls[2].resolve({ task_id: 'B' }); await flush();
  h.calls[3].resolve(taskSnapshot('B', { status: 'completed' })); await flush();
  assert.equal(h.U.state.lastTask, 'B'); assert.equal(h.U.state.requestId, null);
  assert.equal(h.get('#studio-submissions').innerHTML, '');
});
test('studio FIFO: same pending snapshot is not submitted twice after rebuild or input events', async () => {
  const h = fifoController(); await h.U.views.studio();
  h.get('#draw-model').value = 'model'; h.get('#draw-prompt').value = 'same';
  h.get('#draw-form').onsubmit(event); await flush();
  h.get('#draw-form').oninput(); await h.U.views.studio();
  h.get('#draw-form').onsubmit(event); await flush();
  assert.equal(h.calls.length, 1);
  h.calls[0].reject(Error('receipt lost')); await flush();
  h.get('#draw-form').onsubmit(event); await flush();
  assert.equal(h.calls[1].args.request_json, h.calls[0].args.request_json);
});
test('studio FIFO: superseded A task response does not enqueue preview after queued B query', async () => {
  const h = fifoController(); h.U.state.lastTask = 'A';
  const old = h.U.views.studio(); await flush();
  h.U.state.lastTask = 'B'; const fresh = h.U.views.studio(); await flush();
  assert.equal(h.calls.length, 1);
  h.calls[0].resolve(taskSnapshot('A', { status: 'completed', images: [{}] })); await old; await flush();
  assert.equal(h.calls[1].args.task_id, 'B');
  h.calls[1].resolve(taskSnapshot('B')); await fresh;
  assert.equal(h.calls.length, 2);
  assert.match(h.get('#studio-result').innerHTML, /B/);
  assert.equal(h.timers.size, 1);
});
test('studio FIFO: an in-flight old preview cannot render or schedule after a new task/page generation', async () => {
  const h = fifoController(); h.U.state.lastTask = 'A';
  const old = h.U.views.studio(); await flush();
  h.calls[0].resolve(taskSnapshot('A', { images: [{}] })); await flush();
  assert.equal(h.calls[1].name, 'image');
  h.U.state.lastTask = 'B'; const fresh = h.U.views.studio(); await flush();
  h.get('#studio-result').innerHTML = 'new page';
  h.calls[1].resolve({ data_url: 'old-preview', width: 1, height: 1 }); await old; await flush();
  assert.equal(h.get('#studio-result').innerHTML, 'new page');
  assert.equal(h.timers.size, 0);
  h.calls[2].resolve(taskSnapshot('B')); await fresh;
  assert.doesNotMatch(h.get('#studio-result').innerHTML, /old-preview/);
  assert.equal(h.timers.size, 1);
});
test('studio FIFO: transient task and preview failures preserve last good view and retry only reads', async () => {
  const h = fifoController(); h.U.state.lastTask = 'A';
  const opening = h.U.views.studio(); await flush();
  h.calls[0].resolve(taskSnapshot('A')); await opening;
  const previous = h.get('#studio-result').innerHTML;
  for (let i = 0; i < 2; i++) {
    await h.tick(5000); h.calls.at(-1).reject(Error('temporary read failure')); await flush();
    assert.equal(h.timers.size, 1); assert.equal(h.get('#studio-result').innerHTML, previous);
  }
  assert.equal(h.errors.length, 1);
  await h.tick(5000); h.calls.at(-1).resolve(taskSnapshot('A', { images: [{}], status: 'completed' })); await flush();
  h.calls.at(-1).reject(Error('preview unavailable')); await flush();
  assert.equal(h.timers.size, 1); assert.equal(h.errors.length, 1);
  await h.tick(5000); h.calls.at(-1).resolve(taskSnapshot('A', { images: [{}], status: 'completed' })); await flush();
  h.calls.at(-1).resolve({ data_url: 'new-preview', width: 1, height: 1 }); await flush();
  assert.equal(h.timers.size, 0); assert.match(h.get('#studio-result').innerHTML, /new-preview/);
  assert.ok(h.calls.every(c => ['task', 'image'].includes(c.name)));
});
test('studio FIFO: leaving during failed query does not retry or notify on another page', async () => {
  const h = fifoController(); h.U.state.lastTask = 'A';
  const opening = h.U.views.studio(); await flush();
  h.U.state.view = 'tasks'; h.calls[0].reject(Error('stale')); await opening;
  assert.equal(h.timers.size, 0); assert.equal(h.errors.length, 0);
});
test('tasks FIFO: transient failures retry at five seconds without erasing filter drafts or flooding errors', async () => {
  const h = fifoController('tasks'); h.U.empty = () => 'empty';
  const opening = h.U.views.tasks(); await flush(); h.calls[0].resolve(taskList(1)); await opening;
  h.get('#task-search-text').value = 'unsent draft';
  h.get('#task-search-text').oninput({ currentTarget: h.get('#task-search-text') });
  const previous = h.get('#workspace-content').innerHTML;
  for (let i = 0; i < 2; i++) {
    await h.tick(5000); h.calls.at(-1).reject(Error('temporary')); await flush();
    assert.equal(h.timers.size, 1); assert.equal(h.get('#workspace-content').innerHTML, previous);
    assert.equal(h.get('#task-search-text').value, 'unsent draft');
  }
  assert.equal(h.errors.length, 1);
  await h.tick(5000); h.calls.at(-1).resolve(taskList(0)); await flush();
  assert.equal(h.timers.size, 0); assert.equal(h.get('#task-search-text').value, 'unsent draft');
  assert.ok(h.calls.every(c => c.name === 'tasks'));
});
test('tasks FIFO: editing pauses retries and navigation invalidates outstanding read failures', async () => {
  const h = fifoController('tasks'); h.U.empty = () => 'empty';
  const opening = h.U.views.tasks(); await flush(); h.calls[0].reject(Error('temporary')); await opening;
  h.get('#task-search').contains = () => true;
  await h.tick(5000); assert.equal(h.calls.length, 1); assert.equal(h.timers.size, 1);
  h.get('#task-search').contains = () => false;
  await h.tick(5000); assert.equal(h.calls.length, 2);
  h.U.state.view = 'studio'; h.calls[1].reject(Error('stale')); await flush();
  assert.equal(h.timers.size, 0); assert.equal(h.errors.length, 1);
});
test('studio FIFO: explicit recovery resends immutable original content despite a different current draft', async () => {
  const h = fifoController();
  const buttons = [];
  h.get('#studio-submissions').querySelectorAll = () => buttons;
  await h.U.views.studio();
  h.get('#draw-model').value = 'model'; h.get('#draw-prompt').value = 'original';
  h.get('#draw-form').onsubmit(event); await flush();
  const original = h.calls[0].args.request_json;
  const id = JSON.parse(original).request_id;
  buttons.push(node({ dataset: { retryRequest: id } }));
  h.calls[0].reject(Error('receipt lost')); await flush();
  h.get('#draw-prompt').value = 'different draft'; h.get('#draw-form').oninput();
  await h.U.views.studio();
  buttons[0].onclick(); await flush();
  assert.equal(h.calls[1].args.request_json, original);
  assert.equal(h.get('#draw-prompt').value, 'different draft');
});
test('tasks FIFO: newer filter request suppresses old success and its polling timer', async () => {
  const h = fifoController('tasks'); h.U.empty = () => 'empty';
  const old = h.U.views.tasks(); await flush();
  h.U.state.taskSearch = 'new filter'; const fresh = h.U.views.tasks();
  h.get('#workspace-content').innerHTML = 'keep';
  h.calls[0].resolve(taskList(1)); await old; await flush();
  assert.equal(h.get('#workspace-content').innerHTML, 'keep'); assert.equal(h.timers.size, 0);
  assert.equal(h.calls[1].args.search, 'new filter');
  h.calls[1].resolve(taskList(0)); await fresh;
  assert.equal(h.timers.size, 0);
});
test('bootstrap: pending transaction/runtime notices survive read refresh until server confirms clear', async () => {
  const nodes = new Map();
  const get = selector => {
    if (!nodes.has(selector)) nodes.set(selector, node());
    return nodes.get(selector);
  };
  const state = {};
  let response;
  const app = read('app.js');
  const source = app.slice(app.indexOf('  async function bootstrap()'), app.indexOf('  function savedNotice('));
  const bootstrap = new Function('state', '$', 'call', source + ';return bootstrap;')(
    state, get, async () => { if (response instanceof Error) throw response; return response; });
  response = { config_update_pending: true, runtime_refresh_pending: true };
  await bootstrap();
  assert.equal(get('#load-error').hidden, false);
  assert.match(get('#load-error').textContent, /设置仍在生效中/);
  await bootstrap(); // The toolbar refresh uses this same production function.
  assert.equal(get('#load-error').hidden, false);
  response = { config_update_pending: false, runtime_refresh_pending: true };
  await bootstrap();
  assert.equal(get('#load-error').hidden, false);
  assert.match(get('#load-error').textContent, /页面刷新只重新查询状态/);
  response = Error('read failed');
  await assert.rejects(bootstrap(), /read failed/);
  assert.equal(get('#load-error').hidden, false);
  response = { config_update_pending: false, runtime_refresh_pending: false };
  await bootstrap();
  assert.equal(get('#load-error').hidden, true);
  assert.equal(get('#load-error').textContent, '');
  assert.doesNotMatch(read('boot.js'), /hidden\s*=\s*true/);
});

test('page render uses the shared motion component without an undeclared UI alias', async () => {
  const app = read('app.js');
  const source = app.slice(app.indexOf('  async function render()'), app.indexOf('  function updateNavigationIndicator()'));
  const nodes = new Map(), events = [];
  const get = key => { if (!nodes.has(key)) nodes.set(key, {}); return nodes.get(key); };
  const state = { view: 'tasks', dirty: false };
  const motion = { loading: (node, pending) => events.push(pending), enter: () => events.push('enter') };
  const render = new Function('state', '$', 'titles', 'document', 'views', 'updateNavigationIndicator', 'window', source + ';return render;')(
    state, get, { tasks: '绘图任务' }, { querySelectorAll: () => [] },
    { tasks: async () => events.push('rendered') }, () => {}, { DrawpicUI: { motion } },
  );
  await render();
  assert.equal(get('#page-title').textContent, '绘图任务');
  assert.deepEqual(events, [true, 'rendered', 'enter', false]);
});
