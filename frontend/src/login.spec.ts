import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import LoginView from './views/LoginView.vue'
import { RUNTIME_CONFIG } from './config-key'
import { createPanelI18n } from './i18n'
import { LOGIN_REFUSALS, parseRefusal, startUrl } from './login'
import { createPanelRouter } from './router'
import { BUILT_IN } from './texts'

const CONFIG = {
  apiOrigin: 'https://api.example.com',
  languages: ['en', 'ru'],
  defaultLanguage: 'ru',
}

async function login(address: string, language = 'en') {
  const router = createPanelRouter(createMemoryHistory())
  await router.push(address)
  const wrapper = mount(LoginView, {
    global: {
      plugins: [createPanelI18n(language), router],
      provide: { [RUNTIME_CONFIG as symbol]: CONFIG },
    },
  })
  return wrapper
}

describe('the refusal in the fragment of the address', () => {
  it('test_probe_DM_151_refusal_fragment_shows_reason_and_id', async () => {
    // Every code of a refused sign-in shows its own text; the person's
    // Telegram id is shown with it.
    for (const language of ['en', 'ru']) {
      for (const code of LOGIN_REFUSALS) {
        const wrapper = await login(`/login#reason=${code}&telegram_id=7000000403`, language)
        expect(wrapper.get('[data-test="refusal-text"]').text()).toBe(
          BUILT_IN[language]?.refusal[code],
        )
        expect(wrapper.get('[data-test="telegram-id"]').text()).toBe(
          `${BUILT_IN[language]?.refusal.your_id} 7000000403`,
        )
        expect(wrapper.get('[data-test="login-button"]').attributes('href')).toBe(
          'https://api.example.com/auth/telegram/start',
        )
      }
    }
    // The pair: no fragment -- the button alone.
    const plain = await login('/login')
    expect(plain.find('[data-test="refusal"]').exists()).toBe(false)
    expect(plain.find('[data-test="login-button"]').exists()).toBe(true)
  })

  it('shows a refusal without an id, and an unknown code as it came', async () => {
    const withoutId = await login('/login#reason=stranger')
    expect(withoutId.find('[data-test="telegram-id"]').exists()).toBe(false)
    const unknown = await login('/login#reason=moon_phase&telegram_id=5')
    expect(unknown.get('[data-test="refusal-text"]').text()).toBe(
      `${BUILT_IN.en?.refusal.unknown} moon_phase`,
    )
    expect(unknown.get('[data-test="telegram-id"]').text()).toContain('5')
  })

  it('shows an id of digits only', () => {
    expect(parseRefusal('#reason=stranger&telegram_id=abc')?.telegramId).toBeNull()
    expect(parseRefusal('#reason=stranger&telegram_id=12<b>')?.telegramId).toBeNull()
    expect(parseRefusal('#reason=stranger&telegram_id=123')?.telegramId).toBe('123')
    expect(parseRefusal('#reason=')).toBeNull()
    expect(parseRefusal('')).toBeNull()
  })

  it('hands an invite of the address on to the sign-in, and nowhere else', async () => {
    const wrapper = await login('/login?invite=tok%2Fen%201')
    expect(wrapper.get('[data-test="login-button"]').attributes('href')).toBe(
      'https://api.example.com/auth/telegram/start?invite=tok%2Fen%201',
    )
    expect(wrapper.find('[data-test="invite-note"]').exists()).toBe(true)
    expect(startUrl('https://api.example.com', null)).toBe(
      'https://api.example.com/auth/telegram/start',
    )
  })
})
