// Support of the specs of the screens (DM-152): an API answering by
// "METHOD path", recording what it was asked, and a page mounted with the
// router, i18n, pinia and the person of the session. Imported by specs only.

import { vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import type { Component } from 'vue'
import { API_CLIENT, createApiClient } from './api/client'
import { createPanelI18n } from './i18n'
import { createPanelRouter } from './router'
import { useMeStore, type Me } from './stores/me'

export type Answer = unknown | ((body: unknown) => Response)

export interface Asked {
  method: string
  path: string
  body: unknown
}

export function fakeApi(answers: Record<string, Answer>) {
  const asked: Asked[] = []
  const fetchFn = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    const path = String(url).replace('https://api.example.com', '')
    const method = init?.method ?? 'GET'
    const body: unknown = init?.body ? JSON.parse(String(init.body)) : undefined
    asked.push({ method, path, body })
    const answer = answers[`${method} ${path}`]
    if (answer === undefined) {
      return new Response('{"error":{"class":"not_found","message":"Not found"}}', { status: 404 })
    }
    if (typeof answer === 'function') {
      return (answer as (body: unknown) => Response)(body)
    }
    return new Response(JSON.stringify(answer))
  }) as unknown as typeof fetch
  const client = createApiClient({ origin: 'https://api.example.com', fetchFn })
  return { client, asked }
}

export function person(id: string, telegramId: number, name: string) {
  return { id, telegram_id: telegramId, first_name: name, username: null }
}

export async function page(
  component: Component,
  props: Record<string, unknown>,
  me: Me,
  answers: Record<string, Answer>,
) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useMeStore().me = me
  const router = createPanelRouter(createMemoryHistory())
  await router.push('/projects')
  const api = fakeApi(answers)
  const wrapper = mount(component, {
    props,
    global: {
      plugins: [pinia, router, createPanelI18n('en')],
      provide: { [API_CLIENT as symbol]: api.client },
    },
  })
  await flushPromises()
  return { wrapper, asked: api.asked, router }
}
