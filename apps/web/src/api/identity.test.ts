import { describe, expect, it } from 'vitest'
import { parseDomains, toGroupRoles } from './identity'

describe('identity form helpers', () => {
  it('reads domains separated by commas, spaces or semicolons, lowercase and without repeats', () => {
    expect(parseDomains(' AndesBank.example, andes.example.;andesbank.example  ')).toEqual([
      'andesbank.example',
      'andes.example',
    ])
    expect(parseDomains('')).toEqual([])
  })

  it('keeps only complete group → role rows', () => {
    expect(
      toGroupRoles([
        { group: ' it-admins ', role: 'tenantAdmin' },
        { group: '', role: 'finance' },
        { group: 'auditors', role: '' },
      ]),
    ).toEqual({ 'it-admins': 'tenantAdmin' })
  })
})
