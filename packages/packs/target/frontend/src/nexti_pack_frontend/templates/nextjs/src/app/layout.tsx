import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import '@nexti/ds/ds.css'
import { TITLE } from './screens/routes'

export const metadata: Metadata = { title: TITLE }

/** The root layout of the App Router: the document and the NexTI design system styles. */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  )
}
