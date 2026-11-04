import { lazy, Suspense, useEffect, useState } from 'react'
import { createApi } from './api.js'
import { wantsGuided, flowFromConfig } from './flow.js'

// Both screens load on demand, so the old flow's code and styles are only fetched when it is actually shown,
// and the old flow (App.jsx) is used exactly as it was.
const Guided = lazy(() => import('../App.jsx'))
const Chat = lazy(() => import('./ChatApp.jsx'))

export default function Root() {
  const [flow, setFlow] = useState(wantsGuided(window.location.search) ? 'guided' : null)
  useEffect(() => {
    if (flow) return
    let live = true
    createApi().config().then(r => { if (live) setFlow(flowFromConfig(r)) })
    return () => { live = false }
  }, [flow])
  if (!flow) return null
  return <Suspense fallback={null}>{flow === 'guided' ? <Guided /> : <Chat />}</Suspense>
}
