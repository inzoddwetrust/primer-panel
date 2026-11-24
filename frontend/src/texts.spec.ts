import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { BUILT_IN, FALLBACK_LANGUAGE, chooseLanguage } from './texts'
import { LOGIN_REFUSALS } from './login'

// Every key of a nested object of texts, as a dotted path.
function keys(texts: object, prefix = ''): string[] {
  return Object.entries(texts).flatMap(([key, value]) =>
    typeof value === 'object' && value !== null
      ? keys(value as object, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  )
}

// The codes of a refused sign-in, as the API names them (LoginRefusal of
// app/access/login.py, DM-150), written out here.
const API_REFUSALS = [
  'restart',
  'try_later',
  'refused',
  'defect',
  'unavailable',
  'foreign_state',
  'stranger',
  'deactivated',
  'invite_invalid',
]

// Changed by DM-151: the texts are nested messages of vue-i18n; every key is
// in every language, and every code of a refused sign-in has its text.
describe('the built-in texts', () => {
  it('are en and ru, each with every key', () => {
    expect(Object.keys(BUILT_IN).sort()).toEqual(['en', 'ru'])
    expect(keys(BUILT_IN.ru ?? {}).sort()).toEqual(keys(BUILT_IN.en ?? {}).sort())
    expect(BUILT_IN.ru?.config_error).not.toBe(BUILT_IN.en?.config_error)
    expect(FALLBACK_LANGUAGE).toBe('en')
  })

  it('have a text for every code of a refused sign-in, and the page knows them all', () => {
    expect([...LOGIN_REFUSALS]).toEqual(API_REFUSALS)
    for (const language of ['en', 'ru']) {
      const refusal = BUILT_IN[language]?.refusal ?? {}
      expect(Object.keys(refusal).sort()).toEqual([...API_REFUSALS, 'unknown', 'your_id'].sort())
      for (const value of Object.values(refusal)) {
        expect(value).not.toBe('')
      }
    }
  })
})

describe('the languages of the product', () => {
  // primer.yaml declares what the built-in texts are: the machine checks an
  // instance's languages against the file, the page against its texts
  it('are its built-in texts, as primer.yaml declares them', () => {
    // vitest runs in frontend/, the package's root (vitest.config.ts)
    const file = join(process.cwd(), '..', 'primer.yaml')
    const line = readFileSync(file, 'utf-8')
      .split('\n')
      .find((text) => text.startsWith('languages:'))
    const declared = (line ?? '').replace(/#.*$/, '').match(/\[(.*)\]/)?.[1] ?? ''
    expect(declared.split(',').map((code) => code.trim())).toEqual(Object.keys(BUILT_IN))
  })
})

describe('chooseLanguage', () => {
  // the person's language: the first of the browser's the instance turns on,
  // by its primary subtag; none -- the instance's default
  it.each([
    [['ru-RU', 'en'], ['en', 'ru'], 'en', 'ru'],
    [['de', 'RU'], ['en', 'ru'], 'en', 'ru'],
    [['en-GB', 'ru'], ['en', 'ru'], 'ru', 'en'],
    [['de', 'fr'], ['en', 'ru'], 'ru', 'ru'],
    [[], ['en', 'ru'], 'ru', 'ru'],
    // a language of the product the instance does not turn on is not taken
    [['ru-RU', 'en'], ['en'], 'en', 'en'],
    [['ru'], ['en'], 'en', 'en'],
    // the first turned on wins, in the browser's order, not the instance's
    [['en', 'ru'], ['ru', 'en'], 'ru', 'en'],
  ])('%j of %j, default %s -> %s', (preferred, enabled, fallback, language) => {
    expect(chooseLanguage(preferred, enabled, fallback)).toBe(language)
  })
})
