#!/usr/bin/env node
// Rebuilds static/excalidraw.js from the pinned dependencies beside this file.
//
// Every other file in static/ is committed byte-for-byte from something
// upstream published. This one is not — see static/VENDOR.md for why — which
// means the only way anyone can check these bytes is to reproduce them, and
// the only way to reproduce them is a script that a human can actually run.
//
// "Never run npm inside the repository" (static/VENDOR.md, and every other
// tool in this repo) is not negotiable just because this build needs one:
// `npm ci` writes a node_modules tree with tens of thousands of files, and
// there is no correct place for that tree to live under version control. So
// this script never runs `npm` where it sits. It re-executes itself inside a
// throwaway directory *outside* the repo, installs and bundles there, and
// carries only the single finished file back across that boundary. Run it as:
//
//   node tools/build-excalidraw.mjs
//
// and it prints the temp directory, the byte count and the sha256 of what it
// wrote to static/excalidraw.js, so the checksum in static/SHA256SUMS is
// something you can verify rather than something you have to take on faith.
//
// The re-exec is what makes one file do two jobs. Run normally (no stage
// argument) it is the ORCHESTRATOR: it stages entry.js, package.json and
// package-lock.json into the temp directory, runs `npm ci` there, then invokes
// *this same file*, copied alongside them, as a child process with
// EXCALIDRAW_BUILD_STAGE=bundle and the temp directory as its cwd. Run with
// that variable set, it is the BUNDLER: plain esbuild, resolving `entry.js`
// and `node_modules` against its own cwd, exactly the shape `esbuild.build`
// expects and exactly what a `node build-excalidraw.mjs` run by hand inside
// that directory would also do — the orchestration is not part of the bundle
// step's own logic, only of how it gets invoked.
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const THIS_FILE = fileURLToPath(import.meta.url)
const TOOLS_DIR = path.dirname(THIS_FILE)
const REPO_ROOT = path.resolve(TOOLS_DIR, '..')

if (process.env.EXCALIDRAW_BUILD_STAGE === 'bundle') {
  await bundle()
} else {
  await orchestrate()
}

async function orchestrate() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'openproj-excalidraw-'))
  console.log(`building in ${tmp}`)

  fs.copyFileSync(path.join(TOOLS_DIR, 'excalidraw-entry.js'), path.join(tmp, 'entry.js'))
  fs.copyFileSync(path.join(TOOLS_DIR, 'excalidraw-package.json'), path.join(tmp, 'package.json'))
  fs.copyFileSync(
    path.join(TOOLS_DIR, 'excalidraw-package-lock.json'),
    path.join(tmp, 'package-lock.json'),
  )
  // `npm ci` needs the running script inside the tree it installs into, not
  // just the two files above — dynamic `import` resolution walks up from
  // wherever a file lives, never from `process.cwd()`, so a copy staged here
  // is what lets `import * as esbuild from 'esbuild'` below find the copy
  // `npm ci` is about to install rather than nothing at all.
  fs.copyFileSync(THIS_FILE, path.join(tmp, 'build-excalidraw.mjs'))

  console.log('npm ci (exact versions from the lockfile beside this script)…')
  execFileSync('npm', ['ci', '--no-audit', '--no-fund'], { cwd: tmp, stdio: 'inherit' })

  console.log('bundling…')
  execFileSync(process.execPath, ['build-excalidraw.mjs'], {
    cwd: tmp,
    stdio: 'inherit',
    env: { ...process.env, EXCALIDRAW_BUILD_STAGE: 'bundle' },
  })

  const built = path.join(tmp, 'excalidraw.trim.js')
  const dest = path.join(REPO_ROOT, 'static', 'excalidraw.js')
  fs.copyFileSync(built, dest)

  const { createHash } = await import('node:crypto')
  const bytes = fs.readFileSync(dest)
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  console.log(`\nwrote ${dest}`)
  console.log(`${bytes.length} bytes, sha256 ${sha256}`)
  console.log(
    'update static/SHA256SUMS from the checked-out directory with:\n' +
      '  cd static && shasum -a 256 *.js *.mjs *.woff2 > SHA256SUMS',
  )
  console.log(`(build directory left at ${tmp} — remove it once you are done comparing)`)
}

async function bundle() {
  const esbuild = await import('esbuild')
  const PROD = path.resolve('node_modules/@excalidraw/excalidraw/dist/prod')
  const cache = new Map()

  // Every family this bundle embeds has to be one static/VENDOR.md's font
  // search actually looked at — an ALLOWLIST, not a blocklist of the two known
  // cuts. A blocklist's failure is silent: `@excalidraw/excalidraw` version
  // bumps its font set without asking anyone, and a blocklist only knows the
  // names it was told to refuse, so a ninth family arriving in a future
  // re-vendor would sail through as a `data:` URI with no licence review and
  // no test to catch it — exactly the gap the seven-family search was done to
  // close, reopened by the one line a version bump changes. `VETTED_FAMILIES`
  // is the seven static/excalidraw-fonts-LICENSE.txt actually documents;
  // `DROPPED_FAMILIES` is the two that fall back to `local:` on purpose, for
  // two different reasons — Xiaolai for size (209 files, 12,667,492 B, for a
  // CJK fallback face nothing in this tool's English-only UI reaches) and
  // Liberation Sans for licence (see static/VENDOR.md: the copy this package
  // ships is the pre-2012 Ascender/Red Hat build under GPLv2 plus the
  // font-embedding exception, not the OFL 1.1 "Reserved Font Name Liberation"
  // relicense, and the exception text is scoped to documents that embed the
  // font rather than software that bundles it, with no separate file here for
  // a notice to travel beside the way ELK's does). A family that is neither
  // fails the build rather than shipping unreviewed: check its licence
  // against the method static/VENDOR.md's font section describes, then either
  // add it to `VETTED_FAMILIES` (and static/excalidraw-fonts-LICENSE.txt and
  // static/VENDOR.md) or to `DROPPED_FAMILIES` here, the way Liberation was.
  const VETTED_FAMILIES = new Set([
    'Assistant',
    'Cascadia',
    'ComicShanns',
    'Excalifont',
    'Lilita',
    'Nunito',
    'Virgil',
  ])
  const DROPPED_FAMILIES = { Xiaolai: 'local:Xiaolai', Liberation: 'local:Liberation' }

  // `rel` is always `fonts/<Family>/<file>.woff2` by the time it reaches
  // here — both call sites below strip the leading `./` before calling this —
  // so the family is the path segment right after `fonts`, on either
  // separator, matching the `[\\/]` esbuild already uses for the same split
  // elsewhere in this file.
  function familyOf(rel) {
    const parts = rel.split(/[\\/]/)
    const i = parts.indexOf('fonts')
    return i >= 0 ? parts[i + 1] : undefined
  }

  function dataUri(rel) {
    const abs = path.join(PROD, rel)
    if (!fs.existsSync(abs)) return null
    const family = familyOf(rel)
    if (family !== undefined && Object.hasOwn(DROPPED_FAMILIES, family)) {
      return DROPPED_FAMILIES[family]
    }
    if (family === undefined || !VETTED_FAMILIES.has(family)) {
      throw new Error(
        `font family ${JSON.stringify(family ?? rel)} (${rel}) is neither vetted nor a ` +
          'known drop. Its licence has not been reviewed, so this build refuses to embed ' +
          "it silently. Check it against static/VENDOR.md's font section, then either add " +
          "it to VETTED_FAMILIES (and static/excalidraw-fonts-LICENSE.txt and VENDOR.md's " +
          'table) or add it to DROPPED_FAMILIES here, in tools/build-excalidraw.mjs.',
      )
    }
    if (cache.has(abs)) return cache.get(abs)
    const uri = 'data:font/woff2;base64,' + fs.readFileSync(abs).toString('base64')
    cache.set(abs, uri)
    return uri
  }

  // **The API key upstream ships, blanked here.**
  //
  // `@excalidraw/excalidraw` bakes its own build-time `VITE_APP_*` constants
  // into the published package, and one of them is the Firebase config for
  // `excalidraw-room-persistence` — their public collaboration backend. It is
  // Excalidraw's key, not ours, and it is in every copy of this package on
  // GitHub; jcanton's repository got a `google_api_key` secret-scanning alert
  // for it hours after `static/excalidraw.js` was first committed, listing five
  // other public repositories leaking the same string.
  //
  // In this build it is dead text: the output contains exactly one occurrence
  // of the word `firebase` — this config — and no Firebase SDK at all, and the
  // policy every page ships under is `connect-src 'self'`, which refuses every
  // host in the block regardless. So blanking the value costs nothing and takes
  // a live third-party credential out of a public repository.
  //
  // The VALUE only, leaving `{"apiKey":"", ...}` valid JSON: the rest of that
  // object — `authDomain`, `projectId`, `appId`, `messagingSenderId` — is
  // public identifiers rather than a secret, and rewriting the whole literal
  // would be a bigger change to upstream's bytes for no gain.
  //
  // Written as a SHAPE and not as the one known string, on the same argument
  // `VETTED_FAMILIES` is an allowlist: a substitution that only knows the key
  // it was told about is one a version bump silently defeats. `AIza` plus 35
  // characters of Google's key alphabet is the documented shape, and it is what
  // GitHub's own scanner matches. `mustBeClean` re-checks the finished bundle,
  // so a key arriving through a path this `onLoad` does not cover fails the
  // build rather than shipping.
  const GOOGLE_KEY = /AIza[0-9A-Za-z_-]{35}/g

  function scrubbed(source) {
    return source.replace(GOOGLE_KEY, '')
  }

  function mustBeClean(file) {
    const found = fs.readFileSync(file, 'utf8').match(GOOGLE_KEY)
    if (!found) return
    throw new Error(
      `${file} still carries ${found.length} Google API key(s) after the scrub — ` +
        `first is ${found[0].slice(0, 8)}… . A key reached the bundle by a path the ` +
        'onLoad rewrite does not cover (a chunk outside dist/prod, the CSS, or a ' +
        'dependency). Find it and widen the scrub; do not commit the bundle.',
    )
  }

  const plugin = {
    name: 'trim',
    setup(b) {
      // Drop mermaid-to-excalidraw entirely: ~2.8 MiB of mermaid, cytoscape
      // and katex for a text-to-diagram import dialog this tool never opens.
      b.onResolve({ filter: /^@excalidraw\/mermaid-to-excalidraw$/ }, () => ({
        path: 'stub-mermaid',
        namespace: 'stub',
      }))
      b.onLoad({ filter: /.*/, namespace: 'stub' }, () => ({
        contents:
          'export const parseMermaidToExcalidraw = async () => ' +
          '{ throw new Error("mermaid support was stripped from this build") }',
        loader: 'js',
      }))
      // Drop every locale but English. `--format=iife` folds every dynamic
      // `import()` into the one output file regardless, so "en only" has to
      // be enforced here rather than left to the format to do for free.
      b.onResolve({ filter: /dist[\\/]prod[\\/]locales[\\/]/ }, (a) => {
        if (/[\\/]en-[A-Z0-9]+\.js$/.test(a.path) || /[\\/]locales[\\/]en-/.test(a.path)) {
          return null
        }
        return { path: 'stub-locale-' + path.basename(a.path), namespace: 'stub' }
      })
      // The package's CSS is reached through the exports map's `production`
      // condition (the deep `dist/prod/index.css` path is refused), and its
      // `url(./fonts/...)` references are rewritten to the same `data:` URIs
      // (or the same `local:` sentinel) the JS string literals below get.
      b.onLoad({ filter: /dist[\\/]prod[\\/]index\.css$/ }, async (a) => ({
        contents: (await fs.promises.readFile(a.path, 'utf8')).replace(
          /url\((['"]?)(\.\/fonts\/[^'")]+)\1\)/g,
          (m, q, rel) => {
            const u = dataUri(rel.slice(2))
            return u === null ? m : `url("${u}")`
          },
        ),
        loader: 'text',
      }))
      // The fonts are reached as plain JS string literals inside the
      // package's own chunks, not as `import`s or a loader-recognised
      // extension — `--loader:.woff2=dataurl` inlines nothing on its own.
      // This rewrites those literals the same way, in every first-party file
      // esbuild loads out of `dist/prod`, and blanks the API key in the same
      // pass — see `scrubbed` for why there is a key here to blank.
      b.onLoad({ filter: /@excalidraw[\\/]excalidraw[\\/]dist[\\/]prod[\\/].*\.js$/ }, async (a) => ({
        contents: scrubbed(
          (await fs.promises.readFile(a.path, 'utf8')).replace(
            /"(\.\/fonts\/[^"]+\.woff2)"/g,
            (m, rel) => {
              const u = dataUri(rel.slice(2))
              return u === null ? m : JSON.stringify(u)
            },
          ),
        ),
        loader: 'js',
      }))
    },
  }

  await esbuild.build({
    entryPoints: ['entry.js'],
    bundle: true,
    format: 'iife',
    minify: true,
    target: 'es2020',
    conditions: ['production'],
    define: { 'process.env.NODE_ENV': '"production"', 'process.env.IS_PREACT': '"false"' },
    loader: { '.woff2': 'dataurl', '.ttf': 'dataurl', '.css': 'text', '.wasm': 'binary' },
    outfile: 'excalidraw.trim.js',
    plugins: [plugin],
    legalComments: 'none',
    logLevel: 'info',
  })
  mustBeClean('excalidraw.trim.js')
}
