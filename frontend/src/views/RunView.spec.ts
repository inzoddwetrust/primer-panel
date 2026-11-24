import { describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory } from 'vue-router'
import RunView from './RunView.vue'
import { API_CLIENT } from '../api/client'
import { RUNTIME_CONFIG } from '../config-key'
import { createPanelI18n } from '../i18n'
import { createPanelRouter } from '../router'
import { STREAM, type RunPage } from '../run'
import { fakeApi, type Answer } from '../testing'

// A stand-in of EventSource: the test sends its events by hand.
class FakeStream {
  listeners = new Map<string, ((event: MessageEvent<string>) => void)[]>()
  closed = false
  url: string
  constructor(url: string) {
    this.url = url
  }
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener])
  }
  close(): void {
    this.closed = true
  }
  send(type: string, data: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener(new MessageEvent(type, { data: JSON.stringify(data) }))
    }
  }
}

function runPage(extra: Partial<RunPage> = {}): RunPage {
  return {
    run_id: 'r1',
    server_name: 'velo-test',
    verb: 'update',
    started_at: '2026-11-24T12:00:00Z',
    ended_at: null,
    outcome: null,
    status: 'running',
    verdict: null,
    report_llm: null,
    repeat: null,
    last_seq: 0,
    ...extra,
  }
}

async function view(answers: Record<string, Answer>) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createPanelRouter(createMemoryHistory())
  await router.push('/projects')
  const api = fakeApi(answers)
  const streams: FakeStream[] = []
  const wrapper = mount(RunView, {
    props: { serverId: 's1', runId: 'r1' },
    global: {
      plugins: [pinia, router, createPanelI18n('en')],
      provide: {
        [API_CLIENT as symbol]: api.client,
        [RUNTIME_CONFIG as symbol]: {
          apiOrigin: 'https://api.example.com',
          languages: ['en'],
          defaultLanguage: 'en',
        },
        [STREAM as symbol]: (url: string) => {
          const stream = new FakeStream(url)
          streams.push(stream)
          return stream
        },
      },
    },
  })
  await flushPromises()
  return { wrapper, asked: api.asked, streams }
}

const PAGE = 'GET /api/v1/servers/s1/runs/r1'

function step(event: string, seq: number, extra: Record<string, unknown> = {}) {
  return {
    event,
    seq,
    at: `2026-11-24T12:00:0${seq}.000Z`,
    phase: 'main',
    stack: 'velo',
    name: 'build',
    order: 1,
    ...extra,
  }
}

describe('a run', () => {
  it('test_probe_DM_156_ladder_live', async () => {
    // A step appears with its step_started and changes with its
    // step_finished -- as the events come, before the run ends.
    const { wrapper, streams } = await view({ [PAGE]: runPage() })
    const [stream] = streams
    expect(stream?.url).toBe('https://api.example.com/api/v1/streams/servers/s1/runs/r1')
    expect(wrapper.find('[data-test="step-build"]').exists()).toBe(false)
    stream?.send('line', step('step_started', 2))
    await flushPromises()
    expect(wrapper.get('[data-test="step-build"] [data-test="step-status"]').text()).toBe('running')
    stream?.send('line', step('step_finished', 3, { status: 'ok', duration_s: 1.5 }))
    await flushPromises()
    expect(wrapper.get('[data-test="step-build"] [data-test="step-status"]').text()).toBe('ok')
    expect(wrapper.get('[data-test="status"]').text()).toBe('running')
  })

  it('shows the log as it came, nothing added', async () => {
    const { wrapper, streams } = await view({ [PAGE]: runPage() })
    const line = {
      event: 'log',
      seq: 2,
      at: '2026-11-24T12:00:02.000Z',
      phase: 'main',
      stack: 'velo',
      name: 'build',
      stream: 'stderr',
      line: '  token=s3cr3t-marker <b>raw</b>  ',
    }
    streams[0]?.send('line', line)
    await flushPromises()
    expect(wrapper.get('[data-test="log"]').text()).toContain(
      'velo/build   token=s3cr3t-marker <b>raw</b>',
    )
    expect(wrapper.find('[data-test="log"] b').exists()).toBe(false)
  })

  it('shows the last lines of a long log, and all of them when asked', async () => {
    const { wrapper, streams } = await view({ [PAGE]: runPage() })
    for (let seq = 1; seq <= 1002; seq++) {
      streams[0]?.send('line', {
        event: 'log',
        seq,
        at: 'a',
        stack: 's',
        name: 'n',
        stream: 'stdout',
        line: `L${seq}`,
      })
    }
    await flushPromises()
    const shown = () =>
      wrapper
        .get('[data-test="log"]')
        .text()
        .split('\n')
        .map((row) => row.trim())
        .filter((row) => row !== '')
    expect(shown().length).toBe(1000)
    expect(shown()[0]).toBe('a s/n L3')
    expect(shown().at(-1)).toBe('a s/n L1002')
    await wrapper.get('[data-test="show-all"]').trigger('click')
    expect(shown().length).toBe(1002)
    expect(shown()[0]).toBe('a s/n L1')
  })

  it('tells an abandoned run from a finished one, and closes the stream', async () => {
    let page = runPage()
    const { wrapper, streams } = await view({ [PAGE]: () => new Response(JSON.stringify(page)) })
    page = runPage({ status: 'abandoned' })
    streams[0]?.send('status', { status: 'abandoned', last_seq: 4 })
    await flushPromises()
    expect(wrapper.get('[data-test="status"]').text()).toBe('abandoned: stopped without a verdict')
    expect(streams[0]?.closed).toBe(true)
  })

  it('copies the report for an LLM byte for byte', async () => {
    const report = '  # Report\n\nsecret-looking: s3cr3t-marker  \n'
    const writeText = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()
    const { wrapper } = await view({
      [PAGE]: runPage({
        status: 'finished',
        report_llm: report,
        verdict: { result: 'green', exit_code: 0, finished: 'f', verified: false },
      }),
    })
    await wrapper.get('[data-test="copy"]').trigger('click')
    expect(writeText).toHaveBeenCalledWith(report)
    expect(wrapper.get('[data-test="verdict"]').text()).toContain('signature does not hold')
  })

  it('repeats the same command; a destructive one by the name again', async () => {
    const plain = await view({
      [PAGE]: runPage({
        repeat: { verb: 'update', args: { tries: ['velo=1.2.3'] }, sure: false, name: false },
      }),
      'POST /api/v1/servers/s1/commands': { id: 'c1' },
    })
    await plain.wrapper.get('[data-test="repeat"]').trigger('click')
    await flushPromises()
    expect(plain.asked.find((a) => a.method === 'POST')?.body).toEqual({
      verb: 'update',
      args: { tries: ['velo=1.2.3'] },
      confirmed: false,
    })
    const destructive = await view({
      [PAGE]: runPage({ repeat: { verb: 'destroy', args: {}, sure: false, name: true } }),
      'POST /api/v1/servers/s1/commands': { id: 'c2' },
    })
    await destructive.wrapper.get('[data-test="repeat"]').trigger('click')
    expect(destructive.asked.some((a) => a.method === 'POST')).toBe(false)
    await destructive.wrapper.get('[data-test="confirm-input"]').setValue('velo-test')
    await destructive.wrapper.get('[data-test="confirm-yes"]').trigger('click')
    await flushPromises()
    expect(destructive.asked.find((a) => a.method === 'POST')?.body).toEqual({
      verb: 'destroy',
      args: { confirm: 'velo-test' },
      confirmed: true,
    })
  })

  it('says where to repeat when the run cannot be; a run not seen is not found', async () => {
    const { wrapper } = await view({ [PAGE]: runPage() })
    expect(wrapper.find('[data-test="repeat"]').exists()).toBe(false)
    expect(wrapper.find('[data-test="no-repeat"]').exists()).toBe(true)
    const missing = await view({})
    expect(missing.wrapper.find('[data-test="not-found"]').exists()).toBe(true)
    expect(missing.streams).toEqual([])
  })
})
