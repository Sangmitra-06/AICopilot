import { useEffect, useMemo, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import './App.css'
import { newCounts, raise, exhaust, nextFollow, newDk, nextDontKnow, choiceOptions } from './flowState'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

const API = 'http://127.0.0.1:8000'
const SCALE = 1.25
const MIN_W = 360
const GRIP_HALF = 5

async function api(path, body) {
  const r = await fetch(API + path, body === undefined ? {} : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error((await r.text()).slice(0, 300))
  return r.json()
}

const refOf = (lines, page) =>
  lines ? (lines[0] === lines[1] ? `L${lines[0]}` : `L${lines[0]}-${lines[1]}`) : `p${page}`

function chipOf(s) {
  if (s.source === 'image') return ['picture', `Picture · p${s.page} · model's reading`]
  if (s.kind === 'background') return ['bg', 'Background']
  const where = refOf(s.lines, s.page) + (s.lines && !s.precise ? ' (approx.)' : '')
  if (s.kind === 'authors_claim') return ['auth', `Authors' claim · ${where}`]
  return ['paper', `${s.source === 'pdf' ? 'Paper, from PDF' : 'Paper'} · ${where}`]
}

const toSent = (it, kind = 'paper') => ({
  text: it.text, kind, source: 'text', span_ids: [it.span_id], quote: it.quote,
  lines: it.lines, page: it.page, precise: true,
})

const stripNote = d => (d || '').replace(/^\([^)]*\)\s*\n?/, '').trim()
const firstSentence = d => {
  const t = stripNote(d)
  const m = t.match(/^[\s\S]{20,}?[.?!](\s|$)/)
  return (m ? m[0] : t).slice(0, 220).trim()
}

function Page({ pdf, n, hls, onSelect, reg }) {
  const [size, setSize] = useState(null)
  const [vis, setVis] = useState(false)
  const [drag, setDrag] = useState(null)
  const box = useRef(null)
  const canvas = useRef(null)
  const page = useRef(null)
  const drawn = useRef(false)

  useEffect(() => {
    let alive = true
    pdf.getPage(n).then(p => {
      if (!alive) return
      page.current = p
      const v = p.getViewport({ scale: SCALE })
      setSize([v.width, v.height])
    })
    return () => { alive = false }
  }, [pdf, n])

  useEffect(() => {
    const io = new IntersectionObserver(es => { if (es[0].isIntersecting) setVis(true) }, { rootMargin: '900px' })
    io.observe(box.current)
    return () => io.disconnect()
  }, [])

  useEffect(() => {
    if (!size || !vis || drawn.current) return
    drawn.current = true
    const v = page.current.getViewport({ scale: SCALE })
    const c = canvas.current
    c.width = v.width
    c.height = v.height
    page.current.render({ canvasContext: c.getContext('2d'), viewport: v })
  }, [size, vis])

  const pos = e => {
    const r = box.current.getBoundingClientRect()
    return [e.clientX - r.left, e.clientY - r.top]
  }
  const down = e => {
    if (e.button !== 0) return
    const [x, y] = pos(e)
    setDrag({ x0: x, y0: y, x1: x, y1: y })
  }
  const move = e => {
    if (!drag) return
    const [x, y] = pos(e)
    setDrag({ ...drag, x1: x, y1: y })
  }
  const up = () => {
    if (!drag) return
    const x0 = Math.min(drag.x0, drag.x1), x1 = Math.max(drag.x0, drag.x1)
    const y0 = Math.min(drag.y0, drag.y1), y1 = Math.max(drag.y0, drag.y1)
    setDrag(null)
    if (x1 - x0 > 6 && y1 - y0 > 6) onSelect(n, [x0 / SCALE, y0 / SCALE, x1 / SCALE, y1 / SCALE])
  }

  const w = size ? size[0] : 612 * SCALE
  const h = size ? size[1] : 792 * SCALE
  const r = drag && {
    l: Math.min(drag.x0, drag.x1), t: Math.min(drag.y0, drag.y1),
    w: Math.abs(drag.x1 - drag.x0), h: Math.abs(drag.y1 - drag.y0),
  }
  return (
    <div className="page" style={{ width: w, height: h }}
      ref={el => { box.current = el; reg(n, el) }}
      onMouseDown={down} onMouseMove={move} onMouseUp={up} onMouseLeave={up}>
      <canvas ref={canvas} />
      {hls.filter(x => x.page === n).map((x, i) => (
        <div key={i} className={'hl ' + x.cls} style={{
          left: x.bbox[0] * SCALE, top: x.bbox[1] * SCALE,
          width: (x.bbox[2] - x.bbox[0]) * SCALE, height: (x.bbox[3] - x.bbox[1]) * SCALE,
        }} />
      ))}
      {r && <div className="drag" style={{ left: r.l, top: r.t, width: r.w, height: r.h }} />}
      <div className="pno">p{n}</div>
    </div>
  )
}

function Viewer({ url, hls, onSelect, jump }) {
  const [pdf, setPdf] = useState(null)
  const scroller = useRef(null)
  const els = useRef({})

  useEffect(() => {
    if (!url) return
    let alive = true
    setPdf(null)
    pdfjs.getDocument({ url, disableRange: true, disableStream: true }).promise
      .then(d => { if (alive) setPdf(d) })
    return () => { alive = false }
  }, [url])

  useEffect(() => {
    if (!jump || !scroller.current) return
    const el = els.current[jump.page]
    if (el) scroller.current.scrollTo({ top: el.offsetTop + (jump.y || 0) * SCALE - 90, behavior: 'smooth' })
  }, [jump])

  if (!url) return <div className="viewer-empty">Your paper appears here. Drag a box over any part of a page to select it.</div>
  if (!pdf) return <div className="viewer-empty">Loading the PDF…</div>
  return (
    <div className="scroller" ref={scroller}>
      {Array.from({ length: pdf.numPages }, (_, i) => (
        <Page key={i + 1} pdf={pdf} n={i + 1} hls={hls} onSelect={onSelect}
          reg={(n, el) => { els.current[n] = el }} />
      ))}
    </div>
  )
}

function Ptrs({ list, onJump }) {
  if (!list || !list.length) return null
  return list.map((p, i) => (
    <details className="ptr" key={i}>
      <summary>The paper has text on this · {refOf(p.lines, p.page)}</summary>
      <div className="quote">{p.paper_quote}</div>
      <div className="small">{p.explanation}</div>
      {onJump && <button className="btn quiet" onClick={() => onJump(p)}>Show on the paper</button>}
    </details>
  ))
}

function AskCard({ a, crits, onSave }) {
  const [text, setText] = useState('')
  const [field, setField] = useState('')
  return (
    <div className="ask">
      <div className="muted">About your note: “{a.text.slice(0, 140)}{a.text.length > 140 ? '…' : ''}”</div>
      <div><b>{a.question}</b></div>
      <textarea placeholder="Your answer, in your own words (optional)" value={text} onChange={e => setText(e.target.value)} />
      <div className="row">
        <select value={field} onChange={e => setField(e.target.value)}>
          <option value="">Put it under… (optional)</option>
          {crits.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <button className="btn primary" onClick={() => onSave(a, text.trim(), field, false)}>Save</button>
        <button className="btn" onClick={() => onSave(a, '', '', true)}>Dismiss</button>
      </div>
    </div>
  )
}

export default function App() {
  const [pid, setPid] = useState(null)
  const [crit, setCrit] = useState(null)
  const [walk, setWalk] = useState([])
  const [spans, setSpans] = useState([])
  const [notes, setNotes] = useState([])
  const [scores, setScores] = useState({})
  const [draft, setDraft] = useState({})
  const [status, setStatus] = useState(null)
  const [facts, setFacts] = useState({})
  const [checking, setChecking] = useState({})
  const [brief, setBrief] = useState(undefined)
  const [msgs, setMsgs] = useState([])
  const [qr, setQr] = useState([])
  const [mode, setMode] = useState('chat')
  const [curPart, setCurPart] = useState(null)
  const [walkAt, setWalkAt] = useState(-1)
  const [anchor, setAnchor] = useState(null)
  const [text, setText] = useState('')
  const [thinking, setThinking] = useState('')
  const [busy, setBusy] = useState('')
  const [err, setErr] = useState('')
  const [retry, setRetry] = useState(null)
  const [asks, setAsks] = useState([])
  const [edit, setEdit] = useState(null)
  const [dispute, setDispute] = useState(null)
  const [shown, setShown] = useState({})
  const [cur, setCur] = useState([])
  const [jump, setJump] = useState(null)
  const [refs, setRefs] = useState(true)
  const [own, setOwn] = useState({})
  const [finished, setFinished] = useState(false)
  const [width, setWidth] = useState(() => Number(localStorage.getItem('panelW')) || 460)
  const nid = useRef(1000)
  const epoch = useRef(0)
  const dragging = useRef(false)
  const inputRef = useRef(null)
  const endRef = useRef(null)
  const fileRef = useRef(null)
  const briefTried = useRef(false)
  const flow = useRef({ cid: '', lastQ: '', stage: '', re: '', lastQr: [] })
  const follows = useRef(newCounts())
  const dks = useRef(newDk())
  const notesRef = useRef([])
  const scoresRef = useRef({})
  const statusRef = useRef(null)
  notesRef.current = notes
  scoresRef.current = scores
  statusRef.current = status

  const stamp = () => { const e = epoch.current; return () => epoch.current === e }

  const byId = useMemo(() => Object.fromEntries(spans.map(s => [s.id, s])), [spans])
  const critList = crit ? crit.criteria : []
  const cmap = useMemo(() => Object.fromEntries(critList.map(c => [c.id, c])), [crit])
  const url = pid ? `${API}/papers/${pid}/pdf` : null
  const stOf = id => (status && status.criteria[id] ? status.criteria[id].status : 'empty')
  const skippedOf = id => !!(status && status.criteria[id] && status.criteria[id].skipped)
  const allowDispute = !status || status.allow_dispute !== false

  useEffect(() => { localStorage.setItem('panelW', String(Math.round(width))) }, [width])
  useEffect(() => {
    if (endRef.current && mode === 'chat') endRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [msgs.length, thinking, qr.length, mode])
  useEffect(() => {
    if (mode === 'brief' && pid && brief === null && !briefTried.current) {
      briefTried.current = true
      buildBrief(false)
    }
  }, [mode, pid, brief])

  const fail = m => { setErr(m); setRetry(null) }
  async function run(label, fn) {
    setBusy(label); setErr(''); setRetry(null)
    try { await fn() } catch (e) {
      setErr(String(e.message || e))
      setRetry(() => () => run(label, fn))
    }
    setBusy('')
  }
  const addSpans = list => {
    if (list && list.length) setSpans(s => [...s, ...list.filter(x => !s.some(y => y.id === x.id))])
  }
  async function refresh(id = pid) {
    const r = await Promise.allSettled([
      api(`/notes/${id}`), api(`/scores/${id}`), api(`/draft/${id}`),
      api(`/criteria/status/${id}`), api(`/facts/${id}`)])
    const out = { notes: notesRef.current, scores: scoresRef.current, status: statusRef.current }
    const [n, s, d, st, f] = r
    if (n.status === 'fulfilled') { setNotes(n.value); out.notes = n.value; notesRef.current = n.value }
    if (s.status === 'fulfilled') { setScores(s.value); out.scores = s.value; scoresRef.current = s.value }
    if (d.status === 'fulfilled') setDraft(d.value)
    if (st.status === 'fulfilled') { setStatus(st.value); out.status = st.value; statusRef.current = st.value }
    if (f.status === 'fulfilled') setFacts(f.value)
    const bad = r.find(x => x.status === 'rejected')
    if (bad) setErr('Some information could not be loaded: ' + String((bad.reason && bad.reason.message) || bad.reason).slice(0, 160))
    return out
  }
  const ev = (type, payload) => api('/events', { paper_id: pid, type, payload })
  const push = m => { const id = ++nid.current; setMsgs(a => [...a, { id, ...m }]); return id }
  const patch = (id, p) => setMsgs(a => a.map(m => (m.id === id ? { ...m, ...p } : m)))
  const copy = t => navigator.clipboard.writeText(t)
  const focusInput = () => setTimeout(() => { if (inputRef.current) inputRef.current.focus() }, 50)

  function prompt(t, q, stage = 'ask', lastQ = '', extra = null, re = '') {
    const f = flow.current
    f.stage = stage; f.lastQ = lastQ; f.re = re || lastQ || ''; f.lastQr = q
    push({ role: 'a', text: t, ...(extra || {}) })
    setQr(q)
  }

  const startQr = () => [
    { l: 'Walk me through the paper', p: 1, a: 'walk' },
    { l: 'Give me the brief', a: 'brief' },
    { l: 'Start the review form', a: 'form' },
  ]
  const baseQr = c => (c.id === 'summary'
    ? [{ l: 'Help me understand the paper', a: 'gread', arg: 0 },
      { l: "Show me the authors' highlights", a: 'highlights' },
      { l: 'No comment on this part', a: 'nocomment' }]
    : [{ l: "I don't know", a: 'dk' },
      { l: 'Ask something else', a: 'angle' },
      { l: 'No comment on this part', a: 'nocomment' }])

  function welcome(n) {
    if (n > 0) {
      push({ role: 'a', text: `Welcome back. You have ${n} saved point${n > 1 ? 's' : ''}.` })
      setQr([{ l: 'Continue the review form', p: 1, a: 'form' }, { l: 'Review draft', a: 'draftview' }, { l: 'Walk me through the paper', a: 'walk' }])
    } else {
      push({ role: 'a', text: 'I can explain the paper, answer questions about it, and ask about each part of the review form. You answer in your own words, and the review is built from what you say.' })
      setQr(startQr())
    }
  }

  function upload(file) {
    if (!file) return
    run('Reading the paper…', async () => {
      const fd = new FormData()
      fd.append('file', file)
      const r = await fetch(API + '/papers', { method: 'POST', body: fd })
      if (!r.ok) throw new Error(await r.text())
      const d = await r.json()
      const id = d.paper_id
      const [c, w, sp, br] = await Promise.all([
        api('/criteria'), api(`/walk/${id}`), api(`/papers/${id}/spans`), api(`/brief/${id}`)])
      epoch.current += 1
      setCrit(c); setWalk(w); setSpans(sp); setBrief(br || null)
      briefTried.current = false
      flow.current = { cid: '', lastQ: '', stage: '', re: '', lastQr: [] }
      follows.current = newCounts()
      dks.current = newDk()
      setCurPart(null); setAsks([]); setAnchor(null); setCur([]); setFacts({}); setEdit(null)
      setDispute(null); setFinished(false); setWalkAt(-1); setOwn({}); setMsgs([]); setQr([]); setThinking('')
      setPid(id); setMode('chat')
      const f = await refresh(id)
      welcome(f.notes.length)
    })
  }

  async function step(i, simpler = false) {
    const sec = walk[i]
    if (!sec) return
    epoch.current += 1
    const live = stamp()
    setMode('chat'); setWalkAt(i); setQr([]); setThinking('')
    const id = push({ role: 'ex', title: sec + (simpler ? ' (simpler)' : ''), step: i, loading: true })
    try {
      const d = await api('/explain', { paper_id: pid, section: sec, simpler })
      addSpans(d.new_spans)
      patch(id, { loading: false, sentences: d.sentences })
    } catch (e) { patch(id, { loading: false, error: e.message }) }
    if (!live()) return
    const fc = cmap[flow.current.cid]
    setQr([
      ...(i > 0 ? [{ l: 'Back', a: 'step', arg: i - 1 }] : []),
      { l: 'Simpler', a: 'step', arg: i, simpler: true },
      ...(i < walk.length - 1 ? [{ l: 'Next section', p: 1, a: 'step', arg: i + 1 }] : []),
      fc ? { l: `Back to ${fc.tab}`, a: 'resume' } : { l: 'Back to the review form', a: 'form' },
    ])
  }

  function histFor() {
    return msgs
      .filter(m => !m.loading && !m.error && (m.role === 'u' || m.role === 'a' || m.role === 'ex'))
      .map(m => ({
        role: m.role === 'u' ? 'user' : 'assistant',
        text: m.role === 'ex' ? (m.sentences || []).map(s => s.text).join(' ') : (m.text || ''),
      }))
      .filter(h => h.text)
      .slice(-6)
  }

  async function askPaper(t, a) {
    const live = stamp()
    const hist = histFor()
    const id = push({ role: 'ex', loading: true })
    try {
      const d = a && a.kind === 'region'
        ? await api('/ask_selection', { paper_id: pid, page: a.page, rect: a.rect, question: t })
        : await api('/ask', { paper_id: pid, question: t, context: a && a.text ? a.text : '', history: hist })
      addSpans(d.new_spans)
      patch(id, { loading: false, sentences: d.sentences || [], declined: d.declined ? d.message : '' })
    } catch (e) { patch(id, { loading: false, error: e.message }) }
    setAnchor(null)
    if (!live()) return
    const f = flow.current
    const c = cmap[f.cid]
    if (c && f.re) { push({ role: 'a', text: `Back to ${c.name}: ${f.re}` }); setQr(f.lastQr) }
    else setQr(f.lastQr && f.lastQr.length ? f.lastQr : startQr())
  }

  async function explainAnchor() {
    const a = anchor
    if (!a || a.kind !== 'span') return
    const live = stamp()
    setMode('chat'); setQr([])
    const id = push({ role: 'ex', title: 'Selection · ' + a.label, loading: true })
    try {
      const d = await api('/explain_spans', { paper_id: pid, span_ids: a.spanIds })
      addSpans(d.new_spans)
      patch(id, { loading: false, sentences: d.sentences })
    } catch (e) { patch(id, { loading: false, error: e.message }) }
    setAnchor(null)
    if (!live()) return
    const f = flow.current
    setQr(f.lastQr && f.lastQr.length ? f.lastQr : startQr())
  }

  async function onSelect(page, rect) {
    if (!pid) return
    try {
      const d = await api('/select', { paper_id: pid, page, rect })
      if (d.kind === 'span') {
        addSpans([d.span])
        setAnchor({ kind: 'span', spanIds: [d.span.id], page, text: d.span.text.slice(0, 240),
          label: refOf(d.span.lines, d.span.page), bbox: d.span.bbox })
      } else {
        setAnchor({ kind: 'region', spanIds: [], page, rect, text: '', label: `area on p${page}`, bbox: rect })
      }
      setMode('chat')
      focusInput()
    } catch (e) { fail(e.message) }
  }

  function jumpSpan(id) {
    const sp = byId[id]
    if (!sp) return
    setCur([id])
    setJump({ page: sp.page, y: sp.bbox[1], t: Date.now() })
  }
  function focusSentence(s) {
    const ids = (s.span_ids || []).filter(i => byId[i])
    setCur(ids)
    if (ids.length) jumpSpan(ids[0])
    else if (s.page) setJump({ page: s.page, y: 0, t: Date.now() })
  }
  function aboutSentence(s) {
    const ids = (s.span_ids || []).filter(i => byId[i])
    setAnchor({ kind: 'span', spanIds: ids, page: s.page, text: s.text, label: refOf(s.lines, s.page),
      bbox: ids.length ? byId[ids[0]].bbox : null })
    setMode('chat')
    focusInput()
  }
  function aboutItem(it) {
    const sp = byId[it.span_id]
    setAnchor({ kind: 'span', spanIds: [it.span_id], page: it.page, text: it.text || it.quote || '',
      label: refOf(it.lines, it.page), bbox: sp ? sp.bbox : null })
    setMode('chat')
    focusInput()
  }
  const jumpPtr = p => { if (p.span_id) jumpSpan(p.span_id) }

  async function verifyKeys(keys) {
    setChecking(c => ({ ...c, ...Object.fromEntries(keys.map(k => [k, true])) }))
    try {
      await api('/verify', { paper_id: pid, keys })
      await refresh()
    } catch (e) { /* the check can be run again when drafting */ }
    setChecking(c => { const n = { ...c }; keys.forEach(k => delete n[k]); return n })
  }

  function nextPart(fromId, st) {
    const i = critList.findIndex(c => c.id === fromId)
    const order = [...critList.slice(i + 1), ...critList.slice(0, Math.max(i, 0))]
    const open = c => !(st && st.criteria[c.id] && st.criteria[c.id].addressed)
    return order.find(c => c.required && open(c)) || order.find(open) || null
  }

  async function askOpen(c) {
    const live = stamp()
    setThinking('Thinking of a question…')
    try {
      const d = await api('/talk', { paper_id: pid, criterion: c.id, history: [], kind: 'open' })
      if (!live()) return
      if (!d.question) offerChoice(c, 'questions')
      else prompt(d.question, baseQr(c), 'ask', d.question, d.source === 'default' ? { why: d.why } : null)
    } catch (e) {
      if (live()) push({ role: 'err', text: String(e.message || e), retry: () => askOpen(c) })
    }
    if (live()) setThinking('')
  }

  async function startPart(cid) {
    const c = cmap[cid]
    if (!c) return
    if (flow.current.cid === cid && flow.current.stage && flow.current.stage !== 'draft') { setMode('chat'); return }
    epoch.current += 1
    setMode('chat'); setCurPart(cid); setQr([]); setThinking('')
    flow.current = { cid, lastQ: '', stage: '', re: '', lastQr: [] }
    const i = critList.findIndex(x => x.id === cid)
    push({ role: 'sys', text: `${c.name} · part ${i + 1} of ${critList.length}` })
    push({ role: 'form', cid })
    const mine = notesRef.current.filter(n => n.field === cid)
    if (mine.length) {
      push({ role: 'a', text: `You already have ${mine.length} point${mine.length > 1 ? 's' : ''} here.` })
      promptConfirm(c)
      return
    }
    await askOpen(c)
  }

  async function startFirst() {
    const nx = nextPart(null, statusRef.current)
    if (!nx) { promptDraft(null); return }
    await startPart(nx.id)
  }

  function promptConfirm(c) {
    prompt(
      c.list ? `What else, if anything, would you add under ${c.tab}?` : 'Anything to add, or shall we move on?',
      [{ l: c.list ? 'Add another' : 'Add more', a: 'more' },
        { l: c.list ? `That's all for ${c.tab}` : 'Move on', p: 1, a: 'done' }],
      'confirm', '', null, c.list ? `What else under ${c.tab}?` : 'Anything to add?')
  }
  function promptScore(c) {
    prompt(`${c.tab} still needs a score. You choose it, and I won't suggest one.`,
      [...c.scale.map(o => ({ l: o.label ? `${o.value} · ${o.label}` : o.value, a: 'score', arg: o.value })),
        { l: 'No comment on this part', a: 'nocomment' }],
      'score', '', null, `Which ${c.tab} score fits?`)
  }
  function promptDraft(nx) {
    prompt('Everything the form requires is covered. Draft your review from your own words?',
      [{ l: 'Draft my review', p: 1, a: 'draft' },
        ...(nx ? [{ l: `Keep going: ${nx.tab}`, a: 'goto', arg: nx.id }] : []),
        { l: 'Show me what is still open', a: 'open' }], 'draft')
  }
  function showOpen() {
    const st = statusRef.current
    const open = critList.filter(c => !(st && st.criteria[c.id] && st.criteria[c.id].addressed))
    if (!open.length) { push({ role: 'a', text: 'Nothing is open.' }); setQr([{ l: 'Draft my review', p: 1, a: 'draft' }]); return }
    prompt('Still open:', open.map(c => ({ l: c.tab, a: 'goto', arg: c.id })), 'draft')
  }

  function afterPoint(c, fr) {
    const val = fr.scores[c.id] && fr.scores[c.id].value
    if (c.type === 'score' && !val) promptScore(c)
    else promptConfirm(c)
  }

  function writeNow() {
    prompt('Go ahead. What would you say this paper is about?',
      [{ l: "Show me the authors' highlights", a: 'highlights' }],
      'ask', 'What would you say this paper is about, in your own words?', null, 'What would you say this paper is about?')
  }

  async function guideRead(pos) {
    const live = stamp()
    raise(follows.current, flow.current.cid, 1)
    const idxs = [walk.findIndex(w => /abstract/i.test(w)), walk.findIndex(w => /introduction/i.test(w))].filter(i => i >= 0)
    if (!idxs.length || pos >= idxs.length) {
      push({ role: 'a', text: 'I have nothing more to walk through here.' })
      writeNow()
      return
    }
    const sec = walk[idxs[pos]]
    const id = push({ role: 'ex', title: sec, loading: true })
    try {
      const d = await api('/explain', { paper_id: pid, section: sec, simpler: false })
      addSpans(d.new_spans)
      patch(id, { loading: false, sentences: d.sentences })
    } catch (e) { patch(id, { loading: false, error: e.message }) }
    if (!live()) return
    const nextName = idxs[pos + 1] !== undefined ? walk[idxs[pos + 1]].replace(/^\d+(\.\d+)*\s*/, '') : null
    prompt('In a sentence or two, what would you say the paper is about?', [
      ...(nextName ? [{ l: `Explain ${nextName} too`, a: 'gread', arg: pos + 1 }] : []),
      { l: "Show me the authors' highlights", a: 'highlights' },
      { l: "I'll write it now", p: 1, a: 'writenow' },
    ], 'ask', 'What would you say this paper is about, in your own words?', null, 'What would you say this paper is about?')
  }

  async function showHighlights(c) {
    const live = stamp()
    raise(follows.current, c.id, 1)
    setThinking("Gathering the authors' own highlights…")
    try {
      const d = await api('/help/highlights', { paper_id: pid })
      if (!live()) return
      if (!d.items.length) {
        push({ role: 'a', text: "I couldn't pull highlights from this paper." })
        promptConfirm(c)
      } else {
        push({ role: 'ex', title: "The authors' own highlights", sentences: d.items.map(i => toSent(i, 'authors_claim')) })
        const have = notesRef.current.some(n => n.field === c.id)
        prompt(have ? 'How, if at all, would you put that in your own words now?'
          : 'Now, in your own words, what would you say this paper is about?',
        have ? [{ l: 'Keep my summary as it is', a: 'skipfu' }] : [{ l: 'No comment on this part', a: 'nocomment' }],
        'ask', 'What would you say this paper is about, in your own words?', null, 'What would you say this paper is about?')
      }
    } catch (e) {
      if (live()) push({ role: 'err', text: String(e.message || e), retry: () => showHighlights(c) })
    }
    if (live()) setThinking('')
  }

  async function showBear(c, t) {
    const live = stamp()
    setThinking('Looking for what the paper says on this…')
    let got = []
    try {
      const d = await api('/help/bear', { paper_id: pid, criterion: c.id, text: t })
      got = d.facts || []
    } catch (e) { got = [] }
    if (!live()) return true
    setThinking('')
    if (!got.length) return false
    push({ role: 'ex', title: 'What the paper says on this', sentences: got.map(i => toSent(i)) })
    prompt('How, if at all, do these bear on your view?',
      [{ l: 'Skip this question', a: 'skipfu' }, { l: "I don't know", a: 'dk' }],
      'ask', 'How, if at all, do these bear on your view?')
    return true
  }

  async function respondTo(c, t) {
    const live = stamp()
    setThinking('Thinking about how to help…')
    let plan = { move: 'followup', sections: [] }
    try { plan = await api('/help/plan', { paper_id: pid, criterion: c.id, text: t }) } catch (e) { /* fall back to a plain follow-up */ }
    if (!live()) return 'stop'
    setThinking('')
    if (plan.move === 'facts') {
      const shownFacts = await showBear(c, t)
      if (!live()) return 'stop'
      return shownFacts ? 'asked' : 'followup'
    }
    if (plan.move === 'walk') { offerWalk(c, plan.sections); return 'asked' }
    if (plan.move === 'none') return 'none'
    return 'followup'
  }

  function offerWalk(c, idxs) {
    exhaust(follows.current, c)
    const clean = w => w.replace(/^(\d+|[A-Z])(\.\d+)*\.?\s+/, '') || w
    const pills = (idxs || []).filter(i => walk[i]).slice(0, 3).map(i => ({ l: clean(walk[i]), a: 'step', arg: i }))
    prompt('Would it help to walk through part of the paper? Pick a section, or ask me about it.',
      [...pills, { l: 'Walk me through from the start', a: 'walk' }, { l: 'Not now', a: 'skipfu' }],
      'ask', '', null, `What else, if anything, would you add under ${c.tab}?`)
  }

  function resume() {
    const c = cmap[flow.current.cid]
    if (!c) { setQr(startQr()); return }
    setMode('chat')
    promptConfirm(c)
  }

  async function askFollow(c, t, kind) {
    const live = stamp()
    const f = flow.current
    setThinking('Thinking of a follow-up…')
    try {
      const d = await api('/talk', { paper_id: pid, criterion: c.id, history: [{ q: f.lastQ || '', a: t }], kind })
      if (!live()) return
      if (!d.question) offerChoice(c, 'questions')
      else prompt(d.question, [{ l: 'Skip this question', a: 'skipfu' }, { l: "I don't know", a: 'dk' }],
        'ask', d.question, d.source === 'default' ? { why: d.why } : null)
    } catch (e) {
      if (live()) push({ role: 'err', text: String(e.message || e) })
    }
    if (live()) setThinking('')
  }

  async function savePoint(uid, t, a) {
    const live = stamp()
    const f = flow.current
    const c = cmap[f.cid]
    const id = Date.now()
    await ev('note_added', {
      id, field: c ? c.id : '', text: t, span_ids: a ? a.spanIds || [] : [], page: a ? a.page : null,
      rect: a && a.kind === 'region' ? a.rect : null, sentence: a ? a.text || '' : '', revisit: false,
      question: f.lastQ || '',
    })
    patch(uid, { noteId: id })
    setAnchor(null)
    if (c && skippedOf(c.id)) await api('/skip', { paper_id: pid, criterion: c.id, skipped: false })
    const fr = await refresh()
    verifyKeys(['n' + id])
    if (!live()) return
    if (!c) {
      prompt('Saved. I will sort it into the form when you draft.',
        [{ l: 'Start the review form', p: 1, a: 'form' }, { l: 'Keep reading', a: 'walk' }], 'free')
      return
    }
    let step = nextFollow(follows.current, c)
    if (step === 'highlights') { await showHighlights(c); return }
    if (step === 'angle') { await askFollow(c, t, 'angle'); return }
    if (step === 'respond') {
      const r = await respondTo(c, t)
      if (r === 'stop' || r === 'asked') return
      if (r === 'none') { afterPoint(c, fr); return }
      step = nextFollow(follows.current, c)
    }
    if (step === 'deeper') { await askFollow(c, t, 'deeper'); return }
    afterPoint(c, fr)
  }

  async function offerClose(c, keep = null) {
    const nx = nextPart(c.id, statusRef.current)
    const mine = notesRef.current.filter(n => n.field === c.id)
    const val = scoresRef.current[c.id] && scoresRef.current[c.id].value
    const keepBtn = keep ? [{ l: 'Save my message as a point', a: 'savemsg', uid: keep.uid, text: keep.text }] : []
    if (c.type === 'score' && c.required && !val && !skippedOf(c.id)) { promptScore(c); return }
    if (!mine.length && !val) {
      prompt(`Mark ${c.tab} as no comment and move on?`,
        [{ l: `Yes, no comment on ${c.tab}`, p: 1, a: 'done' }, { l: 'Add something', a: 'more' }, ...keepBtn], 'offer')
      return
    }
    prompt(nx ? `Move on to ${nx.name}?` : 'Move on?',
      [{ l: nx ? `Move on to ${nx.tab}` : 'Move on', p: 1, a: 'done' }, { l: 'Add more here', a: 'more' }, ...keepBtn], 'offer')
  }

  async function closePart(c, how) {
    const live = stamp()
    if (how === 'skip') await api('/skip', { paper_id: pid, criterion: c.id, skipped: true })
    const fr = await refresh()
    if (!live()) return
    push({ role: 'a', text: how === 'skip' ? `Marked as no comment on ${c.tab}.` : `${c.tab} is done.` })
    const nx = nextPart(c.id, fr.status)
    if (nx && nx.required) { await startPart(nx.id); return }
    promptDraft(nx)
  }
  async function finishPart() {
    const c = cmap[flow.current.cid]
    if (!c) { setQr(startQr()); return }
    const mine = notesRef.current.filter(n => n.field === c.id)
    const val = scoresRef.current[c.id] && scoresRef.current[c.id].value
    if (!mine.length && !val) { await closePart(c, 'skip'); return }
    if (c.type === 'score' && c.required && !val) { promptScore(c); return }
    await closePart(c, 'done')
  }

  async function pickScore(v, silent = false) {
    const live = stamp()
    const c = cmap[flow.current.cid]
    if (!c) return
    const o = c.scale.find(x => x.value === v)
    if (!silent) push({ role: 'u', text: `${c.tab}: ${v}${o && o.label ? ' · ' + o.label : ''}`, plain: true })
    await api('/score', { paper_id: pid, criterion: c.id, value: v,
      reason: (scoresRef.current[c.id] && scoresRef.current[c.id].reason) || '' })
    await refresh()
    if (!live()) return
    push({ role: 'a', text: "Recorded. It's your score." })
    promptConfirm(c)
  }

  // why: 'explain' (reviewer said "I don't know" again) or 'questions' (nothing new left to ask here).
  function offerChoice(c, why = 'explain') {
    const nx = nextPart(c.id, statusRef.current)
    const lead = why === 'questions' ? `I've asked what I can about ${c.tab}.` : `That's okay. I won't explain ${c.tab} again.`
    prompt(`${lead} You can write something in your own words, skip this part, or come back to it later.`,
      choiceOptions(c, nx, why !== 'questions'), 'stayed', '', null, '')
  }

  async function explainPart() {
    const live = stamp()
    const c = cmap[flow.current.cid]
    if (!c) { prompt('Ask me about the paper, or open a part of the form.', startQr(), 'free'); return }
    if (nextDontKnow(dks.current, c.id) === 'choose') { offerChoice(c); return }
    if (c.id === 'summary') { setThinking(''); await guideRead(0); return }
    setThinking('One moment…')
    try {
      const d = await api('/talk', { paper_id: pid, criterion: c.id, history: [], kind: 'explain' })
      if (!live()) return
      push({ role: 'help', text: d.text || d.question })
      const f = flow.current
      if (f.re) push({ role: 'a', text: f.re })
      setQr(f.lastQr && f.lastQr.length ? f.lastQr : baseQr(c))
    } catch (e) { if (live()) push({ role: 'err', text: String(e.message || e) }) }
    if (live()) setThinking('')
  }
  async function angleQ() {
    const live = stamp()
    const c = cmap[flow.current.cid]
    if (!c) return
    setThinking('Thinking of another question…')
    try {
      const d = await api('/talk', { paper_id: pid, criterion: c.id, history: [{ q: flow.current.lastQ || '', a: '' }], kind: 'angle' })
      if (!live()) return
      if (!d.question) offerChoice(c, 'questions')
      else prompt(d.question, baseQr(c), 'ask', d.question, d.source === 'default' ? { why: d.why } : null)
    } catch (e) { if (live()) push({ role: 'err', text: String(e.message || e) }) }
    if (live()) setThinking('')
  }
  function more(c, stayed = false) {
    if (stayed) {
      prompt(`Okay, staying on ${c.tab}. Type a point, or choose below.`,
        [{ l: 'Move on', a: 'done' }, { l: 'No comment on this part', a: 'nocomment' }],
        'stayed', `What would you add under ${c.tab}?`)
      return
    }
    prompt(`Go ahead. What would you add under ${c.tab}?`, [{ l: "Actually, that's all", a: 'done' }],
      'ask', `What would you add under ${c.tab}?`)
  }

  async function send() {
    const t = text.trim()
    if (!t || thinking || !pid) return
    const a = anchor
    const live = stamp()
    setText(''); setQr([]); setErr('')
    const uid = push({ role: 'u', text: t })
    const f = flow.current
    const c = cmap[f.cid]
    setThinking('Reading your message…')
    try {
      if (c && f.stage === 'score') {
        const sv = c.scale.find(o => o.value === t || (o.label && o.label.toLowerCase() === t.toLowerCase()))
        if (sv) {
          patch(uid, { read: 'Read as: your score.' })
          await pickScore(sv.value, true)
          if (live()) setThinking('')
          return
        }
      }
      let it
      try { it = await api('/intent', { paper_id: pid, text: t, criterion: f.cid, last_q: f.lastQ, stage: f.stage }) }
      catch (e) { it = { intent: 'unread', goto: null } }
      switch (it.intent) {
        case 'answer':
          await savePoint(uid, t, a); break
        case 'done': {
          const extra = it.via === 'model' && t.split(/\s+/).length > 3
          patch(uid, { read: c ? `Read as: done with ${c.name}. Not saved as a point.` : 'Read as: done.' })
          if (c) await offerClose(c, extra ? { uid, text: t } : null)
          else if (walkAt >= 0 && walkAt < walk.length - 1) await step(walkAt + 1)
          else prompt('Okay. What would you like to do next?', startQr(), 'free')
          break
        }
        case 'dontknow':
          patch(uid, { read: 'Read as: not sure. Not saved as a point.' })
          await explainPart(); break
        case 'question':
          patch(uid, { read: 'Read as: a question about the paper. Not saved as a point.' })
          await askPaper(t, a); break
        case 'goto':
          patch(uid, { read: 'Read as: moving to another part.' })
          if (it.goto === 'draft') { setMode('draft'); setQr([]) }
          else if (it.goto) await startPart(it.goto)
          break
        case 'add_more':
          patch(uid, { read: 'Read as: yes, add more.' })
          if (c) more(c)
          break
        case 'nothing_to_add':
          patch(uid, { read: 'Read as: nothing to add. Not saved as a point.' })
          if (c) await offerClose(c)
          break
        case 'move_on':
          patch(uid, { read: 'Read as: yes, move on.' })
          await finishPart()
          break
        case 'stay':
          patch(uid, { read: 'Read as: stay here.' })
          if (c) more(c, true)
          break
        case 'draft_now':
          patch(uid, { read: 'Read as: yes, draft it.' })
          setMode('draft'); draftAll()
          break
        case 'unclear':
          patch(uid, { read: 'Read as: not an answer to the question.' })
          setQr(f.lastQr && f.lastQr.length ? f.lastQr : startQr())
          break
        case 'unread':
          patch(uid, { read: 'Could not read this just now. Not saved.' })
          push({ role: 'a', text: "I couldn't read that just now, so I haven't saved it. You can save it as a point yourself, or send it again." })
          setQr([{ l: 'Save it as a point', p: 1, a: 'savemsg', uid, text: t, anchor: a },
            ...(f.lastQr && f.lastQr.length ? f.lastQr : startQr())])
          break
        default:
          patch(uid, { read: 'Read as: not an answer to the question.' })
          push({ role: 'a', text: 'I can answer questions about the paper, or ask about the next part of the form.' })
          if (f.re && c) push({ role: 'a', text: `Back to ${c.name}: ${f.re}` })
          setQr(f.lastQr && f.lastQr.length ? f.lastQr : startQr())
      }
    } catch (e) { push({ role: 'err', text: String(e.message || e) }) }
    if (live()) setThinking('')
  }

  async function onQr(q) {
    setQr([])
    const c = cmap[flow.current.cid]
    try {
      switch (q.a) {
        case 'walk': await step(0); break
        case 'step': await step(q.arg, !!q.simpler); break
        case 'brief': setMode('brief'); break
        case 'form': await startFirst(); break
        case 'goto': await startPart(q.arg); break
        case 'draftview': setMode('draft'); break
        case 'draft': setMode('draft'); draftAll(); break
        case 'open': showOpen(); break
        case 'dk': push({ role: 'u', text: "I don't know", plain: true }); await explainPart(); break
        case 'angle': push({ role: 'u', text: 'Ask something else', plain: true }); await angleQ(); break
        case 'gread': push({ role: 'u', text: q.l, plain: true }); await guideRead(q.arg); break
        case 'highlights': push({ role: 'u', text: q.l, plain: true }); if (c) await showHighlights(c); break
        case 'writenow': push({ role: 'u', text: q.l, plain: true }); writeNow(); break
        case 'resume': push({ role: 'u', text: q.l, plain: true }); resume(); break
        case 'nocomment':
          push({ role: 'u', text: 'No comment on this part', plain: true })
          if (c) await closePart(c, 'skip')
          break
        case 'skipfu':
          push({ role: 'u', text: q.l, plain: true })
          if (c) { exhaust(follows.current, c); afterPoint(c, { scores: scoresRef.current }) }
          break
        case 'savemsg':
          patch(q.uid, { read: '' })
          await savePoint(q.uid, q.text, q.anchor || null)
          break
        case 'done': push({ role: 'u', text: q.l, plain: true }); await finishPart(); break
        case 'more': push({ role: 'u', text: q.l, plain: true }); if (c) more(c); break
        case 'score': await pickScore(q.arg); break
        default: break
      }
    } catch (e) { push({ role: 'err', text: String(e.message || e) }) }
  }

  function saveEdit() {
    const e = edit
    const t = e.text.trim()
    if (!t) { fail('Write something first.'); return }
    run('Saving…', async () => {
      if (e.kind === 'note') {
        const n = notes.find(x => x.id === e.id)
        if (n && t !== n.text) await ev('note_text_edited', { id: e.id, text: t })
      } else {
        await ev('draft_edited', { field: e.cid, idx: e.idx, text: t })
      }
      setEdit(null)
      await refresh()
      if (e.kind === 'note') verifyKeys(['n' + e.id])
    })
  }
  const removeNote = n => run('Saving…', async () => { await ev('note_removed', { id: n.id }); await refresh() })
  function saveDispute() {
    const reason = (dispute.text || '').trim()
    if (!reason) { fail('Write why you disagree with the check.'); return }
    run('Saving…', async () => {
      await api('/dispute', { paper_id: pid, key: dispute.key, reason })
      setDispute(null)
      await refresh()
    })
  }

  function draftAll() {
    const edited = Object.values(draft).some(d => d.sentences.some(s => s.edits))
    if (edited && !window.confirm('Drafting again replaces the sentences you edited. Earlier versions stay in the history. Continue?')) return
    run('Checking facts and drafting each part. This can take about a minute.', async () => {
      const r = await api('/draft', { paper_id: pid, mode: 'smooth', field: null })
      setDraft(r.draft); setAsks(r.asks || [])
      await refresh()
      if (r.blocked) {
        const parts = []
        if (r.missing.length) parts.push(`Still to address: ${r.missing.map(m => m.tab).join(', ')}.`)
        if (r.conflicts.length) parts.push(`${r.conflicts.length} point${r.conflicts.length > 1 ? 's' : ''} conflict with the paper. Fix or remove them first.`)
        fail('The review can’t be drafted yet. ' + parts.join(' '))
      }
    })
  }
  function sortOnly() {
    run('Sorting your notes…', async () => {
      const r = await api('/sort', { paper_id: pid })
      setAsks(r.asks || [])
      await refresh()
    })
  }
  function copyReview() {
    run('Checking the review before copying…', async () => {
      const r = await api(`/finish/${pid}`, {})
      await refresh()
      if (!r.ok) {
        const parts = []
        if (r.missing.length) parts.push(`Still to address: ${r.missing.map(m => m.tab).join(', ')}.`)
        if (r.conflicts.length) parts.push(`${r.conflicts.length} point${r.conflicts.length > 1 ? 's' : ''} conflict with the paper.`)
        fail('The review can’t be copied yet. ' + parts.join(' '))
        return
      }
      setFinished(true)
      try { await copy(wholeText()) } catch (e) { fail('Could not copy automatically. Select the text and copy it.') }
    })
  }
  function answerAsk(a, t, field, dismiss) {
    if (dismiss) { setAsks(x => x.filter(y => y.key !== a.key)); return }
    if (!t && !field) { fail('Write an answer or choose a part first.'); return }
    run('Saving…', async () => {
      const id = Number(a.key.slice(1))
      const isNote = a.key[0] === 'n'
      if (t) await ev(isNote ? 'note_answer_added' : 'answer_added', { id, question: a.question, text: t })
      if (field) await ev(isNote ? 'note_field_set' : 'field_assigned', { id, field, by: 'user' })
      setAsks(x => x.filter(y => y.key !== a.key))
      await refresh()
    })
  }
  function buildBrief(force = false) {
    run('Building the brief. This takes about 30 seconds.', async () => {
      const b = await api('/brief', { paper_id: pid, force })
      setBrief(b)
    })
  }

  const noteFull = n => [n.text, ...(n.answers || []).map(a => a.text)].filter(Boolean).join(' ')
  const noteRef = n => {
    const sp = byId[(n.span_ids || []).find(i => byId[i])]
    return sp ? refOf(sp.lines, sp.page) : (n.page ? `p${n.page}` : '')
  }
  function jumpNote(n) {
    const id = (n.span_ids || []).find(i => byId[i])
    if (id) jumpSpan(id)
    else if (n.page) setJump({ page: n.page, y: n.rect ? n.rect[1] : 0, t: Date.now() })
  }
  function keyInfo(key) {
    if (key.startsWith('s:')) {
      const cid = key.slice(2)
      const sc = scores[cid]
      return sc && sc.reason ? { label: 'Your score reason', text: sc.reason, ref: '', cid } : null
    }
    const n = notes.find(x => x.id === Number(key.slice(1)))
    return n ? { label: 'Your note', text: noteFull(n), ref: noteRef(n), note: n } : null
  }
  function jumpKey(k) {
    const ki = keyInfo(k)
    if (!ki) return
    if (ki.note && (ki.note.span_ids || []).some(i => byId[i])) jumpSpan(ki.note.span_ids.find(i => byId[i]))
    else if (ki.cid) startPart(ki.cid)
    else if (ki.note && ki.note.field) startPart(ki.note.field)
  }
  function startFix(key) {
    if (key.startsWith('s:')) { startPart(key.slice(2)); return }
    const n = notes.find(x => x.id === Number(key.slice(1)))
    if (n) setEdit({ kind: 'note', id: n.id, text: n.text })
  }
  const refsOf = s => [...new Set((s.src || []).map(k => { const i = keyInfo(k); return i && i.ref }).filter(Boolean))].join(', ')
  const labelOf = (c, v) => { const o = c.scale.find(x => x.value === v); return o && o.label ? ` · ${o.label}` : '' }
  function textFor(c) {
    const d = draft[c.id]
    const sc = scores[c.id]
    const mine = notes.filter(n => n.field === c.id)
    const useDraft = d && d.sentences.length && !own[c.id]
    const items = useDraft
      ? d.sentences.map(s => s.text + (refs && refsOf(s) ? ` (${refsOf(s)})` : ''))
      : mine.map(noteFull)
    const body = c.list && items.length > 1 ? items.map((t, i) => `${i + 1}. ${t}`).join('\n')
      : items.join(useDraft ? ' ' : '\n\n')
    const line = c.type === 'score' && sc && sc.value ? `Score: ${sc.value}${labelOf(c, sc.value)}` : ''
    return [line, body].filter(Boolean).join('\n')
  }
  const wholeText = () => critList.map(c => { const t = textFor(c); return t ? `${c.name}\n${t}` : null }).filter(Boolean).join('\n\n')
  const DISCLOSURE = 'I used an AI assistant to explain parts of the paper, to check my statements against it, and to smooth the wording of notes I wrote. The judgments and the content of the review are my own.'

  const conflicts = Object.keys(facts).filter(k =>
    keyInfo(k) && (facts[k].pointers || []).some(p => p.kind === 'contradicts') && !facts[k].disputed)

  const hls = []
  cur.forEach(id => byId[id] && hls.push({ page: byId[id].page, bbox: byId[id].bbox, cls: 'cur' }))
  if (anchor && anchor.bbox) hls.push({ page: anchor.page, bbox: anchor.bbox, cls: 'anchor' })

  function onGripDown(e) { e.currentTarget.setPointerCapture(e.pointerId); dragging.current = true }
  function onGripMove(e) {
    if (!dragging.current) return
    setWidth(Math.max(MIN_W, Math.min(window.innerWidth * 0.72, window.innerWidth - e.clientX - GRIP_HALF)))
  }
  function onGripKey(e) {
    if (e.key === 'ArrowLeft') setWidth(w => Math.min(window.innerWidth * 0.72, w + 24))
    if (e.key === 'ArrowRight') setWidth(w => Math.max(MIN_W, w - 24))
  }

  const editor = () => (
    <div>
      <textarea value={edit.text} autoFocus onChange={e => setEdit({ ...edit, text: e.target.value })} />
      <div className="row">
        <button className="btn primary" onClick={saveEdit}>Save</button>
        <button className="btn" onClick={() => setEdit(null)}>Cancel</button>
      </div>
    </div>
  )

  function renderConflict(key) {
    const f = facts[key]
    if (!f) return null
    const bad = (f.pointers || []).filter(p => p.kind === 'contradicts')
    if (!bad.length) return null
    if (f.disputed) return <div className="muted">You disagreed with the check: “{f.disputed}”</div>
    const dsp = dispute && dispute.key === key
    return (
      <div className="conflict">
        <b>This conflicts with the paper</b>
        {bad.map((p, i) => (
          <div key={i}>
            <div className="quote">{p.paper_quote}</div>
            <div className="small">{p.explanation}</div>
            <button className="chip" onClick={() => jumpPtr(p)}>Paper · {refOf(p.lines, p.page)}</button>
          </div>
        ))}
        <div className="small">Change your point so it matches the paper, or remove it. The review can’t be drafted while this stands.</div>
        {dsp ? (
          <div>
            <div className="small">Say why the check is wrong. Your reason is saved with the review history.</div>
            <textarea autoFocus value={dispute.text} onChange={e => setDispute({ ...dispute, text: e.target.value })} />
            <div className="row">
              <button className="btn primary" onClick={saveDispute}>Save my reason</button>
              <button className="btn" onClick={() => setDispute(null)}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="row">
            <button className="btn" onClick={() => startFix(key)}>Edit my point</button>
            {allowDispute && <button className="btn quiet" onClick={() => setDispute({ key, text: '' })}>I disagree with this check</button>}
          </div>
        )}
      </div>
    )
  }

  function renderUser(m) {
    const n = m.noteId ? notes.find(x => x.id === m.noteId) : null
    const key = m.noteId ? 'n' + m.noteId : ''
    const ed = !!(edit && edit.kind === 'note' && m.noteId && edit.id === m.noteId)
    const c = n ? cmap[n.field] : null
    const info = key ? ((facts[key] && facts[key].pointers) || []).filter(p => p.kind !== 'contradicts') : []
    return (
      <div className="urow" key={m.id}>
        <div className="u">{ed ? editor() : (n ? n.text : m.text)}</div>
        <div className="meta">
          {m.read && <span>{m.read}</span>}
          {m.noteId && n && !ed && (
            <>
              <span><b>Saved</b>{c ? ` under ${c.name}` : ' (not sorted yet)'}{n.edits ? ` · edited ${n.edits}x` : ''}{checking[key] ? ' · checking against the paper…' : ''}</span>
              <button className="lk" onClick={() => setEdit({ kind: 'note', id: n.id, text: n.text })}>Edit</button>
              <button className="lk" onClick={() => removeNote(n)}>Undo</button>
            </>
          )}
          {m.noteId && !n && <span>Removed</span>}
        </div>
        {m.noteId && n && renderConflict(key)}
        {m.noteId && n && <Ptrs list={info} onJump={jumpPtr} />}
      </div>
    )
  }

  function renderSentence(s, key) {
    const [cls, label] = chipOf(s)
    const quote = s.quote || (s.source === 'image' ? 'No exact text: this comes from a picture.' : 'A background definition, not from the paper.')
    return (
      <div className="sent" key={key}>
        <div className="stext">{s.text}</div>
        <div className="srow">
          <button className={'chip ' + cls} title="Show the exact text and jump to it"
            onClick={() => { focusSentence(s); setShown(o => ({ ...o, [key]: !o[key] })) }}>{label}</button>
          <span className="acts">
            <button className="btn quiet" onClick={() => aboutSentence(s)}>Ask or note about this</button>
          </span>
        </div>
        {shown[key] && <div className="quote">{quote}</div>}
      </div>
    )
  }

  function renderMsg(m) {
    switch (m.role) {
      case 'sys': return <div className="sys" key={m.id}>{m.text}</div>
      case 'form': {
        const c = cmap[m.cid]
        if (!c) return null
        const open = shown['form' + m.id]
        return (
          <div className="formw" key={m.id}>
            {c.has_definition ? (
              <>
                {firstSentence(c.definition)}{' '}
                <button className="lk" onClick={() => setShown(o => ({ ...o, ['form' + m.id]: !o['form' + m.id] }))}>{open ? 'Hide form wording' : 'Form wording'}</button>
                {open && (
                  <div>
                    <div className="deftext">{c.definition}</div>
                    {crit.source && <div className="muted" style={{ marginTop: 4 }}>From the venue's review form{crit.version ? ` · ${crit.version}` : ''} · <a href={crit.source} target="_blank" rel="noreferrer">source</a></div>}
                  </div>
                )}
              </>
            ) : 'The venue\'s wording for this part has not been added yet.'}
          </div>
        )
      }
      case 'a':
        return (
          <div className="a" key={m.id}>
            {m.text}
            {m.why && <div className="muted">A generic question: {m.why}</div>}
          </div>
        )
      case 'help':
        return <div className="help" key={m.id}><div className="lab">What this part of the form asks for</div>{m.text}</div>
      case 'u': return m.plain ? <div className="urow" key={m.id}><div className="u">{m.text}</div></div> : renderUser(m)
      case 'err':
        return (
          <div className="errbar" key={m.id}>
            <span>{m.text}</span>
            {m.retry && <button className="btn" onClick={m.retry}>Retry</button>}
          </div>
        )
      case 'ex':
        return (
          <div className="ex" key={m.id}>
            {m.title && <div className="mtitle">{m.step !== undefined && <span className="stepn">Step {m.step + 1} of {walk.length}</span>}{m.title}</div>}
            {m.loading && <div className="muted working">Working. This can take up to 30 seconds.</div>}
            {m.error && <div className="errbar"><span>{m.error}</span></div>}
            {m.declined && <div className="declined">{m.declined}</div>}
            {m.sentences && m.sentences.length === 0 && !m.declined && !m.loading && !m.error && (
              <div className="muted">Nothing found in the paper for that.</div>
            )}
            {(m.sentences || []).map((s, i) => renderSentence(s, m.id + '-' + i))}
          </div>
        )
      default: return null
    }
  }

  function renderBrief() {
    const building = busy.startsWith('Building the brief')
    return (
      <div className="view">
        <h2 className="ttl">Paper brief</h2>
        <div className="muted">What the authors put forward, in the paper's own order. It is their emphasis, not ours. Built once and saved.</div>
        {(brief === undefined || building) && <div className="muted working" style={{ marginTop: 12 }}>Building the brief. This takes about 30 seconds.</div>}
        {brief === null && !building && (
          <div className="row"><button className="btn primary" onClick={() => buildBrief(false)}>{err ? 'Try again' : 'Build the brief'}</button></div>
        )}
        {brief && brief.groups.map(g => (
          <div key={g.title}>
            <div className="bgrp">{g.title}</div>
            {g.items.length === 0 && <div className="muted">Nothing found.</div>}
            {g.items.map((it, i) => (
              <div className="bit" key={i}>
                <div className="stext">{it.text}</div>
                <div className="srow">
                  <button className="chip auth" onClick={() => jumpSpan(it.span_id)}>Authors · {refOf(it.lines, it.page)}</button>
                  <button className="btn quiet" onClick={() => aboutItem(it)}>Note about this</button>
                </div>
              </div>
            ))}
          </div>
        ))}
        {brief && <div className="row"><button className="btn quiet" onClick={() => buildBrief(true)}>Rebuild the brief</button></div>}
      </div>
    )
  }

  function renderOwn(n) {
    const key = 'n' + n.id
    const ed = edit && edit.kind === 'note' && edit.id === n.id
    return (
      <div className="own" key={n.id}>
        {noteRef(n) && <button className="chip you" onClick={() => jumpNote(n)}>{noteRef(n)}</button>}
        {ed ? editor() : <div className="pre">{n.text}</div>}
        {renderConflict(key)}
        {!ed && (
          <div className="row">
            <button className="btn quiet" onClick={() => setEdit({ kind: 'note', id: n.id, text: n.text })}>Edit</button>
            <button className="btn quiet" onClick={() => removeNote(n)}>Remove</button>
          </div>
        )}
      </div>
    )
  }

  function renderDraftItem(c, s, i) {
    const ed = edit && edit.kind === 'draft' && edit.cid === c.id && edit.idx === i
    return (
      <>
        {ed ? editor() : <div>{s.text}{s.edits ? <span className="muted"> · edited {s.edits}x</span> : null}</div>}
        <div className="srow">
          {(s.src || []).map(k => {
            const ki = keyInfo(k)
            return ki ? <button key={k} className="chip you" onClick={() => jumpKey(k)}>{ki.label}{ki.ref ? ` · ${ki.ref}` : ''}</button> : null
          })}
          {!ed && <button className="btn quiet" onClick={() => setEdit({ kind: 'draft', cid: c.id, idx: i, text: s.text })}>Edit</button>}
        </div>
        {(s.versions || []).length > 0 && (
          <details className="ptr"><summary>Earlier versions</summary>
            {s.versions.map((v, j) => <div className="small" key={j}>{v.old}</div>)}
          </details>
        )}
      </>
    )
  }

  function renderDraft() {
    const missing = status ? status.missing : []
    const ready = missing.length === 0 && conflicts.length === 0
    const unsorted = notes.filter(n => !n.field)
    const drafted = Object.values(draft).some(d => d.sentences.length)
    return (
      <div className="view">
        <h2 className="ttl">Your review</h2>
        <div className="muted">Smoothed from your own words. Nothing is added, and every sentence shows the points it came from.</div>

        <div className={'box ' + (ready ? 'mint' : 'peach')}>
          <b>{ready ? 'Ready to draft' : 'Before you can draft'}</b>
          {missing.length > 0 && (
            <div>
              <div className="muted">Required parts still to address</div>
              <div className="row">
                {missing.map(m => <button key={m.id} className="pill" onClick={() => startPart(m.id)}>{m.tab}</button>)}
              </div>
            </div>
          )}
          {conflicts.length > 0 && (
            <div>
              <div className="muted">Points that conflict with the paper</div>
              {conflicts.map(k => {
                const ki = keyInfo(k)
                return (
                  <div key={k} className="bit">
                    <div className="muted">{ki.label}: “{ki.text.slice(0, 150)}{ki.text.length > 150 ? '…' : ''}”</div>
                    {renderConflict(k)}
                  </div>
                )
              })}
            </div>
          )}
          {unsorted.length > 0 && <div className="muted">{unsorted.length} point{unsorted.length > 1 ? 's' : ''} not sorted yet. Drafting sorts them first.</div>}
          <div className="row">
            <button className="btn primary" onClick={draftAll}>{drafted ? 'Draft again' : 'Draft my review'}</button>
            {unsorted.length > 0 && <button className="btn" onClick={sortOnly}>Sort my notes now</button>}
          </div>
        </div>

        {asks.length > 0 && (
          <div className="box peach">
            <b>Questions about your notes</b>
            <div className="muted">The assistant could not tell where these belong.</div>
            {asks.map(a => <AskCard key={a.key} a={a} crits={critList} onSave={answerAsk} />)}
          </div>
        )}

        {critList.map(c => {
          const d = draft[c.id]
          const sc = scores[c.id]
          const mine = notes.filter(n => n.field === c.id)
          const has = d && d.sentences.length > 0
          const showDraft = has && !own[c.id]
          const t = textFor(c)
          return (
            <section className="asm" key={c.id}>
              <div className="row" style={{ margin: 0 }}>
                <h3 className="asmh">{c.name}</h3>
                <span className="grow" />
                {has && <button className="btn quiet" onClick={() => setOwn(o => ({ ...o, [c.id]: !o[c.id] }))}>{own[c.id] ? 'Show the smoothed version' : 'Show my own words'}</button>}
                {t && <button className="btn quiet" onClick={() => copy(t)}>Copy</button>}
                <button className="btn quiet" onClick={() => startPart(c.id)}>Open in chat</button>
              </div>
              {c.type === 'score' && sc && sc.value && <div className="scoreline">Score: {sc.value}{labelOf(c, sc.value)}</div>}
              {showDraft && d.fallback && <div className="muted">A checked draft could not be built, so this shows your points exactly as written.</div>}
              {showDraft && (c.list && d.sentences.length > 1
                ? <ol>{d.sentences.map((s, i) => <li key={i}>{renderDraftItem(c, s, i)}</li>)}</ol>
                : d.sentences.map((s, i) => <div className="dsent" key={i}>{renderDraftItem(c, s, i)}</div>))}
              {!showDraft && mine.length > 0 && (
                <>
                  {!has && <div className="muted">Not drafted yet. Your points:</div>}
                  {mine.map(renderOwn)}
                </>
              )}
              {!showDraft && mine.length === 0 && skippedOf(c.id) && <div className="muted">No comment.</div>}
              {!showDraft && mine.length === 0 && !skippedOf(c.id) && !(sc && sc.value) && <div className="muted">Nothing here yet.</div>}
            </section>
          )
        })}

        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn primary" onClick={copyReview}>Copy review</button>
          <label className="chk"><input type="checkbox" checked={refs} onChange={e => setRefs(e.target.checked)} /> Include line references</label>
        </div>
        {finished && <div className="box mint">Copied. The review passed every check.</div>}
        <details className="ptr" style={{ marginTop: 12 }}>
          <summary>Suggested AI-use disclosure</summary>
          <div className="quote">{DISCLOSURE}</div>
          <button className="btn quiet" onClick={() => copy(DISCLOSURE)}>Copy</button>
          <div className="muted">Check what your venue requires, and edit this to match how you actually used the tool.</div>
        </details>
      </div>
    )
  }

  let content
  if (!pid) {
    content = (
      <div className="view">
        <h2 className="ttl">Review a paper</h2>
        <div className="muted">Upload the paper you are reviewing. Read it with the assistant, answer its questions in your own words, and the review is built from what you say.</div>
        <div className="row"><button className="btn primary" onClick={() => fileRef.current.click()}>Upload paper</button></div>
      </div>
    )
  } else if (mode === 'brief') content = renderBrief()
  else if (mode === 'draft') content = renderDraft()
  else {
    content = (
      <div className="chat">
        {msgs.map(renderMsg)}
        {thinking && <div className="thinking working">{thinking}</div>}
        <div ref={endRef} />
      </div>
    )
  }

  const curName = curPart && cmap[curPart] ? cmap[curPart].name : null
  const curIdx = curPart ? critList.findIndex(c => c.id === curPart) : -1

  return (
    <div className="app">
      <header className="top">
        <span className="logo">Reviewer co-pilot</span>
        {crit && <span className="venue">{crit.venue}{crit.version ? ` · ${crit.version}` : ''}</span>}
        <span className="grow" />
        {pid && (
          <div className="modes" role="group" aria-label="View">
            <button className={mode === 'chat' ? 'on' : ''} onClick={() => setMode('chat')}>Chat</button>
            <button className={mode === 'brief' ? 'on' : ''} onClick={() => setMode('brief')}>Paper brief</button>
            <button className={mode === 'draft' ? 'on' : ''} onClick={() => setMode('draft')}>Review draft</button>
          </div>
        )}
        <button className="btn" onClick={() => fileRef.current.click()}>{pid ? 'Upload another paper' : 'Upload paper'}</button>
        <input ref={fileRef} type="file" accept="application/pdf" hidden onChange={e => { upload(e.target.files[0]); e.target.value = '' }} />
      </header>
      <div className="main">
        <div className="left"><Viewer url={url} hls={hls} onSelect={onSelect} jump={jump} /></div>
        <div className="grip" role="separator" aria-orientation="vertical" aria-label="Resize the panel" tabIndex={0}
          onPointerDown={onGripDown} onPointerMove={onGripMove} onPointerUp={() => { dragging.current = false }} onKeyDown={onGripKey}><i /></div>
        <aside className="panel" style={{ width }}>
          {pid && status && (
            <div className="rail">
              <div className="rt">
                {curName && mode === 'chat' ? <><b>{curName}</b> · part {curIdx + 1} of {critList.length}</> : <b>Review progress</b>}
                {' · '}{status.started} of {status.total} started
                {conflicts.length > 0 && <span className="bad"> · {conflicts.length} point{conflicts.length > 1 ? 's' : ''} conflict with the paper</span>}
              </div>
              <div className="strip">
                {critList.map(c => (
                  <button key={c.id} className={'seg ' + stOf(c.id) + (skippedOf(c.id) ? ' skp' : '') + (curPart === c.id && mode === 'chat' ? ' cur' : '')}
                    title={`${c.tab}: ${skippedOf(c.id) ? 'no comment' : stOf(c.id)}`}
                    aria-label={`${c.tab}, ${skippedOf(c.id) ? 'no comment' : stOf(c.id)}`} onClick={() => startPart(c.id)} />
                ))}
              </div>
            </div>
          )}
          {busy && <div className="busy" role="status"><div className="indet" /><span>{busy}</span></div>}
          <div className="body">
            {err && (
              <div className="errbar" style={{ marginBottom: 12 }}>
                <span>{err}</span>
                {retry && <button className="btn" onClick={retry}>Retry</button>}
                <button className="btn quiet" onClick={() => { setErr(''); setRetry(null) }}>Dismiss</button>
              </div>
            )}
            {crit && crit.error && <div className="errbar" style={{ marginBottom: 12 }}><span>The criteria file has a problem: {crit.error}</span></div>}
            {content}
          </div>
          {pid && mode === 'chat' && (
            <>
              <div className="qr">
                {qr.map((q, i) => <button key={i} className={'pill' + (q.p ? ' p' : '')} onClick={() => onQr(q)}>{q.l}</button>)}
              </div>
              <div className="composer">
                {anchor && (
                  <div className="anchor">
                    <span className="muted">About</span>
                    <button className="chip" onClick={() => (anchor.spanIds && anchor.spanIds[0]
                      ? jumpSpan(anchor.spanIds[0])
                      : setJump({ page: anchor.page, y: anchor.rect ? anchor.rect[1] : 0, t: Date.now() }))}>{anchor.label}</button>
                    <span className="atext">{anchor.text ? anchor.text.slice(0, 100) : ''}</span>
                    {anchor.kind === 'span' && <button className="btn quiet" onClick={explainAnchor}>Explain</button>}
                    {anchor.kind === 'region' && <button className="btn quiet" onClick={() => { push({ role: 'u', text: 'What does this show?', plain: true }); askPaper('What does this show?', anchor) }}>What does this show?</button>}
                    <button className="btn quiet" aria-label="Clear the selection" onClick={() => setAnchor(null)}>×</button>
                  </div>
                )}
                <div className="cbox">
                  <textarea ref={inputRef} value={text} rows={2}
                    placeholder={curName ? 'Answer in your own words, or ask about the paper' : 'Answer, or ask about the paper'}
                    onChange={e => setText(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }} />
                  <button className="send" onClick={send}>Send</button>
                </div>
                <div className="chint"><span>{curName ? `Writing under ${curName}` : 'Not in a part of the form'}</span><span>Enter to send · Shift+Enter for a new line</span></div>
              </div>
            </>
          )}
        </aside>
      </div>
    </div>
  )
}