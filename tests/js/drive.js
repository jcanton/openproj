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
// be one, and the markup the scripts produce goes back to the caller as *text*,
// to be parsed and judged by the same census the pages get. A shim that judged
// its own output would be a shim that could be wrong in the direction that
// matters.
//
// The same shim answers a second kind of question: what a write path *does*
// when the server says no. Those defects — a conflict report printed as
// "refused", a 500 that left Save disabled for ever, a typo that dropped
// somebody from a cycle — are not in any markup either, and they need three
// things a census does not: the page's own elements to query, a scripted
// answer from `fetch`, and a clock the test controls. Hence the options below.
// Without them the driver behaves exactly as it always did.
//
// Usage: node drive.js '<expression>' '<options json>'  < page.html
// Options: {page: true}      the page's markup is parsed, so document queries
//                            answer from it instead of from a phantom;
//          {replies: [...]}  {status, json} or {status, text} per fetch, in
//                            order — a `text` that is not JSON rejects
//                            `response.json()`, exactly as a 500 does.
//          {storage: {...}}  localStorage starts holding these; "denied" makes
//                            reading the property itself throw, the way a
//                            private window and a blocked-cookies policy do.
// The expression may be async; its promise is awaited, and one that never
// settles comes back as settled: false rather than as an empty answer.
// Prints {written: [...innerHTML strings...], value: <expression result>,
//         errors: [...], calls: [...requests...], settled: <bool>,
//         stored: {...localStorage as the run left it...}} as JSON.

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
  // The words between the tags. A browser has them, and a page mode that did
  // not would make `#state` read as empty however much had been announced into
  // it — which is the one thing several of these tests are about.
  for (const element of root.children) settle(element);
  return root.children;
}

function settle(element) {
  if (element.text) element.textContent = element.text;
  for (const child of element.children) settle(child);
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

// A descendant combinator, checked against the ancestors rather than dropped.
// With the page parsed, `#bets tbody tr` and `#roster tr` are two different sets
// of rows on the same page, and a matcher that read only the last simple
// selector answered with all of them.
function matchesComplex(element, selector) {
  const parts = selector.trim().split(/\s+/);
  if (!matchesOne(element, parts.pop())) return false;
  let want = parts.pop();
  let at = element.parentNode;
  while (want && at) {
    if (at instanceof Element && matchesOne(at, want)) want = parts.pop();
    at = at.parentNode;
  }
  return !want;
}

function selectorMatches(element, selector) {
  return selector.split(',').some(one => matchesComplex(element, one));
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
    // A plain object takes `style.width = …`, which is most of what these pages
    // do, and not `style.setProperty('--sticky-1', …)` — which the table calls
    // while it measures its frozen columns, halfway down a script whose second
    // half is every write path on the page.
    this.style = {setProperty() {}, removeProperty() {}, getPropertyValue: () => ''};
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
    // The three attributes a browser reflects into a property that page scripts
    // read: an `<input value="0.5">` in the roster answers 0.5 to `.value`, the
    // conflict box the table renders with `hidden` starts out hidden, and
    // `.name` is the key every field a save sends is filed under — without it
    // the detail page's PATCH carried one field called "undefined".
    if (name === 'value') this.value = String(value);
    if (name === 'hidden') this.hidden = value !== 'false';
    if (name === 'name') this.name = String(value);
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
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  insertAdjacentElement(_where, node) { node.parentNode = this.parentNode; return node; }
  insertAdjacentHTML(_where, html) { WRITTEN.push(String(html)); }
  remove() {}
  focus() {}
  blur() {}
  select() {}
  setSelectionRange() {}
  scrollIntoView() {}
  getBoundingClientRect() { return {top: 0, left: 0, width: 100, height: 100, bottom: 0, right: 0}; }
  // Empty, and that is the honest answer: this shim has no layout, so nothing in
  // it has a box. The shell asks before measuring the window into a page's one
  // sized box, and takes an empty list to mean "not laid out" — which is exactly
  // the state a run in here is in. Without the method at all the shell's script
  // stopped on a TypeError instead, taking the two lines after it with it.
  getClientRects() { return []; }
  // The graph measures its labels against a canvas before it draws anything, so
  // without this the script stops above every line that saves a dependency.
  getContext() {
    return {font: '', measureText: text => ({width: String(text).length * 7})};
  }
  get firstElementChild() { return this.children[0] || null; }
  get previousElementSibling() { return null; }
  get childNodes() { return [{textContent: this.textContent}, ...this.children]; }
  get parentElement() { return this.parentNode; }
  contains() { return false; }
  setPointerCapture() {}
  matches(selector) { return selectorMatches(this, selector); }
}

// --------------------------------------------------------------------------
// The document. By default it knows nothing about the page except its script
// blocks: getElementById hands back a fresh stub for anything it has not been
// told about, and document.querySelector does the same, because a script asking
// the document for `#rows tbody` must get something it can write to or nothing
// downstream of it ever runs. An *element* asking its own children answers
// honestly from what innerHTML put there, which is what the cell editor needs.
//
// In page mode the markup is parsed and the document answers from it, honestly
// and including with null — which is what a test about a roster, a banner or a
// live region needs, since none of those is something a script wrote.
// --------------------------------------------------------------------------

function makeDocument(inlined, markup) {
  const byId = new Map();
  const bySelector = new Map();
  // The page, when the caller asked for it. A question about what a script
  // writes is answered by phantoms; a question about what it does to the page it
  // is on is not — `document.querySelectorAll('input.rate')` IS the roster, and
  // a shim that answers [] there tests nothing at all.
  let root = null;
  const document = {
    documentElement: null,
    body: null,
    activeElement: null,
    createElement(tag) { return new Element(tag, document); },
    createTextNode(text) { return {textContent: text}; },
    createDocumentFragment() { return new Element('fragment', document); },
    getElementById(id) {
      // Asked of the page every time, and never remembered. A script that writes
      // to `innerHTML` replaces the elements inside it, and a remembered answer
      // is an element that is no longer on the page: the table rebuilds its whole
      // body on every draw and the sticky row at the bottom of it is rebuilt with
      // it, so a shim that kept the first answer was reading and writing a
      // detached node while the page in front of the reader said something else
      // entirely. That is precisely the defect this had to be able to see, and it
      // could not see it — the cache made the check pass vacuously.
      const real = root && root._descendants().find(element => element.id === id);
      if (real) return real;
      // In page mode a miss is a miss, the way it is in a browser: the pages
      // ask for `#over` and `#strangers` and then check what came back. The
      // exception is a `<script type=application/json>` payload — `#suggest`,
      // `#payload` — which has been lifted out of the markup to be run and is
      // still on the page as far as the page is concerned.
      if (root && !inlined.has(id)) return null;
      // Phantoms and payloads stay remembered: a script asking twice for the
      // furniture it is about to write into has to get the same box back.
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
      if (root) return root.querySelector(selector);
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
    querySelectorAll(selector) {
      if (!root) return [];
      checkSelector(selector);
      return root.querySelectorAll(selector);
    },
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() { return true; },
  };
  if (markup !== null) {
    root = new Element('body', document);
    // Not `innerHTML`: that is the very thing the census reads, and the page
    // arriving in it would drown every string the scripts wrote.
    root.children = parseFragment(markup, document);
    for (const child of root.children) child.parentNode = root;
  }
  document.documentElement = new Element('html', document, true);
  document.body = new Element('body', document, true);
  return document;
}

// --------------------------------------------------------------------------

async function run(html, expression, options) {
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

  const document = makeDocument(
    inlined,
    // Everything but the scripts: they have already been taken out to be run,
    // and the parser would take a `</div>` inside a template literal for markup.
    options.page ? html.replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ') : null,
  );
  const listeners = {};

  // What the server said, in order, and what was asked of it. A write path is
  // mostly a set of answers to a refusal, and a `fetch` that always says yes can
  // only test the half where nothing goes wrong.
  const calls = [];
  const replies = (options.replies || []).slice();

  function answer(url, init) {
    // The shell asks `/api/me` on every page load, to draw who is signed in.
    // That is not the write path any of these tests are about: recorded, it
    // shifts every assertion about `calls` by one, and answered from `replies`
    // it eats the refusal the test scripted for the save. Answered here, signed
    // out, which is what a driven page with no session is.
    if (String(url) === '/api/me') {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () => Promise.resolve({org: 'C2SM'}),
        text: () => Promise.resolve('{"org":"C2SM"}'),
      });
    }
    calls.push({
      url: String(url),
      method: (init && init.method) || 'GET',
      body: init && init.body !== undefined ? String(init.body) : null,
    });
    const next = replies.shift() || {};
    const status = next.status === undefined ? 200 : next.status;
    const text = next.text !== undefined
      ? String(next.text)
      : JSON.stringify(next.json === undefined ? {} : next.json);
    return Promise.resolve({
      ok: status < 400,
      status,
      // Parsed from the body it was actually given, so a plain-text 500 rejects
      // here exactly as it does in a browser. That rejection is the defect: it
      // took the page's Save with it.
      json: () => new Promise((resolve, reject) => {
        try { resolve(JSON.parse(text)); } catch (error) { reject(error); }
      }),
      text: () => Promise.resolve(text),
    });
  }

  // Storage, in the three states a browser really has: empty, already holding
  // something, and denied. The third is the one worth having — a denied browser
  // does not answer null, it THROWS, and it throws on the `localStorage`
  // property itself rather than on the method call, which is why it is a getter
  // below and not a stub whose methods raise. A page that guards `getItem` and
  // not the property is still dead at its first read.
  const denied = options.storage === 'denied';
  const held = new Map(Object.entries(denied ? {} : options.storage || {}));
  // A real store and not a black hole: what a page writes it can read back, and
  // what it wrote comes home in the answer, which is how a test says what a
  // draft was saved *as*.
  const storage = {
    getItem: key => (held.has(String(key)) ? held.get(String(key)) : null),
    setItem: (key, value) => { held.set(String(key), String(value)); },
    removeItem: key => { held.delete(String(key)); },
  };

  // Queued, not run. A timer that fired by itself would set a page's autosave
  // going against an answer nobody scripted; `__tick()` runs what is pending, so
  // a test about a timer — the live region re-sets a repeated message on one —
  // says when the clock moves.
  const timers = new Map();
  let ticket = 1;

  class DriverEvent {
    constructor(type, init) {
      this.type = type;
      this.defaultPrevented = false;
      Object.assign(this, init || {});
    }
    // Recorded, because on one of these events the call IS the behaviour: a row
    // says a drop may land on it by calling `preventDefault` on `dragover` and
    // refuses by not calling it. A shim that swallowed the call could not tell a
    // table that accepts every drop from one that accepts the legal ones, which
    // is the entire question about a move.
    preventDefault() { this.defaultPrevented = true; }
    stopPropagation() {}
  }

  const sandbox = {
    document,
    console,
    JSON, Math, Date, Object, Array, String, Number, Boolean, RegExp, Map, Set,
    Promise, Error, URLSearchParams, URL, isNaN, parseInt, parseFloat, encodeURIComponent,
    setTimeout: (fn, delay) => {
      timers.set(ticket, {fn, delay: Number(delay) || 0});
      return ticket++;
    },
    clearTimeout: id => { timers.delete(id); },
    // Every pending timer, soonest first, and the count for a test that wants to
    // say how many were left behind.
    __tick: () => {
      const due = [...timers.values()].sort((one, two) => one.delay - two.delay);
      timers.clear();
      for (const timer of due) timer.fn();
      return due.length;
    },
    __pending: () => timers.size,
    // Still nothing: the only interval on these pages is a two-minute autosave,
    // which is never what a test is asking about.
    setInterval: () => 0,
    clearInterval: () => {},
    requestAnimationFrame: () => 0,
    Event: DriverEvent,
    CustomEvent: DriverEvent,
    EventSource: class { constructor() { this.onmessage = null; } close() {} },
    fetch: answer,
    location: {search: '', pathname: '/', href: 'http://localhost/'},
    history: {replaceState() {}, pushState() {}},
    localStorage: storage,
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
  if (denied) {
    // Defined from inside the context, not with `Object.defineProperty` on the
    // sandbox out here: a throwing getter placed on the sandbox is swallowed by
    // node's global proxy and the name comes back as merely undefined, which is
    // a different failure from the one browsers make. Run in here it throws on
    // the property access — `localStorage`, `window.localStorage`, either — with
    // the error a denied browser raises.
    new vm.Script(
      "Object.defineProperty(globalThis, 'localStorage', {configurable: true," +
      " get() { throw new Error('SecurityError: The operation is insecure.'); }});"
    ).runInContext(context);
  }
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
      // The message as well as the line: `evalmachine.<anonymous>:69` alone says
      // nothing about which of the shim's gaps a page fell into.
      const where = error && error.stack ? error.stack.split('\n')[0] : '';
      errors.push(`${String(error)} at ${where}`);
    }
  }

  let value = null;
  let settled = true;
  try {
    value = new vm.Script(`(${expression})`).runInContext(context, {timeout: 20000});
    if (value && typeof value.then === 'function') {
      // A write path that hangs is one of the defects, not a driver failure:
      // `response.json()` on a plain-text 500 used to leave the cycle page's
      // `flush()` unresolved for ever, with Save disabled behind it. Raced
      // rather than awaited, so that comes back as an answer instead of as a
      // process that produced no output at all.
      const WAITING = {};
      let alarm = null;
      const raced = await Promise.race([value, new Promise(resolve => {
        alarm = setTimeout(() => resolve(WAITING), 2000);
      })]);
      // Held open by the alarm until it fires — nothing else is pending when the
      // page's promise is stuck, and a process that just ends prints nothing at
      // all — then cleared, so a run that settled at once does not wait for it.
      clearTimeout(alarm);
      settled = raced !== WAITING;
      value = settled ? raced : null;
    }
  } catch (error) {
    errors.push('expression: ' + String(error && error.message ? error.message : error));
  }
  return {written: WRITTEN, value, errors, calls, settled, stored: Object.fromEntries(held)};
}

let input = '';
process.stdin.setEncoding('utf-8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', async () => {
  const options = JSON.parse(process.argv[3] || '{}');
  const answer = await run(input, process.argv[2] || 'null', options);
  // Written and then left to drain. `process.exit` here truncates the answer on
  // a pipe, and the table's is a hundred kilobytes of markup.
  process.stdout.write(JSON.stringify(answer));
});
