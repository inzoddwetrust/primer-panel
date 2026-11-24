import { describe, expect, it } from 'vitest'
import { guard } from './router'

describe('the guard of the pages', () => {
  it('lets the sign-in through without asking', async () => {
    let asked = 0
    const check = guard(
      async () => {
        asked++
        return 'signed_in'
      },
      () => false,
    )
    expect(await check({ name: 'login' })).toBe(true)
    expect(asked).toBe(0)
  })

  it('sends a person with no session to the sign-in', async () => {
    const check = guard(
      async () => 'unauthorized',
      () => false,
    )
    expect(await check({ name: 'projects' })).toEqual({ name: 'login' })
  })

  it('keeps the superadmin’s page for the superadmin', async () => {
    const plain = guard(
      async () => 'signed_in',
      () => false,
    )
    expect(await plain({ name: 'admins' })).toEqual({ name: 'projects' })
    expect(await plain({ name: 'project' })).toBe(true)
    const superadmin = guard(
      async () => 'signed_in',
      () => true,
    )
    expect(await superadmin({ name: 'admins' })).toBe(true)
  })
})
