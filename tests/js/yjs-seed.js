// The vendored Yjs, run the way the page runs it, so the server's document and
// the browser's can be compared byte for byte.
//
// The script handed in on stdin is `render._yjs()` — upstream's bytes with the
// import and the export rewritten — and not `static/yjs.bundle.mjs`, because
// what has to agree with pycrdt is the thing the page actually executes. Loaded
// through `new Function` rather than `eval`: a `const` in a direct eval binds
// inside the eval's own scope and never reaches the caller, which is a
// ReferenceError three lines later that reads as the library failing to load.
//
// Usage: node yjs-seed.js  < {"script": "...", "body": "...", "seed": 0,
//                             "insert": {"at": 0, "what": "..."},
//                             "apply": "<base64 update>"}
// Prints {seed, text, update, sv} as JSON, every byte string base64.

'use strict';

// A browser's, in the two shapes lib0 reads at module scope with nothing
// guarding either. `crypto` is already a getter-only global in node, so it is
// only filled in where it is missing; `localStorage` in node 25 exists and has
// no `getItem`, which is a shape no browser has and which throws lib0's
// environment probe on line four.
if (!globalThis.crypto) globalThis.crypto = require('node:crypto').webcrypto;
globalThis.localStorage = {getItem: () => null, setItem: () => {}};

const b64 = bytes => Buffer.from(bytes).toString('base64');
const raw = held => new Uint8Array(Buffer.from(held, 'base64'));

let input = '';
process.stdin.setEncoding('utf-8');
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
  const asked = JSON.parse(input);
  const Y = new Function(asked.script + '\nreturn YJS;')();

  const doc = new Y.Doc();
  // The seed, written with the same client id the server writes it with. This
  // is the whole point of the file: two documents built independently from one
  // text share no history, so if these bytes differ the two are different
  // documents that merely read the same — and merging them inserts the text
  // twice, with nothing anywhere reporting a conflict.
  doc.clientID = asked.seed;
  const text = doc.getText('body');
  doc.transact(() => text.insert(0, asked.body));
  const seed = b64(Y.encodeStateAsUpdate(doc));

  // Off the seed's id before doing anything of its own, exactly as the page
  // does: a second writer sharing that id is indistinguishable from the seed,
  // and Yjs notices — it renumbers the client and says so on stdout, which is
  // where this driver's answer goes.
  doc.clientID = 991;

  let update = null;
  if (asked.insert) {
    const before = Y.encodeStateVector(doc);
    doc.transact(() => text.insert(asked.insert.at, asked.insert.what));
    update = b64(Y.encodeStateAsUpdate(doc, before));
  }
  if (asked.apply) Y.applyUpdate(doc, raw(asked.apply));

  process.stdout.write(JSON.stringify({
    seed, update, text: text.toString(), sv: b64(Y.encodeStateVector(doc)),
  }));
});
