import { useLayoutEffect, useRef } from 'react'

const Paperclip = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M21 11.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l9-9a3.7 3.7 0 0 1 5.2 5.2l-9 9a1.8 1.8 0 0 1-2.6-2.6l8.2-8.2" />
  </svg>
)
const SendArrow = () => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.5"
    strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 19V5M5 12l7-7 7 7" />
  </svg>
)

// The one text box. The paperclip sits inside it on the left and Send on the right. Enter sends; Shift+Enter
// starts a new line. The box keeps the text after a failed send, so pressing Send again retries it.
export default function Composer({ value, onChange, onSend, onAttach, canSend, inputRef }) {
  const file = useRef(null)
  const own = useRef(null)
  const area = inputRef || own
  useLayoutEffect(() => {
    const el = area.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 168) + 'px'
  }, [value, area])
  const submit = e => { e.preventDefault(); if (canSend) onSend() }
  return (
    <form className="ca-composer" onSubmit={submit}>
      <div className="ca-box">
        <button type="button" className="ca-icon" aria-label="Attach paper" onClick={() => file.current && file.current.click()}>
          <Paperclip />
        </button>
        <input ref={file} type="file" accept="application/pdf,.pdf" hidden
          onChange={e => { const f = e.target.files && e.target.files[0]; e.target.value = ''; if (f) onAttach(f) }} />
        <textarea ref={area} rows={1} value={value} placeholder="Write a message" aria-label="Message"
          onChange={e => onChange(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (canSend) onSend() } }} />
        <button type="submit" className="ca-icon ca-send" aria-label="Send" disabled={!canSend}>
          <SendArrow />
        </button>
      </div>
    </form>
  )
}
