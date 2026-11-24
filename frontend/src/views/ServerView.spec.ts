import { describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import ServerView from './ServerView.vue'
import { page } from '../testing'
import type { Button } from '../server'

const ME = {
  user: { id: 'me', telegram_id: 99, first_name: 'Me', username: null },
  is_superadmin: true,
  projects: [],
  panel_grants: [],
}

function head(role: string) {
  return {
    id: 's1',
    name: 'velo-test',
    role,
    project: { id: 'pa', slug: 'velo', name: 'Velo', kind: 'product' },
    heartbeat_at: null,
    machine_version: null,
    machine_release: '0.1.9',
    verdict: null,
    stacks: null,
    health: null,
    ssl: null,
    measured_at: null,
    reasons: [],
  }
}

const NONE = { type: 'object', properties: {} }
// The buttons as the API gives them, written out.
function buttons(sure: boolean): Button[] {
  return [
    {
      verb: 'status',
      preset: {},
      schema: NONE,
      positionals: [],
      sure: false,
      name: 'never',
      destructive_options: {},
    },
    {
      verb: 'ssl',
      preset: { action: 'status' },
      schema: NONE,
      positionals: [],
      sure: false,
      name: 'never',
      destructive_options: {},
    },
    {
      verb: 'deploy',
      preset: {},
      schema: { type: 'object', properties: { ref: { type: 'string' } }, required: ['ref'] },
      positionals: ['ref'],
      sure,
      name: 'never',
      destructive_options: {},
    },
    {
      verb: 'db',
      preset: {},
      schema: {
        type: 'object',
        properties: {
          action: { enum: ['dump', 'restore'], type: 'string' },
          stack: { type: 'string' },
        },
        required: ['action', 'stack'],
      },
      positionals: ['action', 'stack'],
      sure,
      name: 'when',
      destructive_options: { action: ['restore'] },
    },
    {
      verb: 'destroy',
      preset: {},
      schema: { type: 'object', properties: { all: { type: 'boolean' } } },
      positionals: [],
      sure,
      name: 'always',
      destructive_options: {},
    },
    {
      verb: 'verb',
      preset: {},
      schema: { type: 'object', properties: { name: { type: 'string' } }, required: ['name'] },
      positionals: ['name'],
      sure,
      name: 'ask',
      destructive_options: {},
    },
  ]
}

function answers(role: string, sure: boolean) {
  return {
    'GET /api/v1/servers/s1': head(role),
    'GET /api/v1/servers/s1/runs': [],
    'GET /api/v1/servers/s1/verbs': buttons(sure),
    'POST /api/v1/servers/s1/commands': { id: 'c1', state: 'queued' },
  }
}

async function card(role = 'test', sure = false) {
  return page(ServerView, { serverId: 's1' }, ME, answers(role, sure))
}

describe('a server’s card', () => {
  it('test_probe_DM_155_each_button_queues_its_own_verb', async () => {
    // Every kind of button sends exactly its verb and its arguments: none, a
    // preset, a form, a destructive one by the typed name, a project verb.
    const { wrapper, asked } = await card()
    const posts = () => asked.filter((a) => a.method === 'POST').map((a) => a.body)

    await wrapper.get('[data-test="button-status"]').trigger('click')
    await wrapper.get('[data-test="command"]').trigger('submit')
    await flushPromises()

    await wrapper.get('[data-test="button-ssl status"]').trigger('click')
    await wrapper.get('[data-test="command"]').trigger('submit')
    await flushPromises()

    await wrapper.get('[data-test="button-deploy"]').trigger('click')
    await wrapper.get('[data-test="field-ref"] input').setValue('v1.2.0')
    await wrapper.get('[data-test="command"]').trigger('submit')
    await flushPromises()

    await wrapper.get('[data-test="button-db"]').trigger('click')
    await wrapper.get('[data-test="field-action"] select').setValue('restore')
    await wrapper.get('[data-test="field-stack"] input').setValue('velo')
    await wrapper.get('[data-test="command"]').trigger('submit')
    await wrapper.get('[data-test="confirm-input"]').setValue('velo-test')
    await wrapper.get('[data-test="confirm-yes"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-test="button-verb"]').trigger('click')
    await wrapper.get('[data-test="field-name"] input').setValue('hello')
    await wrapper.get('[data-test="command"]').trigger('submit')
    await flushPromises()

    expect(posts()).toEqual([
      { verb: 'status', args: {}, confirmed: false },
      { verb: 'ssl', args: { action: 'status' }, confirmed: false },
      { verb: 'deploy', args: { ref: 'v1.2.0' }, confirmed: false },
      {
        verb: 'db',
        args: { action: 'restore', stack: 'velo', confirm: 'velo-test' },
        confirmed: true,
      },
      { verb: 'verb', args: { name: 'hello' }, confirmed: false },
    ])
  })

  it('goes nowhere until the server’s name is typed exactly', async () => {
    const { wrapper, asked } = await card()
    await wrapper.get('[data-test="button-destroy"]').trigger('click')
    await wrapper.get('[data-test="command"]').trigger('submit')
    const yes = wrapper.get('[data-test="confirm-yes"]')
    for (const typed of ['Velo-test', ' velo-test', 'velo-test ', 'velo-tes']) {
      await wrapper.get('[data-test="confirm-input"]').setValue(typed)
      expect((yes.element as HTMLButtonElement).disabled).toBe(true)
    }
    await wrapper.get('[data-test="confirm-no"]').trigger('click')
    await flushPromises()
    expect(asked.some((a) => a.method === 'POST')).toBe(false)
  })

  it('asks for the name of a project verb the person says is destructive', async () => {
    const { wrapper, asked } = await card()
    await wrapper.get('[data-test="button-verb"]').trigger('click')
    await wrapper.get('[data-test="field-name"] input').setValue('wipe')
    await wrapper.get('[data-test="ask"] input').setValue(true)
    await wrapper.get('[data-test="command"]').trigger('submit')
    await wrapper.get('[data-test="confirm-input"]').setValue('velo-test')
    await wrapper.get('[data-test="confirm-yes"]').trigger('click')
    await flushPromises()
    expect(asked.find((a) => a.method === 'POST')?.body).toEqual({
      verb: 'verb',
      args: { name: 'wipe', confirm: 'velo-test' },
      confirmed: true,
    })
  })

  it('asks "are you sure?" on prod, and only there', async () => {
    const { wrapper, asked } = await card('prod', true)
    await wrapper.get('[data-test="button-deploy"]').trigger('click')
    await wrapper.get('[data-test="field-ref"] input').setValue('v2')
    await wrapper.get('[data-test="command"]').trigger('submit')
    expect(wrapper.find('[data-test="confirm-input"]').exists()).toBe(false)
    expect(asked.some((a) => a.method === 'POST')).toBe(false)
    await wrapper.get('[data-test="confirm-yes"]').trigger('click')
    await flushPromises()
    expect(asked.find((a) => a.method === 'POST')?.body).toEqual({
      verb: 'deploy',
      args: { ref: 'v2' },
      confirmed: true,
    })
    // reading on prod: no question
    await wrapper.get('[data-test="button-status"]').trigger('click')
    await wrapper.get('[data-test="command"]').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[data-test="confirm"]').exists()).toBe(false)
  })

  it('keeps a required field required', async () => {
    const { wrapper, asked } = await card()
    await wrapper.get('[data-test="button-deploy"]').trigger('click')
    expect(wrapper.find('[data-test="field-ref"] [data-test="required"]').exists()).toBe(true)
    await wrapper.get('[data-test="command"]').trigger('submit')
    await flushPromises()
    expect(asked.some((a) => a.method === 'POST')).toBe(false)
    expect(wrapper.get('[data-test="error-class"]').text()).toBe('invalid')
  })

  it('a server not seen is "not found"; no data is said so', async () => {
    const missing = await page(ServerView, { serverId: 'zz' }, ME, {})
    expect(missing.wrapper.find('[data-test="not-found"]').exists()).toBe(true)
    const { wrapper } = await card()
    expect(wrapper.get('[data-test="stands"]').text()).toBe('no data')
    expect(wrapper.find('[data-test="no-runs"]').exists()).toBe(true)
  })

  it('shows a refusal of the API', async () => {
    const { wrapper } = await page(ServerView, { serverId: 's1' }, ME, {
      ...answers('test', false),
      'POST /api/v1/servers/s1/commands': () =>
        new Response('{"error":{"class":"forbidden","message":"The permission db is needed"}}', {
          status: 403,
        }),
    })
    await wrapper.get('[data-test="button-status"]').trigger('click')
    await wrapper.get('[data-test="command"]').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[data-test="error-class"]').text()).toBe('forbidden')
  })
})
