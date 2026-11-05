import { useLayoutEffect, useRef } from 'react'

// One paragraph of the draft: a note the reviewer captured, or a sentence of a generated draft. Editing it and
// leaving the box saves the edit; emptying a note removes it.
function DraftItem({ item, onEdit }) {
  const ref = useRef(null)
  useLayoutEffect(() => {
    const el = ref.current
    if (el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px' }
  }, [item.text])
  return (<>
    {item.label && <p className="ca-label">{item.label}</p>}
    <textarea ref={ref} className="ca-para" defaultValue={item.text} rows={1} aria-label="Edit this paragraph"
      onInput={e => { e.target.style.height = 'auto'; e.target.style.height = e.target.scrollHeight + 'px' }}
      onBlur={e => onEdit(item, e.target.value)} />
  </>)
}

// The review draft by review-form section. Sections are editable text. The only action is Copy all.
export default function DraftPanel({ sections, note, copied, onEdit, onCopy }) {
  return (
    <aside className="ca-panel" aria-label="Review draft">
      <div className="ca-panel-body">
        {note && <p className="ca-note">{note}</p>}
        {sections.map(s => (
          <section key={s.id || 'unplaced'} className="ca-section">
            <h2>{s.name}</h2>
            {s.items.length
              ? s.items.map(i => <DraftItem key={`${i.kind}-${i.id ?? i.idx}-${i.text}`} item={i} onEdit={onEdit} />)
              : <p className="ca-empty">Nothing here yet.</p>}
          </section>
        ))}
      </div>
      <div className="ca-panel-foot">
        <button type="button" className="ca-copy" onClick={onCopy}>{copied ? 'Copied' : 'Copy all'}</button>
      </div>
    </aside>
  )
}
