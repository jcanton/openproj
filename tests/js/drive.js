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
//                            private window and a blocked-cookies policy do —
//                            and it denies both stores, because one policy does.
//          {session: {...}}  the same for sessionStorage: what the TAB was
//                            already holding when this page opened, which is how
//                            a record page is asked what view it came from.
//          {here: "/t?x=1"}  the address the page is at; `/` by default.
//          `__reloads()`     how many times the page asked for `location.reload()`,
//                            which node cannot perform and a test has to be able
//                            to read.
//          {socket: true}    a `WebSocket` the expression drives by hand,
//                            through `__socket.opened()`, `__socket.hear(frame)`,
//                            `__socket.refused(code, reason)` and
//                            `__socket.sent()`. Absent by default, which is
//                            the reader whose browser refuses the upgrade.
// The expression may be async; its promise is awaited, and one that never
// settles comes back as settled: false rather than as an empty answer.
// Prints {written: [...innerHTML strings...], value: <expression result>,
//         errors: [...], calls: [...requests...], settled: <bool>,
//         stored: {...localStorage as the run left it...},
//         tabbed: {...sessionStorage as the run left it...}} as JSON.

'use strict';

const vm = require('node:vm');
const nodeCrypto = require('node:crypto');

// --------------------------------------------------------------------------
// A very small HTML parser, so that a script which sets innerHTML and then
// walks the result — the combobox highlights its options, the cell editor finds
// the input it just wrote — keeps working. Its output is never asserted on.
// --------------------------------------------------------------------------

const VOID = new Set(['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
  'link', 'meta', 'param', 'source', 'track', 'wbr']);

// The five names an escaper in this repository can emit, plus every numeric
// reference. `esc` (the shell) writes four of them and markupsafe writes those
// four as `&#34;`/`&#39;` instead, and `&#128465;` is in two templates — so a
// shim that hands text back undecoded answers `Ann&#39;s note` where a browser
// answers `Ann's note`. That is not a cosmetic difference: `ORIGINAL_BODY` is
// the marker the editor's `mine`/`theirs` branch is decided by, and it is
// compared for equality against the room's text, which has never been escaped.
// A named table and not an HTML entity list, because these are the only names
// this application produces and a list nobody derives goes stale — the numeric
// forms are general because they are a syntax rather than a vocabulary.
const NAMED = {amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' '};

function decoded(text) {
  return text.replace(/&(#\d+|#[xX][0-9a-fA-F]+|[a-zA-Z][a-zA-Z0-9]*);/g, (whole, ref) => {
    if (ref[0] === '#') {
      const point = ref[1] === 'x' || ref[1] === 'X'
        ? parseInt(ref.slice(2), 16) : parseInt(ref.slice(1), 10);
      // Beyond the last code point is not a character reference, it is text
      // that looks like one. Handing it to `fromCodePoint` is a RangeError.
      return Number.isFinite(point) && point <= 0x10ffff ? String.fromCodePoint(point) : whole;
    }
    // A name this application never writes stays as it was typed, which is what
    // a browser does with `&frobnicate;` too.
    return ref in NAMED ? NAMED[ref] : whole;
  });
}

// The elements whose *content* is their value, rather than an attribute. This
// is the whole list in HTML: everything else carries `value=`, which
// `setAttribute` below already reflects.
const CONTENT_IS_VALUE = new Set(['TEXTAREA', 'OPTION']);

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
      const value = decoded((attr[2] || '').replace(/^["']|["']$/g, ''));
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
  if (element.text) element.textContent = decoded(element.text);
  // A `<textarea>`'s value IS its content — there is no `value` attribute to
  // reflect — and this copied the content into `textContent` alone. So a parsed
  // editing surface answered `''` to `.value` where a browser answers the
  // record's body, and in page mode `ORIGINAL_BODY` was therefore always empty.
  // That flips `welcomed()`'s `mine` from false to true on every first
  // connection, which is the one branch in this feature that can lose unsaved
  // work: the harness reported the draft path being taken over a page where
  // nobody had typed. Two of the last three rounds were misled by this file.
  //
  // `'value' in attributes` and not a truth test on it: `<option value="">`
  // means an empty value, and a falsy check would give that option its label
  // instead — which is the "any" row at the top of three of this app's filters.
  if (CONTENT_IS_VALUE.has(element.tagName) && !('value' in element.attributes)) {
    element.value = element.textContent;
  }
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

  // The other end of `append`, and it was missing. The status bar is built at
  // both ends of a row a page may have put something in the middle of, so the
  // page reaches for the standard pair — and a shim that has one and not the
  // other is a shim that stops the whole script on the line the second is
  // called, which is what it did: eleven tests about drafts and rooms failed on
  // `bar.prepend is not a function`, none of them about a status bar.
  prepend(...nodes) {
    for (const node of nodes) node.parentNode = this;
    this.children.unshift(...nodes);
  }

  // A structural copy. The icon picker is the one place these pages clone rather
  // than build: the row it just chose already holds the exact `<svg>` the server
  // would send back, so the new mark is a node this page rendered instead of a
  // string crossing an escaping boundary. Without this the shim stopped inside
  // `chooseRow`, one line after the write it was there to test and with the write
  // already sent — a driver failure that looks exactly like a page bug.
  cloneNode(deep) {
    const copy = new Element(this.tagName, this.ownerDocument);
    copy.attributes = {...this.attributes};
    copy.dataset = {...this.dataset};
    copy.textContent = this.textContent;
    copy.hidden = this.hidden;
    copy.value = this.value;
    if (deep) {
      copy.children = this.children.map(child => {
        const under = child.cloneNode(true);
        under.parentNode = copy;
        return under;
      });
    }
    return copy;
  }

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
  //
  // **It answers that for every element, which makes two functions no-ops in
  // here.** The gutter's `drawGutter` and the room's `drawSeats` both open with
  // `if (!area.getClientRects().length) return;` — "a box nothing is drawing has
  // no rows to sit on" — so under this shim neither ever draws anything. A test
  // written for either one in here would pass without executing the code it is
  // about, which is the vacuous green this file has produced three times. Line
  // numbers and seat bands are asked of Chrome, through `tests/browser.py`.
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

  // Where the page believes it is standing, split the way a browser splits it.
  const here = String(options.here || '/');
  const [herePath, hereRest] = here.split('?');
  const hereQuery = hereRest === undefined ? '' : '?' + hereRest;

  // Storage, in the three states a browser really has: empty, already holding
  // something, and denied. The third is the one worth having — a denied browser
  // does not answer null, it THROWS, and it throws on the `localStorage`
  // property itself rather than on the method call, which is why it is a getter
  // below and not a stub whose methods raise. A page that guards `getItem` and
  // not the property is still dead at its first read.
  //
  // Both stores, because the pages use both and one policy denies both: cookies
  // blocked takes `sessionStorage` with it, and a shim that offered a working
  // one would be a shim in which the record page's back link is never the thing
  // that breaks. They are separate maps for the same reason a browser keeps
  // them separate — a tab's store and a browser's store hold different things
  // and outlive different events.
  //
  // A real store and not a black hole: what a page writes it can read back, and
  // what it wrote comes home in the answer, which is how a test says what a
  // draft was saved *as*.
  const denied = options.storage === 'denied';
  const shelf = start => {
    const held = new Map(Object.entries(denied ? {} : start || {}));
    return [held, {
      getItem: key => (held.has(String(key)) ? held.get(String(key)) : null),
      setItem: (key, value) => { held.set(String(key), String(value)); },
      removeItem: key => { held.delete(String(key)); },
    }];
  };
  const [held, storage] = shelf(options.storage);
  const [tabHeld, tabStorage] = shelf(options.session);

  // A socket, driven by hand, and only when a test asks for one. The room's
  // whole protocol is frames in and frames out, so a shim that delivered them on
  // its own would be a shim deciding the order — and the order is where two of
  // this feature's defects lived. `__socket.opened()` fires the open the page
  // waits for, `__socket.hear(frame)` delivers one, and `__socket.sent()` is
  // every frame the page put on the wire, parsed.
  const wire = {sent: [], live: null};
  class DriverSocket {
    constructor(url) {
      this.url = String(url);
      // Open on arrival: nothing in this shim is asynchronous, and a page that
      // could not send until a later tick would be a page this cannot drive.
      this.readyState = DriverSocket.OPEN;
      this.onopen = this.onmessage = this.onerror = this.onclose = null;
      wire.live = this;
    }
    send(data) { wire.sent.push(String(data)); }
    // A close ALWAYS carries an event, because a browser's does — `code` and
    // `reason` are the only thing a page has to tell a refusal from a drop, and
    // a shim that handed over nothing made every close look like the same close.
    // 1005 is what a browser reports for a close nobody gave a code to, which is
    // what `socket.close()` from the page is.
    close(code, reason) {
      this.readyState = DriverSocket.CLOSED;
      if (this.onclose) this.onclose({code: code || 1005, reason: reason || ''});
    }
  }
  DriverSocket.CONNECTING = 0;
  DriverSocket.OPEN = 1;
  DriverSocket.CLOSING = 2;
  DriverSocket.CLOSED = 3;

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

  let reloads = 0;
  const sandbox = {
    document,
    console,
    // Only what a V8 context does not already have. `Object`, `Array`, `String`,
    // `Map` and the rest are intrinsics of the context `vm` builds, and handing
    // this realm's copies in shadows them — which is invisible until a library
    // asks a value which realm it came from. Yjs asks exactly that:
    // `text.constructor === String` is how `YText.insert` tells a string from an
    // embed, and a string made inside the context answers with the context's
    // `String`, not with the one passed in here. Every insert was therefore
    // stored as a one-unit embed with no text in it, `toString()` skipped it,
    // and the page's document quietly stopped following the textarea — a defect
    // of the shim that would have read as a defect of the editor.
    URLSearchParams, URL,
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
    // Its pair, which was missing: a page that coalesces work onto a frame
    // cancels the frame when a timer beats it to the work, and a bare
    // identifier that is not on the sandbox is a ReferenceError that stops
    // the script on the line it appears in.
    cancelAnimationFrame: () => {},
    Event: DriverEvent,
    CustomEvent: DriverEvent,
    EventSource: class { constructor() { this.onmessage = null; } close() {} },
    fetch: answer,
    // `reload` counts rather than navigating: node has no page to fetch, and a
    // reload is a claim a test needs to make — "the read view under this editor
    // is the server's HTML and is now out of date, so go and get it again".
    // Reachable as `__reloads()`.
    // Where the page believes it is standing. `/` unless a test says otherwise,
    // which is what every run before this one was driven at — and named by the
    // one claim that is about the address itself: a view stamps the page you
    // were on, so that a filtered table is what a record page sends you back to
    // and not the bare view.
    location: {
      search: hereQuery, pathname: herePath, href: 'http://localhost' + here,
      reload: () => { reloads += 1; },
    },
    __reloads: () => reloads,
    history: {replaceState() {}, pushState() {}},
    localStorage: storage,
    sessionStorage: tabStorage,
    // Yjs's lib0 reads `crypto.subtle` and binds `crypto.getRandomValues` at the
    // top of the module with nothing guarding either, so the detail page's
    // editor now stops on its fourth line without one. node's real one is handed
    // through rather than faked: a client id that is not actually random is a
    // document that collides with another tab's, which is the one failure a CRDT
    // cannot recover from.
    crypto: nodeCrypto.webcrypto,
    btoa: value => Buffer.from(value, 'binary').toString('base64'),
    atob: value => Buffer.from(value, 'base64').toString('binary'),
    // node's own, handed through rather than faked: the status bar weighs the
    // document in UTF-8 bytes against the ceiling a save is refused at, and a
    // hand-rolled counter here would be a second implementation of the one
    // arithmetic this repository has already got wrong in two index spaces. A
    // bare identifier that is not on the sandbox is a ReferenceError that stops
    // the script on the line it appears in — which is what this was: the whole
    // detail-page editor died on `new TextEncoder()`, three lines in, and eleven
    // tests about drafts and rooms failed for a reason none of them was about.
    TextEncoder,
    // No `WebSocket` unless `{socket: true}` asks for one, and the default is
    // the point: this shim is then the reader whose browser refuses the socket —
    // a `file://` copy, a proxy that drops the upgrade, a session that may not
    // write — and every test that drives the editor without it is a test that
    // the page degrades to exactly what it was. Asked for, it is `DriverSocket`
    // above and the test moves every frame itself.
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
  if (options.socket) {
    sandbox.WebSocket = DriverSocket;
    sandbox.__socket = {
      opened: () => { if (wire.live && wire.live.onopen) wire.live.onopen(); },
      hear: frame => { wire.live.onmessage({data: JSON.stringify(frame)}); },
      // The server turning this socket away, which is a close and never a frame:
      // a refusal that is accepted and then closed carries its reason in the
      // close event, and there is no other way for one to reach a page.
      refused: (code, reason) => {
        if (wire.live && wire.live.onclose) wire.live.onclose({code, reason});
      },
      // Parsed, because every frame this application sends is JSON and a test
      // asserting on strings would be asserting on key order.
      sent: () => wire.sent.map(one => JSON.parse(one)),
    };
  }

  const context = vm.createContext(sandbox);
  if (denied) {
    // Defined from inside the context, not with `Object.defineProperty` on the
    // sandbox out here: a throwing getter placed on the sandbox is swallowed by
    // node's global proxy and the name comes back as merely undefined, which is
    // a different failure from the one browsers make. Run in here it throws on
    // the property access — `localStorage`, `window.localStorage`, either — with
    // the error a denied browser raises.
    new vm.Script(
      "for (const store of ['localStorage', 'sessionStorage'])" +
      " Object.defineProperty(globalThis, store, {configurable: true," +
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
  return {written: WRITTEN, value, errors, calls, settled,
    stored: Object.fromEntries(held), tabbed: Object.fromEntries(tabHeld)};
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
