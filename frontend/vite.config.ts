import { defineConfig } from 'vite'
import type { Plugin } from 'vite'
import react from '@vitejs/plugin-react'

import { MODE_KEY, NIGHT, clockMode, londonMinutes, modeFor, toMinutes } from './src/theme.ts'

/**
 * Day or night, set before first paint.
 *
 * index.html carries a marker in its <head>; this replaces it with an inline
 * script made from src/theme.ts's own functions — their source, not a copy
 * of the logic — so the page and the app cannot disagree about the mode, and
 * the wall never shows day for a frame and then turns to night. Storage may
 * throw; the clock decides then.
 */
const MARKER = '<!-- mode: set before first paint (vite.config.ts) -->'

function modeBeforePaint(): Plugin {
  const script = `(function () {
${toMinutes}
${londonMinutes}
${clockMode}
${modeFor}
var stored = null;
try { stored = localStorage.getItem(${JSON.stringify(MODE_KEY)}); } catch (e) {}
try { document.documentElement.dataset.theme = ${modeFor.name}(Date.now(), ${JSON.stringify(NIGHT)}, stored); } catch (e) {}
})();`
  return {
    name: 'coinquest-mode-before-paint',
    transformIndexHtml(html) {
      if (!html.includes(MARKER)) throw new Error(`index.html is missing the mode marker: ${MARKER}`)
      return html.replace(MARKER, `<script>${script}</script>`)
    },
  }
}

// In the container the API serves this bundle itself, so requests are
// same-origin. In development the dev server proxies them to the API instead,
// which keeps every fetch in the app a plain relative path either way.
export default defineConfig({
  plugins: [react(), modeBeforePaint()],
  server: {
    proxy: {
      '/health': 'http://127.0.0.1:8600',
      '/api': 'http://127.0.0.1:8600',
    },
  },
})
