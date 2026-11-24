import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import FleetView from './FleetView.vue'
import { page } from '../testing'
import { BUILT_IN } from '../texts'
import type { FleetServer } from '../fleet'

const ME = {
  user: { id: 'me', telegram_id: 99, first_name: 'Me', username: null },
  is_superadmin: false,
  projects: [],
  panel_grants: [],
}
const NO_DATA = BUILT_IN.en?.fleet.no_data ?? ''

function server(name: string, extra: Partial<FleetServer> = {}): FleetServer {
  return {
    id: name,
    name,
    role: 'test',
    project: { id: 'pa', slug: 'velo', name: 'Velo', kind: 'product' },
    heartbeat_at: '2026-11-24T12:00:00Z',
    machine_version: '0.1.9',
    machine_release: '0.1.9',
    verdict: {
      run_id: 'r',
      verb: 'update',
      result: 'green',
      finished: '2026-11-24T11:00:00Z',
      verified: true,
    },
    stacks: [{ stack: 'velo', release: 'v1.2.0' }],
    health: { healthy: 2, unhealthy: 0, starting: 0, none: 0 },
    ssl: { mode: 'letsencrypt', expires: '2027-02-01T00:00:00Z', renews_from: null },
    measured_at: '2026-11-24T12:00:00Z',
    reasons: [],
    ...extra,
  }
}

afterEach(() => {
  vi.useRealTimers()
})

describe('the fleet', () => {
  it('test_probe_DM_154_no_value_without_data', async () => {
    // Every field with no data says "no data" -- never a zero or a blank it
    // did not get. The pair: a zero that came is shown as zero.
    const bare = server('bare', {
      heartbeat_at: null,
      machine_version: null,
      verdict: null,
      stacks: null,
      health: null,
      ssl: null,
      measured_at: null,
    })
    const zero = server('zero', { health: { healthy: 0, unhealthy: 0, starting: 0, none: 0 } })
    const { wrapper } = await page(FleetView, {}, ME, { 'GET /api/v1/servers': [bare, zero] })
    for (const field of ['stands', 'verdict', 'health', 'heartbeat', 'ssl']) {
      expect(wrapper.get(`[data-test="server-bare"] [data-test="${field}"]`).text()).toBe(NO_DATA)
    }
    expect(wrapper.get('[data-test="server-bare"] [data-test="machine"]').text()).toBe(
      `${NO_DATA} (0.1.9)`,
    )
    expect(wrapper.get('[data-test="server-zero"] [data-test="health"]').text()).toBe(
      '0 / 0 / 0 / 0',
    )
    // no field of the mockup without a source: no backup, no drift
    expect(wrapper.html()).not.toMatch(/backup|drift/i)
  })

  it('shows the servers in the API’s order, with their reasons', async () => {
    const first = server('z-red', { reasons: ['no-heartbeat', 'machine-behind'] })
    const second = server('a-green')
    const { wrapper } = await page(FleetView, {}, ME, { 'GET /api/v1/servers': [first, second] })
    const names = wrapper.findAll('[data-test="name"]').map((cell) => cell.text())
    expect(names).toEqual(['z-red', 'a-green'])
    expect(wrapper.get('[data-test="server-z-red"] [data-test="reasons"]').text()).toContain(
      BUILT_IN.en?.fleet.reason['no-heartbeat'],
    )
    expect(wrapper.get('[data-test="server-a-green"] [data-test="reasons"]').text()).toBe('')
  })

  it('says a verdict whose signature does not hold', async () => {
    const forged = server('forged', {
      verdict: {
        run_id: 'r',
        verb: 'update',
        result: 'green',
        finished: '2026-11-24T11:00:00Z',
        verified: false,
      },
      reasons: ['verdict-unverified'],
    })
    const { wrapper } = await page(FleetView, {}, ME, { 'GET /api/v1/servers': [forged] })
    expect(wrapper.get('[data-test="verdict"]').text()).toContain(BUILT_IN.en?.fleet.unverified)
  })

  it('reads the fleet again every 30 s, and stops when the page goes', async () => {
    vi.useFakeTimers()
    const { wrapper, asked } = await page(FleetView, {}, ME, { 'GET /api/v1/servers': [] })
    const reads = () => asked.filter((a) => a.path === '/api/v1/servers').length
    expect(reads()).toBe(1)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(reads()).toBe(2)
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(90_000)
    expect(reads()).toBe(2)
    await flushPromises()
  })

  it('names no servers and shows an error of the API', async () => {
    const none = await page(FleetView, {}, ME, { 'GET /api/v1/servers': [] })
    expect(none.wrapper.find('[data-test="no-servers"]').exists()).toBe(true)
    const failed = await page(FleetView, {}, ME, {
      'GET /api/v1/servers': () =>
        new Response('{"error":{"class":"unavailable","message":"down"}}', { status: 503 }),
    })
    expect(failed.wrapper.get('[data-test="error-class"]').text()).toBe('unavailable')
  })
})
