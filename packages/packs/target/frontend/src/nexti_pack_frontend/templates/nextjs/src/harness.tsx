// The platform's test entry (ADR-0016, ADR-0028): mounts one screen with a recording api and navigation, as in React.
// The screens use no Next.js API (navigation goes through navigate), so they mount without the router.
import { flushSync } from 'react-dom'
import { createRoot } from 'react-dom/client'
import type { Api } from './api/client'
import { SCREENS } from './app/screens'

declare global {
  interface Window {
    __nexti: { mount(id: string, api: Api, navigate: (screen: string) => void): Promise<void> }
  }
}

window.__nexti = {
  async mount(id, api, navigate) {
    const Screen = SCREENS[id]
    if (!Screen) throw new Error(`no screen ${id}`)
    const root = createRoot(document.getElementById('root') as HTMLElement)
    flushSync(() => root.render(<Screen api={api} navigate={navigate} />))
  },
}
