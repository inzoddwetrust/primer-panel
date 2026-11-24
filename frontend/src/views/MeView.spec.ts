import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import MeView from './MeView.vue'
import { API_CLIENT, createApiClient, type ApiClient } from '../api/client'
import { createPanelI18n } from '../i18n'
import { createPanelRouter } from '../router'
import { useMeStore } from '../stores/me'

const ME = {
  user: { id: 'u1', telegram_id: 7000000011, first_name: 'Anna', username: 'anna' },
  is_superadmin: false,
  projects: [
    {
      project: { id: 'p1', slug: 'velo', name: 'Velo', kind: 'product' },
      is_admin: true,
      permissions: ['deploy_test', 'people'],
    },
  ],
  panel_grants: [],
}

function api(response: () => Response) {
  const fetchFn = vi.fn(async () => response()) as unknown as typeof fetch
  return { client: createApiClient({ origin: 'https://api.example.com', fetchFn }), fetchFn }
}

async function page(client: ApiClient) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createPanelRouter(createMemoryHistory())
  await router.push('/')
  const store = useMeStore()
  await store.load(client)
  const wrapper = mount(MeView, {
    global: {
      plugins: [pinia, router, createPanelI18n('en')],
      provide: { [API_CLIENT as symbol]: client },
    },
  })
  return { wrapper, router, store }
}

describe('the page of the person', () => {
  it('shows /api/v1/me', async () => {
    const { wrapper } = await page(api(() => new Response(JSON.stringify(ME))).client)
    expect(wrapper.get('[data-test="name"]').text()).toBe('Anna')
    expect(wrapper.get('[data-test="telegram-id"]').text()).toContain('7000000011')
    expect(wrapper.get('[data-test="projects"]').text()).toContain('Velo')
    expect(wrapper.get('[data-test="projects"]').text()).toContain('deploy_test, people')
    expect(wrapper.find('[data-test="superadmin"]').exists()).toBe(false)
    // Changed by DM-152: the way to the screens of access
    expect(wrapper.find('[data-test="projects-link"]').exists()).toBe(true)
  })

  it('shows an error of the API by its class, message and request', async () => {
    const body = '{"error":{"class":"forbidden","message":"The account is deactivated"}}'
    const { wrapper } = await page(
      api(() => new Response(body, { status: 403, headers: { 'X-Request-ID': 'req-7' } })).client,
    )
    expect(wrapper.get('[data-test="error-class"]').text()).toBe('forbidden')
    expect(wrapper.get('[data-test="error-message"]').text()).toBe('The account is deactivated')
    expect(wrapper.get('[data-test="request-id"]').text()).toContain('req-7')
  })

  it('signs out and shows the sign-in', async () => {
    let call = 0
    const { client, fetchFn } = api(() =>
      ++call === 1 ? new Response(JSON.stringify(ME)) : new Response(null, { status: 204 }),
    )
    const { wrapper, router, store } = await page(client)
    await wrapper.get('[data-test="logout"]').trigger('click')
    await flushPromises()
    expect(fetchFn).toHaveBeenLastCalledWith(
      'https://api.example.com/auth/logout',
      expect.objectContaining({ method: 'POST', credentials: 'include' }),
    )
    expect(store.me).toBeNull()
    expect(router.currentRoute.value.name).toBe('login')
  })
})
