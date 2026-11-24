// The texts of the page, by language: built into the image.
//
// The product's languages are its built-in texts, src/texts/<language>.json,
// declared as `languages` in primer.yaml (protocol 5.2.2). They are the
// messages of vue-i18n (./i18n): one mechanism, the keys the same in every
// language (a test holds them so). The texts of a refused sign-in are keyed
// by the API's codes (./login).
//
// The person's language is the first of the browser's languages the instance
// turns on, by its primary subtag; none -- the instance's default. Which
// languages are on and the default come from /config.json (./config, the
// passport through the env, protocol 5.2.2). FALLBACK_LANGUAGE is the page's
// language before that is known -- when /config.json cannot be read.

import en from './texts/en.json'
import ru from './texts/ru.json'

export type Texts = typeof en

export const BUILT_IN: Readonly<Record<string, Texts>> = { en, ru }

export const FALLBACK_LANGUAGE = 'en'

export function chooseLanguage(
  preferred: readonly string[],
  enabled: readonly string[],
  fallback: string,
): string {
  for (const tag of preferred) {
    const primary = tag.toLowerCase().split('-')[0] ?? ''
    if (enabled.includes(primary)) {
      return primary
    }
  }
  return fallback
}
