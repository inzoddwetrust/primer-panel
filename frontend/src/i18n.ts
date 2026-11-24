// vue-i18n over the built-in texts (./texts): the Composition API mode, the
// language of the page chosen by ./texts, English when a key is missing.

import { createI18n } from 'vue-i18n'
import { BUILT_IN, FALLBACK_LANGUAGE, type Texts } from './texts'

export function createPanelI18n(language: string) {
  return createI18n<[Texts], string, false>({
    legacy: false,
    locale: language,
    fallbackLocale: FALLBACK_LANGUAGE,
    messages: BUILT_IN as Record<string, Texts>,
  })
}
