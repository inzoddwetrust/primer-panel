import { describe, expect, it } from 'vitest'
import { argsFrom, fieldKind, label, missing, needsName, type Button } from './server'

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
