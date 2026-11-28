import { describe, expect, it } from 'vitest'
import { argsFrom, fieldKind, label, missing, needsName, rollsBack, type Button } from './server'

function button(extra: Partial<Button> = {}): Button {
  return {
    verb: 'db',
    preset: {},
    schema: {
      type: 'object',
      properties: {
        action: { enum: ['dump', 'restore', 'reset'], type: 'string' },
        stack: { type: 'string' },
        dump: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null },
        all: { type: 'boolean', default: false },
        tries: { type: 'array', items: { type: 'string' } },
        odd: { type: 'object' },
      },
      required: ['action', 'stack'],
    },
    positionals: [],
    sure: false,
    name: 'when',
    destructive_options: { action: ['restore', 'reset'] },
    sure_below: null,
    ...extra,
  }
}

describe('the rules of a server’s card, as data of the API', () => {
  it('draws each field by its schema', () => {
    const fields = button().schema.properties
    expect(Object.fromEntries(Object.entries(fields).map(([n, f]) => [n, fieldKind(f)]))).toEqual({
      action: 'enum',
      stack: 'string',
      dump: 'string',
      all: 'boolean',
      tries: 'list',
      odd: 'json',
    })
  })

  it('sends the preset and the filled fields, leaving empty optionals out', () => {
    const args = argsFrom(button({ preset: { x: 1 } }), {
      text: {
        action: 'dump',
        stack: 'velo',
        dump: '',
        tries: 'a=1.0.0\n\n b=2.0.0 ',
        odd: '{"k": 1}',
      },
      flag: { all: false },
    })
    expect(args).toEqual({
      x: 1,
      action: 'dump',
      stack: 'velo',
      tries: ['a=1.0.0', 'b=2.0.0'],
      odd: { k: 1 },
    })
  })

  it('names the required fields left empty', () => {
    expect(missing(button(), { action: 'dump' })).toEqual(['stack'])
  })

  it('asks for the name as the button says', () => {
    expect(needsName(button(), { action: 'restore' }, false)).toBe(true)
    expect(needsName(button(), { action: 'dump' }, false)).toBe(false)
    expect(needsName(button({ name: 'always' }), {}, false)).toBe(true)
    expect(needsName(button({ name: 'ask' }), {}, false)).toBe(false)
    expect(needsName(button({ name: 'ask' }), {}, true)).toBe(true)
    expect(needsName(button({ name: 'never' }), { action: 'restore' }, true)).toBe(false)
  })

  it('labels a button with its preset action', () => {
    // Changed by DM-202: ssl status is no button
    expect(label(button({ verb: 'ssl', preset: { action: 'renew' } }))).toBe('ssl renew')
    expect(label(button({ verb: 'update' }))).toBe('update')
  })
})

describe('a rollback of the machine (DM-218)', () => {
  const update = button({ verb: 'self-update', sure_below: 'tag' })

  it.each([
    ['v0.1.12', '0.1.13', true],
    ['v0.1.9', '0.1.10', true],
    ['v0.2.0', '0.10.0', true],
    ['v0.1.12', '0.1.12', false],
    ['v0.1.13', '0.1.12', false],
    ['v0.1.10', '0.1.9', false], // numbers, not texts
    ['v0.1.12', null, false],
    ['v0.1.12', 'odd', false],
    ['latest', '0.1.13', false],
  ])('%s on a box at %s: %s', (tag, machine, back) => {
    expect(rollsBack(update, { tag }, machine)).toBe(back)
  })

  it('a button that names no field is never a rollback', () => {
    expect(rollsBack(button({ sure_below: null }), { tag: 'v0.1.1' }, '0.1.13')).toBe(false)
  })
})
