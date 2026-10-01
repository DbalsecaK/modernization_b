import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { KcPage } from './kc.gen'

// Keycloak renders the page with window.kcContext; outside Keycloak there is nothing to show.
createRoot(document.getElementById('root')!).render(
  <StrictMode>{window.kcContext ? <KcPage kcContext={window.kcContext} /> : <h1>No Keycloak context</h1>}</StrictMode>,
)
