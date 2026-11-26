// A run as the API gives it (DM-156), and its lines as the box sent them.
//
// The page shows every line as it came -- it adds, joins and invents nothing
// -- and the report for an LLM as the box sent it in the envelope. The state
// of the run (running, finished, abandoned, silent) is the API's.

import { inject, type InjectionKey } from 'vue'

export type RunStatus = 'running' | 'finished' | 'abandoned' | 'silent'

export interface RunPage {
  run_id: string
  server_name: string
  verb: string | null
  started_at: string | null
  ended_at: string | null
  outcome: string | null
  status: RunStatus
  verdict: { result: string; exit_code: number; finished: string; verified: boolean } | null
  report_llm: string | null
  repeat: { verb: string; args: Record<string, unknown>; sure: boolean; name: boolean } | null
  last_seq: number
  key_wait: KeyWait | null
}

// A run waiting for a key to a repository (DM-159), as the API reads it from
// the run's lines: the box goes on by itself once the key works.
export interface KeyWait {
  run_id: string
  repo: string
  key: string
  page: string | null
  write: boolean
  why: string | null
  wait_s: number
  again: boolean
  at: string
  state: 'waiting' | 'granted' | 'not_granted' | 'ended'
  reason: string | null
}

// When a wait ends: its start and its seconds; null -- the run does not wait
// (a write key that waits for nothing: no seconds), or the box gave what no
// moment can be made of (DM-210: a wait of 1e300 seconds made `toISOString`
// throw and took the screen down). A wait the box says ended before it began
// -- seconds below zero pass the API -- is shown as it is, a moment in the
// past.
export function waitsUntil(wait: KeyWait): string | null {
  if (wait.wait_s === 0) return null
  const end = new Date(Date.parse(wait.at) + wait.wait_s * 1000)
  if (!Number.isFinite(end.getTime())) return null
  return end.toISOString().replace(/\.\d{3}Z$/, 'Z')
}

// The page of a repository's keys as a link, or null: an `https` address and
// nothing else. The API gives none other (app/runs/keys.py, `https_page`);
// this is the second line, at the place the link is made -- `javascript:` in
// an `href` runs in the Panel's origin (DM-210).
export function httpsPage(page: unknown): string | null {
  if (typeof page !== 'string' || !page.startsWith('https://')) return null
  let url: URL
  try {
    url = new URL(page)
  } catch {
    return null // no address at all
  }
  return url.username === '' && url.password === '' ? page : null
}

// A line of the run's journal (contract 2): its kind is `event`.
export type Line = Record<string, unknown> & { event?: string; seq?: number }

export interface Step {
  key: string
  phase: string
  stack: string
  name: string
  status: string
  reason: unknown
  duration_s: unknown
}

// The ladder of steps, as far as the lines go: a step is running from its
// step_started and has its status from its step_finished.
export function ladder(lines: readonly Line[]): Step[] {
  const steps = new Map<string, Step>()
  for (const line of lines) {
    if (line.event !== 'step_started' && line.event !== 'step_finished') continue
    const key = `${String(line['phase'])}/${String(line['stack'])}/${String(line['name'])}/${String(line['order'])}`
    const step: Step = steps.get(key) ?? {
      key,
      phase: String(line['phase']),
      stack: String(line['stack']),
      name: String(line['name']),
      status: 'running',
      reason: null,
      duration_s: null,
    }
    if (line.event === 'step_finished') {
      step.status = String(line['status'])
      step.reason = line['reason'] ?? null
      step.duration_s = line['duration_s'] ?? null
    }
    steps.set(key, step)
  }
  return [...steps.values()]
}

export const LOG_SHOWN = 1000

// The lines of the log, the last LOG_SHOWN of them unless all are asked for.
export function logLines(lines: readonly Line[], all: boolean): Line[] {
  const log = lines.filter((line) => line.event === 'log')
  return all ? log : log.slice(-LOG_SHOWN)
}

// What the page reads a stream with: an EventSource, given by src/main.ts
// (with the session's cookie) and by a test (a stand-in).
export interface StreamSource {
  addEventListener(type: string, listener: (event: MessageEvent<string>) => void): void
  close(): void
}

export const STREAM: InjectionKey<(url: string) => StreamSource> = Symbol('stream')

export function useStream(): (url: string) => StreamSource {
  const open = inject(STREAM)
  if (open === undefined) {
    throw new Error('no stream is provided')
  }
  return open
}
