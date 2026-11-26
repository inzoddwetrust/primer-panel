// A server's passport as the API gives it (DM-158): read from primer-ops by
// the Panel's key, the secrets by name and state -- never a value. The page
// holds no rule of the passport: the API checks every edit with the machine's
// loader; here are only the types and how a typed value goes back as JSON.

import type { Me } from './stores/me'

export interface Field {
  path: string[]
  value: unknown
}

export interface Secret {
  stack: string
  key: string
  state: 'set' | 'switched_off'
}

export interface TlsPart {
  key: 'cert' | 'key'
  state: 'set' | 'switched_off'
}

export interface Applied {
  commit: string | null
  state: 'applied' | 'pending' | 'unknown'
}

export interface Shown {
  state: 'ready' | 'invalid'
  base: string
  version: number | null
  fields: Field[]
  secrets: Secret[]
  tls: TlsPart[]
  rules: { path: string[]; rule: string }[]
  problems: string[]
  apply: Applied
  panel_key: string
}

export type Passport =
  | Shown
  | { state: 'absent'; panel_key: string }
  | { state: 'not-recipient'; panel_key: string }
  | { state: 'file' }
  | {
      state: 'damaged'
      reason: 'sops-damaged' | 'not-a-file'
      base: string
      panel_key: string
    }

export interface Edited {
  commit: string
  version: number
}

export function shown(passport: Passport | null): passport is Shown {
  return passport?.state === 'ready' || passport?.state === 'invalid'
}

// Edits and "apply" are the permission `passport` of the server's project
// (PRIMER-PANEL-TZ-1); the superadmin holds every permission. The API is the
// truth: a refusal still shows.
export function mayEdit(me: Me | null, projectId: string): boolean {
  if (!me) return false
  if (me.is_superadmin) return true
  return me.projects.some(
    (access) => access.project.id === projectId && access.permissions.includes('passport'),
  )
}

export type Kind = 'string' | 'number' | 'boolean' | 'json'

// How a field is typed: by the JSON type of the value it has now.
export function kindOf(value: unknown): Kind {
  if (typeof value === 'string') return 'string'
  if (typeof value === 'number') return 'number'
  if (typeof value === 'boolean') return 'boolean'
  return 'json'
}

// The text of a field's input as its value goes; a JSON that does not
// parse, or a number that is none, throws -- nothing is sent.
export function valueOf(kind: Kind, text: string, checked: boolean): unknown {
  if (kind === 'string') return text
  if (kind === 'boolean') return checked
  if (kind === 'number') {
    const found = Number(text)
    if (text.trim() === '' || !Number.isFinite(found)) throw new Error('not a number')
    return found
  }
  return JSON.parse(text) as unknown
}

// The text a field's input starts with.
export function textOf(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

export function dotted(path: string[]): string {
  return path.join('.')
}

export function short(commit: string | null): string {
  return commit ? commit.slice(0, 7) : ''
}

// The text of the rule of a field that is not obvious (TZ §19 p.1), or null.
export function ruleOf(passport: Shown, path: string[]): string | null {
  const found = passport.rules.find((rule) => dotted(rule.path) === dotted(path))
  return found ? found.rule : null
}
