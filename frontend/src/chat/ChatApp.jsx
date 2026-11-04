import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import ChatView from './ChatView.jsx'
import { createApi } from './api.js'
import { createController, browserStorage } from './controller.js'
import { buildSections, copyText, editEvent } from './draftModel.js'

const DRAFT_NOTES = {
  noPaper: 'Attach a paper and your draft will appear here.',
  loadFailed: "I couldn't load the draft. Close and reopen it to try again.",
  saveFailed: "That edit didn't save. Edit it again to retry.",
}

// Wires the controller (the conversation) and the draft panel to the page. All behaviour lives in controller.js
// and draftModel.js; this file only holds React state for the text box, drag and drop, and the draft panel.
export default function ChatApp() {
  const api = useMemo(() => createApi(), [])
  const controller = useMemo(() => createController({ api, storage: browserStorage() }), [api])
  const state = useSyncExternalStore(controller.subscribe, controller.getState)

  const [text, setText] = useState('')
  const [dragging, setDragging] = useState(false)
  const [draftOpen, setDraftOpen] = useState(false)
  const [draft, setDraft] = useState({ sections: [], note: '', copied: false })
  const inputRef = useRef(null)
  const criteria = useRef(null)

  useEffect(() => { controller.start() }, [controller])

  const loadDraft = useCallback(async () => {
    if (!state.paperId) return
    if (!criteria.current) {
      const c = await api.criteria()
      if (c.ok && c.data && c.data.criteria) criteria.current = c.data.criteria
    }
    const [n, g] = await Promise.all([api.notes(state.paperId), api.draft(state.paperId)])
    if (!criteria.current || !n.ok || !g.ok) { setDraft(d => ({ ...d, note: DRAFT_NOTES.loadFailed })); return }
    setDraft(d => ({ ...d, note: '', sections: buildSections(criteria.current, n.data, g.data) }))
  }, [api, state.paperId])

  useEffect(() => { if (draftOpen) loadDraft() }, [draftOpen, loadDraft, state.draftVersion])

  const send = useCallback(async () => {
    const r = await controller.send(text)
    if (r.clear) setText('')
    if (inputRef.current) inputRef.current.focus()
  }, [controller, text])

  const selected = useMemo(() => {
    const labels = new Set(text.split(',').map(s => s.trim()).filter(Boolean))
    return new Set((state.menu || []).filter(o => labels.has(o.label)).map(o => o.label))
  }, [text, state.menu])

  // A chip toggles its label in the text box (so several can be picked); "Other, in my words" just opens the box.
  const onChip = useCallback(option => {
    if (option.id === 'other') { if (inputRef.current) inputRef.current.focus(); return }
    const parts = text.split(',').map(s => s.trim()).filter(Boolean)
    const next = parts.includes(option.label) ? parts.filter(p => p !== option.label) : [...parts, option.label]
    setText(next.join(', '))
    if (inputRef.current) inputRef.current.focus()
  }, [text])

  const onEditItem = useCallback(async (item, value) => {
    const ev = editEvent(item, value)
    if (!ev) return
    const r = await api.event(state.paperId, ev.type, ev.payload)
    if (!r.ok) { setDraft(d => ({ ...d, note: DRAFT_NOTES.saveFailed })); return }
    await loadDraft()
  }, [api, state.paperId, loadDraft])

  const onCopy = useCallback(async () => {
    const all = copyText(draft.sections)
    try { await navigator.clipboard.writeText(all) } catch {
      const t = document.createElement('textarea')
      t.value = all
      document.body.appendChild(t)
      t.select()
      try { document.execCommand('copy') } finally { document.body.removeChild(t) }
    }
    setDraft(d => ({ ...d, copied: true }))
    setTimeout(() => setDraft(d => ({ ...d, copied: false })), 1500)
  }, [draft.sections])

  const hasFiles = e => Array.from((e.dataTransfer && e.dataTransfer.types) || []).includes('Files')
  const dragHandlers = {
    onDragEnter: e => { if (hasFiles(e)) { e.preventDefault(); setDragging(true) } },
    onDragOver: e => { if (hasFiles(e)) e.preventDefault() },
    onDragLeave: e => { if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget)) setDragging(false) },
    onDrop: e => {
      if (!hasFiles(e)) return
      e.preventDefault()
      setDragging(false)
      const f = e.dataTransfer.files && e.dataTransfer.files[0]
      if (f) controller.attach(f)
    },
  }

  return (
    <ChatView state={state} text={text} onText={setText} onSend={send} onAttach={controller.attach}
      onChip={onChip} selected={selected} inputRef={inputRef} dragging={dragging} dragHandlers={dragHandlers}
      draftOpen={draftOpen} onToggleDraft={() => setDraftOpen(o => !o)}
      draft={state.paperId ? draft : { ...draft, sections: [], note: DRAFT_NOTES.noPaper }}
      onEditItem={onEditItem} onCopy={onCopy} />
  )
}
