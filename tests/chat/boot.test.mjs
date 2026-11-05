// Item 5: a new boot id from GET /config clears the stored reviewer id and paper id; a PDF that is gone clears the paper id.
import test from 'node:test'
import assert from 'node:assert/strict'
import { syncBoot, BOOT_KEY } from '../../frontend/src/chat/boot.js'
import { createController, memoryStorage, COPY } from '../../frontend/src/chat/controller.js'
import { isMissingPdf } from '../../frontend/src/pdf/missing.js'

const cfg = boot_id => ({ ok: true, status: 200, data: { flow: 'chat', boot_id } })
const stored = () => { const s = memoryStorage(); s.set('copilot.reviewer_id', 'r-old'); s.set('copilot.paper_id', 'p-old'); return s }

test('the first time a boot id is seen it is remembered and nothing is cleared', () => {
  const s = stored()
  syncBoot(s, cfg('b1'))
  assert.equal(s.get(BOOT_KEY), 'b1')
  assert.equal(s.get('copilot.reviewer_id'), 'r-old')
  assert.equal(s.get('copilot.paper_id'), 'p-old')
})

test('the same boot id changes nothing', () => {
  const s = stored(); s.set(BOOT_KEY, 'b1')
  syncBoot(s, cfg('b1'))
  assert.equal(s.get('copilot.reviewer_id'), 'r-old')
  assert.equal(s.get('copilot.paper_id'), 'p-old')
})

test('a different boot id clears the reviewer id and the paper id and stores the new boot id', () => {
  const s = stored(); s.set(BOOT_KEY, 'b1')
  syncBoot(s, cfg('b2'))
  assert.equal(s.get('copilot.reviewer_id'), null)
  assert.equal(s.get('copilot.paper_id'), null)
  assert.equal(s.get(BOOT_KEY), 'b2')
})

test('no boot id (fresh mode off), an unreachable server or an odd answer never clears anything', () => {
  for (const r of [cfg(null), cfg(undefined), cfg(''), { ok: false, status: 0, data: null }, { ok: true, status: 200, data: {} }, undefined]) {
    const s = stored(); s.set(BOOT_KEY, 'b1')
    syncBoot(s, r)
    assert.equal(s.get('copilot.reviewer_id'), 'r-old')
    assert.equal(s.get('copilot.paper_id'), 'p-old')
    assert.equal(s.get(BOOT_KEY), 'b1')
  }
})

test('after a clear the controller starts as a brand new reviewer with no paper', () => {
  const s = stored(); s.set(BOOT_KEY, 'b1')
  syncBoot(s, cfg('b2'))
  const c = createController({ api: {}, storage: s, mint: () => 'r-new' })
  assert.equal(c.getState().reviewerId, 'r-new')
  assert.equal(c.getState().paperId, null)
})

// ------------------------------------------------------------------ the PDF is gone

test('what counts as a missing PDF', () => {
  assert.equal(isMissingPdf({ name: 'MissingPDFException' }), true)
  assert.equal(isMissingPdf({ status: 404 }), true)
  assert.equal(isMissingPdf(new Error('boom')), false)
  assert.equal(isMissingPdf(null), false)
})

test('a missing PDF while working on it after onboarding clears the stored paper id, goes back to attach and says so', async () => {
  const s = memoryStorage(); s.set('copilot.reviewer_id', 'r1'); s.set('copilot.paper_id', 'p1')
  const ok = data => ({ ok: true, status: 200, data })
  const api = { onboarding: async () => ok({ done: true }), thread: async () => ok([]), spans: async () => ok([]),
    open: async () => ok({ opened: false, messages: [] }) }
  const c = createController({ api, storage: s })
  await c.start()
  assert.equal(c.getState().stage, 'chat')
  assert.equal(c.getState().paperId, 'p1')
  c.paperMissing('p1')
  assert.equal(c.getState().stage, 'attach')
  assert.equal(s.get('copilot.paper_id'), null)
  assert.equal(c.getState().paperId, null)
  assert.equal(c.getState().focus, null)
  assert.equal(c.getState().messages.at(-1).text, COPY.paperGone)
  assert.equal(s.get('copilot.reviewer_id'), 'r1')                            // the reviewer is kept
})

test('a missing PDF for a paper that is no longer the current one is ignored', () => {
  const s = memoryStorage(); s.set('copilot.paper_id', 'p2')
  const c = createController({ api: {}, storage: s })
  c.paperMissing('p1')
  assert.equal(c.getState().paperId, 'p2')
  assert.equal(s.get('copilot.paper_id'), 'p2')
})

// The real session: a stale paper id was still stored when onboarding started. The PDF pane tried to load it, the
// file was gone, and the first thing in the thread was "I can't find that paper any more. Attach it again."
test('a stale paper id at the start of onboarding is cleared silently', async () => {
  const s = memoryStorage(); s.set('copilot.reviewer_id', 'r-80a6'); s.set('copilot.paper_id', 'stale-pid')
  const first = 'To start, roughly how many papers have you reviewed before? A number is fine, and zero is a fine answer.'
  const api = { onboarding: async () => ({ ok: true, status: 200, data: { done: false, field: 'papers_reviewed', question: first } }) }
  const c = createController({ api, storage: s })
  c.paperMissing('stale-pid')                   // the PDF pane can report before the first question arrives...
  await c.start()
  c.paperMissing('stale-pid')                   // ...or after it
  assert.equal(s.get('copilot.paper_id'), null)
  assert.equal(c.getState().paperId, null)
  assert.equal(c.getState().stage, 'onboarding')
  assert.deepEqual(c.getState().messages.map(m => m.text), [first])
})

test('a stale paper id found while onboarding is under way is cleared silently', () => {
  const s = memoryStorage(); s.set('copilot.paper_id', 'p1')
  const c = createController({ api: {}, storage: s })
  c.paperMissing('p1')                          // stage is still "boot"
  assert.equal(c.getState().paperId, null)
  assert.equal(c.getState().messages.length, 0)
})

test('a reload after onboarding whose PDF is gone before the onboarding status arrives still says so', async () => {
  const s = memoryStorage(); s.set('copilot.reviewer_id', 'r1'); s.set('copilot.paper_id', 'p1')
  const c = createController({ api: { onboarding: async () => ({ ok: true, status: 200, data: { done: true } }) }, storage: s })
  c.paperMissing('p1')                          // stage "boot": not known yet whether they were working on it
  assert.equal(c.getState().messages.length, 0)
  await c.start()
  assert.equal(c.getState().stage, 'attach')
  assert.deepEqual(c.getState().messages.map(m => m.text), [COPY.paperGone])
})
