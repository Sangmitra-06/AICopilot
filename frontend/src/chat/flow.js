// Which screen to show. Free of React so it can be tested.

// The old guided flow is reachable by ?mode=guided ...
export const wantsGuided = search => new URLSearchParams(search).get('mode') === 'guided'

// ... or when the backend reports that it is serving that flow (GET /config -> {"flow": "guided"}). Anything
// else, including a backend that cannot be reached yet, is the chat-first screen: it says plainly that it
// cannot reach the server, and retries when you send again.
export const flowFromConfig = r => (r && r.ok && r.data && r.data.flow === 'guided' ? 'guided' : 'chat')
