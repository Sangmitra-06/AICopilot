// Formatting for assistant messages, free of React so it can be tested.
//
// A reply may carry **bold**, bullet lists ("- x", "* x", "• x", "1. x") and paragraph breaks. This turns the text into
// plain data: blocks of lines of text runs. The components render a run as a string (React escapes it) or as <strong>,
// never as HTML, so nothing a reply contains can inject markup. Every run is a slice of the original text, so the cite
// parts of a message (see citeModel.pieces) can be laid over the runs by position and a pointer inside bold text or a
// list item stays clickable.
//
//   layout(text, parts?) -> [{ kind: 'p' | 'ul' | 'ol', lines: [[{ text, bold, cite: ids | null }]] }]

const BULLET = /^\s*([-*•–]|\d{1,3}[.)])\s+/
const HEADING = /^\s{0,3}#{1,6}\s+/

// Where each cite piece sits in the text. Parts that do not join to exactly the text are not trusted.
function ranges(text, parts) {
  const ok = Array.isArray(parts) && parts.length && parts.every(p => p && typeof p.text === 'string')
    && parts.map(p => p.text).join('') === text
  if (!ok) return [{ start: 0, end: text.length, cite: null }]
  let at = 0
  return parts.map(p => {
    const r = { start: at, end: at + p.text.length, cite: Array.isArray(p.cite) && p.cite.length ? p.cite : null }
    at = r.end
    return r
  })
}

// [start, end) of the text as runs: split at the cite pieces, with a bold flag.
function runs(text, segments, cuts) {
  const out = []
  for (const [a, b, bold] of segments) {
    for (const c of cuts) {
      const start = Math.max(a, c.start)
      const end = Math.min(b, c.end)
      if (end > start) out.push({ text: text.slice(start, end), bold, cite: c.cite })
    }
  }
  return out
}

// The bold segments of one line: [[start, end, bold]]. A "**" opens bold only when text follows it directly and closes
// only when text precedes it; an unmatched or stray "**" is dropped (never shown) and makes nothing bold.
function segments(text, from, to, allBold) {
  const marks = []
  for (let i = text.indexOf('**', from); i >= 0 && i + 2 <= to; i = text.indexOf('**', i + 2)) marks.push(i)
  const pairs = []
  let open = null
  for (const m of marks) {
    const before = m > from ? text[m - 1] : ' '
    const after = m + 2 < to ? text[m + 2] : ' '
    if (open === null && !/\s/.test(after)) open = m
    else if (open !== null && !/\s/.test(before)) { pairs.push([open, m]); open = null }
  }
  const opens = new Set(pairs.map(pr => pr[0]))
  const closes = new Set(pairs.map(pr => pr[1]))
  const segs = []
  let at = from
  let bold = false
  for (const m of marks) {                  // every "**" is skipped (never shown); only matched pairs switch bold
    if (m > at) segs.push([at, m, bold || allBold])
    at = m + 2
    if (opens.has(m)) bold = true
    else if (closes.has(m)) bold = false
  }
  if (to > at) segs.push([at, to, bold || allBold])
  return segs
}

export function layout(text, parts) {
  const src = typeof text === 'string' ? text : ''
  const cuts = ranges(src, parts)
  const blocks = []
  let cur = null
  let pos = 0
  for (const raw of src.split('\n')) {
    const start = pos
    pos += raw.length + 1
    const line = raw.replace(/\s+$/, '')
    if (!line.trim()) { cur = null; continue }
    let kind = 'p'
    let from = start + (line.length - line.replace(/^\s+/, '').length)
    let allBold = false
    const b = BULLET.exec(line)
    if (b) { kind = /^\d/.test(b[1]) ? 'ol' : 'ul'; from = start + b[0].length }
    else {
      const h = HEADING.exec(line)
      if (h) { from = start + h[0].length; allBold = true }
    }
    const r = runs(src, segments(src, from, start + line.length, allBold), cuts)
    if (!r.length) continue
    if (cur && cur.kind === kind) cur.lines.push(r)
    else { cur = { kind, lines: [r] }; blocks.push(cur) }
  }
  return blocks
}
