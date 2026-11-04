// The chat-first conversation, free of React so it can be tested.
//
// Stages:  boot        not started, or the first load failed (sending again retries it)
//          onboarding  the backend's questions, via GET /onboarding/{rid} and POST /onboarding/{rid}/answer
//          attach      onboarding is closed and no paper is attached yet
//          chat        POST /chat/{pid}
//
// Every backend call goes through `api` (see api.js) and returns { ok, status, data }, so a failure is a value,
// never an exception. A failure puts ONE plain sentence in the thread; sending again retries.

export const COPY = {
  unreachable: "I can't reach the server right now. Send a message to try again.",
  sendFailed: "That didn't go through. Send your message again to retry.",
  uploadFailed: "I couldn't read that file. Attach it again to retry.",
  notPdf: "That doesn't look like a PDF. Attach the paper as a PDF file.",
  attachFirst: 'Attach the paper first, with the paperclip or by dropping the PDF here, and then we can start.',
  askAttach: "That's everything I need. Attach the paper with the paperclip, or drop the PDF here, and we'll start.",
  readyChat: "That's everything I need. Ask me about the paper, or tell me what you think so far.",
  gotPaper: 'Got the paper. Ask me about it, or tell me what you think so far.',
  gotPaperEarly: "Got the paper. Let's finish these few questions first, and then we'll start on it.",
  switched: 'Switched to the new paper.',
  paperGone: "I can't find that paper any more. Attach it again.",
  chatOff: 'Chat is switched off on this server.',
}

const KEYS = { reviewer: 'copilot.reviewer_id', paper: 'copilot.paper_id' }

export function memoryStorage() {
  const m = new Map()
  return { get: k => (m.has(k) ? m.get(k) : null), set: (k, v) => { m.set(k, v) }, remove: k => { m.delete(k) } }
}

// localStorage, if it works (private windows and blocked storage can throw).
export function browserStorage() {
  const guard = f => { try { return f() } catch { return null } }
  return {
    get: k => guard(() => window.localStorage.getItem(k)),
    set: (k, v) => { guard(() => window.localStorage.setItem(k, v)) },
    remove: k => { guard(() => window.localStorage.removeItem(k)) },
  }
}

const mintReviewerId = () => {
  const c = globalThis.crypto
  return 'r-' + (c && c.randomUUID ? c.randomUUID() : String(Date.now()) + Math.random().toString(36).slice(2))
}

export function createController({ api, storage = memoryStorage(), mint = mintReviewerId }) {
  let reviewerId = storage.get(KEYS.reviewer)
  if (!reviewerId) { reviewerId = mint(); storage.set(KEYS.reviewer, reviewerId) }
  let seq = 0
  let starting = false
  let state = {
    stage: 'boot', messages: [], busy: false, menu: null, draftVersion: 0,
    reviewerId, paperId: storage.get(KEYS.paper) || null,
  }
  const listeners = new Set()
  const patch = p => { state = { ...state, ...p }; listeners.forEach(l => l()) }
  const getState = () => state
  const subscribe = l => { listeners.add(l); return () => listeners.delete(l) }

  const add = (role, text, extra = {}) => {
    const m = { id: ++seq, role, text, ...extra }
    patch({ messages: [...state.messages, m] })
    return m
  }
  const say = (text, extra) => add('assistant', text, extra)
  const drop = pred => patch({ messages: state.messages.filter(m => !pred(m)) })
  const dropErrors = () => drop(m => m.kind === 'error')
  const fail = text => { dropErrors(); say(text, { kind: 'error' }) }
  const lastAssistant = () => [...state.messages].reverse().find(m => m.role === 'assistant')

  // Show a backend onboarding step that is not the end: the form walkthrough (novices, once), then the question,
  // with the criteria menu (novices) as chips. `force` shows the question even if it is already the last message.
  // The backend's brief acknowledgement of the last answer (step.ack, empty after a skip or an off-topic reply) leads
  // the first message of the step, so the thread reads "Got it." and then the question, in one turn.
  const lead = (ack, text) => (ack ? `${ack}\n\n${text}` : text)

  function showStep(step, force = false) {
    let ack = step.ack || ''
    if (step.walkthrough && step.walkthrough.text) { say(lead(ack, step.walkthrough.text)); ack = '' }
    const last = lastAssistant()
    if (force || !last || last.text !== step.question) say(lead(ack, step.question))
    patch({ stage: 'onboarding', menu: step.menu && step.menu.length ? step.menu : null })
  }

  function closeOnboarding(ack = '') {
    if (state.paperId) { patch({ stage: 'chat', menu: null }); say(lead(ack, COPY.readyChat)) }
    else { patch({ stage: 'attach', menu: null }); say(lead(ack, COPY.askAttach)) }
  }

  async function loadHistory() {
    const r = await api.thread(state.paperId)
    if (!r.ok || !Array.isArray(r.data)) return
    const turns = r.data
      .filter(t => t.kind === 'chat' && (t.role === 'user' || t.role === 'assistant') && t.text && !(t.meta && t.meta.onboarding))
      .map(t => ({ id: ++seq, role: t.role, text: t.text }))
    if (turns.length) patch({ messages: [...turns, ...state.messages] })
  }

  async function start() {
    if (starting || state.busy) return
    starting = true
    patch({ busy: true })
    try {
      dropErrors()
      const r = await api.onboarding(state.reviewerId)
      if (!r.ok || !r.data) { fail(COPY.unreachable); patch({ stage: 'boot' }); return }
      if (r.data.done) {
        if (state.paperId) { patch({ stage: 'chat', menu: null }); await loadHistory() }
        else closeOnboarding()
      } else {
        showStep(r.data)
      }
    } finally {
      starting = false
      patch({ busy: false })
    }
  }

  async function sendAnswer(text, mine) {
    const r = await api.answer(state.reviewerId, text)
    if (r.ok && r.data) {
      patch({ menu: null })
      if (r.data.done) closeOnboarding(r.data.ack)
      else showStep(r.data)
      return { clear: true }
    }
    drop(m => m.id === mine.id)
    if (r.status === 409 && r.data && r.data.question) {   // the backend has no question pending: show the current one
      showStep(r.data, true)
      return { clear: false }
    }
    fail(COPY.sendFailed)
    return { clear: false }
  }

  async function sendChat(text, mine) {
    const r = await api.chat(state.paperId, state.reviewerId, text)
    if (r.ok && r.data && r.data.reply) {
      if (r.data.mode === 'onboarding') {                  // the backend says onboarding is not finished after all
        const o = r.data.onboarding || {}
        patch({ stage: 'onboarding', menu: o.menu && o.menu.length ? o.menu : null })
      }
      say(r.data.reply)
      if (r.data.draft_changed) patch({ draftVersion: state.draftVersion + 1 })
      return { clear: true }
    }
    drop(m => m.id === mine.id)
    if (r.status === 404) {                                // the paper is gone from the server
      storage.remove(KEYS.paper)
      patch({ paperId: null, stage: 'attach' })
      say(COPY.paperGone)
      return { clear: false }
    }
    if (r.status === 409 && r.data && r.data.error === 'chat_disabled') { say(COPY.chatOff); return { clear: false } }
    fail(COPY.sendFailed)
    return { clear: false }
  }

  // The reviewer pressed send. Returns { clear }: whether the text box should be emptied (a failed send keeps the
  // text, so pressing send again retries it).
  async function send(raw) {
    const text = String(raw || '').trim()
    if (state.busy) return { clear: false }
    if (state.stage === 'boot') { await start(); return { clear: false } }
    if (!text) return { clear: false }
    dropErrors()
    const mine = add('user', text)
    if (state.stage === 'attach') { say(COPY.attachFirst); return { clear: true } }
    patch({ busy: true })
    try {
      return state.stage === 'onboarding' ? await sendAnswer(text, mine) : await sendChat(text, mine)
    } finally {
      patch({ busy: false })
    }
  }

  async function attach(file) {
    if (!file || state.busy) return
    const isPdf = /\.pdf$/i.test(file.name || '') || file.type === 'application/pdf'
    if (!isPdf) { fail(COPY.notPdf); return }
    dropErrors()
    patch({ busy: true })
    try {
      const r = await api.upload(file)
      const pid = r.ok && r.data && r.data.paper_id
      if (!pid) { fail(COPY.uploadFailed); return }
      const stage = state.stage
      storage.set(KEYS.paper, pid)
      patch({ paperId: pid })
      if (stage === 'attach') { patch({ stage: 'chat' }); say(COPY.gotPaper) }
      else if (stage === 'onboarding') say(COPY.gotPaperEarly)
      else { patch({ draftVersion: state.draftVersion + 1 }); say(COPY.switched) }
    } finally {
      patch({ busy: false })
    }
  }

  return { getState, subscribe, start, send, attach }
}
