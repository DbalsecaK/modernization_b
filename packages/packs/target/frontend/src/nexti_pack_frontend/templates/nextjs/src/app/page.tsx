import Link from 'next/link'
import { LINKS, TITLE } from './screens/routes'

/** The entry of the app: the navigation to every screen, the start screen first. */
export default function Home() {
  return (
    <main aria-labelledby="app-title" className="nx-screen">
      <h1 id="app-title">{TITLE}</h1>
      <nav aria-labelledby="app-title">
        <ul>
          {LINKS.map((link) => (
            <li key={link.href}>
              <Link href={link.href}>{link.name}</Link>
            </li>
          ))}
        </ul>
      </nav>
    </main>
  )
}
