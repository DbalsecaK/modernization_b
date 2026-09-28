import type { Schemas } from './client'

type Me = Schemas['MeOut']

// Access rules of the menu and the route guards. The API authorizes every call anyway (OpenFGA); this only
// hides what the user could not use.
export function can(me: Me | null, permission: string): boolean {
  return !!me?.permissions.includes(permission)
}

export function isPlatformOperator(me: Me | null): boolean {
  return !!me?.platformRoles.some((r) => r === 'superAdmin' || r === 'supportOperator')
}

export type NavKey = 'dashboard' | 'projects' | 'tasks' | 'usage' | 'aiConfig' | 'catalog' | 'admin' | 'platform'

export function canOpen(me: Me | null, key: NavKey): boolean {
  switch (key) {
    case 'usage':
      return can(me, 'usage.view')
    case 'aiConfig':
      return can(me, 'models.configure')
    case 'admin':
      return can(me, 'users.manage') || can(me, 'audit.view')
    case 'platform':
      return isPlatformOperator(me)
    default:
      return !!me
  }
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : (parts[0] ?? '?').slice(0, 2)
  return letters.toUpperCase()
}
