// The opening turn in the controller: the app speaks first once a paper is attached and onboarding is closed.
import test from 'node:test'
import assert from 'node:assert/strict'
import { createController, memoryStorage, COPY } from '../../frontend/src/chat/controller.js'
import { createApi } from '../../frontend/src/chat/api.js'

const ok = data => ({ ok: true, status: 200, data })
const DONE = { done: true, reason: 'complete', turn: 12 }
const step = q => ({ done: false, field: 'x', kind: 'question', question: q, turn: 0, max_turns: 14 })
const PDF = { name: 'paper.pdf', type: 'application/pdf' }

function fakeApi(script = {}) {
  const calls = []
  const next = (name, ...args) => {
    calls.push([name, ...args])
    const q = script[name] || []
    const r = q.length > 1 ? q.shift() : q[0]
    return Promise.resolve(typeof r === 'function' ? r(...args) : r)
  }
  return { api: new Proxy({}, { get: (_, name) => (...args) => next(name, ...args) }), calls }
}
const make = (script, storage = memoryStorage()) => {
  const { api, calls } = fakeApi(script)
  return { c: createController({ api, storage, mint: () => 'r-test' }), calls, storage }
}
const texts = c => c.getState().messages.map(m => m.text)

const SPANS = [{ id: 's1', page: 1, bbox: [10, 10, 100, 40], section: 'Abstract' }]
const summary = { kind: 'summary', reply: 'The authors report X (Abstract).', cites: SPANS, parts: [
  { text: 'The authors report X ', cite: null }, { text: '(Abstract)', cite: ['s1'] }, { text: '.', cite: null }] }

test('api.open posts the reviewer id to /chat/{pid}/open', async () => {
  const seen = []
  const api = createApi((url, init) => { seen.push([url, init]); return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) }) })
  await api.open('p1', 'r1')
  assert.match(seen[0][0], /\/chat\/p1\/open$/)
  assert.deepEqual(JSON.parse(seen[0][1].body), { reviewer_id: 'r1' })
})

test('attaching the paper after onboarding asks the backend to open, and shows what it says instead of the stock line', async () => {
  const { c, calls } = make({ onboarding: [ok(DONE)], upload: [ok({ paper_id: 'p1' })],
    open: [ok({ opened: true, messages: [summary] })], spans: [ok(SPANS)] })
  await c.start()
  await c.attach(PDF)
  assert.deepEqual(calls.find(x => x[0] === 'open'), ['open', 'p1', 'r-test'])
  const t = texts(c)
  assert.ok(t.includes('The authors report X (Abstract).'))
  assert.ok(!t.includes(COPY.gotPaper))
  const m = c.getState().messages.at(-1)
  assert.equal(m.parts.length, 3)                                      // the pointer is kept
  assert.deepEqual(c.getState().focus.items.map(i => i.id), ['s1'])    // and the PDF goes to what the summary cites
})

test('when the backend has nothing to say the stock "Got the paper" line stays', async () => {
  const { c } = make({ onboarding: [ok(DONE)], upload: [ok({ paper_id: 'p1' })], open: [ok({ opened: false, messages: [] })] })
  await c.start()
  await c.attach(PDF)
  assert.ok(texts(c).includes(COPY.gotPaper))
})

test('a failed open call is quiet: the stock line, no error message', async () => {
  const { c } = make({ onboarding: [ok(DONE)], upload: [ok({ paper_id: 'p1' })],
    open: [{ ok: false, status: 0, data: null }] })
  await c.start()
  await c.attach(PDF)
  assert.ok(texts(c).includes(COPY.gotPaper))
  assert.ok(!c.getState().messages.some(m => m.kind === 'error'))
})

test('a paper attached during onboarding is opened when onboarding closes', async () => {
  const { c, calls } = make({ onboarding: [ok(step('Q1'))], upload: [ok({ paper_id: 'p1' })],
    answer: [ok(DONE)], open: [ok({ opened: true, messages: [summary] })] })
  await c.start()
  await c.attach(PDF)
  assert.ok(!calls.some(x => x[0] === 'open'))                          // not before onboarding is done
  await c.send('7 papers')
  assert.deepEqual(calls.find(x => x[0] === 'open'), ['open', 'p1', 'r-test'])
  assert.ok(texts(c).includes('The authors report X (Abstract).'))
  assert.equal(c.getState().stage, 'chat')
})

test('a reload with a paper asks again; the backend answers "already" and the thread is not doubled', async () => {
  const storage = memoryStorage()
  storage.set('copilot.paper_id', 'p1')
  const { c, calls } = make({ onboarding: [ok(DONE)], thread: [ok([
    { kind: 'chat', role: 'assistant', text: 'The authors report X (Abstract).', meta: { opening: 'summary' } }])],
    open: [ok({ opened: false, messages: [], reason: 'already' })] }, storage)
  await c.start()
  assert.ok(calls.some(x => x[0] === 'open'))
  assert.deepEqual(texts(c), ['The authors report X (Abstract).'])
})
