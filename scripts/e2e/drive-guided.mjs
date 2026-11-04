// A backend serving the old guided flow (COPILOT_FLOW=guided): the browser must show the old flow with no URL
// parameter. Needs no API key and makes no model calls.
//
//   node scripts/e2e/drive-guided.mjs
import { PORTS, createChecks, log, mkTmp, openBrowser, preflight, startBackend, startFrontend, stopAll, until, up } from './lib.mjs'

const { chrome } = await preflight({ needKey: false })
const t = createChecks()
const tmp = mkTmp()
let b
try {
  startBackend(tmp, { COPILOT_FLOW: 'guided', OPENROUTER_API_KEY: 'offline-no-model', MODEL: 'offline' })
  startFrontend()
  await until(() => up(`http://127.0.0.1:${PORTS.backend}/config`), 40000, 'the backend')
  await until(() => up(`http://localhost:${PORTS.frontend}/`), 20000, 'the frontend preview server')
  const config = await (await fetch(`http://127.0.0.1:${PORTS.backend}/config`)).json()
  t.check(config.flow === 'guided' && config.chat_enabled === false, '/config reports the guided flow', JSON.stringify(config))
  b = await openBrowser(chrome, tmp)
  await b.goto(`http://localhost:${PORTS.frontend}/`)                       // note: no ?mode=guided
  await until(() => b.cdp.eval(`document.body.innerText.includes('Upload paper')`), 15000, 'the old flow')
  t.check(true, 'with no URL parameter, the old flow is shown')
  t.check(!(await b.cdp.eval(`!!document.querySelector('.ca-root')`)), 'the chat screen is not shown')
  await b.shot('guided_by_config')
  t.check(b.cdp.exceptions.length === 0, 'no uncaught exceptions in the page', b.cdp.exceptions.join(' | '))
} catch (e) {
  t.check(false, 'the run completed', e.message)
} finally {
  stopAll()
}
log('screenshots: scripts/e2e/out/')
process.exitCode = t.summary() ? 0 : 1
