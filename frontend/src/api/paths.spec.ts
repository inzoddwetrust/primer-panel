import { afterEach, describe, expect, it, vi } from 'vitest'
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'
import type { Component } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import AddServerView from '../views/AddServerView.vue'
import PassportView from '../views/PassportView.vue'
import ProjectView from '../views/ProjectView.vue'
import RunView from '../views/RunView.vue'
import ServerView from '../views/ServerView.vue'
import { RUNTIME_CONFIG } from '../config-key'
import { createPanelI18n } from '../i18n'
import { createPanelRouter } from '../router'
import { STREAM } from '../run'
import { fakeApi, page as mounted } from '../testing'
import { API_CLIENT } from './client'
import { ApiPath, PathSegmentError, apiPath, segment } from './paths'

// DM-210 (PRIMER-PANEL-REVIEW-0001): a parameter of the page's address does
// not lead a request of the page to another handler of the API.

const U = '0b9f7a52-7c1e-4d3a-9f10-2a6c5e8d4b71'
const P = '5d2c8e14-93ab-4f67-8a02-c41e7b9d0f35'
const RUN = '2026-11-25T10:00:00Z-a3f9'
const API = 'https://api.example.com'
const ME =
  '{"user":{"id":"u1","telegram_id":123456789,"first_name":"Anna","username":"anna"},' +
  '"is_superadmin":true,"projects":[],"panel_grants":[]}'
const CONFIG = `{"apiBaseUrl":"${API}","languages":"en","defaultLanguage":"en"}`
const RUN_PAGE = JSON.stringify({
  run_id: RUN,
  server_name: 'velo-test',
  verb: 'update',
  started_at: '2026-11-25T10:00:00Z',
  ended_at: null,
  outcome: null,
  status: 'running',
  verdict: null,
  report_llm: null,
  repeat: null,
  last_seq: 0,
  key_wait: null,
})

// The page as the browser starts it (src/main.ts) at `path`: every request
// it makes, and every stream it opens, by its address.
async function started(path: string): Promise<{ asked: string[]; app: HTMLElement }> {
  document.body.innerHTML = '<div id="app"></div>'
  window.history.replaceState(null, '', path)
  const asked: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      asked.push(url)
      if (url === '/config.json') return new Response(CONFIG)
      if (url === `${API}/api/v1/me`) return new Response(ME)
      if (url === `${API}/api/v1/servers`) return new Response('[]')
      if (url === `${API}/api/v1/servers/${U}/runs/${RUN}`) return new Response(RUN_PAGE)
      return new Response('{"error":{"class":"not_found","message":"Not found"}}', { status: 404 })
    }),
  )
  vi.stubGlobal(
    'EventSource',
    class {
      constructor(url: string) {
        asked.push(`stream ${url}`)
      }
      addEventListener(): void {}
      close(): void {}
    },
  )
  vi.stubGlobal('navigator', { languages: ['en'], language: 'en' })
  vi.resetModules()
  await import('../main')
  const app = document.getElementById('app') as HTMLElement
  await vi.waitFor(() => expect(app.querySelector('main')).not.toBeNull())
  await new Promise((resolve) => setTimeout(resolve, 20))
  return { asked, app }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// What the page asks when it opens at a path it does not know: its config,
// the person, and the fleet of `/`, where such a path leads. Nothing else.
const UNKNOWN = ['/config.json', `${API}/api/v1/me`, `${API}/api/v1/servers`]

// Every screen with a parameter in its path, and the parameter off its form:
// the traversal of the review (`..%2F`), an encoded `/`, `?` and `#` after a
// good id, a text that is no UUID, a run's id that is none.
const OFF_FORM: [string, string][] = [
  ['server: ..%2F', '/servers/..%2F..%2Fusers'],
  ['server: a good id and %2F', `/servers/${U}%2Fkey-wait`],
  ['server: a good id and %3F', `/servers/${U}%3Fx=1`],
  ['server: a good id and %23', `/servers/${U}%23x`],
  ['server: no UUID', '/servers/s1'],
  ['server: a UUID and a letter', `/servers/${U}x`],
  ['passport: ..%2F', '/servers/..%2F..%2Fusers/passport'],
  ['passport: %2F', `/servers/${U}%2Fruns/passport`],
  ['passport: no UUID', '/servers/s1/passport'],
  ['run: the server ..%2F', `/servers/..%2F..%2Fusers/runs/${RUN}`],
  ['run: the server no UUID', `/servers/s1/runs/${RUN}`],
  ['run: the run ..%2F', `/servers/${U}/runs/..%2F..%2Fcommands`],
  ['run: the run and %2F', `/servers/${U}/runs/${RUN}%2F..`],
  ['run: the run and %3F', `/servers/${U}/runs/${RUN}%3Fx`],
  ['run: no run id', `/servers/${U}/runs/r1`],
  ['project: ..%2F', '/projects/..%2F..%2Fusers'],
  ['project: a good id and %2F', `/projects/${P}%2Farchive`],
  ['project: a good id and %23', `/projects/${P}%23x`],
  ['project: no UUID', '/projects/pa'],
  ['new server: ..%2F', '/projects/..%2F..%2Fusers/servers/new'],
  ['new server: %2F', `/projects/${P}%2Fmembers/servers/new`],
  ['new server: no UUID', '/projects/pa/servers/new'],
]

// The same screens at a path of the form: the first request of each is its
// own -- the pair that says the list above is not green by asking nothing.
const OF_THE_FORM: [string, string, string][] = [
  ['server', `/servers/${U}`, `${API}/api/v1/servers/${U}`],
  ['passport', `/servers/${U}/passport`, `${API}/api/v1/servers/${U}`],
  ['run', `/servers/${U}/runs/${RUN}`, `${API}/api/v1/servers/${U}/runs/${RUN}`],
  ['project', `/projects/${P}`, `${API}/api/v1/projects/${P}`],
]

describe('probe DM-210: a path off its form reaches no API', () => {
  it.each(OFF_FORM)('%s', async (_name, path) => {
    const { asked } = await started(path)
    expect(asked).toEqual(UNKNOWN)
    expect(window.location.pathname).toBe('/')
  })

  it.each(OF_THE_FORM)('the pair: %s asks its own', async (_name, path, first) => {
    const { asked } = await started(path)
    expect(asked.slice(0, 2)).toEqual(['/config.json', `${API}/api/v1/me`])
    expect(asked).toContain(first)
    expect(window.location.pathname).toBe(path)
  })

  it('the pair: a run opens its stream at its own address', async () => {
    const { asked } = await started(`/servers/${U}/runs/${RUN}`)
    expect(asked.filter((url) => url.startsWith('stream '))).toEqual([
      `stream ${API}/api/v1/streams/servers/${U}/runs/${RUN}`,
    ])
  })

  it('the pair: a new server is a page of its project', async () => {
    const { app } = await started(`/projects/${P}/servers/new`)
    expect(window.location.pathname).toBe(`/projects/${P}/servers/new`)
    expect(app.querySelector('main')).not.toBeNull()
  })
})

describe('what the Panel writes itself is of the form', () => {
  const router = createPanelRouter(createMemoryHistory())

  it('every link to a run, a server, a passport, a project opens its page', () => {
    const links: [string, Record<string, string>, string][] = [
      ['run', { serverId: U, runId: RUN }, `/servers/${U}/runs/${RUN}`],
      ['server', { serverId: U }, `/servers/${U}`],
      ['passport', { serverId: U }, `/servers/${U}/passport`],
      ['project', { projectId: P }, `/projects/${P}`],
      ['add-server', { projectId: P }, `/projects/${P}/servers/new`],
    ]
    for (const [name, params, href] of links) {
      const link = router.resolve({ name, params })
      expect(link.href).toBe(href) // a run's id keeps its colons
      const opened = router.resolve(link.fullPath)
      expect([opened.name, opened.params]).toEqual([name, params])
    }
  })

  it('a link made of an id off its form opens no page of that kind', () => {
    const link = router.resolve({ name: 'run', params: { serverId: U, runId: '../../commands' } })
    expect(router.resolve(link.fullPath).name).not.toBe('run')
    expect(router.resolve('/servers/s1').name).not.toBe('server')
  })
})

describe('apiPath', () => {
  it('puts a segment in as it is', () => {
    expect(String(apiPath`/api/v1/servers/${U}/runs/${RUN}`)).toBe(
      `/api/v1/servers/${U}/runs/${RUN}`,
    )
    expect(String(apiPath`/api/v1/projects/${'a.b_c-d'}`)).toBe('/api/v1/projects/a.b_c-d')
  })

  it('takes a path it made as the start of another', () => {
    const base = apiPath`/api/v1/servers/${U}`
    expect(base).toBeInstanceOf(ApiPath)
    expect(String(apiPath`${base}/key-wait`)).toBe(`/api/v1/servers/${U}/key-wait`)
    // a text that only looks like one is a segment as any other: refused
    expect(() => apiPath`${`/api/v1/servers/${U}`}/key-wait`).toThrow(PathSegmentError)
  })

  it.each([
    ['a slash', `${U}/key-wait`],
    ['a traversal', '../../users'],
    ['two dots', '..'],
    ['one dot', '.'],
    ['an encoded slash', `${U}%2Fkey-wait`],
    ['a question mark', `${U}?x=1`],
    ['a hash', `${U}#x`],
    ['a backslash', `${U}\\x`],
    ['a space', `${U} x`],
    ['a line end', `${U}\n`],
    ['a semicolon', `${U};x`],
    ['an at sign', `u@${U}`],
    ['an empty text', ''],
    ['a letter not of ASCII', 'сервер'],
    ['a number', 5],
    ['null', null],
    ['nothing', undefined],
    ['an object', { toString: () => U }],
    ['a list', [U]],
  ])('refuses %s', (_name, value) => {
    expect(() => segment(value)).toThrow(PathSegmentError)
    expect(() => apiPath`/api/v1/servers/${value}`).toThrow(PathSegmentError)
    expect(() => apiPath`/api/v1/servers/${U}/runs/${value}`).toThrow(PathSegmentError)
  })
})

// The second line by itself: a screen given a parameter off its form by
// another way than its route -- mounted with it. No request is made of it,
// and the screen says so; the same screen with an id of the form asks.
describe('a screen given a parameter off its form asks nothing of it', () => {
  const me = {
    user: { id: 'u1', telegram_id: 1, first_name: 'Anna', username: null },
    is_superadmin: true,
    projects: [],
    panel_grants: [],
  }
  const screens = [
    ['server', ServerView, 'serverId', U],
    ['passport', PassportView, 'serverId', U],
    ['project', ProjectView, 'projectId', P],
  ] as const

  for (const [name, view, prop, good] of screens) {
    it.each(['../../users', `${good}/key-wait`, `${good}?x=1`, `${good}#x`, '..'])(
      `${name}: %j`,
      async (crooked) => {
        const { wrapper, asked } = await mounted(view, { [prop]: crooked }, me, {})
        const paths = asked.map((each) => each.path)
        expect(paths.filter((path) => /users|\.\.|key-wait|[?#]/.test(path))).toEqual([])
        expect(paths.filter((path) => path.includes(good))).toEqual([])
        expect(wrapper.find('[data-test="error-path"]').exists()).toBe(true)
        wrapper.unmount()
      },
    )

    it(`${name}: the pair, an id of the form is asked`, async () => {
      const { wrapper, asked } = await mounted(view, { [prop]: good }, me, {})
      expect(asked.some((each) => each.path.includes(good))).toBe(true)
      expect(wrapper.find('[data-test="error-path"]').exists()).toBe(false)
      wrapper.unmount()
    })
  }

  // The two screens that need more than `page` gives: the config, a stream.
  async function withConfig(view: Component, props: Record<string, string>) {
    const pinia = createPinia()
    setActivePinia(pinia)
    const router = createPanelRouter(createMemoryHistory())
    await router.push('/projects')
    const api = fakeApi({})
    const streams: string[] = []
    const wrapper = mount(view, {
      props,
      global: {
        plugins: [pinia, router, createPanelI18n('en')],
        provide: {
          [API_CLIENT as symbol]: api.client,
          [RUNTIME_CONFIG as symbol]: { apiOrigin: API, languages: ['en'], defaultLanguage: 'en' },
          [STREAM as symbol]: (url: string) => {
            streams.push(url)
            return { addEventListener: () => undefined, close: () => undefined }
          },
        },
      },
    })
    await flushPromises()
    // read when asked for: what was requested by then
    return { wrapper, asked: () => api.asked.map((each) => each.path), streams }
  }

  it.each([
    ['the server', { serverId: '../../users', runId: RUN }],
    ['the server with a slash', { serverId: `${U}/runs`, runId: RUN }],
    ['the run', { serverId: U, runId: '../../commands' }],
    ['the run with a slash', { serverId: U, runId: `${RUN}/..` }],
    ['the run with a question mark', { serverId: U, runId: `${RUN}?x` }],
  ])('a run: neither a request nor a stream of %s off its form', async (_name, props) => {
    const { wrapper, asked, streams } = await withConfig(RunView, props)
    expect([asked(), streams]).toEqual([[], []])
    expect(wrapper.find('[data-test="error-path"]').exists()).toBe(true)
    wrapper.unmount()
  })

  it('a run: the pair, ids of the form are asked and listened to', async () => {
    const { wrapper, asked, streams } = await withConfig(RunView, { serverId: U, runId: RUN })
    expect(asked()).toEqual([`/api/v1/servers/${U}/runs/${RUN}`])
    // the page it was not given is "not found": no stream; the pair of the
    // stream is the probe above, where the page is answered
    expect(streams).toEqual([])
    wrapper.unmount()
  })

  it('a new server: no token is asked for a project off its form', async () => {
    const crooked = await withConfig(AddServerView, { projectId: '../../users' })
    await crooked.wrapper.get('[data-test="issue"]').trigger('click')
    await flushPromises()
    expect(crooked.asked()).toEqual([])
    expect(crooked.wrapper.find('[data-test="error-path"]').exists()).toBe(true)
    crooked.wrapper.unmount()
    const good = await withConfig(AddServerView, { projectId: P })
    await good.wrapper.get('[data-test="issue"]').trigger('click')
    await flushPromises()
    expect(good.asked()).toEqual([`/api/v1/projects/${P}/registration-tokens`])
    good.wrapper.unmount()
  })
})

// The fence: no path is put together in src/ by a template of its own. A
// template with a substitution and a `/` is tagged `apiPath`, or is one of
// the addresses written out below, none of which is a path of the API made
// of a parameter.
const ALLOWED = [
  // a link of the page for a person, its token encoded
  'src/access.ts: `${origin}/login?invite=${encodeURIComponent(token)}`',
  // a division in a message
  'src/api/client.ts: `no answer in ${timeoutMs / 1000} s`',
  // the start of the sign-in: the origin of the config and a written path
  'src/login.ts: `${apiOrigin}/auth/telegram/start`',
  // the paths of the pages, made of the forms written in src/router.ts
  'src/router.ts: `${PROJECT}/servers/new`',
  'src/router.ts: `${SERVER}/passport`',
  'src/router.ts: `${SERVER}/runs/:runId(${RUN_ID})`',
  'src/router.ts: `/projects/:projectId(${UUID})`',
  'src/router.ts: `/servers/:serverId(${UUID})`',
  // the key of a step of the ladder, never an address
  "src/run.ts: `${String(line['phase'])}/${String(line['stack'])}/${String(line['name'])}/${String(line['order'])}`",
]

function untagged(source: string): string[] {
  const found: string[] = []
  for (const line of source.split('\n')) {
    const text = line.trim()
    if (text.startsWith('//') || text.startsWith('*')) continue
    for (const match of text.matchAll(/([A-Za-z0-9_$.]*)(`[^`]*\$\{[^`]*`)/g)) {
      const [, tag, template] = match
      if (tag !== 'apiPath' && template?.includes('/')) found.push(template)
    }
  }
  return found
}

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return sources(path)
    return /\.(ts|vue)$/.test(entry.name) && !entry.name.endsWith('.spec.ts') ? [path] : []
  })
}

describe('the fence of the paths', () => {
  it('finds each planted way of making a path by hand, and no tagged one', () => {
    expect(untagged('api.get(`/api/v1/servers/${props.serverId}`)')).toEqual([
      '`/api/v1/servers/${props.serverId}`',
    ])
    expect(untagged('  await api.post(`${base()}/commands`, body)')).toEqual([
      '`${base()}/commands`',
    ])
    expect(untagged('open(`${origin}/api/v1/streams/servers/${id}/runs/${run}`)')).toHaveLength(1)
    expect(untagged('const p = String.raw`/x/${id}`')).toHaveLength(1)
    expect(untagged('api.get(apiPath`/api/v1/servers/${props.serverId}`)')).toEqual([])
    expect(untagged('t(`key.state.${wait.state}`)')).toEqual([])
    expect(untagged('// a comment with `/api/${x}` in it')).toEqual([])
  })

  it('no source of the page makes a path by hand', () => {
    const root = join(__dirname, '..')
    const files = sources(root)
    expect(files.length).toBeGreaterThan(20)
    const found = files.flatMap((file) =>
      untagged(readFileSync(file, 'utf8')).map(
        (template) => `src/${relative(root, file)}: ${template}`,
      ),
    )
    expect(found.sort()).toEqual(ALLOWED)
  })
})
