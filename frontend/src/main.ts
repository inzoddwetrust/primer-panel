import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { createWebHistory } from 'vue-router'
import './theme.css'
import App from './App.vue'
import { API_CLIENT, createApiClient } from './api/client'
import { loadConfig } from './config'
import { RUNTIME_CONFIG } from './config-key'
import { createPanelI18n } from './i18n'
import { createPanelRouter, guard } from './router'
import { STREAM } from './run'
import { useMeStore } from './stores/me'
import { BUILT_IN, FALLBACK_LANGUAGE, chooseLanguage } from './texts'

// The page starts from /config.json: the API's origin and the instance's
// languages (./config). Until it is read -- and when it cannot be -- the page
// speaks the first of the browser's languages the product has, else
// FALLBACK_LANGUAGE (protocol 5.2.2), and shows the error.
export async function start(): Promise<void> {
  const preferred = navigator.languages ?? [navigator.language]
  let language = chooseLanguage(preferred, Object.keys(BUILT_IN), FALLBACK_LANGUAGE)
  try {
    const config = await loadConfig()
    language = chooseLanguage(preferred, config.languages, config.defaultLanguage)
    const i18n = createPanelI18n(language)
    document.documentElement.lang = language
    document.title = i18n.global.t('title')
    const pinia = createPinia()
    const router = createPanelRouter(createWebHistory())
    const app = createApp(App, { error: null })
    app.use(pinia).use(i18n)
    const me = useMeStore(pinia)
    // A 401 anywhere: the person is dropped and the sign-in shown (gate R4).
    const api = createApiClient({
      origin: config.apiOrigin,
      onUnauthorized: () => {
        me.clear()
        void router.replace({ name: 'login' })
      },
    })
    router.beforeEach(
      guard(
        () => me.load(api),
        () => me.me?.is_superadmin === true,
      ),
    )
    // A run's stream, with the session's cookie (DM-156)
    const stream = (url: string) => new EventSource(url, { withCredentials: true })
    app.provide(API_CLIENT, api).provide(RUNTIME_CONFIG, config).provide(STREAM, stream).use(router)
    app.mount('#app')
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error)
    document.documentElement.lang = language
    createApp(App, { error: message }).use(createPanelI18n(language)).mount('#app')
  }
}

void start()
