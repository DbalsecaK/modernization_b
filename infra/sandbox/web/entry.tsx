// Entry of a prototype bundle (ADR-0013), written by the platform, never by a model. It mounts the agent's screen
// with the NexTI design system and talks to the page only through a closed set of postMessage events: the frame has
// an opaque origin, no cookies, no storage and no network (CSP connect-src 'none').
import { Component, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import '@nexti/ds/ds.css'
import Screen from './prototype/Screen'

type Outbound =
  | { type: 'ready' }
  | { type: 'field'; name: string }
  | { type: 'navigate'; to: string }
  | { type: 'error'; message: string }

function send(message: Outbound) {
  window.parent.postMessage({ source: 'nexti-prototype', ...message }, '*')
}

class Boundary extends Component<{ children: ReactNode }, { failed: string | null }> {
  state = { failed: null as string | null }
  static getDerivedStateFromError(error: unknown) {
    return { failed: error instanceof Error ? error.message : String(error) }
  }
  componentDidCatch(error: unknown) {
    send({ type: 'error', message: error instanceof Error ? error.message : String(error) })
  }
  render() {
    if (this.state.failed) return <div className="nx-root nx-empty">The prototype failed: {this.state.failed}</div>
    return this.props.children
  }
}

// A click on an element marked with data-field lets the reviewer comment on that field.
document.addEventListener(
  'click',
  (event) => {
    const target = (event.target as HTMLElement | null)?.closest('[data-field]')
    if (target) send({ type: 'field', name: target.getAttribute('data-field') ?? '' })
  },
  true,
)

createRoot(document.getElementById('root')!).render(
  <Boundary>
    <Screen navigate={(to: string) => send({ type: 'navigate', to })} />
  </Boundary>,
)
send({ type: 'ready' })
