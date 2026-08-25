/**
 * Where the e2e run's scratch pieces live, computed once so
 * playwright.config.ts and start-server.mjs cannot disagree about them.
 *
 * Plain JS, not TypeScript: start-server.mjs is run directly by `node`, with
 * no loader that would strip types, so anything it imports has to already
 * be plain JS. playwright.config.ts imports this same file rather than a
 * parallel .ts copy, so there is exactly one definition of each path.
 */

import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))

export const FRONTEND_ROOT = path.resolve(here, '..')
export const REPO_ROOT = path.resolve(FRONTEND_ROOT, '..')
export const DB_PATH = path.join(here, '.tmp', 'e2e.db')
export const PORT = 8611
export const BASE_URL = `http://127.0.0.1:${PORT}`

/** A sqlite:/// URL from a filesystem path, forward-slashed regardless of
 * platform — Windows paths with backslashes are not valid in the URL. */
export function sqliteUrl(dbPath) {
  return `sqlite:///${dbPath.split(path.sep).join('/')}`
}

/** The repo's own venv if one exists (this project's convention — see
 * CLAUDE.md), falling back to whatever `python` resolves to on PATH. */
export function pythonExecutable() {
  const win = path.join(REPO_ROOT, '.venv', 'Scripts', 'python.exe')
  const posix = path.join(REPO_ROOT, '.venv', 'bin', 'python')
  if (existsSync(win)) return win
  if (existsSync(posix)) return posix
  return 'python'
}
