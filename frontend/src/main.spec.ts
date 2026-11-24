import { afterEach, describe, expect, it, vi } from 'vitest'
import { BUILT_IN } from './texts'

// The page as the browser starts it: src/main.ts against the container's
// /config.json, answered here. Changed by DM-148: the texts package is gone
// with the packages of the blank, so the page asks for /config.json alone and
// speaks its built-in texts.
const CONFIG = '{"apiBaseUrl":"https://api.example.com","languages":"en,ru","defaultLanguage":"ru"}'

async function page(config: Response): Promise<{ app: HTMLElement; asked: string[] }> {
  document.body.innerHTML = '<div id="app"></div>'
  const asked: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (path: string) => {
      asked.push(path)
      return config
    }),
  )
  vi.stubGlobal('navigator', { languages: ['de'], language: 'de' })
  vi.resetModules()
  await import('./main')
  const app = document.getElementById('app') as HTMLElement
  await vi.waitFor(() => expect(app.querySelector('main')).not.toBeNull())
  return { app, asked }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('the page', () => {
  it("speaks the instance's default in its built-in texts, asking /config.json alone", async () => {
    const { app, asked } = await page(new Response(CONFIG))
    expect(asked).toEqual(['/config.json'])
    expect(app.querySelector('[data-test="config-error"]')).toBeNull()
    expect(app.querySelector('[data-test="api-origin"]')?.textContent).toBe(
      `${BUILT_IN.ru?.api_label} https://api.example.com`,
    )
    expect(document.documentElement.lang).toBe('ru')
  })

  it('shows the error of an unreadable /config.json in the fallback language', async () => {
    const { app } = await page(new Response('missing', { status: 404 }))
    expect(app.querySelector('[data-test="config-error"]')?.textContent).toContain(
      BUILT_IN.en?.config_error,
    )
    expect(app.querySelector('[data-test="api-origin"]')).toBeNull()
  })
})
