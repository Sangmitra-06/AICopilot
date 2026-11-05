// Shared helpers for the browser end-to-end scripts (see README.md, "End-to-end browser check").
//
// These scripts start a real backend (temporary database) and the built frontend, and drive headless Chrome over the
// DevTools protocol. They are NOT part of the default test runs: pytest only collects tests/, and `node --test` is only
// pointed at tests/loops and tests/chat.
//
// The API key is never read into this process's environment, printed, or logged. backend/.env is only inspected to see
// whether OPENROUTER_API_KEY and MODEL have values (booleans); the backend loads the file itself.
import { spawn, spawnSync } from 'node:child_process'
import fs from 'node:fs'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
export const PORTS = { backend: 8000, frontend: 5173, chrome: 9333 }
export const OUT = process.env.E2E_OUT ? path.resolve(process.env.E2E_OUT) : path.join(ROOT, 'scripts', 'e2e', 'out')
export const ENV_FILE = path.join(ROOT, 'backend', '.env')
export const sleep = ms => new Promise(r => setTimeout(r, ms))
export const log = (...a) => console.log('[e2e]', ...a)

// ------------------------------------------------------------------ the key: presence only, never the value

export function parseEnv(text) {
  const out = new Map()
  for (const raw of String(text).split(/\r?\n/)) {
    if (raw.trim().startsWith('#')) continue
    const m = raw.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/)
    if (!m) continue
    let v = m[2]
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) v = v.slice(1, -1)
    out.set(m[1], v)
  }
  return out
}

// { file, exists, key, model }: booleans only. The values are dropped before this function returns.
export function keyStatus(file = ENV_FILE, read = fs.readFileSync, exists = fs.existsSync) {
  if (!exists(file)) return { file, exists: false, key: false, model: false }
  const vars = parseEnv(read(file, 'utf8'))
  return { file, exists: true, key: Boolean(vars.get('OPENROUTER_API_KEY')), model: Boolean(vars.get('MODEL')) }
}

// ------------------------------------------------------------------ what is needed, and what to say when it is not

export function chromeCandidates(platform = process.platform, env = process.env) {
  if (platform === 'win32') {
    const roots = [env.PROGRAMFILES, env['PROGRAMFILES(X86)'], env.LOCALAPPDATA].filter(Boolean)
    return [
      ...roots.map(r => path.join(r, 'Google', 'Chrome', 'Application', 'chrome.exe')),
      ...roots.map(r => path.join(r, 'Microsoft', 'Edge', 'Application', 'msedge.exe')),   // Chromium: same protocol
    ]
  }
  if (platform === 'darwin') {
    return ['/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', '/Applications/Chromium.app/Contents/MacOS/Chromium']
  }
  return ['/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium', '/usr/bin/chromium-browser', '/snap/bin/chromium']
}

// An explicit CHROME_PATH wins, and if it is wrong that is reported (no silent fallback to some other browser).
export function findChrome({ env = process.env, exists = fs.existsSync, platform = process.platform } = {}) {
  if (env.CHROME_PATH) return exists(env.CHROME_PATH) ? env.CHROME_PATH : null
  return chromeCandidates(platform, env).find(p => exists(p)) || null
}

// The reasons to skip, as plain sentences that say how to fix each. Pure, so it can be tested.
export function problems({ chrome, chromePathSet = false, key, needKey, distExists, nodeModulesExists, busyPorts = [] }) {
  const out = []
  if (!chrome) {
    out.push(chromePathSet
      ? 'CHROME_PATH is set but does not point at a file. Fix it, or unset it to use an installed Chrome.'
      : 'Chrome was not found. Install Google Chrome, or set CHROME_PATH to its executable.')
  }
  if (needKey) {
    if (!key.exists) out.push('backend/.env was not found, so there is no API key. Create it with OPENROUTER_API_KEY and MODEL (see the README), or run with --offline.')
    else if (!key.key) out.push('backend/.env has no OPENROUTER_API_KEY value. Add it (see the README), or run with --offline.')
    else if (!key.model) out.push('backend/.env has no MODEL value. Add it (see the README), or run with --offline.')
  }
  if (!nodeModulesExists) out.push('frontend/node_modules is missing. Run `npm install` in frontend/.')
  if (!distExists) out.push('frontend/dist is missing. Run `npm run build` in frontend/.')
  for (const p of busyPorts) out.push(`Port ${p} is already in use. Stop whatever is using it, then run this again.`)
  return out
}

export const portFree = port => new Promise(res => {
  const s = net.createServer()
  s.once('error', () => res(false))
  s.once('listening', () => s.close(() => res(true)))
  s.listen(port, '127.0.0.1')
})

// Checks everything and, if anything is missing, says so plainly and exits 0 (a skip is not a failure).
export async function preflight({ needKey }) {
  const chrome = findChrome()
  const busyPorts = []
  for (const p of Object.values(PORTS)) if (!(await portFree(p))) busyPorts.push(p)
  const found = problems({
    chrome, chromePathSet: Boolean(process.env.CHROME_PATH), key: keyStatus(), needKey,
    distExists: fs.existsSync(path.join(ROOT, 'frontend', 'dist', 'index.html')),
    nodeModulesExists: fs.existsSync(path.join(ROOT, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js')),
    busyPorts,
  })
  if (found.length) {
    log('SKIPPED: the browser check cannot run here.')
    for (const f of found) log(' - ' + f)
    process.exit(0)
  }
  return { chrome }
}

// ------------------------------------------------------------------ processes

const procs = []
export function pythonPath() {
  if (process.env.PYTHON) return process.env.PYTHON
  const venvs = [ROOT, path.join(ROOT, 'backend')]                       // .venv at the root, or in backend/ as the README sets up
  for (const v of venvs) {
    for (const p of [path.join(v, '.venv', 'Scripts', 'python.exe'), path.join(v, '.venv', 'bin', 'python')]) if (fs.existsSync(p)) return p
  }
  return process.platform === 'win32' ? 'python' : 'python3'
}

export function track(child) { procs.push(child); return child }

// Stop one tracked process (and its children), e.g. to restart the backend.
export function stopOne(p) {
  try {
    if (process.platform === 'win32') spawnSync('taskkill', ['/F', '/T', '/PID', String(p.pid)], { stdio: 'ignore' })
    else p.kill('SIGTERM')
  } catch { /* already gone */ }
  const i = procs.indexOf(p)
  if (i >= 0) procs.splice(i, 1)
}

export function stopAll() {
  for (const p of procs) {
    try {
      if (process.platform === 'win32') spawnSync('taskkill', ['/F', '/T', '/PID', String(p.pid)], { stdio: 'ignore' })
      else p.kill('SIGTERM')
    } catch { /* already gone */ }
  }
  procs.length = 0
}

export const up = async url => { try { return (await fetch(url)).ok } catch { return false } }

export async function until(fn, ms = 20000, what = 'the condition') {
  const t0 = Date.now()
  while (Date.now() - t0 < ms) { const v = await fn(); if (v) return v; await sleep(150) }
  throw new Error('timed out waiting for ' + what)
}

export function startFrontend() {
  const vite = path.join(ROOT, 'frontend', 'node_modules', 'vite', 'bin', 'vite.js')
  return track(spawn(process.execPath, [vite, 'preview', '--port', String(PORTS.frontend), '--strictPort'],
    { cwd: path.join(ROOT, 'frontend'), stdio: 'ignore' }))
}

// The real backend over a throwaway database. It loads backend/.env itself; nothing about the key passes through here.
export function startBackend(tmp, extraEnv = {}) {
  fs.mkdirSync(OUT, { recursive: true })
  const logFd = fs.openSync(path.join(OUT, 'backend.log'), 'w')
  const env = { ...process.env, COPILOT_DB: path.join(tmp, 'events.db'), COPILOT_DATA_DIR: path.join(tmp, 'data'), ...extraEnv }
  return track(spawn(pythonPath(), ['-m', 'uvicorn', 'app.main:app', '--port', String(PORTS.backend)],
    { cwd: path.join(ROOT, 'backend'), env, stdio: ['ignore', logFd, logFd] }))
}

// The real backend with a scripted model (scripts/e2e/scripted_backend.py): no key and no network call.
export function startScriptedBackend(tmp, extraEnv = {}) {
  fs.mkdirSync(OUT, { recursive: true })
  const logFd = fs.openSync(path.join(OUT, 'backend.log'), 'w')
  const env = { ...process.env, COPILOT_DB: path.join(tmp, 'events.db'), COPILOT_DATA_DIR: path.join(tmp, 'data'), ...extraEnv }
  return track(spawn(pythonPath(), [path.join(ROOT, 'scripts', 'e2e', 'scripted_backend.py'), String(PORTS.backend)],
    { cwd: path.join(ROOT, 'backend'), env, stdio: ['ignore', logFd, logFd] }))
}

export function makePaper(file, extra = []) {
  const r = spawnSync(pythonPath(), [path.join(ROOT, 'scripts', 'e2e', 'make_paper.py'), file, ...extra], { encoding: 'utf8' })
  if (r.status !== 0) throw new Error('could not build the test PDF (is pymupdf installed in the project venv?)')
  return file
}

export function mkTmp(prefix = 'copilot-e2e-') { return fs.mkdtempSync(path.join(os.tmpdir(), prefix)) }

// ------------------------------------------------------------------ the browser, over the DevTools protocol

class CDP {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map(); this.exceptions = []
    ws.onmessage = e => {
      const m = JSON.parse(e.data)
      if (m.id && this.pending.has(m.id)) {
        const { res, rej } = this.pending.get(m.id)
        this.pending.delete(m.id)
        if (m.error) rej(new Error(JSON.stringify(m.error))); else res(m.result)
      } else if (m.method === 'Runtime.exceptionThrown') {
        const d = m.params.exceptionDetails
        this.exceptions.push(`${d.text} ${(d.exception && d.exception.description) || ''}`.trim())
      }
    }
  }
  send(method, params = {}) {
    const id = ++this.id
    this.ws.send(JSON.stringify({ id, method, params }))
    return new Promise((res, rej) => this.pending.set(id, { res, rej }))
  }
  async eval(expression) {
    const r = await this.send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (r.exceptionDetails) throw new Error('eval failed: ' + JSON.stringify(r.exceptionDetails).slice(0, 300))
    return r.result.value
  }
}

export async function openBrowser(chromePath, tmp, { width = 1280, height = 860 } = {}) {
  track(spawn(chromePath, ['--headless=new', `--remote-debugging-port=${PORTS.chrome}`, `--user-data-dir=${path.join(tmp, 'profile')}`,
    `--window-size=${width},${height}`, '--no-first-run', '--no-default-browser-check', 'about:blank'], { stdio: 'ignore' }))
  const target = await until(async () => {
    try { return (await (await fetch(`http://127.0.0.1:${PORTS.chrome}/json/list`)).json()).find(t => t.type === 'page') } catch { return null }
  }, 20000, 'Chrome to start')
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise(r => { ws.onopen = r })
  const cdp = new CDP(ws)
  await cdp.send('Page.enable'); await cdp.send('DOM.enable'); await cdp.send('Runtime.enable')
  await cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: false })
  fs.mkdirSync(OUT, { recursive: true })
  const resize = (w, h, mobile = false, scale = 1) => cdp.send('Emulation.setDeviceMetricsOverride', { width: w, height: h, deviceScaleFactor: scale, mobile })
  const shot = async name => {
    const r = await cdp.send('Page.captureScreenshot', { format: 'png' })
    fs.writeFileSync(path.join(OUT, name + '.png'), Buffer.from(r.data, 'base64'))
  }
  const msgs = () => cdp.eval(`[...document.querySelectorAll('.ca-msg')].map(e => ({ who: e.classList.contains('ca-user') ? 'user' : 'assistant', text: e.innerText }))`)
  const buttons = () => cdp.eval(`[...document.querySelectorAll('button')].map(b => b.getAttribute('aria-label') || b.textContent.trim())`)
  // The paper is attached and the app has spoken: its opening (the first section in the reviewer's reading order, after an
  // optional summary), or the stock line when there is nothing to open with.
  const OPENED = /Got the paper|start of the paper|as you said you like to|here it is/
  const waitPaper = (ms = 60000) => until(async () => (await msgs()).some(m => OPENED.test(m.text)), ms, 'the opening message after the paper was attached')
  const waitMsg = (sub, ms = 20000) => until(async () => (await msgs()).some(m => m.text.includes(sub)), ms, `a message containing "${sub}"`)
  const idle = () => until(async () => !(await cdp.eval(`!!document.querySelector('.ca-wait')`)), 90000, 'the working mark to go away')
  async function type(text) {
    await cdp.eval(`document.querySelector('textarea[aria-label=Message]').focus()`)
    await cdp.send('Input.insertText', { text })
    const k = { key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 }
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', ...k, text: '\r' })
    await cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', ...k })
  }
  // Send text and wait for the assistant's reply to arrive; returns the new assistant message(s).
  async function say(text) {
    const before = (await msgs()).length
    await type(text)
    await until(async () => (await msgs()).length > before + 1, 90000, `a reply to "${text}"`)
    await idle()
    return (await msgs()).slice(before + 1)
  }
  const goto = async url => { await cdp.send('Page.navigate', { url }); await sleep(600) }
  async function attach(file) {
    const { root } = await cdp.send('DOM.getDocument', { depth: -1 })
    const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: 'input[type=file]' })
    await cdp.send('DOM.setFileInputFiles', { files: [file], nodeId })
  }
  return { cdp, resize, shot, msgs, buttons, waitMsg, waitPaper, idle, type, say, goto, attach }
}

// ------------------------------------------------------------------ checks with a pass/fail summary

export function createChecks() {
  const results = []
  return {
    check(ok, label, detail = '') {
      results.push({ ok: Boolean(ok), label })
      log(`${ok ? 'PASS' : 'FAIL'}  ${label}${!ok && detail ? '  -> ' + detail : ''}`)
    },
    note(label) { log(`note  ${label}`) },
    summary() {
      const failed = results.filter(r => !r.ok)
      log(`${results.length - failed.length} of ${results.length} checks passed.`)
      return failed.length === 0
    },
  }
}
