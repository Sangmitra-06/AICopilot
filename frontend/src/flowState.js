// Follow-up bookkeeping for the per-part conversation, kept free of React so it can be tested.
// `counts` maps a part id to how many automatic follow-ups that part has used. It is never reset
// while a paper is open: "Add more" and re-entering a part do not buy more follow-ups.

export const FOLLOW = { judge: 2, describe: 1 }
export const capFor = c => FOLLOW[c && c.style === 'describe' ? 'describe' : 'judge']

export const newCounts = () => ({})
export const level = (counts, cid) => counts[cid] || 0
export const raise = (counts, cid, n) => { counts[cid] = Math.max(level(counts, cid), n) }
export const exhaust = (counts, c) => raise(counts, c.id, capFor(c))

// The next automatic follow-up after a saved point, or null when this part has used its share.
// 'respond' (judge parts only) is the help move; if it turns out to offer nothing the caller asks again
// and gets 'deeper'.
export function nextFollow(counts, c) {
  const at = level(counts, c.id)
  if (c.id === 'summary') {
    if (at < 1) { raise(counts, c.id, 1); return 'highlights' }
    return null
  }
  if (c.style === 'describe') {
    if (at < 1) { raise(counts, c.id, 1); return 'angle' }
    return null
  }
  if (at === 0) { raise(counts, c.id, 1); return 'respond' }
  if (at < 2) { raise(counts, c.id, 2); return 'deeper' }
  return null
}

// "I don't know" on a part: explain it once, after that offer a concrete choice instead of
// explaining and asking the same question again.
export const newDk = () => ({})
export function nextDontKnow(dk, cid) {
  dk[cid] = (dk[cid] || 0) + 1
  return dk[cid] === 1 ? 'explain' : 'choose'
}

// Buttons for the choice. `nx` is the next open part, or null. "Ask something else" is left out
// when the part has no new questions left to ask.
export const choiceOptions = (c, nx, withAngle = true) => [
  { l: 'No comment on this part', a: 'nocomment' },
  ...(nx ? [{ l: `Come back to this later: go to ${nx.tab}`, a: 'goto', arg: nx.id }] : []),
  ...(withAngle ? [{ l: 'Ask something else', a: 'angle' }] : []),
]
