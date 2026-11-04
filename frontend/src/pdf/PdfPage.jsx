import { useEffect, useRef, useState } from 'react'

// One page of the PDF: a canvas, the highlights drawn over it, and a rubber band while the reviewer drags a box.
//
// NOTE: this duplicates the page rendering and highlight logic of `Page` in src/App.jsx (the old guided flow), which
// is deliberately left untouched. Keep the two in sync, or delete one when the old flow is removed. The differences:
// the scale is a prop (the pane fits the page to its width) and the page size is known up front (see PdfViewer).
//
// `size` is [width, height] in CSS pixels at `scale`; `hls` are the highlights { page, bbox } in PDF points, only the
// ones for this page are drawn. A page is drawn when it is near the viewport; a page that fails to draw stays blank.
export default function PdfPage({ pdf, n, scale, size, hls, onSelect, reg }) {
  const [vis, setVis] = useState(false)
  const [drag, setDrag] = useState(null)
  const box = useRef(null)
  const canvas = useRef(null)
  const task = useRef(null)
  const drawnAt = useRef(0)

  useEffect(() => {
    const io = new IntersectionObserver(es => { if (es[0].isIntersecting) setVis(true) }, { rootMargin: '900px' })
    io.observe(box.current)
    return () => io.disconnect()
  }, [])

  useEffect(() => {
    if (!vis || drawnAt.current === scale) return
    drawnAt.current = scale
    let alive = true
    pdf.getPage(n).then(page => {
      if (!alive) return
      const v = page.getViewport({ scale })
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const c = canvas.current
      c.width = Math.floor(v.width * dpr)
      c.height = Math.floor(v.height * dpr)
      if (task.current) task.current.cancel()
      task.current = page.render({ canvasContext: c.getContext('2d'), viewport: v, transform: dpr === 1 ? null : [dpr, 0, 0, dpr, 0, 0] })
      task.current.promise.catch(() => {})                         // cancelled by a newer draw, or a bad page: stay quiet
    }).catch(() => {})
    return () => { alive = false }
  }, [pdf, n, scale, vis])

  const pos = e => {
    const r = box.current.getBoundingClientRect()
    return [e.clientX - r.left, e.clientY - r.top]
  }
  const down = e => {
    if (e.button !== 0) return
    const [x, y] = pos(e)
    setDrag({ x0: x, y0: y, x1: x, y1: y })
  }
  const move = e => {
    if (!drag) return
    const [x, y] = pos(e)
    setDrag({ ...drag, x1: x, y1: y })
  }
  const up = () => {
    if (!drag) return
    const x0 = Math.min(drag.x0, drag.x1), x1 = Math.max(drag.x0, drag.x1)
    const y0 = Math.min(drag.y0, drag.y1), y1 = Math.max(drag.y0, drag.y1)
    setDrag(null)
    if (x1 - x0 > 6 && y1 - y0 > 6) onSelect(n, [x0 / scale, y0 / scale, x1 / scale, y1 / scale])
  }

  const r = drag && {
    l: Math.min(drag.x0, drag.x1), t: Math.min(drag.y0, drag.y1),
    w: Math.abs(drag.x1 - drag.x0), h: Math.abs(drag.y1 - drag.y0),
  }
  return (
    <div className="pdf-page" style={{ width: size[0], height: size[1] }}
      ref={el => { box.current = el; reg(n, el) }}
      onMouseDown={down} onMouseMove={move} onMouseUp={up} onMouseLeave={up}>
      <canvas ref={canvas} />
      {hls.filter(x => x.page === n).map(x => (
        <div key={x.id} className="pdf-hl" style={{
          left: x.bbox[0] * scale, top: x.bbox[1] * scale,
          width: (x.bbox[2] - x.bbox[0]) * scale, height: (x.bbox[3] - x.bbox[1]) * scale,
        }} />
      ))}
      {r && <div className="pdf-drag" style={{ left: r.l, top: r.t, width: r.w, height: r.h }} />}
      <div className="pdf-pno">p{n}</div>
    </div>
  )
}
