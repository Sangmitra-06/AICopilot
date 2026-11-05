// A thin client for the backend. Every call resolves to { ok, status, data }; nothing throws, so callers decide
// what a failure means. A network failure ("Failed to fetch") is { ok: false, status: 0 }.

// Same origin: the backend serves the built frontend (frontend/dist) and the API on one port. In development, Vite's
// dev and preview servers forward the API paths to the backend (vite.config.js).
export const API_BASE = ''

const post = body => ({ method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const seg = s => encodeURIComponent(s)

export function createApi(fetchImpl = (...a) => fetch(...a), base = API_BASE) {
  async function call(path, init) {
    try {
      const r = await fetchImpl(base + path, init)
      let data = null
      try { data = await r.json() } catch { data = null }
      return { ok: r.ok, status: r.status, data }
    } catch (e) {
      return { ok: false, status: 0, data: null, error: String(e) }
    }
  }
  return {
    config: () => call('/config'),
    onboarding: rid => call(`/onboarding/${seg(rid)}`),
    answer: (rid, text) => call(`/onboarding/${seg(rid)}/answer`, post({ text })),
    chat: (pid, rid, message) => call(`/chat/${seg(pid)}`, post({ reviewer_id: rid, message })),
    open: (pid, rid) => call(`/chat/${seg(pid)}/open`, post({ reviewer_id: rid })),
    // With the reviewer id the paper id is per reviewer and per paper: two people with the same PDF each get their own
    // opening, walk, notes and draft.
    upload: (file, rid) => {
      const fd = new FormData()
      fd.append('file', file)
      return call(rid ? `/papers?reviewer_id=${seg(rid)}` : '/papers', { method: 'POST', body: fd })
    },
    thread: pid => call(`/thread/${seg(pid)}`),
    spans: pid => call(`/papers/${seg(pid)}/spans`),
    select: (pid, page, rect) => call('/select', post({ paper_id: pid, page, rect })),
    pdfUrl: pid => `${base}/papers/${seg(pid)}/pdf`,
    criteria: () => call('/criteria'),
    notes: pid => call(`/notes/${seg(pid)}`),
    draft: pid => call(`/draft/${seg(pid)}`),
    event: (pid, type, payload) => call('/events', post({ paper_id: pid, type, payload })),
  }
}
