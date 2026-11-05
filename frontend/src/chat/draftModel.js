// The review draft as the side panel shows it: by review-form section, each section a list of editable paragraphs.
// Free of React so it can be tested. A paragraph is either one of the reviewer's notes (captured in chat) or one
// sentence of a generated draft ("draft it"); a section shows the generated sentences once there are any,
// otherwise its notes (plus any note added since the draft was made).

export const LEGACY = { P: 'summary', S: 'strengths', W: 'weaknesses', Q: 'comments' }
export const UNPLACED = { id: '', name: 'Not placed in a section yet' }

export function buildSections(criteria, notes, draft) {
  const forms = (criteria || []).map(c => ({ id: c.id, name: c.name }))
  const ids = new Set(forms.map(f => f.id))
  const live = (notes || []).filter(n => n && !n.removed && String(n.text || '').trim())
  const fieldOf = n => LEGACY[n.field] || n.field || ''
  const sections = forms.map(f => {
    const gen = draft && draft[f.id] && Array.isArray(draft[f.id].sentences) ? draft[f.id].sentences : []
    const sentences = gen
      .map((s, idx) => ({ kind: 'sentence', field: f.id, idx, text: String(s.text || '') }))
      .filter(i => i.text.trim())
    const own = live.filter(n => fieldOf(n) === f.id).map(n => ({ kind: 'note', id: n.id, text: String(n.text) }))
    // A section shows its generated sentences once there are any. A note the reviewer added AFTER the draft was made is
    // not in them (the sentences list the notes they were made from, in `src`), so it is shown after them: nothing the
    // app said it added is ever hidden. A draft with no record of its sources keeps hiding the notes (never twice).
    const known = gen.every(s => Array.isArray(s.src))
    const used = new Set(gen.flatMap(s => s.src || []))
    const mine = sentences.length
      ? [...sentences, ...(known ? own.filter(n => !used.has('n' + n.id)) : [])]
      : own
    return { ...f, items: mine }
  })
  const loose = live.filter(n => !ids.has(fieldOf(n))).map(n => ({ kind: 'note', id: n.id, text: String(n.text) }))
  if (loose.length) sections.push({ ...UNPLACED, items: loose })
  return sections
}

export const hasContent = section => section.items.some(i => i.text.trim())

// Everything the reviewer has, section by section, ready to paste. Empty sections are left out.
export function copyText(sections) {
  return sections.filter(hasContent)
    .map(s => `${s.name}\n${s.items.map(i => i.text.trim()).filter(Boolean).join('\n\n')}`)
    .join('\n\n')
}

// The event that records an edit to one paragraph, or null if nothing changed. Emptying a note removes it;
// emptying a generated sentence blanks it (it then disappears from the panel).
export function editEvent(item, newText) {
  const text = String(newText).trim()
  if (text === item.text.trim()) return null
  if (item.kind === 'note') {
    return text ? { type: 'note_text_edited', payload: { id: item.id, text } } : { type: 'note_removed', payload: { id: item.id } }
  }
  return { type: 'draft_edited', payload: { field: item.field, idx: item.idx, text } }
}
