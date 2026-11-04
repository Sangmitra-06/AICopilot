import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import * as pdfjs from 'pdfjs-dist'
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import PdfPage from './PdfPage.jsx'
import { scrollTarget } from '../chat/citeModel.js'
import './pdf.css'

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl

// The PDF pane. It shows the paper, draws `focus.items` (the spans the conversation pointed at, or the reviewer
// selected) and scrolls to the first of them whenever `focus` changes. It never highlights anything else and never
// scrolls on its own. A paper that cannot be loaded leaves the pane blank. `onSelect(page, rect)` is called with a box
// the reviewer dragged, in PDF points.
//
// NOTE: loading and scrolling mirror `Viewer` in src/App.jsx (the old guided flow, left untouched); keep them in sync
// or delete one when the old flow is removed. Differences: pages are fitted to the pane's width, and every page's size
// is read before anything is laid out, so scrolling to a page far down is exact.
const PAD = 28, MIN_SCALE = 0.5, MAX_SCALE = 1.6

export default function PdfViewer({ url, focus, onSelect }) {
  const [doc, setDoc] = useState(null)                 // { url, pdf, sizes }: sizes = [width, height] of every page, in PDF points
  const [width, setWidth] = useState(0)
  const scroller = useRef(null)
  const els = useRef({})

  useEffect(() => {
    if (!url) return
    let alive = true
    pdfjs.getDocument({ url, disableRange: true, disableStream: true }).promise
      .then(async d => {
        const dims = []
        for (let i = 1; i <= d.numPages; i++) {
          const v = (await d.getPage(i)).getViewport({ scale: 1 })
          dims.push([v.width, v.height])
        }
        if (alive) setDoc({ url, pdf: d, sizes: dims })
      })
      .catch(() => {})
    return () => { alive = false }
  }, [url])

  const loaded = doc && doc.url === url ? doc : null      // a document for another paper is never shown
  const pdf = loaded && loaded.pdf
  const sizes = loaded && loaded.sizes

  useLayoutEffect(() => {
    const el = scroller.current
    if (!el) return
    const measure = () => setWidth(el.clientWidth)
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [pdf])

  // Fit the widest page to the pane, in steps of 0.05 so that a window drag does not redraw every page each pixel.
  const widest = sizes ? Math.max(...sizes.map(s => s[0])) : 612
  const fit = width ? (width - PAD) / widest : 1
  const scale = Math.round(Math.min(MAX_SCALE, Math.max(MIN_SCALE, fit)) * 20) / 20

  const ready = Boolean(pdf && sizes && width)
  useEffect(() => {
    const t = scrollTarget(focus)
    if (!t || !ready || !scroller.current) return
    const el = els.current[t.page]
    if (el) scroller.current.scrollTo({ top: el.offsetTop + t.y * scale - 90, behavior: 'smooth' })
  }, [focus, ready])    // eslint-disable-line react-hooks/exhaustive-deps -- scale changes must not re-scroll

  if (!url) return null
  return (
    <div className="pdf-scroller" ref={scroller}>
      {ready && sizes.map((s, i) => (
        <PdfPage key={i + 1} pdf={pdf} n={i + 1} scale={scale} size={[s[0] * scale, s[1] * scale]}
          hls={focus ? focus.items : []} onSelect={onSelect} reg={(n, el) => { els.current[n] = el }} />
      ))}
    </div>
  )
}
