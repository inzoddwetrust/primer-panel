import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AddServerView from './AddServerView.vue'
import { API_CLIENT } from '../api/client'
import { RUNTIME_CONFIG } from '../config-key'
import { createPanelI18n } from '../i18n'
import { createPanelRouter } from '../router'
import { fakeApi, type Answer } from '../testing'

const TOKEN = 'tok-0123456789abcdef0123456789abcdef'
const ISSUED = {
  id: 't1',
  token: TOKEN,
  expires_at: '2099-01-01T00:00:00Z',
  release: '0.1.10',
  install_url: 'https://github.com/inzoddwetrust/primer/releases/download/v0.1.10/install.sh',
  box_refusals: ['token-used', 'token-expired', 'register:already', 'from-the-future'],
}
const STATE = 'GET /api/v1/projects/pa/registration-tokens/t1'

async function view(answers: Record<string, Answer>) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createPanelRouter(createMemoryHistory())
  await router.push('/projects')
  const api = fakeApi({ 'POST /api/v1/projects/pa/registration-tokens': ISSUED, ...answers })
  const wrapper = mount(AddServerView, {
    props: { projectId: 'pa' },
    global: {
      plugins: [pinia, router, createPanelI18n('en')],
      provide: {
        [API_CLIENT as symbol]: api.client,
        [RUNTIME_CONFIG as symbol]: {
          apiOrigin: 'https://api.example.com',
          languages: ['en'],
          defaultLanguage: 'en',
        },
      },
    },
  })
  await wrapper.get('[data-test="issue"]').trigger('click')
  await flushPromises()
  return { wrapper, asked: api.asked }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('a new server', () => {
  it('test_probe_DM_157_command_has_release_and_token', async () => {
    // The command carries the token in the environment, never as an argument;
    // the screen carries the machine's release and its install.sh.
    const { wrapper } = await view({
      [STATE]: { used_at: null, expires_at: ISSUED.expires_at, server: null },
    })
    const command = wrapper.get('[data-test="command"]').text()
    expect(wrapper.get('[data-test="command"]').element.textContent).toBe(
      ` PRIDEM_REGISTER_TOKEN=${TOKEN} pridem register --panel https://api.example.com`,
    )
    expect(command).not.toMatch(/--token/)
    expect(wrapper.get('[data-test="needs"]').text()).toContain('v0.1.10')
    expect(wrapper.get('[data-test="install"]').text()).toBe(
      `curl -fsSLO ${ISSUED.install_url} && bash install.sh`,
    )
    expect(wrapper.get('[data-test="warning"]').text()).toContain('sudo drops the variable')
  })

  it('waits for the box and stops when it registered', async () => {
    vi.useFakeTimers()
    let state: unknown = { used_at: null, expires_at: ISSUED.expires_at, server: null }
    const { wrapper, asked } = await view({ [STATE]: () => new Response(JSON.stringify(state)) })
    const polls = () => asked.filter((a) => a.path.endsWith('/registration-tokens/t1')).length
    expect(wrapper.find('[data-test="waiting"]').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(polls()).toBe(1)
    state = {
      used_at: '2026-11-24T12:00:00Z',
      expires_at: ISSUED.expires_at,
      server: { id: 's9', name: 'velo-dev' },
    }
    await vi.advanceTimersByTimeAsync(5_000)
    expect(wrapper.get('[data-test="registered"]').text()).toContain('velo-dev')
    await vi.advanceTimersByTimeAsync(30_000)
    expect(polls()).toBe(2)
  })

  it('stops when the token expired', async () => {
    vi.useFakeTimers()
    const { wrapper, asked } = await view({
      [STATE]: { used_at: null, expires_at: '2000-01-01T00:00:00Z', server: null },
    })
    await vi.advanceTimersByTimeAsync(5_000)
    expect(wrapper.find('[data-test="expired"]').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(asked.filter((a) => a.path.endsWith('/registration-tokens/t1')).length).toBe(1)
  })

  it('says what a box may answer, from the API', async () => {
    const { wrapper } = await view({})
    const text = wrapper.get('[data-test="refusals"]').text()
    expect(text).toContain('token-used')
    expect(text).toContain('the token is used: issue a new one')
    expect(text).toContain('register:already')
    expect(text).toContain('from-the-future — from-the-future')
  })

  it('shows a refusal of the API to issue', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createPanelRouter(createMemoryHistory())
    await router.push('/projects')
    const api = fakeApi({
      'POST /api/v1/projects/pa/registration-tokens': () =>
        new Response(
          '{"error":{"class":"forbidden","message":"The permission servers is needed"}}',
          {
            status: 403,
          },
        ),
    })
    const wrapper = mount(AddServerView, {
      props: { projectId: 'pa' },
      global: {
        plugins: [pinia, router, createPanelI18n('en')],
        provide: {
          [API_CLIENT as symbol]: api.client,
          [RUNTIME_CONFIG as symbol]: {
            apiOrigin: 'https://api.example.com',
            languages: ['en'],
            defaultLanguage: 'en',
          },
        },
      },
    })
    await wrapper.get('[data-test="issue"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="error-class"]').text()).toBe('forbidden')
    expect(wrapper.find('[data-test="command"]').exists()).toBe(false)
  })
})
