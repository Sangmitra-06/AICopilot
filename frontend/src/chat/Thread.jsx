import { useEffect, useRef } from 'react'

// One option of the criteria menu (novices only), or "Other, in my words".
function Chip({ option, selected, onPick }) {
  return (
    <button type="button" className="ca-chip" aria-pressed={selected} title={option.description || undefined}
      onClick={() => onPick(option)}>
      {option.label}
    </button>
  )
}

function Message({ message }) {
  const cls = message.role === 'user' ? 'ca-msg ca-user' : 'ca-msg ca-assistant'
  return <p className={cls}>{message.text}</p>
}

// The conversation: assistant text on the page, the reviewer's text in a soft bubble. Nudges, gap lists and
// failures are all just messages. `menu` (criteria options) shows as chips under the newest assistant message.
export default function Thread({ messages, busy, menu, selected, onChip }) {
  const end = useRef(null)
  useEffect(() => { if (end.current && end.current.scrollIntoView) end.current.scrollIntoView({ block: 'end' }) },
    [messages.length, busy, menu])
  return (
    <div className="ca-thread" role="log" aria-live="polite">
      <div className="ca-column">
        {messages.map(m => <Message key={m.id} message={m} />)}
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
