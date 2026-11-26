import { describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import PassportView from './PassportView.vue'
import ServerView from './ServerView.vue'
import { page } from '../testing'
import type { Me } from '../stores/me'

// The passport as the API gives it, written out: the secrets by name and
// state, never a value (DM-158).
const BASE = '1111111111111111111111111111111111111111'
const NEXT = '2222222222222222222222222222222222222222'
const KEY = 'age1panelkeyofthespecs'
const SECRET = 'typed-secret-of-the-spec-0001'

function ready(state: 'ready' | 'invalid' = 'ready') {
  return {
    state,
    base: BASE,
    version: 7,
    fields: [
      { path: ['domains', 'frontend'], value: 'test.velo.example' },
      { path: ['policies', 'gc', 'keep_releases'], value: 2 },
      { path: ['policies', 'backup', 'enabled'], value: false },
      { path: ['languages'], value: ['ru', 'en'] },
    ],
    secrets: [
      { stack: 'comms', key: 'TELEGRAM_BOT_TOKEN', state: 'set' },
      { stack: 'comms', key: 'MAILGUN_API_KEY', state: 'switched_off' },
    ],
    tls: [{ key: 'cert', state: 'set' }],
    rules: [{ path: ['policies', 'gc', 'keep_releases'], rule: 'keep_releases' }],
    problems: state === 'invalid' ? ['policies.gc.keep_releases [greater_than_equal]'] : [],
    apply: { commit: BASE, state: 'pending' },
    panel_key: KEY,
  }
}

function head(role: string) {
  return {
    id: 's1',
    name: 'velo-test',
    role,
    project: { id: 'pa', slug: 'velo', name: 'Velo', kind: 'product' },
    heartbeat_at: null,
    machine_version: null,
    machine_release: '0.1.10',
    verdict: null,
    stacks: null,
    health: null,
    ssl: null,
    measured_at: null,
    reasons: [],
  }
}

function me(permissions: string[], superadmin = false): Me {
  return {
    user: { id: 'me', telegram_id: 99, first_name: 'Me', username: null },
    is_superadmin: superadmin,
    projects: [
      {
        project: { id: 'pa', slug: 'velo', name: 'Velo', kind: 'product' },
        is_admin: false,
        permissions,
      },
    ],
    panel_grants: [],
  }
}

const PASSPORT = 'GET /api/v1/servers/s1/passport'
const SERVER = 'GET /api/v1/servers/s1'
const FIELD = 'PUT /api/v1/servers/s1/passport/field'
const SECRET_PUT = 'PUT /api/v1/servers/s1/passport/secret'
const APPLY = 'POST /api/v1/servers/s1/passport/apply'

function refusal(status: number, errorClass: string, message: string) {
  return () => new Response(JSON.stringify({ error: { class: errorClass, message } }), { status })
}

async function open(answers: Record<string, unknown>, who: Me = me(['passport'])) {
  return page(PassportView, { serverId: 's1' }, who, { [SERVER]: head('test'), ...answers })
}

describe('the page of a passport', () => {
  it('shows the fields, the rules and the secrets by name and state', async () => {
    const { wrapper } = await open({ [PASSPORT]: ready() })
    expect(wrapper.get('[data-test="version"]').text()).toContain('7')
    expect(wrapper.get('[data-test="field-domains.frontend"]').text()).toContain(
      'test.velo.example',
    )
    expect(
      wrapper.get('[data-test="field-policies.gc.keep_releases"] [data-test="rule"]').text(),
    ).toContain('previous release')
    expect(wrapper.get('[data-test="secret-comms.TELEGRAM_BOT_TOKEN"]').text()).toContain('set')
    expect(wrapper.get('[data-test="secret-comms.MAILGUN_API_KEY"]').text()).toContain(
      'switched off',
    )
    expect(wrapper.get('[data-test="tls-cert"]').text()).toContain('set')
    expect(wrapper.get('[data-test="apply-state"]').text()).toContain('waiting')
    expect(wrapper.find('[data-test="problems"]').exists()).toBe(false)
  })

  it('shows what the machine refuses, and the page still edits', async () => {
    const { wrapper } = await open({ [PASSPORT]: ready('invalid') })
    expect(wrapper.get('[data-test="problems"]').text()).toContain('policies.gc.keep_releases')
    expect(wrapper.findAll('[data-test="edit"]').length).toBe(4)
  })

  it.each([
    [{ state: 'absent', panel_key: KEY }, 'state-absent', 'no passport'],
    [{ state: 'file' }, 'state-file', 'from a file'],
    [
      { state: 'damaged', reason: 'sops-damaged', base: BASE, panel_key: KEY },
      'state-damaged',
      'not a sops file',
    ],
    [
      { state: 'damaged', reason: 'not-a-file', base: BASE, panel_key: KEY },
      'state-damaged',
      'not a file',
    ],
    [{ state: 'not-recipient', panel_key: KEY }, 'state-not-recipient', KEY],
  ])('a state without fields: %o', async (answer, test, said) => {
    const { wrapper } = await open({ [PASSPORT]: answer })
    expect(wrapper.get(`[data-test="${test}"]`).text()).toContain(said)
    for (const other of ['state-absent', 'state-file', 'state-damaged', 'state-not-recipient']) {
      if (other !== test) expect(wrapper.find(`[data-test="${other}"]`).exists()).toBe(false)
    }
    expect(wrapper.find('[data-test="fields"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="apply"]').exists()).toBe(false)
  })

  it("copies the Panel's key", async () => {
    const { wrapper } = await open({ [PASSPORT]: { state: 'not-recipient', panel_key: KEY } })
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    await wrapper.get('[data-test="copy-key"]').trigger('click')
    expect(writeText).toHaveBeenCalledWith(KEY)
  })

  it('reads only, without `passport`; the superadmin edits', async () => {
    const reader = await open({ [PASSPORT]: ready() }, me(['deploy_test']))
    for (const control of ['edit', 'replace', 'new-secret', 'apply']) {
      expect(reader.wrapper.find(`[data-test="${control}"]`).exists()).toBe(false)
    }
    const superadmin = await open({ [PASSPORT]: ready() }, me([], true))
    expect(superadmin.wrapper.find('[data-test="apply"]').exists()).toBe(true)
  })

  it('sends a field back in its own JSON type, from the base it read', async () => {
    const { wrapper, asked } = await open({
      [PASSPORT]: ready(),
      [FIELD]: { commit: NEXT, version: 8 },
    })
    await wrapper.findAll('[data-test="edit"]')[1]!.trigger('click')
    await wrapper.get('[data-test="field-text"]').setValue('1')
    await wrapper.get('[data-test="field-form"]').trigger('submit')
    await flushPromises()
    const put = asked.find((call) => call.method === 'PUT')
    expect(put?.body).toEqual({ base: BASE, path: ['policies', 'gc', 'keep_releases'], value: 1 })
    expect(wrapper.get('[data-test="saved"]').text()).toContain('8')
    expect(asked.filter((call) => call.path === '/api/v1/servers/s1/passport').length).toBe(2)
  })

  it('sends nothing for a value that is not of its type', async () => {
    const { wrapper, asked } = await open({ [PASSPORT]: ready() })
    await wrapper.findAll('[data-test="edit"]')[3]!.trigger('click')
    await wrapper.get('[data-test="field-json"]').setValue('[ru')
    await wrapper.get('[data-test="field-form"]').trigger('submit')
    await flushPromises()
    expect(asked.some((call) => call.method === 'PUT')).toBe(false)
    expect(wrapper.get('[data-test="api-error"]').text()).toContain('not valid')
  })

  it('keeps a refusal of a stale base on the screen, and reads again on asking', async () => {
    const { wrapper, asked } = await open({
      [PASSPORT]: ready(),
      [FIELD]: refusal(409, 'conflict', 'the passport has changed since 1111: read it again'),
    })
    await wrapper.findAll('[data-test="edit"]')[0]!.trigger('click')
    await wrapper.get('[data-test="field-text"]').setValue('new.velo.example')
    await wrapper.get('[data-test="field-form"]').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[data-test="api-error"]').text()).toContain('has changed')
    const readings = () => asked.filter((call) => call.path === '/api/v1/servers/s1/passport')
    expect(readings().length).toBe(1)
    await wrapper.get('[data-test="reread"]').trigger('click')
    await flushPromises()
    expect(readings().length).toBe(2)
  })
})

describe('a secret on the page', () => {
  it('is typed hidden and never filled in', async () => {
    const { wrapper } = await open({ [PASSPORT]: ready() })
    await wrapper.findAll('[data-test="replace"]')[0]!.trigger('click')
    const input = wrapper.get('[data-test="secret-value"]')
    expect(input.attributes('type')).toBe('password')
    expect(input.attributes('autocomplete')).toBe('new-password')
    expect((input.element as HTMLInputElement).value).toBe('')
  })

  it.each([
    ['it is saved', { commit: NEXT, version: 8 }],
    ['it is refused', refusal(422, 'invalid', 'the passport is refused: asked.comms.K [x]')],
  ])('leaves the page with its request when %s', async (_case, answer) => {
    const { wrapper, asked } = await open({ [PASSPORT]: ready(), [SECRET_PUT]: answer })
    await wrapper.findAll('[data-test="replace"]')[0]!.trigger('click')
    await wrapper.get('[data-test="secret-value"]').setValue(SECRET)
    await wrapper.get('[data-test="secret-form"]').trigger('submit')
    await flushPromises()
    const put = asked.find((call) => call.method === 'PUT')
    expect(put?.body).toEqual({
      base: BASE,
      stack: 'comms',
      key: 'TELEGRAM_BOT_TOKEN',
      value: SECRET,
    })
    // gone from the page: the screen, its inputs, the state of its component
    expect(wrapper.html()).not.toContain(SECRET)
    const left = wrapper.find('[data-test="secret-value"]')
    if (left.exists()) expect((left.element as HTMLInputElement).value).toBe('')
    const state = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$
      .setupState
    expect(JSON.stringify(state['secret'] ?? null)).not.toContain(SECRET)
  })

  it('of tls goes by its key, a new one by its stack and key', async () => {
    const { wrapper, asked } = await open({
      [PASSPORT]: ready(),
      [SECRET_PUT]: { commit: NEXT, version: 8 },
    })
    await wrapper.findAll('[data-test="replace"]')[2]!.trigger('click')
    expect(wrapper.get('[data-test="secret-value"]').element.tagName).toBe('TEXTAREA')
    await wrapper.get('[data-test="secret-value"]').setValue('-----BEGIN CERTIFICATE-----')
    await wrapper.get('[data-test="secret-form"]').trigger('submit')
    await flushPromises()
    await wrapper.get('[data-test="new-secret"]').trigger('click')
    await wrapper.get('[data-test="stack"]').setValue('velo')
    await wrapper.get('[data-test="key"]').setValue('MEET_JWT_SECRET')
    await wrapper.get('[data-test="secret-value"]').setValue('another-secret-of-the-spec')
    await wrapper.get('[data-test="secret-form"]').trigger('submit')
    await flushPromises()
    const puts = asked.filter((call) => call.method === 'PUT').map((call) => call.body)
    expect(puts).toEqual([
      { base: BASE, tls: 'cert', value: '-----BEGIN CERTIFICATE-----' },
      { base: BASE, stack: 'velo', key: 'MEET_JWT_SECRET', value: 'another-secret-of-the-spec' },
    ])
  })
})

describe('"apply" on the page', () => {
  it('queues at once on test', async () => {
    const { wrapper, asked } = await open({ [PASSPORT]: ready(), [APPLY]: { id: 'c1' } })
    await wrapper.get('[data-test="apply"]').trigger('click')
    await flushPromises()
    expect(asked.find((call) => call.method === 'POST')?.body).toEqual({ confirmed: false })
    expect(wrapper.get('[data-test="queued"]').text()).toContain('update')
  })

  it('asks "are you sure?" on prod, and sends confirmed only after yes', async () => {
    const { wrapper, asked } = await page(PassportView, { serverId: 's1' }, me(['passport']), {
      [SERVER]: head('prod'),
      [PASSPORT]: ready(),
      [APPLY]: { id: 'c1' },
    })
    await wrapper.get('[data-test="apply"]').trigger('click')
    await flushPromises()
    expect(asked.some((call) => call.method === 'POST')).toBe(false)
    await wrapper.get('[data-test="confirm-no"]').trigger('click')
    await wrapper.get('[data-test="apply"]').trigger('click')
    await wrapper.get('[data-test="confirm-yes"]').trigger('click')
    await flushPromises()
    const posts = asked.filter((call) => call.method === 'POST').map((call) => call.body)
    expect(posts).toEqual([{ confirmed: true }])
  })

  it('shows a refusal of the API', async () => {
    const { wrapper } = await open({
      [PASSPORT]: ready(),
      [APPLY]: refusal(409, 'conflict', 'the machine refuses this passport'),
    })
    await wrapper.get('[data-test="apply"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="api-error"]').text()).toContain('machine refuses')
    expect(wrapper.find('[data-test="queued"]').exists()).toBe(false)
  })
})

describe('the card of a server and the passport', () => {
  it('lead to each other', async () => {
    const { wrapper } = await open({ [PASSPORT]: ready() })
    expect(wrapper.get('[data-test="to-server"]').attributes('href')).toBe('/servers/s1')
    const card = await page(ServerView, { serverId: 's1' }, me(['passport']), {
      [SERVER]: head('test'),
      'GET /api/v1/servers/s1/runs': [],
      'GET /api/v1/servers/s1/verbs': [],
    })
    expect(card.wrapper.get('[data-test="to-passport"]').attributes('href')).toBe(
      '/servers/s1/passport',
    )
  })
})
