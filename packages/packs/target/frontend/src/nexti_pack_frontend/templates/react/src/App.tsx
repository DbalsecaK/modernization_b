import { useMemo, useState } from 'react'
import { createApi } from './api/client'
import { SCREENS, START } from './screens'

/** The shell: one screen at a time; a screen opens another with navigate(id). */
export default function App() {
  const api = useMemo(() => createApi(), [])
  const [current, setCurrent] = useState(START)
  const Screen = SCREENS[current]
  return Screen ? <Screen api={api} navigate={setCurrent} /> : null
}
