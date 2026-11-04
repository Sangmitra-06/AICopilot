// Loop 3: every "I don't know" re-ran the same explanation and re-asked the same question.
import test from 'node:test'
import assert from 'node:assert/strict'
import * as fs from '../../frontend/src/flowState.js'

test('the first "I don\'t know" on a part explains', () => {
  assert.equal(fs.nextDontKnow(fs.newDk(), 'weaknesses'), 'explain')
})

test('later ones on the same part never explain again', () => {
  const dk = fs.newDk()
  const seen = Array.from({ length: 6 }, () => fs.nextDontKnow(dk, 'weaknesses'))
  assert.deepEqual(seen, ['explain', 'choose', 'choose', 'choose', 'choose', 'choose'])
})

test('the count is per part', () => {
  const dk = fs.newDk()
  fs.nextDontKnow(dk, 'weaknesses')
  fs.nextDontKnow(dk, 'weaknesses')
  assert.equal(fs.nextDontKnow(dk, 'strengths'), 'explain')
})

test('the choice is concrete and always has a way out', () => {
  const opts = fs.choiceOptions({ id: 'weaknesses', tab: 'Weaknesses' }, { id: 'soundness', tab: 'Soundness' })
  const acts = opts.map(o => o.a)
  assert.ok(acts.includes('nocomment'))
  assert.ok(opts.some(o => o.a === 'goto' && o.arg === 'soundness'))
})

test('with no next part the choice still offers a way out', () => {
  const opts = fs.choiceOptions({ id: 'ethics', tab: 'Ethics' }, null)
  assert.ok(opts.some(o => o.a === 'nocomment'))
  assert.ok(opts.every(o => o.a !== 'goto'))
})

test('when a part has no questions left the choice drops "Ask something else"', () => {
  const opts = fs.choiceOptions({ id: 'weaknesses', tab: 'Weaknesses' }, null, false)
  assert.ok(opts.every(o => o.a !== 'angle'))
  assert.ok(opts.some(o => o.a === 'nocomment'))
})
