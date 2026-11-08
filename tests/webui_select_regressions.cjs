// Component event and viewport seams; actual browser layout is checked separately.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function element(tag = 'DIV') {
  const attributes = new Map(), listeners = new Map();
  return { tagName: tag, nodeType: 1, style: {}, children: [], value: '', disabled: false,
    isConnected: true, offsetHeight: 160, selectedIndex: 0, textContent: '', type: '',
    attributes, listeners,
    append(...nodes) { this.children.push(...nodes); nodes.forEach(node => { node.parentElement = this; }); },
    replaceWith() {}, focus() { this.ownerDocument.activeElement = this; },
    matches(selector) { return selector === 'select' ? tag === 'SELECT' : selector === ':disabled' ? this.disabled : selector === ':popover-open' ? Boolean(this.open) : false; },
    closest() { return null; }, querySelectorAll() { return []; }, querySelector() { return null; },
    setAttribute(name, value) { attributes.set(name, String(value)); },
    getAttribute(name) { return attributes.get(name) ?? null; },
    removeAttribute(name) { attributes.delete(name); },
    addEventListener(name, callback) { listeners.set(name, callback); },
    dispatchEvent(event) { listeners.get(event.type)?.(event); },
    getBoundingClientRect() { return this.rect || { left: 20, right: 320, top: 400, bottom: 442, width: 300, height: 42 }; },
    showPopover() { this.open = true; }, hidePopover() { this.open = false; },
    contains(node) { return node === this || this.children.includes(node); },
  };
}

function harness() {
  const document = element('DOCUMENT'), body = element('BODY');
  document.body = body;
  document.documentElement = { clientWidth: 390 };
  document.activeElement = body;
  const search = element('INPUT'), list = element(), status = element('P'), panel = element();
  panel.append(search, list, status);
  search.type = 'search'; list.id = 'select-options';
  panel.querySelector = selector => ({ input: search, '[role=listbox]': list, '[role=status]': status })[selector];
  const native = element('SELECT');
  native.validity = { valid: true }; native.required = false;
  native.getAttribute = name => name === 'aria-label' ? '绘图选项' : null;
  native.options = ['图片', '文本'].map((label, index) => ({ label, value: String(index), index, disabled: false, hidden: false, parentElement: native }));
  Object.defineProperty(native, 'selectedOptions', { get: () => [native.options[native.selectedIndex]] });
  document.querySelectorAll = () => [native];
  let trigger, divs = 0;
  document.createElement = tag => {
    if (tag === 'div') return divs++ === 0 ? panel : element();
    if (tag === 'button') {
      trigger = element('BUTTON');
      const text = element('SPAN');
      trigger.querySelector = () => text;
      trigger.ownerDocument = document;
      return trigger;
    }
    throw new Error(`Unexpected element: ${tag}`);
  };
  for (const node of [body, search, list, status, panel, native]) node.ownerDocument = document;
  const viewportListeners = new Map();
  const viewport = { width: 390, height: 844, offsetTop: 0, offsetLeft: 0,
    addEventListener(name, callback) { viewportListeners.set(name, callback); } };
  const U = { e: String, icon: () => '', toast() {} };
  const context = vm.createContext({ document, window: { DrawpicUI: U, visualViewport: viewport, addEventListener() {} },
    innerHeight: 844, Node: { ELEMENT_NODE: 1 }, Event: class { constructor(type) { this.type = type; } },
    MutationObserver: class { observe() {} } });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../src/maimai_drawpic/interfaces/webui/src/forms/select.js'), 'utf8'), context);
  trigger.listeners.get('click')();
  return { document, panel, search, native, trigger, viewport, viewportListeners };
}

function key(value, extra = {}) {
  return { key: value, prevented: false, stopped: false,
    preventDefault() { this.prevented = true; }, stopPropagation() { this.stopped = true; }, ...extra };
}

test('search: IME confirmation never selects a value or closes the popup', () => {
  for (const extra of [{ isComposing: true }, { keyCode: 229 }]) {
    const h = harness(), event = key('Enter', extra);
    h.search.listeners.get('keydown')(event);
    assert.equal(h.panel.open, true);
    assert.equal(h.native.selectedIndex, 0);
    assert.equal(event.prevented, false);
  }
});

test('search: IME Escape remains available to cancel composition', () => {
  const h = harness(), event = key('Escape', { isComposing: true });
  h.document.listeners.get('keydown')(event);
  assert.equal(h.panel.open, true);
  assert.equal(event.prevented, false);
});

test('search: Home and End preserve normal text editing', () => {
  for (const name of ['Home', 'End']) {
    const h = harness(), event = key(name);
    h.search.listeners.get('keydown')(event);
    assert.equal(event.prevented, false);
  }
});

test('mobile: a keyboard-covered anchor keeps search open inside the visible viewport', () => {
  const h = harness();
  h.viewport.height = 260;
  h.viewportListeners.get('resize')();
  assert.equal(h.panel.open, true);
  const top = parseFloat(h.panel.style.top);
  assert.ok(top >= 8 && top + h.panel.offsetHeight <= 252);
});

test('mobile: zoomed viewport bounds also constrain popup width and horizontal position', () => {
  const h = harness();
  h.viewport.width = 200;
  h.viewport.offsetLeft = 100;
  h.viewportListeners.get('resize')();
  const left = parseFloat(h.panel.style.left), width = parseFloat(h.panel.style.width);
  assert.ok(left >= 108 && left + width <= 292);
});
