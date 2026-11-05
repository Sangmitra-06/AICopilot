import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The chat frontend calls the API on its own origin (src/chat/api.js). In production the FastAPI backend serves
// frontend/dist itself. For `npm run dev` and `vite preview` (the e2e scripts), these API paths are forwarded to the
// backend on port 8000 (override with BACKEND_URL). Everything else (the page, assets) stays with Vite.
const BACKEND = process.env.BACKEND_URL || 'http://127.0.0.1:8000'
const API_PATHS = '^/(config|onboarding|profile|chat|papers|thread|select|criteria|notes|draft|events)(/|\?|$)'
const proxy = { [API_PATHS]: { target: BACKEND, changeOrigin: true } }

// The dev-server proxy is left out in middleware mode (the node render tests embed Vite that way; a proxy there would
// keep their process alive).
const apiProxy = {
  name: 'api-proxy',
  config: cfg => (cfg.server && cfg.server.middlewareMode ? {} : { server: { proxy } }),
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), apiProxy],
  preview: { proxy },
})
