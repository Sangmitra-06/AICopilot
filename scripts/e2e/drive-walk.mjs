// The guided walk in a real browser: "next" shows a short description of the next section AND the PDF moves there every
// time. Real backend, SCRIPTED model (no key, no network call; see scripted_backend.py).
//
//   node scripts/e2e/drive-walk.mjs
//
// Prints PASS/FAIL per check, exits 1 on a failure, and skips (exit 0) with a reason if Chrome, the built frontend or a
// free port is missing. Screenshots go to scripts/e2e/out/ (git-ignored).
import path from 'node:path'
import { PORTS, createChecks, makePaper, mkTmp, openBrowser, preflight, sleep, startFrontend, startScriptedBackend, stopAll, until, up } from './lib.mjs'

const { chrome } = await preflight({ needKey: false })
const FRONT = `http://localhost:${PORTS.frontend}/`
const t = createChecks()
const tmp = mkTmp()
let b

const ev = e => b.cdp.eval(e)
const settle = async () => { await sleep(1300) }                               // a smooth scroll takes a moment
// Where the highlights are, in the scroller's own coordinates (so a scroll alone does not change them), and whether they are on screen.
const marks = () => ev(`(() => { const s = document.querySelector('.pdf-scroller'), sr = s.getBoundingClientRect();
  return [...document.querySelectorAll('.pdf-hl')].map(h => { const r = h.getBoundingClientRect(), p = h.closest('.pdf-page');
    return { page: [...document.querySelectorAll('.pdf-page')].indexOf(p) + 1, y: Math.round(r.top - sr.top + s.scrollTop), visible: r.top >= sr.top - 1 && r.bottom <= sr.bottom + 1 } }) })()`)
const key = m => JSON.stringify(m.map(x => [x.page, x.y]))
const pointers = s => (s.match(/\((?:Sections? [\d., ]+|[A-Z][\w ;.-]*)\)/g) || []).length
const lastReply = async () => (await b.msgs()).at(-1).text

try {
  const pdf = makePaper(path.join(tmp, 'long.pdf'), ['long'])
  startFrontend()
  await until(() => up(FRONT), 20000, 'the frontend preview server')
  startScriptedBackend(tmp)
  await until(() => up(`http://127.0.0.1:${PORTS.backend}/config`), 40000, 'the backend')
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
  await until(() => ev(`document.querySelectorAll('.pdf-page').length === 4`), 20000, 'four pages of the PDF')
  await until(() => ev(`[...document.querySelectorAll('.pdf-page canvas')].some(c => c.width > 0)`), 20000, 'a page to be drawn')
  await settle()

  const opening = (await b.msgs()).filter(m => m.who === 'assistant').at(-1).text
  t.check(/^Let's begin at the start of the paper, with the abstract\./.test(opening) && opening.includes('\n') && /This part of Abstract/.test(opening),
    'the opening names the section and describes it', opening.slice(0, 160))
  let prev = await marks()
  t.check(prev.length >= 1 && prev[0].visible, 'the opening highlights the first section, on screen', JSON.stringify(prev))

  for (const [i, sec] of ['1 Introduction', '2 Method', '3 Experiments'].entries()) {
    const reply = (await b.say('next')).at(-1).text
    const [lead, ...rest] = reply.split(/\n+/)
    t.check(/^Moving to the /.test(lead) && !/\(/.test(lead), `"next" #${i + 1}: the app's line, no pointer on it`, lead)
    t.check(rest.join(' ').includes('This part of ' + sec), `"next" #${i + 1}: a short description of ${sec} follows`, reply.slice(0, 200))
    t.check(reply.split(/(?<=[.!?])\s+/).every(s => pointers(s) <= 1) && !/\[|p\d+-s\d+/.test(reply), `"next" #${i + 1}: at most one pointer per sentence, no marker shown`, reply)
    await settle()
    const now = await marks()
    t.check(now.length >= 1 && now[0].visible, `"next" #${i + 1}: the new section is highlighted and its first passage is on screen`, JSON.stringify(now))
    t.check(key(now) !== key(prev), `"next" #${i + 1}: the PDF moved to a different place than before`, `${key(prev)} -> ${key(now)}`)
    prev = now
    await b.shot(`w0${i + 1}_next`)
  }
  t.check(prev.every(m => m.page === 4), 'the last section is on page 4 and the pane scrolled there', JSON.stringify(prev))
  t.check(await ev(`document.querySelector('.pdf-scroller').scrollTop > 500`), 'the PDF scrolled down to page 4')

  const end = (await b.say('next')).at(-1).text
  t.check(/^That was the last section in your order\./.test(end), 'after the last section "next" says so', end.slice(0, 120))
  t.check(b.cdp.exceptions.length === 0, 'no uncaught exceptions in the page', b.cdp.exceptions.join(' | '))
} catch (e) {
  t.check(false, 'the run completed', e.message)
  try { if (b) await b.shot('zz_walk_failure') } catch { /* no browser */ }
} finally {
  stopAll()
}
process.exitCode = t.summary() ? 0 : 1
