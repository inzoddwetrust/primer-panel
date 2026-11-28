// A server's card as the API gives it (DM-155): the head is the fleet's row;
// the buttons are data of the API -- the verbs of the machine the person may
// queue on this server, each with its form (the JSON Schema of the verb's own
// arguments), what it presets and how it is confirmed. The page holds no rule
// of verbs: it asks for the server's name when the button says so.

export interface FieldSchema {
  type?: string
  enum?: string[]
  anyOf?: FieldSchema[]
  items?: FieldSchema
  title?: string
  default?: unknown
}

export interface Button {
  verb: string
  preset: Record<string, unknown>
  schema: { type: string; properties: Record<string, FieldSchema>; required?: string[] }
  positionals: string[]
  sure: boolean
  name: 'always' | 'when' | 'ask' | 'never'
  destructive_options: Record<string, unknown[]>
  // The field whose release below the box's machine asks "are you sure?"
  // (DM-218: `tag` of `self-update`); null -- none.
  sure_below: string | null
}

export interface RunRow {
  run_id: string
  verb: string | null
  started_at: string | null
  ended_at: string | null
  outcome: string | null
  verdict: { result: string; verified: boolean } | null
  running: boolean
}

export function label(button: Button): string {
  const action = button.preset['action']
  return typeof action === 'string' ? `${button.verb} ${action}` : button.verb
}

export type FieldKind = 'enum' | 'boolean' | 'string' | 'list' | 'json'

// What a form holds: text in its inputs, a flag in its checkboxes.
export interface FormValues {
  text: Record<string, string>
  flag: Record<string, boolean>
}

export function emptyForm(): FormValues {
  return { text: {}, flag: {} }
}

// The input a field of the schema takes; one the page cannot draw is JSON text.
export function fieldKind(field: FieldSchema): FieldKind {
  const plain = field.anyOf?.find((part) => part.type !== 'null') ?? field
  if (plain.enum) return 'enum'
  if (plain.type === 'boolean') return 'boolean'
  if (plain.type === 'string') return 'string'
  if (plain.type === 'array' && plain.items?.type === 'string') return 'list'
  return 'json'
}

export function enumOf(field: FieldSchema): string[] {
  const plain = field.anyOf?.find((part) => part.type !== 'null') ?? field
  return plain.enum ?? []
}

// The arguments a button sends: what it presets and what the form holds --
// an empty optional field is left out, as the machine's default.
export function argsFrom(button: Button, values: FormValues): Record<string, unknown> {
  const args: Record<string, unknown> = { ...button.preset }
  for (const [name, field] of Object.entries(button.schema.properties)) {
    const kind = fieldKind(field)
    const value = values.text[name]
    if (kind === 'boolean') {
      if (values.flag[name] === true) args[name] = true
    } else if (kind === 'list') {
      const lines = (value ?? '')
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line !== '')
      if (lines.length > 0) args[name] = lines
    } else if (kind === 'json') {
      if (value !== undefined && value.trim() !== '') args[name] = JSON.parse(value)
    } else if (value !== undefined && value !== '') {
      args[name] = value
    }
  }
  return args
}

// The required fields the form has left empty.
export function missing(button: Button, args: Record<string, unknown>): string[] {
  return (button.schema.required ?? []).filter((name) => args[name] === undefined)
}

// A release as numbers -- `v0.1.12` and `0.1.12` alike; null -- none.
function release(text: unknown): number[] | null {
  if (typeof text !== 'string') return null
  const found = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(text)
  return found ? found.slice(1).map(Number) : null
}

// Whether the command turns the box's machine back to a lower release
// (DM-218): the button names its field; "are you sure?" on any role.
export function rollsBack(
  button: Button,
  args: Record<string, unknown>,
  machine: string | null,
): boolean {
  if (button.sure_below === null) return false
  const asked = release(args[button.sure_below])
  const now = release(machine)
  if (asked === null || now === null) return false
  for (let at = 0; at < 3; at += 1) {
    if (asked[at] !== now[at]) return (asked[at] ?? 0) < (now[at] ?? 0)
  }
  return false
}

// Whether the server's name is typed before the command goes (R-18): the
// button's own word -- always, when an argument has a destructive value the
// API named, or when the person says a project verb is destructive.
export function needsName(button: Button, args: Record<string, unknown>, asked: boolean): boolean {
  if (button.name === 'always') return true
  if (button.name === 'ask') return asked
  if (button.name === 'when') {
    return Object.entries(button.destructive_options).some(([field, values]) =>
      values.includes(args[field]),
    )
  }
  return false
}
