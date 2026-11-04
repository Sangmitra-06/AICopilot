import { Fragment, useEffect, useRef } from 'react'
import { layout } from './format.js'

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

// One run of an assistant message: a string (React escapes it, so a reply can never inject markup), bold as <strong>, and
// a section pointer as the clickable Cite. Runs are slices of the reply text, so a pointer inside bold or a list stays one.
function Run({ run, onCite }) {
  const inner = run.cite && onCite ? <Cite text={run.text} ids={run.cite} onCite={onCite} /> : run.text
  return run.bold ? <strong>{inner}</strong> : inner
}

function Line({ line, onCite }) {
  return line.map((r, i) => <Run key={i} run={r} onCite={onCite} />)
}

function Lines({ lines, onCite }) {
  return lines.map((l, i) => (
    <Fragment key={i}>{i > 0 && <br />}<Line line={l} onCite={onCite} /></Fragment>
  ))
}

function Block({ block, onCite }) {
  if (block.kind === 'p') return <p><Lines lines={block.lines} onCite={onCite} /></p>
  const List = block.kind === 'ol' ? 'ol' : 'ul'
  return <List>{block.lines.map((l, i) => <li key={i}><Line line={l} onCite={onCite} /></li>)}</List>
}

// The reviewer's own text is shown exactly as typed. An assistant message gets bold, lists and paragraphs (format.js);
// a single paragraph keeps the plain <p> it always had.
function Message({ message, onCite }) {
  const mine = message.role === 'user'
  const cls = mine ? 'ca-msg ca-user' : 'ca-msg ca-assistant'
  const blocks = mine ? [] : layout(message.text, message.parts)
  if (!blocks.length) return <p className={cls}>{message.text}</p>
  if (blocks.length === 1 && blocks[0].kind === 'p') {
    return <p className={cls}><Lines lines={blocks[0].lines} onCite={onCite} /></p>
  }
  return <div className={cls + ' ca-fmt'}>{blocks.map((b, i) => <Block key={i} block={b} onCite={onCite} />)}</div>
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
