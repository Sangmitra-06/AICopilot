// The chat-first conversation: onboarding in the thread, the 409 case, the switch to chat, and failure states.
import test from 'node:test'
import assert from 'node:assert/strict'
import { createController, memoryStorage, COPY } from '../../frontend/src/chat/controller.js'

// A scripted backend. Each method takes the next scripted response for that call, or the last one repeated.
const ok = data => ({ ok: true, status: 200, data })
const status = (s, data) => ({ ok: false, status: s, data })
const down = { ok: false, status: 0, data: null, error: 'TypeError: Failed to fetch' }
const step = (question, extra = {}) => ({ done: false, field: 'x', kind: 'question', question, turn: 0, max_turns: 14, ...extra })
const DONE = { done: true, reason: 'complete', turn: 12 }

function fakeApi(script = {}) {
  const calls = []
  const next = (name, ...args) => {
    calls.push([name, ...args])
    const q = script[name] || []
    const r = q.length > 1 ? q.shift() : q[0]
    return Promise.resolve(typeof r === 'function' ? r(...args) : r)
  }
  const api = new Proxy({}, { get: (_, name) => (...args) => next(name, ...args) })
  return { api, calls }
}

const texts = c => c.getState().messages.map(m => `${m.role[0]}:${m.text}`)
const make = (script, storage = memoryStorage()) => {
  const { api, calls } = fakeApi(script)
  return { c: createController({ api, storage, mint: () => 'r-test' }), calls, storage }
}

// ------------------------------------------------------------------ onboarding in the thread

test('a new reviewer starts with the backend\'s first question as an assistant message', async () => {
  const { c, calls } = make({ onboarding: [ok(step('How many papers have you reviewed?'))] })
  await c.start()
  assert.equal(c.getState().stage, 'onboarding')
  assert.deepEqual(texts(c), ['a:How many papers have you reviewed?'])
  assert.deepEqual(calls[0], ['onboarding', 'r-test'])
})

test('a reply is sent to the answer endpoint and the next question follows it', async () => {
  const { c, calls } = make({ onboarding: [ok(step('Q1'))], answer: [ok(step('Q2'))] })
  await c.start()
  const r = await c.send('  7 papers ')
  assert.deepEqual(r, { clear: true })
  assert.deepEqual(calls.at(-1), ['answer', 'r-test', '7 papers'])
  assert.deepEqual(texts(c), ['a:Q1', 'u:7 papers', 'a:Q2'])
  assert.equal(c.getState().stage, 'onboarding')
})

test('a novice walkthrough is shown once, before the question, and the criteria menu becomes chips', async () => {
  const menu = [{ id: 'soundness', label: 'Soundness' }, { id: 'other', label: 'Other, in my words' }]
  const { c } = make({
    onboarding: [ok(step('What counts as a strength?', { walkthrough: { text: 'The form has 10 parts.' }, menu }))],
    answer: [ok(step('And a weakness?'))],
  })
  await c.start()
  assert.deepEqual(texts(c), ['a:The form has 10 parts.', 'a:What counts as a strength?'])
  assert.deepEqual(c.getState().menu, menu)
  await c.send('Soundness')
  assert.equal(c.getState().menu, null)                       // chips go away once answered
  assert.deepEqual(texts(c).slice(-1), ['a:And a weakness?'])
})

test('without a menu there are no chips', async () => {
  const { c } = make({ onboarding: [ok(step('Q1'))] })
  await c.start()
  assert.equal(c.getState().menu, null)
})

test('starting twice (a double mount) does not repeat the question', async () => {
  const { c } = make({ onboarding: [ok(step('Q1'))] })
  await Promise.all([c.start(), c.start()])
  assert.deepEqual(texts(c), ['a:Q1'])
})

test('reloading mid-onboarding shows the pending question once', async () => {
  const { c } = make({ onboarding: [ok(step('Q1'))] })
  await c.start()
  await c.start()
  assert.deepEqual(texts(c), ['a:Q1'])
})

// ------------------------------------------------------------------ acknowledgements

test('the backend\'s acknowledgement leads the next question, in one message', async () => {
  const { c } = make({ onboarding: [ok(step('Q1'))], answer: [ok(step('Q2', { ack: 'Got it.' }))] })
  await c.start()
  await c.send('7 papers')
  assert.deepEqual(texts(c), ['a:Q1', 'u:7 papers', 'a:Got it.\n\nQ2'])
})

test('no acknowledgement, no change: a skip or an off-topic reply shows just the question', async () => {
  const { c } = make({ onboarding: [ok(step('Q1'))], answer: [ok(step('Q2', { ack: '' })), ok(step('Q3'))] })
  await c.start()
  await c.send('idk')
  await c.send('banana')
  assert.deepEqual(texts(c), ['a:Q1', 'u:idk', 'a:Q2', 'u:banana', 'a:Q3'])
})

test('with a walkthrough the acknowledgement leads the walkthrough and the question stays its own message', async () => {
  const { c } = make({ onboarding: [ok(step('Q1'))],
    answer: [ok(step('Reading order?', { ack: 'Thanks.', walkthrough: { text: 'The form has 10 parts.' } }))] })
  await c.start()
  await c.send('new to me')
  assert.deepEqual(texts(c).slice(-2), ['a:Thanks.\n\nThe form has 10 parts.', 'a:Reading order?'])
})

test('the acknowledgement of the last answer leads the request for the paper', async () => {
  const { c } = make({ onboarding: [ok(step('Q12'))], answer: [ok({ ...DONE, ack: 'Noted.' })] })
  await c.start()
  await c.send('x')
  assert.equal(texts(c).at(-1), 'a:Noted.\n\n' + COPY.askAttach)
})

test('a 409 shows the current question plainly: the backend sends no acknowledgement with it', async () => {
  const { c } = make({ onboarding: [ok(step('Q1', { ack: '' }))], answer: [status(409, step('Q1', { ack: '' }))] })
  await c.start()
  await c.send('7 papers')
  assert.deepEqual(texts(c), ['a:Q1', 'a:Q1'])
})

test('a reload shows the pending question with no acknowledgement', async () => {
  const { c } = make({ onboarding: [ok(step('Q3', { ack: '' }))] })
  await c.start()
  assert.deepEqual(texts(c), ['a:Q3'])
})

// ------------------------------------------------------------------ the 409 case

test('on a 409 the returned current question is shown and the reply is not recorded', async () => {
  const body = { ...step('Q1'), error: 'no_question_pending', message: 'GET /onboarding first' }
  const { c } = make({ onboarding: [ok(step('Q1'))], answer: [status(409, body)] })
  await c.start()
  const r = await c.send('7 papers')
  assert.deepEqual(r, { clear: false })                       // the text stays in the box so it can be sent again
  assert.deepEqual(texts(c), ['a:Q1', 'a:Q1'])                // the question is shown again, the reply is not echoed
  assert.equal(c.getState().stage, 'onboarding')
})

test('a 409 carrying a different question shows that question', async () => {
  const { c } = make({ onboarding: [ok(step('Q1'))], answer: [status(409, { ...step('The real first question') })] })
  await c.start()
  await c.send('hello')
  assert.deepEqual(texts(c), ['a:Q1', 'a:The real first question'])
})

test('after a 409, sending again goes through', async () => {
  const { c } = make({ onboarding: [ok(step('Q1'))], answer: [status(409, step('Q1')), ok(step('Q2'))] })
  await c.start()
  await c.send('7 papers')
  const r = await c.send('7 papers')
  assert.deepEqual(r, { clear: true })
  assert.deepEqual(texts(c).slice(-2), ['u:7 papers', 'a:Q2'])
})

// ------------------------------------------------------------------ onboarding closes, then chat

test('when onboarding closes the next message asks for the paper', async () => {
  const { c } = make({ onboarding: [ok(step('Q12'))], answer: [ok(DONE)] })
  await c.start()
  await c.send('x')
  assert.equal(c.getState().stage, 'attach')
  assert.equal(texts(c).at(-1), 'a:' + COPY.askAttach)
  assert.match(COPY.askAttach, /Attach the paper/)
})

test('typing before the paper is attached gets a plain reminder and no backend call', async () => {
  const { c, calls } = make({ onboarding: [ok(DONE)] })
  await c.start()
  const n = calls.length
  await c.send('what does it say?')
  assert.equal(calls.length, n)
  assert.deepEqual(texts(c).slice(-2), ['u:what does it say?', 'a:' + COPY.attachFirst])
})

test('attaching the paper switches the thread to chat, and the next message goes to /chat/{pid}', async () => {
  const { c, calls, storage } = make({
    onboarding: [ok(DONE)], upload: [ok({ paper_id: 'p9', sections: [] })],
    chat: [ok({ mode: 'chat', reply: 'Table 2 reports accuracy.', draft_changed: false })],
  })
  await c.start()
  await c.attach({ name: 'paper.pdf', type: 'application/pdf' })
  assert.equal(c.getState().stage, 'chat')
  assert.equal(c.getState().paperId, 'p9')
  assert.equal(storage.get('copilot.paper_id'), 'p9')
  assert.equal(texts(c).at(-1), 'a:' + COPY.gotPaper)
  await c.send('which datasets?')
  assert.deepEqual(calls.at(-1), ['chat', 'p9', 'r-test', 'which datasets?'])
  assert.deepEqual(texts(c).slice(-2), ['u:which datasets?', 'a:Table 2 reports accuracy.'])
})

test('the last onboarding answer with the paper already attached goes straight to chat', async () => {
  const { c } = make({
    onboarding: [ok(step('Q12'))], answer: [ok(DONE)], upload: [ok({ paper_id: 'p9' })],
  })
  await c.start()
  await c.attach({ name: 'paper.pdf' })
  assert.equal(c.getState().stage, 'onboarding')              // the paper does not skip the questions
  assert.equal(texts(c).at(-1), 'a:' + COPY.gotPaperEarly)
  await c.send('x')
  assert.equal(c.getState().stage, 'chat')
  assert.equal(texts(c).at(-1), 'a:' + COPY.readyChat)
})

test('a reload after onboarding and upload restores the conversation from the thread', async () => {
  const storage = memoryStorage()
  storage.set('copilot.paper_id', 'p9')
  const turns = [
    { role: 'user', kind: 'chat', text: 'hi', meta: {} },
    { role: 'assistant', kind: 'chat', text: 'Hello.', meta: {} },
    { role: 'assistant', kind: 'explain', text: 'old guided flow turn', meta: {} },
    { role: 'user', kind: 'chat', text: 'an onboarding turn', meta: { onboarding: true } },
  ]
  const { c } = make({ onboarding: [ok(DONE)], thread: [ok(turns)] }, storage)
  await c.start()
  assert.equal(c.getState().stage, 'chat')
  assert.deepEqual(texts(c), ['u:hi', 'a:Hello.'])
})

test('a chat reply that says draft_changed bumps the draft version', async () => {
  const { c } = make({ onboarding: [ok(DONE)], upload: [ok({ paper_id: 'p9' })],
    chat: [ok({ mode: 'chat', reply: 'Added.', draft_changed: true })] })
  await c.start()
  await c.attach({ name: 'p.pdf' })
  const v = c.getState().draftVersion
  await c.send('yes')
  assert.equal(c.getState().draftVersion, v + 1)
})

test('if the backend says onboarding is not finished, the thread goes back to the questions', async () => {
  const menu = [{ id: 'soundness', label: 'Soundness' }]
  const { c } = make({ onboarding: [ok(DONE)], upload: [ok({ paper_id: 'p9' })],
    chat: [ok({ mode: 'onboarding', reply: 'How familiar are you with the subarea?', onboarding: { menu } })] })
  await c.start()
  await c.attach({ name: 'p.pdf' })
  await c.send('hi')
  assert.equal(c.getState().stage, 'onboarding')
  assert.deepEqual(c.getState().menu, menu)
})

// ------------------------------------------------------------------ failure states

const errors = c => c.getState().messages.filter(m => m.kind === 'error')

test('"Failed to fetch" on load puts one plain sentence in the thread; sending again retries', async () => {
  const { c, calls } = make({ onboarding: [down, ok(step('Q1'))] })
  await c.start()
  assert.equal(c.getState().stage, 'boot')
  assert.deepEqual(texts(c), ['a:' + COPY.unreachable])
  const r = await c.send('')                                  // even an empty send retries the load
  assert.deepEqual(r, { clear: false })
  assert.equal(c.getState().stage, 'onboarding')
  assert.deepEqual(texts(c), ['a:Q1'])                        // the error sentence is gone
  assert.equal(calls.filter(x => x[0] === 'onboarding').length, 2)
})

test('failing again does not pile up sentences', async () => {
  const { c } = make({ onboarding: [down] })
  await c.start()
  await c.send('hello')
  await c.send('hello')
  assert.equal(errors(c).length, 1)
})

test('a failed answer shows one sentence, keeps the text, and sending again retries it', async () => {
  const { c, calls } = make({ onboarding: [ok(step('Q1'))], answer: [down, ok(step('Q2'))] })
  await c.start()
  const bad = await c.send('7 papers')
  assert.deepEqual(bad, { clear: false })
  assert.deepEqual(texts(c), ['a:Q1', 'a:' + COPY.sendFailed])   // the unsent reply is not left in the thread
  const good = await c.send('7 papers')
  assert.deepEqual(good, { clear: true })
  assert.deepEqual(texts(c), ['a:Q1', 'u:7 papers', 'a:Q2'])
  assert.equal(calls.filter(x => x[0] === 'answer').length, 2)
})

test('a backend error (500) on an answer is the same one sentence, not a modal or a stack trace', async () => {
  const { c } = make({ onboarding: [ok(step('Q1'))], answer: [status(500, { detail: 'boom' })] })
  await c.start()
  await c.send('x')
  assert.deepEqual(errors(c).map(m => m.text), [COPY.sendFailed])
})

test('a failed chat message shows one sentence and retries on the next send', async () => {
  const { c, calls } = make({ onboarding: [ok(DONE)], upload: [ok({ paper_id: 'p9' })],
    chat: [down, ok({ mode: 'chat', reply: 'Here you go.' })] })
  await c.start()
  await c.attach({ name: 'p.pdf' })
  assert.deepEqual(await c.send('hi'), { clear: false })
  assert.equal(errors(c).length, 1)
  assert.deepEqual(await c.send('hi'), { clear: true })
  assert.equal(errors(c).length, 0)
  assert.equal(texts(c).at(-1), 'a:Here you go.')
  assert.equal(calls.filter(x => x[0] === 'chat').length, 2)
})

test('a failed upload shows one sentence; attaching again retries', async () => {
  const { c } = make({ onboarding: [ok(DONE)], upload: [down, ok({ paper_id: 'p9' })] })
  await c.start()
  await c.attach({ name: 'p.pdf' })
  assert.equal(c.getState().stage, 'attach')
  assert.deepEqual(errors(c).map(m => m.text), [COPY.uploadFailed])
  await c.attach({ name: 'p.pdf' })
  assert.equal(c.getState().stage, 'chat')
  assert.equal(errors(c).length, 0)
})

test('something that is not a PDF is refused with one sentence and no upload', async () => {
  const { c, calls } = make({ onboarding: [ok(DONE)] })
  await c.start()
  await c.attach({ name: 'notes.docx', type: 'application/msword' })
  assert.equal(calls.filter(x => x[0] === 'upload').length, 0)
  assert.deepEqual(errors(c).map(m => m.text), [COPY.notPdf])
})

test('a paper that is gone from the server asks for it to be attached again', async () => {
  const { c, storage } = make({ onboarding: [ok(DONE)], upload: [ok({ paper_id: 'p9' })], chat: [status(404, { detail: 'unknown paper' })] })
  await c.start()
  await c.attach({ name: 'p.pdf' })
  await c.send('hi')
  assert.equal(c.getState().stage, 'attach')
  assert.equal(c.getState().paperId, null)
  assert.equal(storage.get('copilot.paper_id'), null)
  assert.equal(texts(c).at(-1), 'a:' + COPY.paperGone)
})

test('a server running the old guided flow says so in one sentence', async () => {
  const { c } = make({ onboarding: [ok(DONE)], upload: [ok({ paper_id: 'p9' })],
    chat: [status(409, { error: 'chat_disabled', flow: 'guided' })] })
  await c.start()
  await c.attach({ name: 'p.pdf' })
  await c.send('hi')
  assert.equal(texts(c).at(-1), 'a:' + COPY.chatOff)
})

test('nothing is sent while another call is running', async () => {
  let release
  const { api, calls } = fakeApi({ onboarding: [ok(step('Q1'))], answer: [() => new Promise(r => { release = () => r(ok(step('Q2'))) })] })
  const c = createController({ api, storage: memoryStorage(), mint: () => 'r-test' })
  await c.start()
  const first = c.send('one')
  assert.deepEqual(await c.send('two'), { clear: false })
  release()
  await first
  assert.equal(calls.filter(x => x[0] === 'answer').length, 1)
})

// ------------------------------------------------------------------ the reviewer id

test('a reviewer id is made once and kept', () => {
  const storage = memoryStorage()
  const a = createController({ api: fakeApi().api, storage, mint: () => 'r-first' })
  const b = createController({ api: fakeApi().api, storage, mint: () => 'r-second' })
  assert.equal(a.getState().reviewerId, 'r-first')
  assert.equal(b.getState().reviewerId, 'r-first')
})

test('the default reviewer id is accepted by the backend\'s id rule', () => {
  const c = createController({ api: fakeApi().api })
  assert.match(c.getState().reviewerId, /^[A-Za-z0-9_-]{1,64}$/)
})
