// The criteria chips (novices only) fill the text box with their labels, comma-separated, so several can be picked.
// React-free so it can be tested; ChatApp uses toggleLabel inside a functional state update, so two quick clicks
// never overwrite each other.

const parts = text => String(text || '').split(',').map(s => s.trim()).filter(Boolean)

// Add the label to the text if it is not there, remove it if it is.
export function toggleLabel(text, label) {
  const p = parts(text)
  return (p.includes(label) ? p.filter(x => x !== label) : [...p, label]).join(', ')
}

// The labels of the menu that are currently in the text (shown as pressed).
export function selectedLabels(text, menu) {
  const have = new Set(parts(text))
  return new Set((menu || []).filter(o => have.has(o.label)).map(o => o.label))
}
