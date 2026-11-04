import Thread from './Thread.jsx'
import Composer from './Composer.jsx'
import DraftPanel from './DraftPanel.jsx'
import './chat.css'

// The whole chat-first screen as a pure function of its props (so it can be rendered in a test):
//   one centered column (the thread and the text box), a small "Review draft" toggle, and, when toggled, the
//   draft side panel. Nothing else.
export default function ChatView({
  state, text, onText, onSend, onAttach, onChip, selected, inputRef, dragging, dragHandlers,
  draftOpen, onToggleDraft, draft, onEditItem, onCopy,
}) {
  const canSend = !state.busy && (state.stage === 'boot' || text.trim().length > 0)
  return (
    <div className={'ca-root' + (dragging ? ' ca-drag' : '')} {...dragHandlers}>
      <div className="ca-main">
        <div className="ca-bar">
          <button type="button" className="ca-toggle" aria-pressed={draftOpen} onClick={onToggleDraft}>Review draft</button>
        </div>
        <Thread messages={state.messages} busy={state.busy} menu={state.menu} selected={selected} onChip={onChip} />
        <Composer value={text} onChange={onText} onSend={onSend} onAttach={onAttach} canSend={canSend} inputRef={inputRef} />
      </div>
      {draftOpen && (
        <DraftPanel sections={draft.sections} note={draft.note} copied={draft.copied} onEdit={onEditItem} onCopy={onCopy} />
      )}
    </div>
  )
}
