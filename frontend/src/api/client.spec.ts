import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError,
  ApiNetworkError,
  ApiTimeoutError,
  REQUEST_TIMEOUT_MS,
  createApiClient,
} from './client'

const ORIGIN = 'https://api.example.com'

function answering(response: () => Response) {
  const calls: Array<{ url: string; init: RequestInit | undefined }> = []
  const fetchFn = vi.fn(async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), init })
    return response()
  }) as unknown as typeof fetch
  return { fetchFn, calls }
}

async function failure(promise: Promise<unknown>): Promise<unknown> {
  try {
    await promise
  } catch (error: unknown) {
    return error
  }
  throw new Error('the request did not fail')
}

afterEach(() => {
  vi.useRealTimers()
})

describe('the API client', () => {
  it('asks the API with the session cookie and gives the data', async () => {
    const { fetchFn, calls } = answering(() => new Response('{"ok":true}'))
    const api = createApiClient({ origin: ORIGIN, fetchFn })
    expect(await api.get('/api/v1/me')).toEqual({ ok: true })
    const [call] = calls
    expect(call?.url).toBe('https://api.example.com/api/v1/me')
    expect(call?.init?.credentials).toBe('include')
    expect(call?.init?.method).toBe('GET')
    expect(call?.init?.body).toBeUndefined()
  })

  it('sends a body as JSON', async () => {
    const { fetchFn, calls } = answering(() => new Response(null, { status: 204 }))
    const api = createApiClient({ origin: ORIGIN, fetchFn })
    expect(await api.post('/auth/logout', { a: 1 })).toBeUndefined()
    const headers = calls[0]?.init?.headers as Record<string, string>
    expect(headers['Content-Type']).toBe('application/json')
    expect(calls[0]?.init?.body).toBe('{"a":1}')
    expect(calls[0]?.init?.credentials).toBe('include')
  })

  it.each([
    [403, 'forbidden', 'The permission people is needed'],
    [404, 'not_found', 'Not found'],
    [503, 'unavailable', 'Sessions are unavailable'],
  ])('reads a refusal %i in the one form of errors', async (status, errorClass, message) => {
    const body = JSON.stringify({ error: { class: errorClass, message } })
    const { fetchFn } = answering(
      () => new Response(body, { status, headers: { 'X-Request-ID': 'req-42' } }),
    )
    const error = await failure(createApiClient({ origin: ORIGIN, fetchFn }).get('/x'))
    expect(error).toBeInstanceOf(ApiError)
    const refused = error as ApiError
    expect([refused.status, refused.errorClass, refused.message, refused.requestId]).toEqual([
      status,
      errorClass,
      message,
      'req-42',
    ])
  })

  it.each([
    ['not json', '<html>bad gateway</html>'],
    ['velo form', '{"error":"forbidden","message":"x","detail":"y"}'],
    ['no class', '{"error":{"message":"x"}}'],
  ])('calls an answer off the form invalid_response (%s)', async (_, body) => {
    const { fetchFn } = answering(() => new Response(body, { status: 502 }))
    const error = await failure(createApiClient({ origin: ORIGIN, fetchFn }).get('/x'))
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).errorClass).toBe('invalid_response')
    expect((error as ApiError).status).toBe(502)
  })

  it('tells the page of a 401, and still fails the request', async () => {
    const body = '{"error":{"class":"unauthorized","message":"Sign in"}}'
    const { fetchFn } = answering(() => new Response(body, { status: 401 }))
    const onUnauthorized = vi.fn()
    const api = createApiClient({ origin: ORIGIN, fetchFn, onUnauthorized })
    const error = await failure(api.get('/api/v1/me'))
    expect(onUnauthorized).toHaveBeenCalledOnce()
    expect((error as ApiError).errorClass).toBe('unauthorized')
    // the pair: another refusal does not drop the person
    const other = answering(
      () => new Response('{"error":{"class":"forbidden","message":"x"}}', { status: 403 }),
    )
    await failure(
      createApiClient({ origin: ORIGIN, fetchFn: other.fetchFn, onUnauthorized }).get('/x'),
    )
    expect(onUnauthorized).toHaveBeenCalledOnce()
  })

  it('names a request that never reached the API', async () => {
    const fetchFn = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }) as unknown as typeof fetch
    const error = await failure(createApiClient({ origin: ORIGIN, fetchFn }).get('/x'))
    expect(error).toBeInstanceOf(ApiNetworkError)
  })

  it('gives up after its timeout', async () => {
    vi.useFakeTimers()
    expect(REQUEST_TIMEOUT_MS).toBe(15_000)
    const fetchFn = vi.fn(
      (_: unknown, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted')))
        }),
    ) as unknown as typeof fetch
    const pending = failure(createApiClient({ origin: ORIGIN, fetchFn }).get('/x'))
    await vi.advanceTimersByTimeAsync(REQUEST_TIMEOUT_MS)
    expect(await pending).toBeInstanceOf(ApiTimeoutError)
  })
})
