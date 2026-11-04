// The skip logic and key handling of the browser scripts (scripts/e2e). No browser is started here.
import test from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { parseEnv, keyStatus, findChrome, chromeCandidates, problems } from '../../scripts/e2e/lib.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const SECRET = 'sk-or-v1-THIS-MUST-NEVER-APPEAR-ANYWHERE'

// ------------------------------------------------------------------ the key: presence only

test('parseEnv reads KEY=value lines, quotes, export and comments', () => {
  const m = parseEnv(`# a comment\nOPENROUTER_API_KEY="${SECRET}"\nexport MODEL='some/model'\n\nBLANK=\n  SPACED = x  \nnot a line`)
  assert.equal(m.get('OPENROUTER_API_KEY'), SECRET)
  assert.equal(m.get('MODEL'), 'some/model')
  assert.equal(m.get('BLANK'), '')
  assert.equal(m.get('SPACED'), 'x')
  assert.equal(m.size, 4)
})

test('keyStatus reports whether the key and model have values, as booleans only', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'keytest-'))
  const f = path.join(tmp, '.env')
  fs.writeFileSync(f, `OPENROUTER_API_KEY=${SECRET}\nMODEL=m\n`)
  const s = keyStatus(f)
  assert.deepEqual(s, { file: f, exists: true, key: true, model: true })
  assert.ok(!JSON.stringify(s).includes(SECRET), 'the value must not survive in the result')
  assert.ok(Object.values(s).every(v => typeof v === 'boolean' || v === f))
})

test('keyStatus: a missing file, an empty key and a missing model are each reported', () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'keytest-'))
  assert.deepEqual(keyStatus(path.join(tmp, 'nope.env')).exists, false)
  fs.writeFileSync(path.join(tmp, 'a.env'), 'OPENROUTER_API_KEY=\nMODEL=m\n')
  assert.deepEqual([keyStatus(path.join(tmp, 'a.env')).key, keyStatus(path.join(tmp, 'a.env')).model], [false, true])
  fs.writeFileSync(path.join(tmp, 'b.env'), `OPENROUTER_API_KEY=${SECRET}\n`)
  assert.deepEqual([keyStatus(path.join(tmp, 'b.env')).key, keyStatus(path.join(tmp, 'b.env')).model], [true, false])
})

// ------------------------------------------------------------------ finding Chrome

test('an explicit CHROME_PATH wins, and a wrong one is not silently replaced by another browser', () => {
  const exists = p => p === '/my/chrome' || p === '/usr/bin/google-chrome'
  assert.equal(findChrome({ env: { CHROME_PATH: '/my/chrome' }, exists, platform: 'linux' }), '/my/chrome')
  assert.equal(findChrome({ env: { CHROME_PATH: '/wrong' }, exists, platform: 'linux' }), null)
})

test('the usual install locations are searched per platform', () => {
  assert.equal(findChrome({ env: {}, exists: p => p === '/usr/bin/chromium', platform: 'linux' }), '/usr/bin/chromium')
  assert.equal(findChrome({ env: {}, exists: p => p.includes('Google Chrome.app'), platform: 'darwin' })?.includes('Google Chrome'), true)
  const win = chromeCandidates('win32', { PROGRAMFILES: 'C:\\Program Files', 'PROGRAMFILES(X86)': 'C:\\Program Files (x86)', LOCALAPPDATA: 'C:\\Users\\u\\AppData\\Local' })
  assert.ok(win.some(p => p.endsWith('chrome.exe')) && win.some(p => p.endsWith('msedge.exe')))
  assert.equal(findChrome({ env: {}, exists: () => false, platform: 'linux' }), null)
})

// ------------------------------------------------------------------ what makes the scripts skip, and what they say

const ok = { chrome: '/c', key: { exists: true, key: true, model: true }, needKey: true, distExists: true, nodeModulesExists: true, busyPorts: [] }

test('with everything in place there is nothing to skip for', () => {
  assert.deepEqual(problems(ok), [])
})

test('no Chrome: skip, and say how to fix it', () => {
  const p = problems({ ...ok, chrome: null })
  assert.equal(p.length, 1)
  assert.match(p[0], /Chrome was not found/)
  assert.match(p[0], /CHROME_PATH/)
})

test('a wrong CHROME_PATH is named as the problem', () => {
  assert.match(problems({ ...ok, chrome: null, chromePathSet: true })[0], /CHROME_PATH is set but does not point at a file/)
})

test('no key: skip, and point at the README and --offline', () => {
  for (const key of [{ exists: false, key: false, model: false }, { exists: true, key: false, model: true }, { exists: true, key: true, model: false }]) {
    const p = problems({ ...ok, key })
    assert.equal(p.length, 1)
    assert.match(p[0], /backend\/\.env/)
    assert.match(p[0], /--offline/)
  }
})

test('an offline run does not need the key at all', () => {
  assert.deepEqual(problems({ ...ok, needKey: false, key: { exists: false, key: false, model: false } }), [])
})

test('an unbuilt frontend, missing node_modules and busy ports are each said plainly', () => {
  const p = problems({ ...ok, distExists: false, nodeModulesExists: false, busyPorts: [8000, 5173] })
  assert.equal(p.length, 4)
  assert.ok(p.some(m => /npm run build/.test(m)) && p.some(m => /npm install/.test(m)))
  assert.ok(p.some(m => /Port 8000 is already in use/.test(m)) && p.some(m => /Port 5173 is already in use/.test(m)))
})

test('no message can contain the key: only booleans reach it', () => {
  const p = problems({ ...ok, key: { exists: true, key: false, model: false, leaked: SECRET } })
  assert.ok(!p.join('\n').includes(SECRET))
})

test('run for real with a bad CHROME_PATH, preflight prints SKIPPED with the reason and exits 0', () => {
  const lib = pathToFileURL(path.join(ROOT, 'scripts', 'e2e', 'lib.mjs')).href
  const r = spawnSync(process.execPath, ['--input-type=module', '-e', `import { preflight } from '${lib}'; await preflight({ needKey: false }); console.log('REACHED')`],
    { encoding: 'utf8', env: { ...process.env, CHROME_PATH: path.join(os.tmpdir(), 'no-such-chrome.exe') } })
  assert.equal(r.status, 0)
  assert.match(r.stdout, /SKIPPED/)
  assert.match(r.stdout, /CHROME_PATH is set but does not point at a file/)
  assert.doesNotMatch(r.stdout, /REACHED/)
})

// ------------------------------------------------------------------ not part of the default runs

test('nothing under scripts/ looks like a test, so pytest and `node --test` discovery cannot pick it up', () => {
  const walk = d => fs.readdirSync(d, { withFileTypes: true }).flatMap(e => (e.isDirectory() ? (e.name === 'out' ? [] : walk(path.join(d, e.name))) : [path.join(d, e.name)]))
  const files = walk(path.join(ROOT, 'scripts'))
  assert.ok(files.length >= 4)
  for (const f of files) {
    const n = path.basename(f)
    assert.ok(!/\.(test|spec)\.[cm]?js$/.test(n) && !/^test_.*\.py$/.test(n) && !/_test\.py$/.test(n), n)
  }
})

test('pytest is pointed only at tests/', () => {
  assert.match(fs.readFileSync(path.join(ROOT, 'pytest.ini'), 'utf8'), /testpaths\s*=\s*tests\s*$/m)
})

test('every browser script at least parses', () => {
  for (const f of ['lib.mjs', 'drive.mjs', 'drive-guided.mjs']) {
    const r = spawnSync(process.execPath, ['--check', path.join(ROOT, 'scripts', 'e2e', f)], { encoding: 'utf8' })
    assert.equal(r.status, 0, `${f}: ${r.stderr}`)
  }
})
