import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import AccessBoundary from './components/AccessBoundary'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AccessBoundary>
      {(connection) => <App key={`${connection.session.userId}:${connection.session.expiresAt}`} connection={connection} />}
    </AccessBoundary>
  </StrictMode>,
)
