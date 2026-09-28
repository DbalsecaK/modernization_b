import { describe, expect, it } from 'vitest'
import { canOpen, initials } from './access'
import type { Schemas } from './client'

function me(permissions: string[], platformRoles: string[] = []): Schemas['MeOut'] {
  return {
    user: { id: 'u', email: 'a@b.example', displayName: 'Ana Vélez', locale: 'en' },
    activeTenant: null,
    tenants: [],
    platformRoles,
    permissions,
    authMethod: 'keycloak',
    csrfToken: 'x',
  }
}

describe('menu access', () => {
  it('shows each section only with its permission', () => {
    const member = me([])
    expect(canOpen(member, 'dashboard')).toBe(true)
    expect(canOpen(member, 'admin')).toBe(false)
    expect(canOpen(member, 'usage')).toBe(false)
    expect(canOpen(member, 'aiConfig')).toBe(false)
    expect(canOpen(member, 'platform')).toBe(false)
  })

  it('opens administration to user managers and auditors', () => {
    expect(canOpen(me(['users.manage']), 'admin')).toBe(true)
    expect(canOpen(me(['audit.view']), 'admin')).toBe(true)
  })

  it('opens the platform section to NexTI operators only', () => {
    expect(canOpen(me([], ['superAdmin']), 'platform')).toBe(true)
    expect(canOpen(me([], ['supportOperator']), 'platform')).toBe(true)
  })

  it('hides everything without a session', () => {
    expect(canOpen(null, 'dashboard')).toBe(false)
  })
})

describe('initials', () => {
  it('uses the first and last names', () => {
    expect(initials('Ana María Vélez')).toBe('AV')
    expect(initials('carlos')).toBe('CA')
    expect(initials('  ')).toBe('?')
  })
})
