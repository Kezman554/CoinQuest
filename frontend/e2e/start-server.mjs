#!/usr/bin/env node
/**
 * Everything the e2e suite needs before a browser can be pointed at it,
 * done in one script so shell sequencing — not Playwright's globalSetup/
 * webServer ordering, which turned out not to guarantee this — is what
 * makes the database exist before the server tries to open it.
 *
 * Build the real production bundle (this suite drives what a deploy
 * actually serves, not the dev server), seed a fresh scratch database with
 * the mix Session T's card asked to be tested against, then start the real
 * app against it and hand off stdio — this process *is* the server
 * Playwright's webServer waits on.
 */

import { execFileSync, execSync, spawn } from 'node:child_process'
import { mkdirSync, rmSync } from 'node:fs'
import path from 'node:path'

import { DB_PATH, FRONTEND_ROOT, PORT, REPO_ROOT, pythonExecutable, sqliteUrl } from './paths.mjs'

const dbDir = path.dirname(DB_PATH)
rmSync(dbDir, { recursive: true, force: true })
mkdirSync(dbDir, { recursive: true })

// A single command string through execSync, not execFileSync with an args
// array and shell:true — Node warns the latter's arguments aren't escaped
// for the shell. npm needs a shell on Windows (it resolves to npm.cmd,
// which spawn/execFile cannot run directly); a literal string sidesteps
// the warning because there is no separate args array to be unescaped.
execSync('npm run build', { cwd: FRONTEND_ROOT, stdio: 'inherit' })

execFileSync(pythonExecutable(), [path.join(FRONTEND_ROOT, 'e2e', 'seed_database.py'), DB_PATH], {
  cwd: REPO_ROOT,
  stdio: 'inherit',
})

const server = spawn(
  pythonExecutable(),
  ['-m', 'uvicorn', 'app.main:app', '--port', String(PORT)],
  {
    cwd: REPO_ROOT,
    stdio: 'inherit',
    env: {
      ...process.env,
      CHILD_NAME: 'E2E Kid',
      PARENT_PIN: '0000',
      PARENT_NAMES: 'E2E Parent',
      DATABASE_URL: sqliteUrl(DB_PATH),
      TZ: 'Europe/London',
      FRONTEND_DIR: path.join(REPO_ROOT, 'frontend', 'dist'),
    },
  },
)

server.on('exit', (code) => process.exit(code ?? 0))
