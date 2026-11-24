import { describe, expect, it } from 'vitest'
import {
  cell,
  columnTargets,
  inviteLink,
  inviteState,
  mayChange,
  setToSend,
  staffTouched,
  visiblePermissions,
  type Member,
} from './access'

// The list of the API, written out; the page knows none of its own.
const ALL = ['deploy_test', 'deploy_prod', 'seeds', 'db', 'people']

function member(isAdmin: boolean, permissions: string[], effective = permissions): Member {
  return {
    user: { id: 'u', telegram_id: 1, first_name: 'A', username: null },
    is_admin: isAdmin,
    permissions,
    effective,
  }
}

describe('the rules of the screens of access', () => {
  it('shows a person only what they hold; the superadmin all', () => {
    expect(visiblePermissions(ALL, ['seeds', 'people'], false)).toEqual(['seeds', 'people'])
    expect(visiblePermissions(ALL, [], true)).toEqual(ALL)
  })

  it('sends the chosen and keeps what is held out of sight', () => {
    // the admin sees seeds and people; the staff member holds db from the superadmin
    expect(setToSend(ALL, ['seeds'], ['db', 'people'], ['seeds', 'people'])).toEqual([
      'seeds',
      'db',
    ])
    expect(setToSend(ALL, [], ['db'], ALL)).toEqual([])
  })

  it('shows an admin’s people as the API’s, not a checkbox', () => {
    const admin = member(true, ['seeds'], ['seeds', 'people'])
    expect(cell(admin, 'people')).toEqual({ on: true, fixed: true })
    expect(cell(admin, 'seeds')).toEqual({ on: true, fixed: false })
    expect(cell(admin, 'db')).toEqual({ on: false, fixed: false })
  })

  it('turns a column on in the rows where it is off', () => {
    const rows = [{ member: member(true, ['db']) }, { member: member(true, []) }]
    expect(columnTargets(rows, 'db')).toEqual([rows[1]])
    expect(columnTargets(rows, 'seeds')).toEqual(rows)
  })

  it('counts the staff a taken permission reaches', () => {
    const members = [member(true, ['db']), member(false, ['db']), member(false, ['seeds'])]
    expect(staffTouched(members, ['db'])).toBe(1)
    expect(staffTouched(members, ['db', 'seeds'])).toBe(2)
  })

  it('links an invite to the page’s own sign-in', () => {
    expect(inviteLink('https://primer.team', 'a/b c')).toBe(
      'https://primer.team/login?invite=a%2Fb%20c',
    )
  })

  it('names an invite’s state', () => {
    const now = new Date('2026-11-24T12:00:00Z')
    const base = { id: 'i', is_admin: false, permissions: [], used_at: null, revoked_at: null }
    expect(inviteState({ ...base, expires_at: '2026-11-25T00:00:00Z' }, now)).toBe('active')
    expect(inviteState({ ...base, expires_at: '2026-11-24T00:00:00Z' }, now)).toBe('expired')
    expect(inviteState({ ...base, expires_at: '2026-11-25T00:00:00Z', used_at: 'x' }, now)).toBe(
      'used',
    )
    expect(inviteState({ ...base, expires_at: '2026-11-25T00:00:00Z', revoked_at: 'x' }, now)).toBe(
      'revoked',
    )
  })

  it('lets the superadmin alone change an admin; people change staff', () => {
    expect(mayChange(member(true, []), ['people'], false)).toBe(false)
    expect(mayChange(member(true, []), [], true)).toBe(true)
    expect(mayChange(member(false, []), ['people'], false)).toBe(true)
    expect(mayChange(member(false, []), ['seeds'], false)).toBe(false)
  })
})
