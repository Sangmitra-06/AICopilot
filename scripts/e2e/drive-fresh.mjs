// Clean state every run (dev only), in a real browser: with COPILOT_FRESH=1 a restarted backend has a new boot id, and the
// page forgets its stored reviewer id and paper id; a paper whose PDF has vanished is forgotten too. Real backend, SCRIPTED
// model (no key, no network call).
//
//   node scripts/e2e/drive-fresh.mjs
import fs from 'node:fs'
import path from 'node:path'
import { PORTS, createChecks, makePaper, mkTmp, openBrowser, preflight, sleep, startFrontend, startScriptedBackend, stopAll, stopOne, until, up } from './lib.mjs'

const { chrome } = await preflight({ needKey: false })
const FRONT = `http://localhost:${PORTS.frontend}/`
const CONFIG = `http://127.0.0.1:${PORTS.backend}/config`
const t = createChecks()
const tmp = mkTmp()
let b, backend
const ev = e => b.cdp.eval(e)
const ids = () => ev(`({ r: localStorage.getItem('copilot.reviewer_id'), p: localStorage.getItem('copilot.paper_id'), boot: localStorage.getItem('copilot.boot_id') })`)
const startBackend = async env => { backend = startScriptedBackend(tmp, env); await until(() => up(CONFIG), 40000, 'the backend') }

try {
  const pdf = makePaper(path.join(tmp, 'paper.pdf'), [])
  startFrontend()
  await until(() => up(FRONT), 20000, 'the frontend preview server')
  await startBackend({ COPILOT_FRESH: '1' })
  const boot1 = (await (await fetch(CONFIG)).json()).boot_id
  t.check(typeof boot1 === 'string' && boot1.length >= 16, 'with COPILOT_FRESH=1 /config reports a boot id', String(boot1))
  b = await openBrowser(chrome, tmp, { width: 1366, height: 768 })

  await b.goto(FRONT)
  await b.waitMsg('papers have you reviewed')
  for (let i = 0; i < 16; i++) {
    if ((await b.msgs()).some(m => m.text.includes('Attach the paper'))) break
    await b.say('idk')
  }
  await b.waitMsg('Attach the paper')
  await b.attach(pdf)
  await b.waitPaper()
  const first = await ids()
  t.check(first.r && first.p && first.boot === boot1, 'the page stored a reviewer id, a paper id and the boot id', JSON.stringify(first))

  // 1. the PDF vanishes from the server: the page forgets the paper and asks for it again
  stopOne(backend)                                   // (Windows keeps the file locked while the backend runs)
  await sleep(800)
  fs.rmSync(path.join(tmp, 'data'), { recursive: true, force: true })
  fs.mkdirSync(path.join(tmp, 'data'))
  await startBackend({})                             // the database is kept, only the PDF is gone
  const status = await ev(`fetch('http://127.0.0.1:${PORTS.backend}/papers/${first.p}/pdf').then(r => r.status)`)
  t.check(status === 404, 'the missing PDF is a 404, not a 500', String(status))
  await b.goto(FRONT)
  await until(async () => (await ids()).p === null, 15000, 'the stored paper id to be cleared')
  await until(async () => (await b.msgs()).some(m => /find that paper any more/.test(m.text)), 15000, 'the "attach it again" line')
  const after1 = await ids()
  t.check(after1.p === null && after1.r === first.r, 'the paper id is cleared and the reviewer is kept', JSON.stringify(after1))
  await b.shot('f01_paper_gone')

  // 2. the backend restarts with a clean state: a new boot id clears the reviewer id too, so onboarding starts over
  stopOne(backend)
  await sleep(800)
  await startBackend({ COPILOT_FRESH: '1' })
  const boot2 = (await (await fetch(CONFIG)).json()).boot_id
  t.check(boot2 && boot2 !== boot1, 'a restarted backend has a different boot id', `${boot1} -> ${boot2}`)
  await b.goto(FRONT)
  await b.waitMsg('papers have you reviewed')
  const after2 = await ids()
  t.check(after2.boot === boot2 && after2.r && after2.r !== first.r, 'the page got a new reviewer id and remembers the new boot id', JSON.stringify(after2))
  t.check((await b.msgs()).length === 1, 'onboarding starts from the first question, with nothing before it')
  await b.shot('f02_fresh_start')

  // 3. without the switch there is no boot id, and a restart changes nothing the page stored
  stopOne(backend)
  await sleep(800)
  await startBackend({})
  const plain = (await (await fetch(CONFIG)).json()).boot_id
  t.check(plain === null, 'without COPILOT_FRESH /config has no boot id', String(plain))
  const keep = await ids()
  await b.goto(FRONT)
  await b.waitMsg('papers have you reviewed')
  t.check((await ids()).r === keep.r, 'a normal restart keeps the stored reviewer id')
  t.check(b.cdp.exceptions.length === 0, 'no uncaught exceptions in the page', b.cdp.exceptions.join(' | '))
} catch (e) {
  t.check(false, 'the run completed', e.message)
  try { if (b) await b.shot('zz_fresh_failure') } catch { /* no browser */ }
} finally {
  stopAll()
}
process.exitCode = t.summary() ? 0 : 1
