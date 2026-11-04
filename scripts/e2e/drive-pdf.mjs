// The PDF pane in a real browser: the PDF follows the conversation, using the real backend with a SCRIPTED model (no
// key, no network call; see scripted_backend.py).
//
//   node scripts/e2e/drive-pdf.mjs
//
// Prints PASS/FAIL per check, exits 1 on a failure, and skips (exit 0) with a reason if Chrome, the built frontend or a
// free port is missing. Screenshots go to scripts/e2e/out/ (git-ignored).
import path from 'node:path'
import { PORTS, createChecks, makePaper, mkTmp, openBrowser, preflight, sleep, startFrontend, startScriptedBackend, stopAll, until, up } from './lib.mjs'

const { chrome } = await preflight({ needKey: false })
const BASE = ['Review draft', 'Attach paper', 'Send']
const FRONT = `http://localhost:${PORTS.frontend}/`
const t = createChecks()
const tmp = mkTmp()
let b

const ev = e => b.cdp.eval(e)
const scrollTop = () => ev(`document.querySelector('.pdf-scroller').scrollTop`)
const hls = () => ev(`[...document.querySelectorAll('.pdf-hl')].map(h => { const p = h.closest('.pdf-page'); return { page: [...document.querySelectorAll('.pdf-page')].indexOf(p) + 1, w: h.offsetWidth, h: h.offsetHeight } })`)
const settle = async () => { await sleep(1200) }                               // a smooth scroll takes a moment
const lastReply = async () => (await b.msgs()).at(-1).text

try {
  const pdf = makePaper(path.join(tmp, 'long.pdf'), ['long'])
  startFrontend()
  await until(() => up(FRONT), 20000, 'the frontend preview server')
  startScriptedBackend(tmp)
  await until(() => up(`http://127.0.0.1:${PORTS.backend}/config`), 40000, 'the backend')
  b = await openBrowser(chrome, tmp, { width: 1366, height: 768 })        // a laptop screen

  // onboarding, skipped quickly
  await b.goto(FRONT)
  await b.waitMsg('papers have you reviewed')
  for (let i = 0; i < 16; i++) {
    if ((await b.msgs()).some(m => m.text.includes('Attach the paper'))) break
    await b.say('idk')
  }
  await b.waitMsg('Attach the paper')

  // 1. before a paper is attached: the centered chat, no PDF pane
  t.check(await ev(`!document.querySelector('.ca-pdf') && !document.querySelector('.ca-with-pdf')`), 'before a paper is attached there is no PDF pane')
  const colBefore = await ev(`(() => { const r = document.querySelector('.ca-column').getBoundingClientRect(); const w = document.querySelector('.ca-thread').clientWidth; return [Math.round(r.left), Math.round(w - r.right)] })()`)
  t.check(Math.abs(colBefore[0] - colBefore[1]) <= 2, 'the chat column is centered', JSON.stringify(colBefore))
  await b.shot('p01_before_attach')

  // 2. attach: PDF on the left, chat on the right
  await b.attach(pdf)
  await b.waitMsg('Got the paper', 60000)
  await until(() => ev(`document.querySelectorAll('.pdf-page').length === 4`), 20000, 'four pages of the PDF')
  await until(() => ev(`[...document.querySelectorAll('.pdf-page canvas')].some(c => c.width > 0)`), 20000, 'a page to be drawn')
  const lay = await ev(`(() => { const r = s => document.querySelector(s).getBoundingClientRect(); const p = r('.ca-pdf'), m = r('.ca-main'); return { pdfL: p.left, pdfR: p.right, mainL: m.left, mainR: m.right, w: innerWidth } })()`)
  t.check(lay.pdfL === 0 && lay.pdfR <= lay.mainL + 1 && lay.pdfR > 400 && lay.mainR >= lay.w - 1, 'after upload the PDF is on the left and the chat on the right', JSON.stringify(lay))
  t.check(lay.mainR - lay.mainL >= 600, 'the chat column is still usable on a laptop screen', `${lay.mainR - lay.mainL}px wide`)
  const fit = await ev(`(() => { const s = document.querySelector('.pdf-scroller'); const p = document.querySelector('.pdf-page').getBoundingClientRect(); return { sw: s.scrollWidth, cw: s.clientWidth, pageW: Math.round(p.width) } })()`)
  t.check(fit.sw <= fit.cw, 'the PDF fits the pane with no sideways scroll', JSON.stringify(fit))
  t.check(JSON.stringify(await b.buttons()) === JSON.stringify(BASE), 'no new buttons or toggles: only Review draft, Attach paper and Send', JSON.stringify(await b.buttons()))
  t.check((await hls()).length === 0, 'nothing is highlighted before a reply cites something')
  await b.shot('p02_attached_laptop')

  // 3. a reply that cites nothing does not move the PDF
  await b.say('hello there')
  t.check((await scrollTop()) === 0 && (await hls()).length === 0, 'a reply that cites nothing leaves the PDF where it was, with no highlight')

  // 4. a reply that cites a passage: pointer text, scroll to it, one highlight
  const reply = (await b.say('where do they report accuracy?')).at(-1).text
  t.check(/\(Section 3\)/.test(reply) && !/\[|p\d+-s\d+/.test(reply), 'the reply shows "(Section 3)" and no marker or id', reply)
  await settle()
  const h1 = await hls()
  t.check(h1.length === 1 && h1[0].page === 4 && h1[0].w > 20 && h1[0].h > 5, 'exactly the cited passage is highlighted, on page 4', JSON.stringify(h1))
  const top1 = await scrollTop()
  t.check(top1 > 500, 'the PDF scrolled down to page 4', `scrollTop ${top1}`)
  const vis = await ev(`(() => { const h = document.querySelector('.pdf-hl').getBoundingClientRect(), s = document.querySelector('.pdf-scroller').getBoundingClientRect(); return h.top >= s.top && h.bottom <= s.bottom })()`)
  t.check(vis, 'the highlighted passage is inside the visible part of the pane')
  const colour = await ev(`getComputedStyle(document.querySelector('.pdf-hl')).backgroundColor`)
  t.check(/rgba\(255, 214, 102/.test(colour), 'the highlight is the one neutral colour', colour)
  const cite = await ev(`(() => { const c = document.querySelector('.ca-cite'); return c ? { tag: c.tagName, text: c.textContent, cursor: getComputedStyle(c).cursor, bg: getComputedStyle(c).backgroundColor } : null })()`)
  t.check(cite && cite.tag === 'SPAN' && cite.text === '(Section 3)', 'the pointer in the reply is plain text (a span, not a button)', JSON.stringify(cite))
  await b.shot('p03_cited_scrolled')

  // 5. a reply that cites nothing, after one that did: the PDF stays exactly where it is
  await b.say('thanks')
  t.check((await scrollTop()) === top1 && (await hls()).length === 1, 'a later reply that cites nothing does not move the PDF or change the highlight')

  // 6. an unknown id is dropped without a trace; a gap report and a draft cite nothing
  const ghost = (await b.say('where is the ghost section?')).at(-1).text
  t.check(!/p9-s99|\[|\(Section/.test(ghost) && (await scrollTop()) === top1 && (await hls()).length === 1, 'an id the paper does not have: no text, no scroll, no new highlight', ghost)
  await b.say("what's missing?")
  t.check((await scrollTop()) === top1 && (await hls()).length === 1, 'a gap report does not move the PDF')

  // 7. clicking a pointer brings the highlight back
  await ev(`document.querySelector('.pdf-scroller').scrollTo({ top: 0 })`)
  await settle()
  t.check((await scrollTop()) === 0, 'scrolled back to the top by hand')
  await ev(`[...document.querySelectorAll('.ca-cite')].at(0).click()`)
  await settle()
  const top2 = await scrollTop()
  t.check(Math.abs(top2 - top1) < 4 && (await hls()).length === 1, 'clicking the pointer in a reply scrolls back to its highlight', `${top2} vs ${top1}`)

  // 8. two cited passages: both highlighted, scrolled to the first
  await b.say('how is the training set up?')
  await settle()
  const h2 = await hls()
  t.check(h2.length === 2 && h2.map(h => h.page).join() === '1,1', 'two cited passages are both highlighted (and nothing else)', JSON.stringify(h2))
  t.check((await scrollTop()) < 200, 'the PDF scrolled to the first cited passage (page 1)', `scrollTop ${await scrollTop()}`)
  const pointer = (await lastReply()).match(/\(Sections? [^)]*\)/g)
  t.check(pointer && pointer.length >= 1 && !/\[|p\d+-s\d+/.test(await lastReply()), 'pointers read as plain text', await lastReply())
  await b.shot('p04_two_highlights')

  // 9. selecting text in the PDF puts it in the text box as a quotation
  await b.say('where do they report accuracy?')
  await settle()
  const r = await ev(`(() => { const h = document.querySelector('.pdf-hl').getBoundingClientRect(); return { x0: h.left + 2, y0: h.top + 1, x1: h.right - 2, y1: h.bottom - 1 } })()`)
  const m = (type, x, y) => b.cdp.send('Input.dispatchMouseEvent', { type, x, y, button: 'left', buttons: type === 'mouseReleased' ? 0 : 1, clickCount: 1 })
  await m('mouseMoved', r.x0, r.y0); await m('mousePressed', r.x0, r.y0)
  await m('mouseMoved', (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2); await m('mouseMoved', r.x1, r.y1)
  const dragBox = await ev(`!!document.querySelector('.pdf-drag')`)
  await b.shot('p05_dragging')
  await m('mouseReleased', r.x1, r.y1)
  t.check(dragBox, 'a rectangle shows while dragging on the page')
  await until(() => ev(`document.querySelector('textarea[aria-label=Message]').value.includes('Table 2')`), 8000, 'the selection to reach the text box')
  const box = await ev(`document.querySelector('textarea[aria-label=Message]').value`)
  t.check(/^“Table 2 reports accuracy/.test(box) && box.endsWith('” '), 'the selected text is in the text box as a quotation', JSON.stringify(box))
  await ev(`(() => { const a = document.querySelector('textarea[aria-label=Message]'); const set = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set; set.call(a, ''); a.dispatchEvent(new Event('input', { bubbles: true })) })()`)

  // 10. dragging over empty page area finds no text: quiet
  const before = (await b.msgs()).length
  await m('mouseMoved', 200, 700); await m('mousePressed', 200, 700); await m('mouseMoved', 300, 740); await m('mouseReleased', 300, 740)
  await sleep(800)
  const emptyBox = await ev(`document.querySelector('textarea[aria-label=Message]').value`)
  t.check(emptyBox === '' && (await b.msgs()).length === before, 'a box over nothing readable changes nothing and shows no error')

  // 11. the draft panel is still a toggle, and opens over the chat without squeezing the PDF
  const pdfW = await ev(`document.querySelector('.ca-pdf').getBoundingClientRect().width`)
  await ev(`document.querySelector('.ca-toggle').click()`)
  await until(() => ev(`!!document.querySelector('.ca-panel')`), 10000, 'the draft panel')
  const pan = await ev(`(() => { const p = document.querySelector('.ca-panel').getBoundingClientRect(), v = document.querySelector('.ca-pdf').getBoundingClientRect(); return { pdfW: v.width, panL: p.left, pdfR: v.right, panR: p.right, w: innerWidth, top: p.top } })()`)
  t.check(Math.abs(pan.pdfW - pdfW) < 1 && pan.panL >= pan.pdfR - 1 && pan.panR <= pan.w + 1, 'the draft panel opens over the chat; the PDF keeps its width', JSON.stringify(pan))
  t.check(await ev(`document.querySelector('.ca-toggle').getBoundingClientRect().bottom <= document.querySelector('.ca-panel').getBoundingClientRect().top + 1`), 'the Review draft toggle stays visible above the panel')
  await b.shot('p06_draft_panel_open')
  await ev(`document.querySelector('.ca-toggle').click()`)

  // 12. reload: the pointers are still there and still work
  await b.goto(FRONT)
  await until(() => ev(`document.querySelectorAll('.ca-cite').length > 0 && document.querySelectorAll('.pdf-page').length === 4`), 20000, 'the thread and the PDF to reload')
  t.check((await hls()).length === 0, 'after a reload nothing is highlighted until a pointer is clicked')
  await ev(`[...document.querySelectorAll('.ca-cite')].at(-1).click()`)
  await until(async () => (await hls()).length > 0, 8000, 'a highlight after clicking a pointer')
  t.check(true, 'after a reload a pointer in an earlier reply still brings back its highlight')
  await b.shot('p07_after_reload')

  // 13. a narrow window: chat only
  await b.resize(780, 800)
  await sleep(500)
  t.check(await ev(`getComputedStyle(document.querySelector('.ca-pdf')).display === 'none'`), 'on a narrow window the PDF pane steps aside and the chat stays')
  await b.shot('p08_narrow')
  await b.resize(1366, 768)

  t.check(b.cdp.exceptions.length === 0, 'no uncaught exceptions in the page', b.cdp.exceptions.join(' | '))
} catch (e) {
  t.check(false, 'the run completed', e.message)
  try { if (b) await b.shot('zz_pdf_failure') } catch { /* no browser */ }
} finally {
  stopAll()
}
process.exitCode = t.summary() ? 0 : 1
