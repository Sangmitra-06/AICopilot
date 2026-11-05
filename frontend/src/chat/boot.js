// Dev-only clean state, frontend half (React-free, tested). When the backend runs with COPILOT_FRESH=1 it reports a boot
// id in GET /config. If that id differs from the one stored last time, the backend has started from nothing, so the stored
// reviewer id and paper id point at nothing: forget them. No boot id (the normal case), an unreachable server or an odd
// answer changes nothing.
import { KEYS } from './controller.js'

export const BOOT_KEY = 'copilot.boot_id'

export function syncBoot(storage, configResponse) {
  const id = configResponse && configResponse.ok && configResponse.data ? configResponse.data.boot_id : null
  if (typeof id !== 'string' || !id) return
  const seen = storage.get(BOOT_KEY)
  if (seen && seen !== id) { storage.remove(KEYS.reviewer); storage.remove(KEYS.paper) }
  if (seen !== id) storage.set(BOOT_KEY, id)
}
