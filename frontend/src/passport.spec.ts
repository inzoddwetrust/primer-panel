import { describe, expect, it } from 'vitest'
import { kindOf, mayEdit, ruleOf, short, textOf, valueOf, type Shown } from './passport'

const ME = {
  user: { id: 'me', telegram_id: 99, first_name: 'Me', username: null },
  is_superadmin: false,
  projects: [
    {
      project: { id: 'pa', slug: 'a', name: 'A', kind: 'product' },
      is_admin: false,
      permissions: ['deploy_test', 'passport'],
    },
    {
      project: { id: 'pb', slug: 'b', name: 'B', kind: 'product' },
      is_admin: true,
      permissions: ['deploy_test'],
    },
  ],
  panel_grants: [],
}

describe('the passport, on the page', () => {
  it("is edited with `passport` of the server's project, or by the superadmin", () => {
    expect(mayEdit(ME, 'pa')).toBe(true)
    expect(mayEdit(ME, 'pb')).toBe(false)
    expect(mayEdit(ME, 'pz')).toBe(false)
    expect(mayEdit({ ...ME, is_superadmin: true }, 'pz')).toBe(true)
    expect(mayEdit(null, 'pa')).toBe(false)
  })

  it('sends a value back in the JSON type it has', () => {
    expect([kindOf('x'), kindOf(2), kindOf(false), kindOf(['a']), kindOf({ a: 1 })]).toEqual([
      'string',
      'number',
      'boolean',
      'json',
      'json',
    ])
    expect(valueOf('number', '2', false)).toBe(2)
    expect(valueOf('string', '2', false)).toBe('2')
    expect(valueOf('boolean', '', true)).toBe(true)
    expect(valueOf('json', '["ru", "en"]', false)).toEqual(['ru', 'en'])
    expect(() => valueOf('number', 'two', false)).toThrow()
    expect(() => valueOf('number', ' ', false)).toThrow()
    expect(() => valueOf('json', '[ru', false)).toThrow()
    expect([textOf('x'), textOf(2), textOf(true), textOf(['a'])]).toEqual([
      'x',
      '2',
      'true',
      '["a"]',
    ])
  })

  it('names the rule of a field that is not obvious, and a commit short', () => {
    const passport = {
      rules: [{ path: ['policies', 'gc', 'keep_releases'], rule: 'keep_releases' }],
    } as unknown as Shown
    expect(ruleOf(passport, ['policies', 'gc', 'keep_releases'])).toBe('keep_releases')
    expect(ruleOf(passport, ['policies', 'gc'])).toBeNull()
    expect(short('0123456789abcdef')).toBe('0123456')
    expect(short(null)).toBe('')
  })
})
