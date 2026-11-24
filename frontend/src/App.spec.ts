import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import { createPinia } from 'pinia'
import App from './App.vue'
import source from './App.vue?raw'
import loginSource from './views/LoginView.vue?raw'
import meSource from './views/MeView.vue?raw'
import { createPanelI18n } from './i18n'
import { createPanelRouter } from './router'
import { BUILT_IN } from './texts'

// Changed by DM-151: the page is the shell of the router -- the pages are the
// sign-in and the person; the texts are vue-i18n's over the built-in ones.
// Changed by DM-154: the menu reads the person (pinia); `/` is the fleet.
describe('App', () => {
  it('shows the configuration error instead of the pages', () => {
    const wrapper = mount(App, {
      props: { error: '/config.json answered 404' },
      global: { plugins: [createPanelI18n('ru')] },
    })
    expect(wrapper.get('[data-test="config-error"]').text()).toBe(
      `${BUILT_IN.ru?.config_error} /config.json answered 404`,
    )
    expect(wrapper.get('[data-test="title"]').text()).toBe(BUILT_IN.ru?.title)
  })

  it('shows the page of the route when the configuration is read', async () => {
    const router = createPanelRouter(createMemoryHistory())
    await router.push('/nowhere')
    expect(router.currentRoute.value.path).toBe('/')
    const wrapper = mount(App, {
      props: { error: null },
      global: {
        plugins: [createPanelI18n('en'), router, createPinia()],
        stubs: { FleetView: true, MeView: true },
      },
    })
    expect(wrapper.find('[data-test="config-error"]').exists()).toBe(false)
  })

  it('takes colors, fonts and the logo only from custom properties', () => {
    for (const file of [source, loginSource, meSource]) {
      const start = file.indexOf('<style')
      if (start < 0) {
        continue
      }
      const style = file.slice(start)
      expect(style).not.toMatch(/#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|url\(/)
    }
    expect(source.slice(source.indexOf('<style'))).toContain('var(--color-brand-primary)')
  })
})
