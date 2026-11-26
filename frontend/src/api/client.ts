// The client of the Panel's API (DM-151): translated from velo's
// frontend/src/api/client.ts onto the blank's form.
//
// No module-level state: createApiClient makes one client per application
// (src/main.ts) and the views reach it through provide/inject (useApi).
// The session is the cookie panel_session of the API's host (DM-150): every
// request goes with credentials: 'include'; the page never sees a token.
//
// Every request ends in its data or in one of three errors:
//   ApiError        -- the API answered and refused: its class and message,
//                      from the one form {"error": {"class", "message"}}; an
//                      answer that is not JSON or not that form is the class
//                      invalid_response;
//   ApiNetworkError -- the request never reached the API;
//   ApiTimeoutError -- no answer within the timeout (15 s).
// A 401 also calls onUnauthorized: the page drops the person and shows the
// sign-in (src/main.ts).

import { inject, type InjectionKey } from 'vue'

export const REQUEST_TIMEOUT_MS = 15_000

export class ApiError extends Error {
  constructor(
    public status: number,
    public errorClass: string,
    message: string,
    public requestId: string | null,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export class ApiNetworkError extends Error {
  constructor() {
    super('the API is not reachable')
    this.name = 'ApiNetworkError'
  }
}

export class ApiTimeoutError extends Error {
  constructor(timeoutMs: number) {
    super(`no answer in ${timeoutMs / 1000} s`)
    this.name = 'ApiTimeoutError'
  }
}

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

import type { ApiPath } from './paths'

// A path is a text of the page's own source, or one made by apiPath
// (src/api/paths.ts) -- the only way a parameter or an id gets into one.
export type Path = string | ApiPath

export interface ApiClient {
  request<T>(method: HttpMethod, path: Path, body?: unknown): Promise<T>
  get<T>(path: Path): Promise<T>
  post<T>(path: Path, body?: unknown): Promise<T>
  put<T>(path: Path, body?: unknown): Promise<T>
}

export interface ClientOptions {
  // The https origin of the API, from /config.json
  origin: string
  fetchFn?: typeof fetch
  onUnauthorized?: () => void
  timeoutMs?: number
}

function errorOf(status: number, data: unknown, requestId: string | null): ApiError {
  if (typeof data === 'object' && data !== null && 'error' in data) {
    const error = (data as { error: unknown }).error
    if (typeof error === 'object' && error !== null) {
      const { class: errorClass, message } = error as Record<string, unknown>
      if (typeof errorClass === 'string' && typeof message === 'string') {
        return new ApiError(status, errorClass, message, requestId)
      }
    }
  }
  return new ApiError(status, 'invalid_response', `the API answered ${status}`, requestId)
}

export function createApiClient(options: ClientOptions): ApiClient {
  const fetchFn = options.fetchFn ?? ((input, init) => fetch(input, init))
  const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS

  async function request<T>(method: HttpMethod, path: Path, body?: unknown): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
    }
    const controller = new AbortController()
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, timeoutMs)
    let response: Response
    try {
      response = await fetchFn(options.origin + String(path), {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        credentials: 'include',
        signal: controller.signal,
      })
    } catch {
      throw timedOut ? new ApiTimeoutError(timeoutMs) : new ApiNetworkError()
    } finally {
      clearTimeout(timer)
    }
    const requestId = response.headers.get('X-Request-ID')
    if (response.status === 401) {
      options.onUnauthorized?.()
    }
    if (response.status === 204) {
      return undefined as T
    }
    let data: unknown
    try {
      data = await response.json()
    } catch {
      throw new ApiError(
        response.status,
        'invalid_response',
        `the API answered ${response.status}`,
        requestId,
      )
    }
    if (!response.ok) {
      throw errorOf(response.status, data, requestId)
    }
    return data as T
  }

  return {
    request,
    get: <T>(path: string) => request<T>('GET', path),
    post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
    put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  }
}

export const API_CLIENT: InjectionKey<ApiClient> = Symbol('api-client')

export function useApi(): ApiClient {
  const client = inject(API_CLIENT)
  if (client === undefined) {
    throw new Error('no API client is provided')
  }
  return client
}
