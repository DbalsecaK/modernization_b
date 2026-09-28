import { useSyncExternalStore } from 'react'
import { readStorage, writeStorage } from './storage'

// Mock session. In the real platform authentication is done by Keycloak (spec 15.1, D-19): the BFF runs the
// OIDC code flow and issues an httpOnly session cookie; the browser never holds a token. The login, MFA,
// reset and invitation screens become a Keycloak theme (Keycloakify) built from these prototype pages.
const KEY = 'nexti.session'
const listeners = new Set<() => void>()

export type AuthMethod = 'sso' | 'password'

export interface Session {
  email: string
  method: AuthMethod
  provider?: string
}

function read(): string | null {
  return readStorage(KEY)
}

export function signIn(session: Session) {
  writeStorage(KEY, JSON.stringify(session))
  listeners.forEach((l) => l())
}

export function signOut() {
  writeStorage(KEY, null)
  listeners.forEach((l) => l())
}

export function getSession(): Session | null {
  const raw = read()
  if (!raw) return null
  try {
    return JSON.parse(raw) as Session
  } catch {
    return null
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export function useSession(): Session | null {
  const raw = useSyncExternalStore(subscribe, read, () => null)
  if (!raw) return null
  try {
    return JSON.parse(raw) as Session
  } catch {
    return null
  }
}

// Home-realm discovery: domains whose tenant enforces SSO (mock of the tenant identity settings).
export const ssoDomains: Record<string, { provider: string; enforced: boolean }> = {
  'andesbank.example': { provider: 'Microsoft Entra ID', enforced: true },
  'pacificcu.example': { provider: 'Okta', enforced: false },
  'nexti.example': { provider: 'Google Workspace', enforced: false },
}

export function discoverRealm(email: string) {
  const domain = email.split('@')[1]?.toLowerCase().trim()
  return domain ? ssoDomains[domain] ?? null : null
}

// Pending password sign-in waiting for its second factor (mock of the server-side MFA challenge).
let pendingEmail: string | null = null
let pendingRedirect: string | undefined

export function startMfaChallenge(email: string, redirectTo?: string) {
  pendingEmail = email
  pendingRedirect = redirectTo
}

export function pendingChallenge() {
  return pendingEmail ? { email: pendingEmail, redirect: pendingRedirect } : null
}

export function clearChallenge() {
  pendingEmail = null
  pendingRedirect = undefined
}
