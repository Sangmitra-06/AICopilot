// The review draft panel's data: sections, copy-all, and what an edit turns into. Plus the API client.
import test from 'node:test'
import assert from 'node:assert/strict'
import { buildSections, copyText, editEvent, hasContent, UNPLACED } from '../../frontend/src/chat/draftModel.js'
import { createApi } from '../../frontend/src/chat/api.js'

const CRIT = [
  { id: 'summary', name: 'Paper summary' }, { id: 'strengths', name: 'Summary of strengths' },
  { id: 'weaknesses', name: 'Summary of weaknesses' }, { id: 'ethics', name: 'Ethical concerns' },
]
const note = (id, field, text, extra = {}) => ({ id, field, text, ...extra })

test('every review-form section appears, in the form\'s order, even when empty', () => {
  const s = buildSections(CRIT, [], {})
  assert.deepEqual(s.map(x => x.id), ['summary', 'strengths', 'weaknesses', 'ethics'])
  assert.ok(s.every(x => x.items.length === 0))
})

test('notes are grouped under their section, in the reviewer\'s words', () => {
  const s = buildSections(CRIT, [note(1, 'weaknesses', 'Five participants per region seems low'), note(2, 'strengths', 'Clear dataset')], {})
  assert.deepEqual(s[2].items, [{ kind: 'note', id: 1, text: 'Five participants per region seems low' }])
  assert.deepEqual(s[1].items.map(i => i.text), ['Clear dataset'])
})

test('old single-letter fields map to their sections', () => {
  const s = buildSections(CRIT, [note(1, 'W', 'old weakness'), note(2, 'S', 'old strength')], {})
  assert.deepEqual([s[1].items[0].text, s[2].items[0].text], ['old strength', 'old weakness'])
})

test('a generated draft replaces the notes for that section only', () => {
  const draft = { weaknesses: { sentences: [{ text: 'I find the sample low.' }, { text: 'I would like variance.' }] } }
  const s = buildSections(CRIT, [note(1, 'weaknesses', 'raw note'), note(2, 'strengths', 'kept note')], draft)
  assert.deepEqual(s[2].items.map(i => [i.kind, i.idx, i.text]), [['sentence', 0, 'I find the sample low.'], ['sentence', 1, 'I would like variance.']])
  assert.deepEqual(s[1].items.map(i => i.kind), ['note'])
})

test('a blanked generated sentence disappears but the others keep their positions', () => {
  const draft = { weaknesses: { sentences: [{ text: 'one' }, { text: '' }, { text: 'three' }] } }
  const items = buildSections(CRIT, [], draft)[2].items
  assert.deepEqual(items.map(i => [i.idx, i.text]), [[0, 'one'], [2, 'three']])
})

test('notes outside the form land in one extra section at the end', () => {
  const s = buildSections(CRIT, [note(1, '', 'not sorted yet'), note(2, 'mystery', 'odd field')], {})
  assert.equal(s.at(-1).name, UNPLACED.name)
  assert.deepEqual(s.at(-1).items.map(i => i.text), ['not sorted yet', 'odd field'])
})

test('removed and empty notes are not shown', () => {
  const s = buildSections(CRIT, [note(1, 'weaknesses', 'gone', { removed: true }), note(2, 'weaknesses', '   ')], {})
  assert.equal(s[2].items.length, 0)
})

test('copy all: sections with content, headed by name, paragraphs apart; empty sections left out', () => {
  const s = buildSections(CRIT, [note(1, 'weaknesses', 'A'), note(2, 'weaknesses', 'B'), note(3, 'summary', 'S')], {})
  assert.equal(copyText(s), 'Paper summary\nS\n\nSummary of weaknesses\nA\n\nB')
  assert.equal(copyText(buildSections(CRIT, [], {})), '')
  assert.equal(hasContent(s[0]), true)
  assert.equal(hasContent(s[1]), false)
})

test('an edit to a note is a note_text_edited event; emptying it removes it', () => {
  const item = { kind: 'note', id: 7, text: 'old' }
  assert.deepEqual(editEvent(item, ' new '), { type: 'note_text_edited', payload: { id: 7, text: 'new' } })
  assert.deepEqual(editEvent(item, '  '), { type: 'note_removed', payload: { id: 7 } })
  assert.equal(editEvent(item, 'old'), null)
})

test('an edit to a generated sentence is a draft_edited event at its position', () => {
  const item = { kind: 'sentence', field: 'weaknesses', idx: 2, text: 'old' }
  assert.deepEqual(editEvent(item, 'new'), { type: 'draft_edited', payload: { field: 'weaknesses', idx: 2, text: 'new' } })
  assert.deepEqual(editEvent(item, ''), { type: 'draft_edited', payload: { field: 'weaknesses', idx: 2, text: '' } })
  assert.equal(editEvent(item, 'old'), null)
})

// ------------------------------------------------------------------ the API client

const resp = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body })

test('the client returns { ok, status, data } and sends JSON', async () => {
  const seen = []
  const api = createApi(async (url, init) => { seen.push([url, init]); return resp(200, { reply: 'hi' }) }, 'http://x')
  const r = await api.chat('p1', 'rev-1', 'hello')
  assert.deepEqual(r, { ok: true, status: 200, data: { reply: 'hi' } })
  assert.equal(seen[0][0], 'http://x/chat/p1')
  assert.deepEqual(JSON.parse(seen[0][1].body), { reviewer_id: 'rev-1', message: 'hello' })
  assert.equal(seen[0][1].headers['Content-Type'], 'application/json')
})

test('a 409 still returns its body, so the caller can show the current question', async () => {
  const api = createApi(async () => resp(409, { error: 'no_question_pending', question: 'Q1' }))
  const r = await api.answer('rev', 'x')
  assert.equal(r.ok, false)
  assert.equal(r.status, 409)
  assert.equal(r.data.question, 'Q1')
})

test('a network failure is a value, not an exception', async () => {
  const api = createApi(async () => { throw new TypeError('Failed to fetch') })
  const r = await api.onboarding('rev')
  assert.deepEqual([r.ok, r.status, r.data], [false, 0, null])
})

test('a body that is not JSON is data: null, not a crash', async () => {
  const api = createApi(async () => ({ ok: false, status: 502, json: async () => { throw new SyntaxError('x') } }))
  assert.deepEqual(await api.config(), { ok: false, status: 502, data: null })
})

test('ids are encoded into paths and events carry the paper id', async () => {
  const seen = []
  const api = createApi(async (url, init) => { seen.push([url, init]); return resp(200, {}) }, 'http://x')
  await api.onboarding('a b/c')
  await api.event('p1', 'note_removed', { id: 3 })
  assert.equal(seen[0][0], 'http://x/onboarding/a%20b%2Fc')
  assert.deepEqual(JSON.parse(seen[1][1].body), { paper_id: 'p1', type: 'note_removed', payload: { id: 3 } })
})
