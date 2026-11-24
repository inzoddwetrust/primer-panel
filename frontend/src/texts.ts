// The texts of the page, by language: built into the image.
//
// The product's languages are its built-in texts, src/texts/<language>.json,
// declared as `languages` in primer.yaml (protocol 5.2.2).
//
// The person's language is the first of the browser's languages the instance
// turns on, by its primary subtag; none -- the instance's default. Which
// languages are on and the default come from /config.json (./config, the
// passport through the env, protocol 5.2.2). FALLBACK_LANGUAGE is the page's
// language before that is known -- when /config.json cannot be read.

import en from './texts/en.json'
import ru from './texts/ru.json'

export interface Texts {
  title: string
  config_error: string
  api_label: string
}

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
