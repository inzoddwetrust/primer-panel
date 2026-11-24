import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { BUILT_IN, FALLBACK_LANGUAGE, chooseLanguage } from './texts'

describe('the built-in texts', () => {
  it('are en and ru, each with every key', () => {
    expect(Object.keys(BUILT_IN).sort()).toEqual(['en', 'ru'])
    expect(Object.keys(BUILT_IN.ru ?? {}).sort()).toEqual(Object.keys(BUILT_IN.en ?? {}).sort())
    expect(BUILT_IN.ru?.config_error).not.toBe(BUILT_IN.en?.config_error)
    expect(FALLBACK_LANGUAGE).toBe('en')
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
