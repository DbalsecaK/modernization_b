import type { Api } from '../api/client'

/** What every page receives: the typed backend client and the navigation. */
export interface ScreenProps {
  api: Api
  navigate: (screen: string) => void
}
