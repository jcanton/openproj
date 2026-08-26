// The entry point esbuild bundles. One global, `window.ExcalidrawLib`, carrying
// React, ReactDOM, createRoot and every export `@excalidraw/excalidraw` has —
// `Excalidraw`, `exportToBlob`, `loadSceneOrLibraryFromBlob` and the rest —
// because the page that mounts this has no module graph to import into and
// gets exactly one <script> tag to work with.
import React from 'react'
import * as ReactDOM from 'react-dom'
import { createRoot } from 'react-dom/client'
import * as Ex from '@excalidraw/excalidraw'
import css from '@excalidraw/excalidraw/index.css'

// The package ships a stylesheet, not a <link>; injecting it here as a <style>
// means the vendored bundle is the one file it claims to be, rather than a
// script that then goes and fetches a second one.
if (typeof document !== 'undefined') {
  const s = document.createElement('style')
  s.setAttribute('data-excalidraw', '')
  s.textContent = css
  document.head.appendChild(s)
}

window.ExcalidrawLib = { React, ReactDOM, createRoot, ...Ex }
