/** A business rejection of the backend (HTTP 422): the message is the one to show to the user. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    readonly legacyCode: string | null,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

type Payload = { code?: string; legacyCode?: string | null; message?: string }

/** One call of the backend: a JSON body for POST/PUT/PATCH, query parameters otherwise. */
export async function call<T>(
  fetchImpl: typeof fetch,
  baseUrl: string,
  method: string,
  path: string,
  request: object,
  withBody: boolean,
): Promise<T> {
  let url = baseUrl + path
  if (!withBody) {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(request)) {
      if (value !== undefined && value !== null) query.set(key, String(value))
    }
    url += query.toString() ? `?${query}` : ''
  }
  const response = await fetchImpl(url, {
    method,
    headers: withBody ? { 'Content-Type': 'application/json' } : undefined,
    body: withBody ? JSON.stringify(request) : undefined,
  })
  const payload = (await response.json().catch(() => ({}))) as Payload
  if (!response.ok) {
    const message = payload.message ?? response.statusText
    throw new ApiError(response.status, payload.code ?? 'ERROR', payload.legacyCode ?? null, message)
  }
  return payload as T
}
