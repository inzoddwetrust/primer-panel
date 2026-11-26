import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import KeyWait from './KeyWait.vue'
import ServerView from '../views/ServerView.vue'
import { createPanelI18n } from '../i18n'
import { createPanelRouter } from '../router'
import { page } from '../testing'
import { httpsPage, waitsUntil, type KeyWait as Wait } from '../run'

// A wait for a key as the API gives it, written out (DM-159).
const KEY =
  'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl pridem x'
const PAGE = 'https://github.com/o/velo/settings/keys'

function wait(extra: Partial<Wait> = {}): Wait {
  return {
    run_id: 'r1',
    repo: 'git@github.com:o/velo.git',
    key: KEY,
    page: PAGE,
    write: false,
    why: null,
    wait_s: 1800,
    again: false,
    at: '2026-11-26T12:00:03.000Z',
    state: 'waiting',
    reason: null,
    ...extra,
  }
}

async function shown(given: Wait, serverId?: string) {
  const router = createPanelRouter(createMemoryHistory())
  await router.push('/projects')
  const wrapper = mount(KeyWait, {
    props: serverId ? { wait: given, serverId } : { wait: given },
    global: { plugins: [router, createPanelI18n('en')] },
  })
  await flushPromises()
  return wrapper
}

describe('a wait for a key', () => {
  it('shows the key, the page of the repository and until when', async () => {
    const wrapper = await shown(wait())
    expect(wrapper.get('[data-test="key-key"]').text()).toBe(KEY)
    const link = wrapper.get('[data-test="key-page"]')
    expect(link.attributes('href')).toBe(PAGE)
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toBe('noopener noreferrer')
    expect(wrapper.get('[data-test="key-repo"]').text()).toContain('read only')
    expect(wrapper.get('[data-test="key-until"]').text()).toContain('2026-11-26T12:30:03Z')
    expect(wrapper.find('[data-test="key-run"]').exists()).toBe(false)
  })

  it('builds no link without a page of the machine', async () => {
    const wrapper = await shown(wait({ page: null, repo: 'git@gitlab.com:o/x.git' }))
    expect(wrapper.find('[data-test="key-page"]').exists()).toBe(false)
    expect(wrapper.html()).not.toContain('github.com/o/x')
    expect(wrapper.get('[data-test="key-repo"]').text()).toContain('git@gitlab.com:o/x.git')
  })

  it('of a write key says so and why; one that waits for nothing says that', async () => {
    const wrapper = await shown(wait({ write: true, why: 'types of the frontend', wait_s: 0 }))
    expect(wrapper.get('[data-test="key-repo"]').text()).toContain('write access')
    expect(wrapper.get('[data-test="key-why"]').text()).toBe('types of the frontend')
    expect(wrapper.find('[data-test="key-until"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="key-no-wait"]').text()).toContain('next run')
    expect(waitsUntil(wait({ wait_s: 0 }))).toBeNull()
  })

  it.each([
    ['granted', 'went on'],
    ['not_granted', 'did not come'],
    ['ended', 'ended'],
  ] as const)('%s', async (state, said) => {
    const wrapper = await shown(
      wait({ state, reason: state === 'not_granted' ? 'deploy_key:no-access' : null }),
    )
    expect(wrapper.get('h2').text()).toContain(said)
    expect(wrapper.find('[data-test="key-until"]').exists()).toBe(false)
  })

  it('says a refused fresh key again, and copies the key', async () => {
    const wrapper = await shown(wait({ again: true }))
    expect(wrapper.get('[data-test="key-again"]').text()).toContain('spread')
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    await wrapper.get('[data-test="key-copy"]').trigger('click')
    expect(writeText).toHaveBeenCalledWith(KEY)
  })

  it('on the card leads to its run', async () => {
    const wrapper = await shown(wait(), 's1')
    expect(wrapper.get('[data-test="key-run"]').attributes('href')).toBe('/servers/s1/runs/r1')
  })
})

describe('the card of a server', () => {
  const head = {
    id: 's1',
    name: 'velo-test',
    role: 'test',
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
  const bare = {
    user: { id: 'me', telegram_id: 99, first_name: 'Me', username: null },
    is_superadmin: false,
    projects: [
      {
        project: { id: 'pa', slug: 'velo', name: 'Velo', kind: 'product' },
        is_admin: false,
        permissions: [],
      },
    ],
    panel_grants: [],
  }

  it('shows the wait with its key to a member without a permission', async () => {
    const { wrapper } = await page(ServerView, { serverId: 's1' }, bare, {
      'GET /api/v1/servers/s1': head,
      'GET /api/v1/servers/s1/runs': [],
      'GET /api/v1/servers/s1/verbs': [],
      'GET /api/v1/servers/s1/key-wait': wait(),
    })
    expect(wrapper.get('[data-test="key-key"]').text()).toBe(KEY)
    expect(wrapper.get('[data-test="key-page"]').attributes('href')).toBe(PAGE)
  })

  it('shows nothing when the running run waits for no key', async () => {
    const { wrapper } = await page(ServerView, { serverId: 's1' }, bare, {
      'GET /api/v1/servers/s1': head,
      'GET /api/v1/servers/s1/runs': [],
      'GET /api/v1/servers/s1/verbs': [],
      'GET /api/v1/servers/s1/key-wait': null,
    })
    expect(wrapper.find('[data-test="key-wait"]').exists()).toBe(false)
  })
})

// DM-210 (PRIMER-PANEL-REVIEW-0001): the page of a key comes from the
// journal of a box, and a link is made of it in the person's browser.
describe('probe DM-210: the page of a key is a link only when it is https', () => {
  const NO_LINKS = [
    'javascript:alert(document.cookie)',
    'JavaScript:alert(1)',
    ' javascript:alert(1)',
    'data:text/html,<script>alert(1)</script>',
    'vbscript:msgbox(1)',
    'http://github.com/o/velo/settings/keys',
    'https://user:secret@github.com/o/velo',
    'https://user@github.com/o/velo',
    '//github.com/o/velo',
    '/o/velo/settings/keys',
    'github.com/o/velo',
    'https://',
    '',
  ]

  it.each(NO_LINKS)('no link and no text of %j', async (crooked) => {
    const wrapper = await shown(wait({ page: crooked }))
    expect(wrapper.find('[data-test="key-page"]').exists()).toBe(false)
    expect(wrapper.findAll('a').map((a) => a.attributes('href'))).toEqual([])
    if (crooked !== '') {
      expect(wrapper.html()).not.toContain(crooked.trim().slice(0, 12))
    }
    // the rest of the wait is on the page
    expect(wrapper.get('[data-test="key-key"]').text()).toBe(KEY)
    expect(httpsPage(crooked)).toBeNull()
  })

  it('the pair: an https address is the link, as it came', async () => {
    for (const good of [PAGE, 'https://gitlab.example.com:8443/o/x/-/settings/repository#keys']) {
      const wrapper = await shown(wait({ page: good }))
      expect(wrapper.get('[data-test="key-page"]').attributes('href')).toBe(good)
      expect(httpsPage(good)).toBe(good)
    }
  })

  it('a page that is no text is no link', () => {
    for (const value of [null, undefined, 5, true, [PAGE], { href: PAGE }]) {
      expect(httpsPage(value)).toBeNull()
    }
  })
})

describe('a wait the box counts oddly takes no screen down (DM-210)', () => {
  it('a wait that ended before it began is shown as it is, a moment in the past', async () => {
    const wrapper = await shown(wait({ wait_s: -5 }))
    expect(wrapper.get('[data-test="key-until"]').text()).toContain('2026-11-26T11:59:58Z')
    expect(wrapper.find('[data-test="key-no-wait"]').exists()).toBe(false)
  })

  it.each([
    ['seconds no moment holds', { wait_s: 1e300 }],
    ['seconds below every moment', { wait_s: -1e300 }],
    ['a start that is no moment', { at: 'soon' }],
  ])('%s: the wait is shown without its end', async (_name, extra) => {
    expect(waitsUntil(wait(extra))).toBeNull()
    const wrapper = await shown(wait(extra))
    expect(wrapper.find('[data-test="key-until"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="key-key"]').text()).toBe(KEY)
  })
})
