// The sign-in of the Panel, as the page sees it (DM-150, DM-151).
//
// Signing in is a navigation of the browser, never a fetch: the button leads
// to the API's /auth/telegram/start; an invite link of the frontend
// (/login?invite=<token>) hands its token on to that address, and the page
// keeps it nowhere. Every refused sign-in comes back to
// /login#reason=<code>[&telegram_id=<id>]: the fragment never reaches a
// server. The codes are the API's LoginRefusal (app/access/login.py).

export const LOGIN_REFUSALS = [
  'restart',
  'try_later',
  'refused',
  'defect',
  'unavailable',
  'foreign_state',
  'stranger',
  'deactivated',
  'invite_invalid',
] as const

export type LoginRefusal = (typeof LOGIN_REFUSALS)[number]

export interface Refusal {
  // a known code, or null for a code the page does not know
  reason: LoginRefusal | null
  // the code as the address gives it
  given: string
  // the person's Telegram id: digits only, else null
  telegramId: string | null
}

const DIGITS = /^[0-9]{1,19}$/

function isRefusal(value: string): value is LoginRefusal {
  return (LOGIN_REFUSALS as readonly string[]).includes(value)
}

// The refusal in the fragment of the address; null when there is none.
export function parseRefusal(hash: string): Refusal | null {
  const params = new URLSearchParams(hash.replace(/^#/, ''))
  const given = params.get('reason')
  if (!given) {
    return null
  }
  const id = params.get('telegram_id')
  return {
    reason: isRefusal(given) ? given : null,
    given,
    telegramId: id !== null && DIGITS.test(id) ? id : null,
  }
}

// The address of the sign-in on the API, with the invite of the page's own
// address when it has one.
export function startUrl(apiOrigin: string, invite: string | null): string {
  const url = `${apiOrigin}/auth/telegram/start`
  return invite ? `${url}?invite=${encodeURIComponent(invite)}` : url
}
