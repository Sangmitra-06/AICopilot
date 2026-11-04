// The criteria chips: picking several fills the text box with their labels.
import test from 'node:test'
import assert from 'node:assert/strict'
import { toggleLabel, selectedLabels } from '../../frontend/src/chat/chips.js'

test('a chip adds its label, and clicking it again removes it', () => {
  assert.equal(toggleLabel('', 'Soundness'), 'Soundness')
  assert.equal(toggleLabel('Soundness', 'Soundness'), '')
})

test('several chips build a comma-separated list, in the order picked', () => {
  assert.equal(toggleLabel(toggleLabel('', 'Excitement'), 'Reproducibility'), 'Excitement, Reproducibility')
  assert.equal(toggleLabel('Excitement, Reproducibility', 'Excitement'), 'Reproducibility')
})

test('two quick clicks both count: each is applied to the result of the one before (a functional update)', () => {
  // This is what ChatApp does with setText(prev => toggleLabel(prev, label)): the second click sees the first.
  const clicks = ['Soundness', 'Excitement']
  assert.equal(clicks.reduce((text, label) => toggleLabel(text, label), ''), 'Soundness, Excitement')
})

test('words the reviewer typed themselves are kept when a chip is toggled', () => {
  assert.equal(toggleLabel('my own criterion', 'Soundness'), 'my own criterion, Soundness')
  assert.equal(toggleLabel('my own criterion, Soundness', 'Soundness'), 'my own criterion')
})

test('stray spaces and commas do not create empty entries', () => {
  assert.equal(toggleLabel(' , Soundness ,, ', 'Excitement'), 'Soundness, Excitement')
  assert.equal(toggleLabel(null, 'Soundness'), 'Soundness')
})

test('the pressed chips are the menu entries whose labels are in the text', () => {
  const menu = [{ id: 'a', label: 'Soundness' }, { id: 'b', label: 'Excitement' }, { id: 'other', label: 'Other, in my words' }]
  assert.deepEqual([...selectedLabels('Excitement, something else', menu)], ['Excitement'])
  assert.equal(selectedLabels('', menu).size, 0)
  assert.equal(selectedLabels('Soundness', null).size, 0)
})
