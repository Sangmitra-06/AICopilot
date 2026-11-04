// Citations to highlights: the pure mapping (citeModel.js) and how the controller uses it. The PDF moves only when a
// reply cites something that can be located; unknown ids and unlocatable spans fail quietly.
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  locate, resolve, withCites, nextFocus, selectionFocus, scrollTarget, pieces, quoteInto,
} from '../../frontend/src/chat/citeModel.js'
import { createController, memoryStorage } from '../../frontend/src/chat/controller.js'

const span = (id, page, bbox = [50, 100, 300, 130], extra = {}) => ({ id, page, bbox, section: '4 Experiments', ...extra })
const BY = { s1: span('s1', 1), s4: span('s4', 4, [60, 200, 310, 240]), s7: span('s7', 7, [10, 10, 20, 20]) }

// ------------------------------------------------------------------ locate / resolve

test('a span with a page and a box can be located', () => {
  assert.deepEqual(locate(BY.s4), { id: 's4', page: 4, bbox: [60, 200, 310, 240] })
})

for (const [why, bad] of [
  ['no box', span('x', 2, null)], ['a box of the wrong length', span('x', 2, [1, 2, 3])],
  ['a NaN in the box', span('x', 2, [1, NaN, 3, 4])], ['a box with no area', span('x', 2, [10, 10, 10, 40])],
  ['an inverted box', span('x', 2, [30, 30, 10, 10])], ['no page', { id: 'x', bbox: [1, 1, 5, 5] }],
  ['page 0', span('x', 0)], ['a fractional page', span('x', 1.5)], ['a string page', span('x', '2')],
  ['null', null], ['a string', 'p1'],
]) test(`a span with ${why} cannot be located, quietly`, () => assert.equal(locate(bad), null))

test('resolve keeps the order cited, drops unknown ids and lists an id once', () => {
  assert.deepEqual(resolve(['s4', 'nope', 's1', 's4'], BY).map(h => h.id), ['s4', 's1'])
})

test('resolve with no ids, bad input or no spans is an empty list', () => {
  assert.deepEqual(resolve([], BY), [])
  assert.deepEqual(resolve(undefined, BY), [])
  assert.deepEqual(resolve('s1', BY), [])
  assert.deepEqual(resolve(['s1'], null), [])
  assert.deepEqual(resolve(['__proto__', 'constructor', 'toString'], BY), [])
})

test('a span that cannot be located is skipped and the others still show', () => {
  const by = { ...BY, bad: span('bad', 2, null) }
  assert.deepEqual(resolve(['bad', 's1'], by).map(h => h.id), ['s1'])
})

test('the highlights are copies: drawing never edits the span list', () => {
  const h = resolve(['s1'], BY)[0]
  h.bbox[0] = 999
  assert.equal(BY.s1.bbox[0], 50)
})

// ------------------------------------------------------------------ focus

test('citing a located span makes it the focus, scrolling to the first one cited', () => {
  const f = nextFocus(null, ['s4', 's1'], BY)
  assert.deepEqual(f.items.map(h => h.id), ['s4', 's1'])
  assert.deepEqual(scrollTarget(f), { page: 4, y: 200 })
})

test('a reply that cites nothing leaves the focus exactly as it was (the PDF does not move)', () => {
  const f = nextFocus(null, ['s1'], BY)
  assert.equal(nextFocus(f, [], BY), f)
  assert.equal(nextFocus(f, undefined, BY), f)
  assert.equal(nextFocus(null, [], BY), null)
})

test('a reply that cites only unknown or unlocatable spans leaves the focus as it was', () => {
  const f = nextFocus(null, ['s1'], BY)
  assert.equal(nextFocus(f, ['ghost'], BY), f)
  assert.equal(nextFocus(f, ['bad'], { bad: span('bad', 2, null) }), f)
  assert.equal(nextFocus(null, ['ghost'], BY), null)
})

test('citing the same spans again is a new focus, so the PDF scrolls back to them', () => {
  const a = nextFocus(null, ['s4'], BY)
  const b = nextFocus(a, ['s4'], BY)
  assert.notEqual(a, b)
  assert.equal(b.seq, a.seq + 1)
})

test('the focus holds only what was cited: a later citation replaces the earlier highlights', () => {
  const a = nextFocus(null, ['s1', 's4'], BY)
  const b = nextFocus(a, ['s7'], BY)
  assert.deepEqual(b.items.map(h => h.id), ['s7'])
})

test('the reviewer\'s own selection becomes the focus, and an unlocatable one changes nothing', () => {
  const f = nextFocus(null, ['s1'], BY)
  assert.deepEqual(selectionFocus(f, span('sel', 3)).items.map(h => h.id), ['sel'])
  assert.equal(selectionFocus(f, { id: 'sel', text: 'x' }), f)
  assert.equal(selectionFocus(null, null), null)
})

test('withCites adds the boxes a reply brought and keeps what was already known', () => {
  const by = withCites({ s1: BY.s1 }, [{ id: 's4', page: 4, bbox: [1, 2, 3, 4] }, null, {}])
  assert.deepEqual(Object.keys(by).sort(), ['s1', 's4'])
  assert.equal(withCites(BY, undefined).s1, BY.s1)
})

// ------------------------------------------------------------------ the pieces of a message

test('a message with pointers renders as plain text and clickable pointers that join to the text', () => {
  const m = { text: 'Table 2 has it (Section 4).', parts: [{ text: 'Table 2 has it ', cite: null }, { text: '(Section 4)', cite: ['s4'] }, { text: '.', cite: null }] }
  const p = pieces(m)
  assert.equal(p.map(x => x.text).join(''), m.text)
  assert.deepEqual(p.filter(x => x.cite).map(x => x.cite), [['s4']])
})

test('a message without parts, or with parts that do not match the text, is one plain piece', () => {
  assert.deepEqual(pieces({ text: 'Hello.' }), [{ text: 'Hello.', cite: null }])
  assert.deepEqual(pieces({ text: 'Hello.', parts: [{ text: 'Other', cite: ['s1'] }] }), [{ text: 'Hello.', cite: null }])
  assert.deepEqual(pieces({ text: 'Hello.', parts: [] }), [{ text: 'Hello.', cite: null }])
  assert.deepEqual(pieces({ text: 'Hello.', parts: [null] }), [{ text: 'Hello.', cite: null }])
})

// ------------------------------------------------------------------ quoting a selection into the text box

test('a selection is quoted into an empty box, ready for the reviewer to type after it', () => {
  assert.equal(quoteInto('', 'Accuracy of 71.2 on SST-2.'), '“Accuracy of 71.2 on SST-2.” ')
})

test('a selection goes after what the reviewer already typed, on its own line', () => {
  assert.equal(quoteInto('This part:  ', 'Accuracy\n of 71.2'), 'This part:\n“Accuracy of 71.2” ')
})

test('an empty selection leaves the box alone and a long one is cut at a word', () => {
  assert.equal(quoteInto('abc', '   '), 'abc')
  const q = quoteInto('', 'word '.repeat(300))
  assert.ok(q.length < 420 && q.includes('…”'))
})

// ------------------------------------------------------------------ the controller

const ok = data => ({ ok: true, status: 200, data })
function chatController({ chatReplies, spans = Object.values(BY), select } = {}) {
  const storage = memoryStorage()
  storage.set('copilot.paper_id', 'p1')
  const q = [...chatReplies]
  const calls = []
  const api = {
    onboarding: async () => ok({ done: true, reason: 'complete', turn: 12 }),
    thread: async () => ok([]),
    open: async () => ok({ opened: false, messages: [], reason: 'already' }),
    spans: async () => (spans === null ? { ok: false, status: 500, data: null } : ok(spans)),
    chat: async (...a) => { calls.push(a); return q.length > 1 ? q.shift() : q[0] },
    select: async (...a) => select(...a),
  }
  return { c: createController({ api, storage, mint: () => 'r1' }), calls }
}
const reply = (text, cites = [], parts) => ok({ mode: 'chat', reply: text, cites, parts: parts || null })

test('a reply that cites a span moves the PDF to it and highlights it', async () => {
  const { c } = chatController({ chatReplies: [reply('Table 2 has it (Section 4).', [{ id: 's4', page: 4, bbox: [60, 200, 310, 240] }])] })
  await c.start()
  assert.equal(c.getState().focus, null)                         // nothing is highlighted before a reply cites something
  await c.send('where is accuracy?')
  const f = c.getState().focus
  assert.deepEqual(f.items.map(h => h.id), ['s4'])
  assert.deepEqual(scrollTarget(f), { page: 4, y: 200 })
})

test('a reply that cites nothing does not move or change the PDF', async () => {
  const { c } = chatController({ chatReplies: [
    reply('Table 2 has it (Section 4).', [{ id: 's4', page: 4, bbox: [60, 200, 310, 240] }]),
    reply('Happy to help with that.', []),
    reply("Here's what the draft is missing.", undefined),
  ] })
  await c.start()
  await c.send('first')
  const before = c.getState().focus
  await c.send('second')
  await c.send('third')
  assert.equal(c.getState().focus, before)                       // the very same focus object: no scroll, no change
  assert.equal(c.getState().focus.seq, 1)
})

test('a reply that cites an id the paper does not have changes nothing', async () => {
  const { c } = chatController({ chatReplies: [reply('Somewhere.', [{ id: 'ghost' }])] })
  await c.start()
  await c.send('where?')
  assert.equal(c.getState().focus, null)
  assert.equal(c.getState().messages.at(-1).text, 'Somewhere.')  // and no error message
})

test('a cited span with no usable box fails quietly: no focus, no error in the thread', async () => {
  const { c } = chatController({ chatReplies: [reply('It is here (Section 4).', [{ id: 's9', page: 4, bbox: null }])] })
  await c.start()
  await c.send('where?')
  assert.equal(c.getState().focus, null)
  assert.ok(c.getState().messages.every(m => m.kind !== 'error'))
})

test('the reply\'s own boxes work even when the span list never loaded', async () => {
  const { c } = chatController({ spans: null, chatReplies: [reply('Here (Section 4).', [{ id: 's4', page: 4, bbox: [60, 200, 310, 240] }])] })
  await c.start()
  await c.send('where?')
  assert.deepEqual(c.getState().focus.items.map(h => h.id), ['s4'])
})

test('a reply keeps its pointers on the message so they can be clicked', async () => {
  const parts = [{ text: 'Here ', cite: null }, { text: '(Section 4)', cite: ['s4'] }, { text: '.', cite: null }]
  const { c } = chatController({ chatReplies: [reply('Here (Section 4).', [{ id: 's4', page: 4, bbox: [60, 200, 310, 240] }], parts)] })
  await c.start()
  await c.send('where?')
  assert.deepEqual(c.getState().messages.at(-1).parts, parts)
})

test('clicking a pointer re-focuses its spans, even after the PDF moved elsewhere', async () => {
  const { c } = chatController({ chatReplies: [
    reply('A (Section 4).', [{ id: 's4', page: 4, bbox: [60, 200, 310, 240] }]),
    reply('B (Section 1).', [{ id: 's1', page: 1, bbox: [50, 100, 300, 130] }]),
  ] })
  await c.start()
  await c.send('a')
  await c.send('b')
  assert.deepEqual(c.getState().focus.items.map(h => h.id), ['s1'])
  c.focusCite(['s4'])
  assert.deepEqual(c.getState().focus.items.map(h => h.id), ['s4'])
  c.focusCite(['ghost'])                                         // an unknown pointer: quiet, unchanged
  assert.deepEqual(c.getState().focus.items.map(h => h.id), ['s4'])
})

test('a drag on the PDF returns the text there and highlights what was selected', async () => {
  const seen = []
  const { c } = chatController({ chatReplies: [reply('x')], select: async (...a) => { seen.push(a); return ok({ kind: 'span', span: span('sel', 2, [10, 10, 100, 30], { text: 'Selected words.' }) }) } })
  await c.start()
  assert.equal(await c.selectRect(2, [10, 10, 100, 30]), 'Selected words.')
  assert.deepEqual(seen[0], ['p1', 2, [10, 10, 100, 30]])
  assert.deepEqual(c.getState().focus.items.map(h => h.id), ['sel'])
})

test('a drag over nothing readable, or a failed lookup, returns nothing and changes nothing', async () => {
  for (const answer of [ok({ kind: 'region' }), { ok: false, status: 500, data: null }, ok({ kind: 'span', span: { id: 'x', text: '' } })]) {
    const { c } = chatController({ chatReplies: [reply('x')], select: async () => answer })
    await c.start()
    assert.equal(await c.selectRect(1, [0, 0, 50, 50]), '')
    assert.equal(c.getState().focus, null)
  }
})

test('a reload brings back the pointers of earlier replies', async () => {
  const storage = memoryStorage(); storage.set('copilot.paper_id', 'p1')
  const parts = [{ text: 'Here ', cite: null }, { text: '(Section 4)', cite: ['s4'] }]
  const api = {
    onboarding: async () => ok({ done: true, reason: 'complete', turn: 12 }),
    thread: async () => ok([{ role: 'assistant', kind: 'chat', text: 'Here (Section 4)', meta: { cites: ['s4'], parts } }]),
    open: async () => ok({ opened: false, messages: [], reason: 'already' }),
    spans: async () => ok(Object.values(BY)),
  }
  const c = createController({ api, storage, mint: () => 'r1' })
  await c.start()
  assert.deepEqual(c.getState().messages[0].parts, parts)
  assert.equal(c.getState().focus, null)                         // history is shown, not scrolled to
  c.focusCite(['s4'])
  assert.deepEqual(c.getState().focus.items.map(h => h.id), ['s4'])
})
