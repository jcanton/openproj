// Run a rendered page's own <script> blocks and report every string they hand
// to innerHTML.
//
// Four of the injection defects this repository shipped were in markup that no
// rendered file contains: a table row, a tooltip, a combobox option and a
// roster row are all built by script at runtime, so a test that greps the page
// sees nothing. jsdom would do this, but a dev dependency downloaded from npm
// is a network fetch and a node_modules in a repository whose whole premise is
// that nothing is fetched — so this is a DOM shim that is exactly as big as the
// four scripts need and no bigger. It is not a browser and does not pretend to
// be one: it parses nothing on the page except the <script> blocks, and the
// markup the scripts produce goes back to the caller as *text*, to be parsed
// and judged by the same census the pages get. A shim that judged its own
// output would be a shim that could be wrong in the direction that matters.
//
// Usage: node drive.js '<expression>'  < page.html
// Prints {written: [...innerHTML strings...], value: <expression result>,
//         errors: [...]} as JSON.

'use strict';

const vm = require('node:vm');

// --------------------------------------------------------------------------
// A very small HTML parser, so that a script which sets innerHTML and then
// walks the result — the combobox highlights its options, the cell editor finds
// the input it just wrote — keeps working. Its output is never asserted on.
// --------------------------------------------------------------------------

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
  'link', 'meta', 'param', 'source', 'track', 'wbr']);

function parseFragment(html, owner) {
  const root = {children: [], text: ''};
  const stack = [root];
  const token = /<\/?([a-zA-Z][-\w]*)((?:[^>"']|"[^"]*"|'[^']*')*)>|([^<]+)/g;
  let match;
  while ((match = token.exec(html)) !== null) {
    const [whole, tag, rest, text] = match;
    const top = stack[stack.length - 1];
    if (text !== undefined) {
      top.text = (top.text || '') + text;
      continue;
    }
    if (whole.startsWith('</')) {
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].tagName === tag.toUpperCase()) { stack.length = i; break; }
      }
      continue;
    }
    const element = new Element(tag, owner);
    for (const attr of (rest || '').matchAll(/([-\w:]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s>]*))?/g)) {
      const value = (attr[2] || '').replace(/^["']|["']$/g, '');
      element.setAttribute(attr[1], value);
    }
    element.parentNode = top === root ? owner : top;
    top.children.push(element);
    if (!VOID.has(tag.toLowerCase()) && !whole.endsWith('/>')) stack.push(element);
  }
  return root.children;
}

// --------------------------------------------------------------------------
// Selectors: tag, #id, .class, [attr], [attr=value], and comma-separated lists.
// --------------------------------------------------------------------------

function matchesOne(element, selector) {
  const parts = selector.trim().split(/(?=[.#[])/).filter(Boolean);
  return parts.every(part => {
    if (part.startsWith('#')) return element.id === part.slice(1);
    if (part.startsWith('.')) return element.classList.contains(part.slice(1));
    if (part.startsWith('[')) {
      const [, name, , value] = /\[([-\w]+)(=["']?([^\]"']*)["']?)?\]/.exec(part) || [];
      if (!name) return false;
      const held = element.getAttribute(name);
      return value === undefined ? held !== null : held === value;
    }
    // A descendant combinator is written in the pages ("#roster tr[data-login]")
    // but only ever against the document, which answers with a stub — so the
    // last simple selector is all that has to match here.
    return element.tagName === part.toUpperCase();
  });
}

function selectorMatches(element, selector) {
  return selector.split(',').some(one => matchesOne(element, one.trim().split(/\s+/).pop()));
}

// The one thing a real querySelector does that this shim must not skip: refuse a
// selector that is not one. A page that builds `[data-login="${login}"]` out of
// typed text hands the browser an unterminated string the moment somebody's name
// holds a quote, and the browser throws — which is how the Add button on the
// cycle page comes to do nothing at all. A shim that shrugged at it would let
// that bug pass as working code.
function checkSelector(selector) {
  // Backslash escapes first, or `CSS.escape` — the fix for exactly this bug —
  // would look like the bug: it turns a quote into `\"`, which is a quote that
  // does not end anything and must not be counted as one.
  const bare = String(selector).replace(/\\./g, '');
  const count = character => (bare.match(character) || []).length;
  if (count(/"/g) % 2 || count(/'/g) % 2 || count(/\[/g) !== count(/\]/g)) {
    throw new SyntaxError(`'${selector}' is not a valid selector`);
  }
}

// The tag a phantom should claim, so that `closest('td')` answers with a TD.
function lastTag(selector) {
  const word = /([a-zA-Z][-\w]*)\s*(?:[.#[][^,]*)?$/.exec(selector.split(',')[0].trim());
  return word ? word[1] : 'div';
}

// --------------------------------------------------------------------------
// The elements themselves.
// --------------------------------------------------------------------------

const WRITTEN = [];

class Element {
  // `phantom` is the difference between an element the page really has and one
  // the shim invented because a script asked the document for it. A phantom
  // answers every further query with another phantom, so a chain like
  // `document.querySelector('.scroll').querySelector('svg')` keeps going
  // instead of throwing three lines into a script whose interesting part is
  // three hundred lines down. A real element — one `createElement` made, or one
  // `innerHTML` parsed — answers honestly, including with null, which is what
  // the cell editor asks of the cell it is about to fill.
  constructor(tag, owner, phantom) {
    this._phantom = !!phantom;
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.attributes = {};
    this.dataset = {};
    this.style = {};
    this.parentNode = null;
    this.ownerDocument = owner;
    this.hidden = false;
    this.value = '';
    this.textContent = '';
    this.selectedOptions = [];
    this._html = '';
    this._listeners = {};
    const self = this;
    this.classList = {
      add(...names) { names.forEach(n => self._classes().add(n)); self._writeClasses(); },
      remove(...names) { names.forEach(n => self._classes().delete(n)); self._writeClasses(); },
      toggle(name, on) {
        const held = self._classes();
        if (on === undefined ? held.has(name) : !on) held.delete(name); else held.add(name);
        self._writeClasses();
      },
      contains(name) { return self._classes().has(name); },
    };
  }

  _classes() {
    if (!this._classSet) this._classSet = new Set((this.className || '').split(/\s+/).filter(Boolean));
    return this._classSet;
  }

  _writeClasses() {
    this.attributes.class = [...this._classes()].join(' ');
  }

  get className() { return this.attributes.class || ''; }
  set className(value) { this.attributes.class = String(value); this._classSet = null; }

  get id() { return this.attributes.id || ''; }
  set id(value) { this.attributes.id = String(value); }

  get innerHTML() { return this._html; }
  set innerHTML(value) {
    this._html = String(value);
    WRITTEN.push(this._html);
    this.children = parseFragment(this._html, this.ownerDocument);
    for (const child of this.children) child.parentNode = this;
  }

  setAttribute(name, value) {
    this.attributes[name] = String(value);
    if (name === 'class') this._classSet = null;
    if (name.startsWith('data-')) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      this.dataset[key] = String(value);
    }
  }

  getAttribute(name) {
    return name in this.attributes ? this.attributes[name] : null;
  }

  removeAttribute(name) { delete this.attributes[name]; }
  hasAttribute(name) { return name in this.attributes; }

  addEventListener(type, handler) { (this._listeners[type] ||= []).push(handler); }
  removeEventListener() {}

  dispatchEvent(event) {
    event.target = event.target || this;
    for (const handler of this._listeners[event.type] || []) handler.call(this, event);
    const named = 'on' + event.type;
    if (typeof this[named] === 'function') this[named].call(this, event);
    return true;
  }

  _descendants() {
    return this.children.flatMap(child => [child, ...child._descendants()]);
  }

  querySelector(selector) {
    checkSelector(selector);
    const found = this._descendants().find(el => selectorMatches(el, selector));
    if (found) return found;
    return this._phantom ? new Element(lastTag(selector), this.ownerDocument, true) : null;
  }

  querySelectorAll(selector) {
    checkSelector(selector);
    return this._descendants().filter(el => selectorMatches(el, selector));
  }

  closest(selector) {
    checkSelector(selector);
    let at = this;
    while (at) {
      if (at instanceof Element && selectorMatches(at, selector)) return at;
      at = at.parentNode;
    }
    return this._phantom ? new Element(lastTag(selector), this.ownerDocument, true) : null;
  }

  append(...nodes) {
    for (const node of nodes) { node.parentNode = this; this.children.push(node); }
  }

  appendChild(node) { this.append(node); return node; }
  insertAdjacentElement(_where, node) { node.parentNode = this.parentNode; return node; }
  insertAdjacentHTML(_where, html) { WRITTEN.push(String(html)); }
  remove() {}
  focus() {}
  blur() {}
  select() {}
  setSelectionRange() {}
  scrollIntoView() {}
  getBoundingClientRect() { return {top: 0, left: 0, width: 100, height: 100, bottom: 0, right: 0}; }
  get firstElementChild() { return this.children[0] || null; }
  get previousElementSibling() { return null; }
  get childNodes() { return [{textContent: this.textContent}, ...this.children]; }
  get parentElement() { return this.parentNode; }
  contains() { return false; }
  setPointerCapture() {}
  matches(selector) { return selectorMatches(this, selector); }
}

// --------------------------------------------------------------------------
// The document, which knows nothing about the page except its script blocks.
// getElementById hands back a fresh stub for anything it has not been told
// about, and document.querySelector does the same: a script asking the document
// for `#rows tbody` must get something it can write to, or nothing downstream
// of it ever runs. An *element* asking its own children answers honestly from
// what innerHTML put there, which is what the cell editor needs.
// --------------------------------------------------------------------------

function makeDocument(inlined) {
  const byId = new Map();
  const bySelector = new Map();
  const document = {
    documentElement: null,
    body: null,
    activeElement: null,
    createElement(tag) { return new Element(tag, document); },
    createTextNode(text) { return {textContent: text}; },
    createDocumentFragment() { return new Element('fragment', document); },
    getElementById(id) {
      if (!byId.has(id)) {
        const element = new Element('div', document, true);
        element.id = id;
        if (inlined.has(id)) element.textContent = inlined.get(id);
        byId.set(id, element);
      }
      return byId.get(id);
    },
    querySelector(selector) {
      checkSelector(selector);
      // A selector that both descends and filters on an attribute value is a
      // page asking whether one particular record is already on screen —
      // `#roster tr[data-login="ann"]`. The shim never parsed the page, so the
      // honest answer is no, and answering "yes, here is an element" would stop
      // the cycle page adding the row this test exists to look at. Everything
      // else is furniture the script is about to write into, and gets a phantom.
      if (/\s/.test(selector.trim()) && /\[[-\w]+\s*=/.test(selector)) return null;
      if (!bySelector.has(selector)) {
        bySelector.set(selector, new Element(lastTag(selector), document, true));
      }
      return bySelector.get(selector);
    },
    querySelectorAll() { return []; },
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() { return true; },
  };
  document.documentElement = new Element('html', document, true);
  document.body = new Element('body', document, true);
  return document;
}

// --------------------------------------------------------------------------

function run(html, expression) {
  const inlined = new Map();
  const scripts = [];
  for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
    const [, attributes, source] = match;
    const id = (/\bid\s*=\s*["']([^"']+)["']/.exec(attributes) || [])[1];
    if (/type\s*=\s*["']application\/json["']/i.test(attributes)) {
      if (id) inlined.set(id, source);
      continue;
    }
    scripts.push(source);
  }

  const document = makeDocument(inlined);
  const listeners = {};

  class DriverEvent {
    constructor(type, init) { this.type = type; Object.assign(this, init || {}); }
    preventDefault() {}
    stopPropagation() {}
  }

  const sandbox = {
    document,
    console,
    JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Map, Set,
    Promise, Error, URLSearchParams, URL, isNaN, parseInt, parseFloat, encodeURIComponent,
    // Nothing is scheduled: a timer that fired would run a page's autosave
    // against a fetch that resolves to nothing, and the markup under test is
    // all written synchronously.
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    requestAnimationFrame: () => 0,
    Event: DriverEvent,
    CustomEvent: DriverEvent,
    EventSource: class { constructor() { this.onmessage = null; } close() {} },
    fetch: () => Promise.resolve({ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve('') }),
    location: {search: '', pathname: '/', href: 'http://localhost/'},
    history: {replaceState() {}, pushState() {}},
    localStorage: {getItem: () => null, setItem() {}, removeItem() {}},
    matchMedia: () => ({matches: false, addEventListener() {}, addListener() {}}),
    getComputedStyle: () => ({getPropertyValue: () => ''}),
    // The escape the pages reach for when a selector has to hold typed text.
    CSS: {escape: value => String(value).replace(/[^\w-]/g, c => '\\' + c)},
    innerWidth: 1280,
    innerHeight: 800,
    // How far the page has been scrolled. The suggestion popup is parked on the
    // body and positioned in page coordinates, so it reads these — and a bare
    // identifier that is not on the sandbox is a ReferenceError, which would have
    // stopped the script at the line the popup is built on.
    scrollX: 0,
    scrollY: 0,
    addEventListener(type, handler) { (listeners[type] ||= []).push(handler); },
    removeEventListener() {},
    dispatchEvent(event) {
      for (const handler of listeners[event.type] || []) handler(event);
      return true;
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;

  const context = vm.createContext(sandbox);
  const errors = [];
  for (const source of scripts) {
    try {
      new vm.Script(source).runInContext(context, {timeout: 20000});
    } catch (error) {
      // Expected and deliberate. This shim is not a browser, so a page script
      // reaches for something it has not got sooner or later; a function
      // declaration is instantiated before any of that runs, so the thing under
      // test is defined either way. The caller asserts it got markup back,
      // which is what proves the run went far enough to matter.
      errors.push(String(error && error.stack ? error.stack.split('\n')[0] : error));
    }
  }

  let value = null;
  try {
    value = new vm.Script(`(${expression})`).runInContext(context, {timeout: 20000});
  } catch (error) {
    errors.push('expression: ' + String(error && error.message ? error.message : error));
  }
  return {written: WRITTEN, value, errors};
}

let input = '';
process.stdin.setEncoding('utf-8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  const answer = run(input, process.argv[2] || 'null');
  process.stdout.write(JSON.stringify(answer));
});
