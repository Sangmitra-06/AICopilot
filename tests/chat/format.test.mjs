// Formatting of assistant messages: **bold**, bullet lists and paragraph breaks, with no HTML injection. The layout is
// React-free (format.js); the render test at the bottom loads the real Thread through Vite's SSR loader.
import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { layout } from '../../frontend/src/chat/format.js'

const flat = blocks => blocks.map(b => ({ kind: b.kind, lines: b.lines.map(l => l.map(n => (n.bold ? `*${n.text}*` : n.text)).join('')) }))
const joined = blocks => blocks.map(b => b.lines.map(l => l.map(n => n.text).join('')).join('\n')).join('\n\n')

test('plain text is one paragraph, untouched', () => {
  assert.deepEqual(flat(layout('Got it. Tell me more.')), [{ kind: 'p', lines: ['Got it. Tell me more.'] }])
})

test('**bold** becomes a bold run and the markers are gone', () => {
  const b = layout('The **main claim** is stated in **Section 3**.')
  assert.deepEqual(flat(b), [{ kind: 'p', lines: ['The *main claim* is stated in *Section 3*.'] }])
  assert.ok(!joined(b).includes('**'))
})

test('blank lines make paragraphs; a single newline stays a line break inside one', () => {
  assert.deepEqual(flat(layout('One.\n\nTwo line a\nTwo line b\n\n\nThree.')), [
    { kind: 'p', lines: ['One.'] }, { kind: 'p', lines: ['Two line a', 'Two line b'] }, { kind: 'p', lines: ['Three.'] }])
})

test('bullets with -, *, • and numbers become lists, with bold inside items', () => {
  assert.deepEqual(flat(layout('Open:\n- Summary\n- **Strengths**: none yet\n\nThen:\n1. first\n2) second')), [
    { kind: 'p', lines: ['Open:'] }, { kind: 'ul', lines: ['Summary', '*Strengths*: none yet'] },
    { kind: 'p', lines: ['Then:'] }, { kind: 'ol', lines: ['first', 'second'] }])
  assert.deepEqual(flat(layout('* a\n• b')), [{ kind: 'ul', lines: ['a', 'b'] }])
})

test('a list straight after a sentence, with no blank line, is still a list', () => {
  assert.deepEqual(flat(layout('Sections:\n- A\n- B')), [{ kind: 'p', lines: ['Sections:'] }, { kind: 'ul', lines: ['A', 'B'] }])
})

test('an unmatched ** is dropped, not shown; a lone * or a product like 3 * 4 is left alone', () => {
  assert.deepEqual(flat(layout('This **never closes')), [{ kind: 'p', lines: ['This never closes'] }])
  assert.deepEqual(flat(layout('a ** b ** c')), [{ kind: 'p', lines: ['a  b  c'] }])   // spaces inside: not bold, not shown
  assert.deepEqual(flat(layout('3 * 4 = 12')), [{ kind: 'p', lines: ['3 * 4 = 12'] }])
})

test('bold does not run across lines', () => {
  assert.deepEqual(flat(layout('**one\ntwo**')), [{ kind: 'p', lines: ['one', 'two'] }])
})

test('a markdown heading line is shown as a bold line without the #', () => {
  assert.deepEqual(flat(layout('## Weaknesses\nnothing yet')), [{ kind: 'p', lines: ['*Weaknesses*', 'nothing yet'] }])
})

test('HTML is never interpreted: tags stay as the text they are', () => {
  const b = layout('<b>hi</b> <script>alert(1)</script> **bold**')
  assert.equal(joined(b), '<b>hi</b> <script>alert(1)</script> bold')
  assert.ok(b[0].lines[0].every(n => typeof n.text === 'string'))
})

test('pointers keep working: the cite parts are laid over the formatted runs, also inside bold', () => {
  const text = 'The **result (Section 4)** holds.\n- see (Section 3)'
  const i4 = text.indexOf('(Section 4)')
  const i3 = text.indexOf('(Section 3)')
  const parts = [
    { text: text.slice(0, i4), cite: null }, { text: '(Section 4)', cite: ['s4'] },
    { text: text.slice(i4 + 11, i3), cite: null }, { text: '(Section 3)', cite: ['s3'] }]
  assert.equal(parts.map(p => p.text).join(''), text)
  const b = layout(text, parts)
  const nodes = b.flatMap(x => x.lines.flat())
  assert.deepEqual(nodes.filter(n => n.cite).map(n => [n.text, n.cite]), [['(Section 4)', ['s4']], ['(Section 3)', ['s3']]])
  assert.equal(nodes.find(n => n.cite && n.cite[0] === 's4').bold, true)           // bold survives the split
  assert.equal(nodes.find(n => n.cite && n.cite[0] === 's3').bold, false)
  assert.equal(joined(b), 'The result (Section 4) holds.\n\nsee (Section 3)')
  assert.deepEqual(b.map(x => x.kind), ['p', 'ul'])
})

test('parts that do not match the text are ignored rather than trusted', () => {
  const b = layout('Hello (Section 1)', [{ text: 'Something else', cite: ['s1'] }])
  assert.deepEqual(b[0].lines[0].map(n => n.cite), [null])
})

test('empty and odd inputs give no blocks and no crash', () => {
  assert.deepEqual(layout(''), [])
  assert.deepEqual(layout(null), [])
  assert.deepEqual(flat(layout('   \n  \n')), [])
})

// ------------------------------------------------------------------ rendered through the real component

const root = fileURLToPath(new URL('../../frontend/', import.meta.url))
let server, React, renderToStaticMarkup, Thread
before(async () => {
  const req = createRequire(root + 'package.json')
  const { createServer } = await import(pathToFileURL(req.resolve('vite')).href)
  server = await createServer({ root, appType: 'custom', logLevel: 'silent', server: { middlewareMode: true, hmr: false },
    optimizeDeps: { noDiscovery: true, include: [] } })
  React = req('react')
  renderToStaticMarkup = req('react-dom/server').renderToStaticMarkup
  Thread = (await server.ssrLoadModule('/src/chat/Thread.jsx')).default
})
after(async () => { if (server) await server.close() })

const render = (messages, onCite = () => {}) => renderToStaticMarkup(React.createElement(Thread,
  { messages, busy: false, menu: null, selected: new Set(), onChip() {}, onCite }))

test('rendered: bold is <strong>, lists are <ul>/<li>, paragraphs are separate, and no ** is shown', () => {
  const m = render([{ id: 1, role: 'assistant', text: 'Here is **what is open**:\n- Summary\n- Strengths\n\nAnything else?' }])
  assert.match(m, /<strong>what is open<\/strong>/)
  assert.match(m, /<ul><li>Summary<\/li><li>Strengths<\/li><\/ul>/)
  assert.match(m, /<p>Anything else\?<\/p>/)
  assert.ok(!m.includes('**'))
})

test('rendered: a plain one-line reply keeps the simple paragraph markup', () => {
  assert.match(render([{ id: 1, role: 'assistant', text: 'Hello' }]), /<p class="ca-msg ca-assistant">Hello<\/p>/)
})

test('rendered: HTML in a reply is escaped, never injected', () => {
  const m = render([{ id: 1, role: 'assistant', text: '<img src=x onerror=alert(1)> and <script>alert(2)</script> **ok**' }])
  assert.ok(!m.includes('<img') && !m.includes('<script'))
  assert.match(m, /&lt;img src=x onerror=alert\(1\)&gt;/)
  assert.match(m, /<strong>ok<\/strong>/)
})

test('rendered: the reviewer\'s own message is never reformatted (their asterisks stay)', () => {
  const m = render([{ id: 1, role: 'user', text: 'I think **this** is a "5 * 3" thing\n- not a list' }])
  assert.match(m, /<p class="ca-msg ca-user">I think \*\*this\*\* is a &quot;5 \* 3&quot; thing\n- not a list<\/p>/)
})

test('rendered: pointers are still clickable text inside formatted replies', () => {
  const text = '**Found it** (Section 4)\n- also (Section 3)'
  const parts = [{ text: '**Found it** ', cite: null }, { text: '(Section 4)', cite: ['s4'] },
    { text: '\n- also ', cite: null }, { text: '(Section 3)', cite: ['s3'] }]
  const m = render([{ id: 1, role: 'assistant', text, parts }])
  assert.match(m, /<strong>Found it<\/strong> <span class="ca-cite" tabindex="0">\(Section 4\)<\/span>/)
  assert.match(m, /<li>also <span class="ca-cite" tabindex="0">\(Section 3\)<\/span><\/li>/)
  assert.ok(!m.includes('**'))
})
