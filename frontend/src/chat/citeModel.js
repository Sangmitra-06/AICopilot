// Citations to highlights, free of React so it can be tested.
//
// The backend's reply carries `cites` (the spans the reply points at, each with page and bounding box) and `parts`
// (the reply cut into plain pieces, the pointers marked with the span ids they stand for). The reviewer never sees an
// id. The PDF pane shows exactly one set of highlights, the "focus", and it only ever holds spans that a reply cited
// or that the reviewer selected: nothing is highlighted unprompted.

const finite = n => typeof n === 'number' && Number.isFinite(n)

// A span the viewer can draw: a whole-number page and a four-number box with some area. Anything else cannot be
// located, and fails quietly (no highlight, no error).
export function locate(span) {
  if (!span || typeof span !== 'object') return null
  const { page, bbox } = span
  if (!Number.isInteger(page) || page < 1) return null
  if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(finite)) return null
  if (bbox[2] <= bbox[0] || bbox[3] <= bbox[1]) return null
  return { id: span.id, page, bbox: bbox.slice() }
}

// span ids -> drawable highlights, in the order given. Unknown ids and spans that cannot be located are dropped; an id
// listed twice is drawn once. `byId` maps span id -> span ({ id, page, bbox, ... }).
export function resolve(ids, byId) {
  const out = []
  const seen = new Set()
  for (const id of Array.isArray(ids) ? ids : []) {
    if (seen.has(id) || !byId || !Object.prototype.hasOwnProperty.call(byId, id)) continue
    seen.add(id)
    const h = locate(byId[id])
    if (h) out.push(h)
  }
  return out
}

// A reply's `cites` as an id -> span map entry each, merged over what is already known. The reply's own geometry is
// used as it arrives, so a reply is never un-drawable just because the span list has not loaded yet.
export function withCites(byId, cites) {
  const next = { ...(byId || {}) }
  for (const c of Array.isArray(cites) ? cites : []) if (c && c.id) next[c.id] = { ...(next[c.id] || {}), ...c }
  return next
}

// The next focus after a reply (or a click on a pointer). `ids` is what was cited. Returns `prev` unchanged when
// nothing cited can be located, so a reply that cites nothing never moves the PDF; otherwise a new focus whose `seq`
// is higher, so that focusing the same spans again scrolls to them again.
export function nextFocus(prev, ids, byId) {
  const items = resolve(ids, byId)
  if (!items.length) return prev || null
  return { items, seq: (prev ? prev.seq : 0) + 1 }
}

// The reviewer's own selection (a rectangle dragged on the page and answered by /select) as a focus.
export function selectionFocus(prev, span) {
  const h = locate(span)
  if (!h) return prev || null
  return { items: [h], seq: (prev ? prev.seq : 0) + 1 }
}

// Where the viewer scrolls to: the first highlight of the focus.
export function scrollTarget(focus) {
  return focus && focus.items && focus.items.length ? { page: focus.items[0].page, y: focus.items[0].bbox[1] } : null
}

// The pieces to render for a message: plain text, and pointers (clickable) carrying their span ids. A message with
// no pointers is one plain piece. The pieces always join to exactly the message text.
export function pieces(message) {
  const text = String((message && message.text) || '')
  const parts = message && message.parts
  if (!Array.isArray(parts) || !parts.length) return [{ text, cite: null }]
  const ok = parts.every(p => p && typeof p.text === 'string') && parts.map(p => p.text).join('') === text
  if (!ok) return [{ text, cite: null }]
  return parts.map(p => ({ text: p.text, cite: Array.isArray(p.cite) && p.cite.length ? p.cite : null }))
}

const SNIPPET_MAX = 400

// Put text the reviewer selected in the PDF into the text box as a quotation, after whatever they already typed.
export function quoteInto(current, selected) {
  let s = String(selected || '').replace(/\s+/g, ' ').trim()
  if (!s) return current
  if (s.length > SNIPPET_MAX) s = s.slice(0, SNIPPET_MAX).replace(/\s+\S*$/, '') + '…'
  const q = '“' + s.replace(/[“”]/g, '"') + '” '
  const base = String(current || '')
  if (!base.trim()) return q
  return base.replace(/\s+$/, '') + '\n' + q
}
