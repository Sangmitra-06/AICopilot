// The whole chat-first journey in a real browser, against a real backend (temporary database).
//
//   node scripts/e2e/drive.mjs             full run; makes a few real model calls with the key in backend/.env
//   node scripts/e2e/drive.mjs --offline   everything that needs no model; the backend gets a dummy key, so no real call is possible
//
// Prints PASS/FAIL per check and exits 1 if any check fails. Skips (exit 0) with a clear message if Chrome, the key
// (full run only), the built frontend or a free port is missing. Screenshots go to scripts/e2e/out/ (git-ignored).
import path from 'node:path'
import { PORTS, createChecks, makePaper, mkTmp, openBrowser, preflight, startBackend, startFrontend, stopAll, until, up } from './lib.mjs'

const offline = process.argv.includes('--offline')
const { chrome } = await preflight({ needKey: !offline })
const ACKS = ['Got it.', 'Okay, noted.', 'Noted.', 'Understood.', 'Alright.', 'Thanks.']
const BASE = ['Review draft', 'Attach paper', 'Send']
const FRONT = `http://localhost:${PORTS.frontend}/`
const t = createChecks()
const tmp = mkTmp()
let b

const ackOf = text => ACKS.find(a => text.startsWith(a + '\n\n')) || ''
const claimsCapture = text => text.split(/(?<=[.!?])\s+|\n+/).some(s => /\b(added|saved|captured|recorded)\b/i.test(s) && !/\?|want me|can add|could add/i.test(s))
const notes = () => b.cdp.eval(`fetch('http://127.0.0.1:${PORTS.backend}/notes/' + localStorage.getItem('copilot.paper_id')).then(r => r.json()).then(n => n.map(x => x.text))`)

try {
  const pdf = makePaper(path.join(tmp, 'paper.pdf'))
  startFrontend()
  await until(() => up(FRONT), 20000, 'the frontend preview server')
  b = await openBrowser(chrome, tmp)

  // 1. backend down: one plain sentence, only the three always-visible buttons
  await b.goto(FRONT)
  await until(async () => (await b.msgs()).length > 0, 10000, 'the first message')
  const down = await b.msgs()
  t.check(down.length === 1 && /can't reach the server/i.test(down[0].text), 'backend down: one plain sentence in the thread', JSON.stringify(down))
  t.check(JSON.stringify(await b.buttons()) === JSON.stringify(BASE), 'only Review draft, Attach paper and Send are visible', JSON.stringify(await b.buttons()))
  await b.shot('01_backend_down')

  // 2. start the backend; sending again retries
  startBackend(tmp, offline ? { OPENROUTER_API_KEY: 'offline-no-model', MODEL: 'offline' } : {})
  await until(() => up(`http://127.0.0.1:${PORTS.backend}/config`), 40000, 'the backend')
  await b.cdp.eval(`document.querySelector('button[aria-label=Send]').click()`)
  await b.waitMsg('papers have you reviewed')
  const retried = await b.msgs()
  t.check(retried.length === 1 && !/reach the server/.test(retried[0].text), 'pressing Send retries; the error sentence is replaced by the first question')
  await b.shot('02_first_question')

  // 3. onboarding in the thread: a brief acknowledgement after a real answer, none after a skip
  const first = (await b.say('7 papers'))[0].text
  const second = (await b.say('it is my own area'))[0].text
  t.check(ACKS.includes(ackOf(first)) && first.includes('familiar'), 'a real answer is acknowledged, then the next question', first.slice(0, 80))
  t.check(ACKS.includes(ackOf(second)) && ackOf(first) !== ackOf(second), 'the next acknowledgement is different', `${ackOf(first)} / ${ackOf(second)}`)
  const skipped = (await b.say('idk'))[0].text
  t.check(ackOf(skipped) === '' && /read the paper on your own/i.test(skipped), 'a skipped answer gets no acknowledgement', skipped.slice(0, 80))
  const off = (await b.say('banana'))[0].text
  t.check(ackOf(off) === '' && /which|what|how/i.test(off), 'an off-topic reply gets a follow-up, not an acknowledgement', off.slice(0, 80))
  for (let i = 0; i < 14; i++) {
    if ((await b.msgs()).some(m => m.text.includes('Attach the paper'))) break
    await b.say('idk')
  }
  await b.waitMsg('Attach the paper')
  t.check(true, 'onboarding closed and the thread asks for the paper')
  await b.shot('03_attach_the_paper')

  // 4. attach through the paperclip's file input
  await b.attach(pdf)
  await b.waitMsg('Got the paper', 60000)
  t.check(true, 'the paper was uploaded and the thread switched to chat')
  await b.shot('04_paper_attached')

  if (!offline) {
    // 5. chat with the real model
    const reply = (await b.say('which datasets do they use?')).at(-1).text
    t.check(reply.length > 0 && !/couldn't put together a reply/.test(reply), 'a chat reply arrived and was not the fallback', reply.slice(0, 100))
    await b.shot('05_chat_reply')

    // 6. a stated view: the assistant must never say it was captured unless it was
    const view = 'I think five participants per region seems low'
    const r1 = (await b.say(view)).at(-1).text
    const n1 = await notes()
    t.check(!(claimsCapture(r1) && n1.length === 0), 'a stated view: no claim of a capture that did not happen', r1.slice(0, 160))
    if (/(?:want|would you like) me to add|(?:shall|should) i add/i.test(r1)) {
      await b.say('yes')
      const n2 = await notes()
      t.check(n2.some(x => view.toLowerCase().includes(x.toLowerCase().slice(0, 20))), 'after "yes" the offered view is in the draft', JSON.stringify(n2))
    } else {
      t.note('the model made no capture offer this time (it varies); nothing to confirm')
    }
  }

  // 7. the draft panel: the only new buttons are Copy all; paragraphs are editable text
  await b.cdp.eval(`document.querySelector('.ca-toggle').click()`)
  await until(() => b.cdp.eval(`!!document.querySelector('.ca-panel') && document.querySelectorAll('.ca-section').length > 0`), 15000, 'the draft panel')
  await b.shot('06_draft_panel')
  t.check(JSON.stringify(await b.buttons()) === JSON.stringify([...BASE, 'Copy all']), 'the panel adds one button, Copy all', JSON.stringify(await b.buttons()))
  if (await b.cdp.eval(`!!document.querySelector('.ca-para')`)) {
    await b.cdp.eval(`(() => { const p = document.querySelector('.ca-para'); p.focus(); p.select() })()`)
    await b.cdp.send('Input.insertText', { text: 'five participants per region seems low (edited in the panel)' })
    await b.cdp.eval(`document.querySelector('textarea[aria-label=Message]').focus()`)         // leaving the paragraph saves it
    await until(async () => (await notes()).some(x => x.includes('edited in the panel')), 8000, 'the edit to reach the server')
    t.check(true, 'an edit in the panel was saved to the server')
  }
  await b.cdp.eval(`document.querySelector('.ca-copy').click()`)
  await until(() => b.cdp.eval(`document.querySelector('.ca-copy').textContent === 'Copied'`), 4000, 'the copy button to say Copied')
  t.check(true, 'Copy all works (the label becomes "Copied")')
  await b.shot('07_after_edit_and_copy')

  // 8. a novice: walkthrough and criteria chips
  await b.cdp.eval(`localStorage.clear()`)
  await b.goto(FRONT)
  await b.waitMsg('papers have you reviewed')
  for (const a of ['0', 'new to me', 'abstract', 'alone', 'after I read it', 'pdf']) await b.say(a)
  await until(() => b.cdp.eval(`document.querySelectorAll('.ca-chip').length > 0`), 15000, 'the criteria chips')
  const all = await b.msgs()
  t.check(all.some(m => /review form has \d+ parts/.test(m.text)), 'a novice sees a short walkthrough of the form')
  const chips = await b.cdp.eval(`[...document.querySelectorAll('.ca-chip')].map(c => c.textContent)`)
  t.check(chips.at(-1) === 'Other, in my words' && chips.length >= 3, 'chips: the criteria, then "Other, in my words" last', JSON.stringify(chips))
  await b.cdp.eval(`document.querySelectorAll('.ca-chip')[0].click(); document.querySelectorAll('.ca-chip')[1].click()`)
  const box = await b.cdp.eval(`document.querySelector('textarea[aria-label=Message]').value`)
  t.check(box === `${chips[0]}, ${chips[1]}`, 'picking chips fills the text box', box)
  await b.shot('08_novice_chips')
  await b.resize(390, 800, true, 2)
  await new Promise(r => setTimeout(r, 400))
  await b.shot('09_narrow_screen')
  await b.resize(1280, 860)

  // 9. the old flow, only through ?mode=guided
  await b.goto(FRONT + '?mode=guided')
  await until(() => b.cdp.eval(`document.body.innerText.includes('Upload paper')`), 15000, 'the old flow')
  t.check(!(await b.cdp.eval(`!!document.querySelector('.ca-root')`)), '?mode=guided shows the old flow and not the chat screen')
  await b.shot('10_guided_old_flow')

  t.check(b.cdp.exceptions.length === 0, 'no uncaught exceptions in the page', b.cdp.exceptions.join(' | '))
} catch (e) {
  t.check(false, 'the run completed', e.message)
  try { if (b) await b.shot('zz_failure') } catch { /* no browser */ }
} finally {
  stopAll()
}
process.exitCode = t.summary() ? 0 : 1
