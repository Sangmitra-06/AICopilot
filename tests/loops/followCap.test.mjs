// Loop 2: "Add more" (and re-entering a part) used to reset the follow-up counter,
// so a reviewer who kept adding points was questioned about every one of them.
import test from 'node:test'
import assert from 'node:assert/strict'
import * as fs from '../../frontend/src/flowState.js'

const judge = { id: 'weaknesses', style: 'judge' }
const describe = { id: 'comments', style: 'describe' }
const summary = { id: 'summary', style: 'describe' }

// App.jsx's more() and startPart() called these when they existed; the fix removed them.
const addMore = (counts, cid) => { if (typeof fs.addMore === 'function') fs.addMore(counts, cid) }
const enterPart = (counts, cid) => { if (typeof fs.enterPart === 'function') fs.enterPart(counts, cid) }

// The reviewer saves a point; the assistant may follow up; repeat.
function askedAfter(c, saves, between) {
  const counts = fs.newCounts()
  let asked = 0
  for (let i = 0; i < saves; i++) {
    if (fs.nextFollow(counts, c)) asked++
    if (between) between(counts, c.id, i)
  }
  return asked
}

test('judge part: two follow-ups, then none', () => {
  const counts = fs.newCounts()
  assert.equal(fs.nextFollow(counts, judge), 'respond')
  assert.equal(fs.nextFollow(counts, judge), 'deeper')
  assert.equal(fs.nextFollow(counts, judge), null)
})

test('describe part and summary: one follow-up, then none', () => {
  for (const c of [describe, summary]) {
    const counts = fs.newCounts()
    assert.ok(fs.nextFollow(counts, c))
    assert.equal(fs.nextFollow(counts, c), null)
  }
})

test('"Add more" does not buy more follow-ups', () => {
  const asked = askedAfter(judge, 8, addMore)
  assert.ok(asked <= fs.capFor(judge), `asked ${asked} follow-ups, cap is ${fs.capFor(judge)}`)
})

test('re-entering a part does not buy more follow-ups', () => {
  const asked = askedAfter(judge, 8, enterPart)
  assert.ok(asked <= fs.capFor(judge), `asked ${asked} follow-ups, cap is ${fs.capFor(judge)}`)
})

test('the cap is per part', () => {
  const counts = fs.newCounts()
  fs.nextFollow(counts, judge); fs.nextFollow(counts, judge)
  assert.equal(fs.nextFollow(counts, judge), null)
  assert.equal(fs.nextFollow(counts, { id: 'strengths', style: 'judge' }), 'respond')
})

test('skipping the follow-up uses the part up', () => {
  const counts = fs.newCounts()
  fs.exhaust(counts, judge)
  assert.equal(fs.nextFollow(counts, judge), null)
})
