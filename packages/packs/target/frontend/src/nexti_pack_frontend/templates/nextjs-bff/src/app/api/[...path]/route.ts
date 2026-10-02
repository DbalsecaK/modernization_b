// The BFF (ADR-0028): forwards /api/** to the generated backend as it is, without business logic. The backend's base
// URL comes from the environment (NEXTI_BACKEND_URL); without it the BFF answers 502.
const DROPPED = new Set(['connection', 'keep-alive', 'transfer-encoding', 'upgrade', 'host', 'content-length',
  'content-encoding'])

function copy(headers: Headers): Headers {
  const out = new Headers()
  headers.forEach((value, key) => {
    if (!DROPPED.has(key.toLowerCase())) out.set(key, value)
  })
  return out
}

async function forward(request: Request, context: { params: Promise<{ path: string[] }> }): Promise<Response> {
  const base = process.env.NEXTI_BACKEND_URL
  if (!base) {
    return Response.json({ code: 'BFF_NOT_CONFIGURED', message: 'The backend URL is not configured' }, { status: 502 })
  }
  const { path } = await context.params
  if (path.some((segment) => segment === '.' || segment === '..')) {
    return Response.json({ code: 'BAD_PATH', message: 'Invalid path' }, { status: 400 })
  }
  const target = `${base.replace(/\/+$/, '')}/api/${path.map(encodeURIComponent).join('/')}${new URL(request.url).search}`
  const withBody = request.method !== 'GET' && request.method !== 'HEAD'
  const response = await fetch(target, {
    method: request.method,
    headers: copy(request.headers),
    body: withBody ? await request.arrayBuffer() : undefined,
    redirect: 'manual',
  })
  return new Response(response.body, { status: response.status, statusText: response.statusText,
    headers: copy(response.headers) })
}

export const dynamic = 'force-dynamic'
export { forward as DELETE, forward as GET, forward as PATCH, forward as POST, forward as PUT }
