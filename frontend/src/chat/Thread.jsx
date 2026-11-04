import { useEffect, useRef } from 'react'
import { pieces } from './citeModel.js'

// One option of the criteria menu (novices only), or "Other, in my words".
function Chip({ option, selected, onPick }) {
  return (
    <button type="button" className="ca-chip" aria-pressed={selected} title={option.description || undefined}
      onClick={() => onPick(option)}>
      {option.label}
    </button>
  )
}

// A section pointer in a reply, "(Section 4)": plain text that shows the passage again in the PDF when clicked. It is
// styled as text (not a button) and reachable by keyboard; the reviewer never sees a span id.
function Cite({ text, ids, onCite }) {
  const go = () => onCite(ids)
  return (
    <span className="ca-cite" tabIndex={0} onClick={go}
      onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go() } }}>{text}</span>
  )
}

function Message({ message, onCite }) {
  const cls = message.role === 'user' ? 'ca-msg ca-user' : 'ca-msg ca-assistant'
  const ps = onCite ? pieces(message) : null
  if (!ps || !ps.some(p => p.cite)) return <p className={cls}>{message.text}</p>
  return (
    <p className={cls}>
      {ps.map((p, i) => (p.cite ? <Cite key={i} text={p.text} ids={p.cite} onCite={onCite} /> : p.text))}
    </p>
  )
}

// The conversation: assistant text on the page, the reviewer's text in a soft bubble. Nudges, gap lists and
// failures are all just messages. `menu` (criteria options) shows as chips under the newest assistant message.
export default function Thread({ messages, busy, menu, selected, onChip, onCite }) {
  const end = useRef(null)
  useEffect(() => { if (end.current && end.current.scrollIntoView) end.current.scrollIntoView({ block: 'end' }) },
    [messages.length, busy, menu])
  return (
    <div className="ca-thread" role="log" aria-live="polite">
      <div className="ca-column">
        {messages.map(m => <Message key={m.id} message={m} onCite={onCite} />)}
        {menu && menu.length > 0 && (
          <div className="ca-chips">
            {menu.map(o => <Chip key={o.id} option={o} selected={selected.has(o.label)} onPick={onChip} />)}
          </div>
        )}
        {busy && <p className="ca-msg ca-assistant ca-wait" aria-label="Working">…</p>}
        <div ref={end} />
      </div>
    </div>
  )
}
