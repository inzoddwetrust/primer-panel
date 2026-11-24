import { afterEach, describe, expect, it, vi } from 'vitest'
import { BUILT_IN } from './texts'

// The page as the browser starts it: src/main.ts against the container's
// /config.json and the API, answered here.
//
// Changed by DM-151: the page starts the router -- `/` loads the person from
// the API with the session cookie and goes to the sign-in without one.
const CONFIG = '{"apiBaseUrl":"https://api.example.com","languages":"en,ru","defaultLanguage":"ru"}'
const ME =
  '{"user":{"id":"u1","telegram_id":123456789,"first_name":"Anna","username":"anna"},' +
  '"is_superadmin":true,"projects":[],"panel_grants":[]}'

interface Asked {
  url: string
  credentials: RequestCredentials | undefined
}

async function page(
  path: string,
  me: Response,
  config: Response = new Response(CONFIG),
): Promise<{ app: HTMLElement; asked: Asked[] }> {
  document.body.innerHTML = '<div id="app"></div>'
  window.history.replaceState(null, '', path)
  const asked: Asked[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      asked.push({ url, credentials: init?.credentials })
      return url === '/config.json' ? config : me
    }),
  )
  vi.stubGlobal('navigator', { languages: ['de'], language: 'de' })
  vi.resetModules()
  await import('./main')
  const app = document.getElementById('app') as HTMLElement
  await vi.waitFor(() =>
    expect(app.querySelector('main, [data-test="config-error"]')).not.toBeNull(),
  )
  return { app, asked }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the page', () => {
  it('shows the person of the session, asked with the cookie', async () => {
    const { app, asked } = await page('/', new Response(ME))
    await vi.waitFor(() => expect(app.querySelector('[data-test="me"]')).not.toBeNull())
    expect(asked.map((a) => a.url)).toEqual(['/config.json', 'https://api.example.com/api/v1/me'])
    expect(asked[1]?.credentials).toBe('include')
    expect(app.querySelector('[data-test="superadmin"]')?.textContent).toBe(
      BUILT_IN.ru?.me.superadmin,
    )
    expect(document.documentElement.lang).toBe('ru')
  })

  it('goes to the sign-in without a session', async () => {
    const refused = new Response('{"error":{"class":"unauthorized","message":"Sign in"}}', {
      status: 401,
    })
    const { app } = await page('/', refused)
    await vi.waitFor(() => expect(app.querySelector('[data-test="login-button"]')).not.toBeNull())
    expect(window.location.pathname).toBe('/login')
    expect(app.querySelector('[data-test="login-button"]')?.getAttribute('href')).toBe(
      'https://api.example.com/auth/telegram/start',
    )
  })

  it('shows the error of an unreadable /config.json in the fallback language', async () => {
    const { app } = await page('/', new Response(ME), new Response('missing', { status: 404 }))
    expect(app.querySelector('[data-test="config-error"]')?.textContent).toContain(
      BUILT_IN.en?.config_error,
    )
  })
})
