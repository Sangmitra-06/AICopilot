// Which screen is shown: the chat-first screen by default, the old guided flow behind ?mode=guided or when the
// backend reports it is serving that flow.
import test from 'node:test'
import assert from 'node:assert/strict'
import { wantsGuided, flowFromConfig } from '../../frontend/src/chat/flow.js'

test('?mode=guided asks for the old flow, nothing else does', () => {
  assert.equal(wantsGuided('?mode=guided'), true)
  assert.equal(wantsGuided('?x=1&mode=guided'), true)
  assert.equal(wantsGuided(''), false)
  assert.equal(wantsGuided('?mode=chat'), false)
  assert.equal(wantsGuided('?mode=Guided'), false)
})

test('/config reporting guided mode shows the old flow', () => {
  assert.equal(flowFromConfig({ ok: true, status: 200, data: { flow: 'guided', chat_enabled: false } }), 'guided')
})

test('/config reporting chat mode shows the chat-first screen', () => {
  assert.equal(flowFromConfig({ ok: true, status: 200, data: { flow: 'chat', chat_enabled: true } }), 'chat')
})

test('an unreachable or odd /config is the chat-first screen, which then says it cannot reach the server', () => {
  assert.equal(flowFromConfig({ ok: false, status: 0, data: null }), 'chat')
  assert.equal(flowFromConfig({ ok: false, status: 500, data: { flow: 'guided' } }), 'chat')
  assert.equal(flowFromConfig({ ok: true, status: 200, data: {} }), 'chat')
  assert.equal(flowFromConfig({ ok: true, status: 200, data: { flow: 'banana' } }), 'chat')
  assert.equal(flowFromConfig(undefined), 'chat')
})
