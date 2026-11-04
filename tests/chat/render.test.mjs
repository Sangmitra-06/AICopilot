// Renders the real components (through Vite's SSR loader) and lists every control on screen, so "minimal" is a
// test and not a claim. No browser: this checks structure, not appearance.
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'

const root = fileURLToPath(new URL('../../frontend/', import.meta.url))
let server, React, renderToStaticMarkup, View, DraftPanel

before(async () => {
  const req = createRequire(root + 'package.json')
  const { createServer } = await import(pathToFileURL(req.resolve('vite')).href)
  server = await createServer({
    root, appType: 'custom', logLevel: 'silent', server: { middlewareMode: true, hmr: false },
    optimizeDeps: { noDiscovery: true, include: [] },
  })
  React = req('react')                                    // the same instance the components import
  renderToStaticMarkup = req('react-dom/server').renderToStaticMarkup
  View = (await server.ssrLoadModule('/src/chat/ChatView.jsx')).default
  DraftPanel = (await server.ssrLoadModule('/src/chat/DraftPanel.jsx')).default
})
after(async () => { if (server) await server.close() })

const state = (over = {}) => ({ stage: 'chat', messages: [], busy: false, menu: null, draftVersion: 0, ...over })
const props = (over = {}) => ({
  state: state(), text: '', onText() {}, onSend() {}, onAttach() {}, onChip() {}, selected: new Set(), inputRef: null,
  dragging: false, dragHandlers: {}, draftOpen: false, onToggleDraft() {}, draft: { sections: [], note: '', copied: false },
  onEditItem() {}, onCopy() {}, ...over,
})
const html = over => renderToStaticMarkup(React.createElement(View, props(over)))

// What a person can press or type into: [{kind, label}] in document order. (<input> has no closing tag, so inputs
// are collected first and removed before the paired elements are read.)
function controls(markup) {
  const out = []
  const label = (attrs, inner = '') => (attrs.match(/aria-label="([^"]*)"/) || [])[1] || inner.replace(/<[^>]*>/g, '').trim()
  for (const m of markup.matchAll(/<input\b([^>]*)>/g)) {
    if (/\bhidden\b/.test(m[1])) continue                            // the file picker behind the paperclip
    out.push({ kind: 'input', label: label(m[1]), at: m.index })
  }
  const rest = markup.replace(/<input\b[^>]*>/g, '')
  for (const m of rest.matchAll(/<(button|textarea|a|select)\b([^>]*)>([\s\S]*?)<\/\1>/g)) {
    out.push({ kind: m[1], label: label(m[2], m[3]), at: m.index })
  }
  return out.sort((x, y) => x.at - y.at).map(({ kind, label }) => ({ kind, label }))
}
const buttons = markup => controls(markup).filter(c => c.kind === 'button').map(c => c.label)

test('by default, three buttons and one text box: Review draft, Attach paper, Send, and the message box', () => {
  const m = html()
  assert.deepEqual(buttons(m), ['Review draft', 'Attach paper', 'Send'])
  assert.deepEqual(controls(m).filter(c => c.kind !== 'button'), [{ kind: 'textarea', label: 'Message' }])
})

test('nothing else is on screen: no links, selects, other inputs, dialogs, banners or menus', () => {
  const m = html({ state: state({ messages: [{ id: 1, role: 'assistant', text: 'Hello' }, { id: 2, role: 'user', text: 'Hi' }] }) })
  assert.equal(controls(m).filter(c => c.kind === 'a' || c.kind === 'select').length, 0)
  for (const banned of ['role="dialog"', 'aria-modal', 'role="alert"', 'role="banner"', 'role="menu"', 'role="tab"', '<nav', '<header', '<footer']) {
    assert.ok(!m.includes(banned), banned)
  }
})

test('the only icons are the paperclip and the send arrow; the toggle is text', () => {
  const m = html()
  assert.equal((m.match(/<svg/g) || []).length, 2)
  assert.match(m, /<button[^>]*>Review draft<\/button>/)
})

test('the paperclip is inside the text box, with the send button, and the toggle is outside it', () => {
  const m = html()
  const box = m.slice(m.indexOf('class="ca-box"'))
  assert.ok(box.indexOf('Attach paper') > -1 && box.indexOf('Attach paper') < box.indexOf('<textarea'))
  assert.ok(box.indexOf('<textarea') < box.indexOf('aria-label="Send"'))
  assert.ok(m.indexOf('Review draft') < m.indexOf('class="ca-box"'))
})

test('the thread shows assistant text on the page and the reviewer\'s text apart', () => {
  const m = html({ state: state({ messages: [{ id: 1, role: 'assistant', text: 'How many papers?' }, { id: 2, role: 'user', text: '7' }] }) })
  assert.match(m, /<p class="ca-msg ca-assistant">How many papers\?<\/p>/)
  assert.match(m, /<p class="ca-msg ca-user">7<\/p>/)
})

test('a failure, a nudge and a gap list are plain assistant messages, not banners', () => {
  const m = html({ state: state({ messages: [
    { id: 1, role: 'assistant', text: 'That didn\'t go through. Send your message again to retry.', kind: 'error' },
    { id: 2, role: 'assistant', text: 'Open items:\n- Required, nothing in it yet: Soundness.' }] }) })
  assert.equal((m.match(/class="ca-msg ca-assistant"/g) || []).length, 2)
  assert.deepEqual(buttons(m), ['Review draft', 'Attach paper', 'Send'])
})

test('onboarding with a criteria menu adds only the chips: the options and "Other, in my words"', () => {
  const menu = [{ id: 'soundness', label: 'Soundness' }, { id: 'excitement', label: 'Excitement' }, { id: 'other', label: 'Other, in my words' }]
  const m = html({ state: state({ stage: 'onboarding', menu, messages: [{ id: 1, role: 'assistant', text: 'What counts as a strength?' }] }) })
  assert.deepEqual(buttons(m), ['Review draft', 'Soundness', 'Excitement', 'Other, in my words', 'Attach paper', 'Send'])
  assert.equal((m.match(/class="ca-chip"/g) || []).length, 3)
})

test('a chosen chip is marked pressed', () => {
  const menu = [{ id: 'soundness', label: 'Soundness' }, { id: 'other', label: 'Other, in my words' }]
  const m = html({ state: state({ stage: 'onboarding', menu }), selected: new Set(['Soundness']) })
  assert.match(m, /aria-pressed="true"[^>]*>Soundness</)
})

test('without a menu (everyone but novices) there are no chips', () => {
  assert.ok(!html({ state: state({ stage: 'onboarding' }) }).includes('ca-chip'))
})

test('Send is disabled with nothing to send, and enabled with text', () => {
  assert.match(html(), /aria-label="Send" disabled/)
  assert.doesNotMatch(html({ text: 'hello' }), /aria-label="Send" disabled/)
})

test('Send is enabled for an empty retry after the first load failed', () => {
  assert.doesNotMatch(html({ state: state({ stage: 'boot' }) }), /aria-label="Send" disabled/)
})

test('the thread shows a quiet working mark while a call is running', () => {
  assert.match(html({ state: state({ busy: true }) }), /ca-wait/)
})

// ------------------------------------------------------------------ the draft panel

const sections = [
  { id: 'summary', name: 'Paper summary', items: [] },
  { id: 'weaknesses', name: 'Summary of weaknesses', items: [{ kind: 'note', id: 1, text: 'Five participants per region seems low' }, { kind: 'note', id: 2, text: 'Single run' }] },
]

test('the panel is closed by default and opened by the toggle', () => {
  assert.ok(!html().includes('ca-panel'))
  const m = html({ draftOpen: true, draft: { sections, note: '', copied: false } })
  assert.match(m, /aria-pressed="true"[^>]*>Review draft</)
  assert.ok(m.includes('ca-panel'))
})

test('the panel\'s only action is Copy all; sections are editable text, not buttons', () => {
  const m = html({ draftOpen: true, draft: { sections, note: '', copied: false } })
  assert.deepEqual(buttons(m), ['Review draft', 'Attach paper', 'Send', 'Copy all'])
  const paras = controls(m).filter(c => c.kind === 'textarea' && c.label === 'Edit this paragraph')
  assert.equal(paras.length, 2)
  assert.match(m, /<h2>Paper summary<\/h2>/)
  assert.match(m, /Nothing here yet\./)
  assert.match(m, /Five participants per region seems low/)
})

test('after copying, the button says so (a label change, not a new control)', () => {
  const m = html({ draftOpen: true, draft: { sections, note: '', copied: true } })
  assert.deepEqual(buttons(m).slice(-1), ['Copied'])
})

test('no score pickers, confirmations or per-message buttons anywhere', () => {
  const m = html({ draftOpen: true, draft: { sections, note: '', copied: false },
    state: state({ messages: [{ id: 1, role: 'assistant', text: 'Hi' }, { id: 2, role: 'user', text: 'Hey' }] }) })
  for (const bad of ['<select', 'type="radio"', 'type="checkbox"', 'type="range"', 'Confirm', 'Cancel', 'Delete', 'Regenerate', 'Edit</button>']) {
    assert.ok(!m.includes(bad), bad)
  }
})

test('the panel can show a plain sentence instead of sections (no paper, or a load failure)', () => {
  const m = renderToStaticMarkup(React.createElement(DraftPanel, { sections: [], note: 'Attach a paper and your draft will appear here.', copied: false, onEdit() {}, onCopy() {} }))
  assert.match(m, /<p class="ca-note">Attach a paper/)
})

test('dropping a file onto the thread highlights it with no extra screen', () => {
  const m = html({ dragging: true })
  assert.match(m, /class="ca-root ca-drag"/)
  assert.deepEqual(buttons(m), ['Review draft', 'Attach paper', 'Send'])
})

// ------------------------------------------------------------------ the PDF pane (after a paper is attached)

const PARTS = [{ text: 'Table 2 has the numbers ', cite: null }, { text: '(Section 4)', cite: ['s4'] }, { text: '.', cite: null }]
const withPaper = over => html({
  pane: React.createElement('div', { className: 'pdf-scroller' }, React.createElement('div', { className: 'pdf-page' })),
  onCite() {}, state: state({ paperId: 'p1', messages: [{ id: 1, role: 'assistant', text: 'Table 2 has the numbers (Section 4).', parts: PARTS }] }), ...over,
})

test('with a paper the PDF is on the left of the chat, and there is no pane before one is attached', () => {
  const m = withPaper()
  assert.ok(m.indexOf('class="ca-pdf"') > -1 && m.indexOf('class="ca-pdf"') < m.indexOf('class="ca-main"'))
  assert.match(m, /class="ca-root ca-with-pdf"/)
  assert.ok(!html().includes('ca-pdf') && !html().includes('ca-with-pdf'))
})

test('the PDF pane adds no controls: the same three buttons and one text box', () => {
  const m = withPaper()
  assert.deepEqual(buttons(m), ['Review draft', 'Attach paper', 'Send'])
  assert.deepEqual(controls(m).filter(c => c.kind !== 'button'), [{ kind: 'textarea', label: 'Message' }])
})

test('a pointer in a reply is plain text, not a button, and no span id is on screen', () => {
  const m = withPaper()
  assert.match(m, /Table 2 has the numbers <span class="ca-cite" tabindex="0">\(Section 4\)<\/span>\./)
  assert.ok(!/\bs4\b/.test(m.replace(/class="[^"]*"/g, '')))
  assert.ok(!m.includes('[s4]'))
  assert.deepEqual(buttons(m), ['Review draft', 'Attach paper', 'Send'])
})

test('a message without pointers renders exactly as before, with or without the pane', () => {
  const messages = [{ id: 1, role: 'assistant', text: 'Hello' }]
  assert.match(withPaper({ state: state({ paperId: 'p1', messages }) }), /<p class="ca-msg ca-assistant">Hello<\/p>/)
  assert.match(html({ state: state({ messages }) }), /<p class="ca-msg ca-assistant">Hello<\/p>/)
})

test('the draft panel still opens as a toggle next to the PDF pane', () => {
  const m = withPaper({ draftOpen: true })
  assert.ok(m.includes('class="ca-pdf"') && m.includes('ca-panel'))
  assert.deepEqual(buttons(m).slice(0, 1), ['Review draft'])
})

test('the real PDF viewer renders as an empty scroller until the document loads, and nothing without a url', async () => {
  const Viewer = (await server.ssrLoadModule('/src/pdf/PdfViewer.jsx')).default
  const on = renderToStaticMarkup(React.createElement(Viewer, { url: 'http://x/p.pdf', focus: null, onSelect() {} }))
  assert.equal(on, '<div class="pdf-scroller"></div>')
  assert.equal(renderToStaticMarkup(React.createElement(Viewer, { url: null, focus: null, onSelect() {} })), '')
})
