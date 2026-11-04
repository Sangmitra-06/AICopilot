import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import Root from './chat/Root.jsx'

// Root picks the screen: the chat-first one by default, the old guided flow (App.jsx, unchanged) behind ?mode=guided.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
