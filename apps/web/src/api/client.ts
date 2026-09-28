import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from './schema'

// Typed client of the platform API. Types come from the API's OpenAPI document (`pnpm api:types`).
// Same origin (Vite proxy in development): the session is an httpOnly cookie the browser sends by itself;
// this code never sees a token.
export type Schemas = components['schemas']

let csrfToken: string | null = null

/** The session's CSRF token (from /api/v1/me), sent back on every mutating request. */
export function setCsrfToken(token: string | null) {
  csrfToken = token
}

const SAFE = new Set(['GET', 'HEAD', 'OPTIONS'])

const csrf: Middleware = {
  onRequest({ request }) {
    if (!SAFE.has(request.method) && csrfToken) request.headers.set('X-CSRF-Token', csrfToken)
    return request
  },
}

export const api = createClient<paths>({ baseUrl: globalThis.location?.origin ?? '', credentials: 'same-origin' })
api.use(csrf)

/** An RFC 9457 problem returned by the API; `code` is stable and safe to branch on. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    detail: string,
  ) {
    super(detail)
  }
}

export function toApiError(response: Response, error: unknown): ApiError {
  const problem = (error ?? {}) as { code?: string; detail?: string }
  return new ApiError(response.status, problem.code ?? 'unknown_error', problem.detail ?? response.statusText)
}
