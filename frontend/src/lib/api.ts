// Thin client for the CuraLink FastAPI backend (proxied at /api by Vite).
// No secrets live in the frontend: the session is an HttpOnly cookie and all
// third-party keys stay on the server.

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public recoverable = true,
    public details: Record<string, unknown> = {},
  ) {
    super(message)
  }
}

const BASE = '/api/v1'

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'X-CuraLink-Client': 'web' }
  let payload: BodyInit | undefined
  if (body instanceof FormData) payload = body
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(BASE + path, { method, headers, body: payload, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, 'NETWORK', 'Can’t reach the CuraLink server. Check that the backend is running.', true)
  }
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new ApiError(res.status, data.code ?? 'ERROR', data.message ?? 'Something went wrong.', data.recoverable ?? true, data.details ?? {})
  return data as T
}

export const api = {
  get: <T>(path: string) => request<T>('GET', path),
  post: <T>(path: string, body?: unknown) => request<T>('POST', path, body),
  patch: <T>(path: string, body?: unknown) => request<T>('PATCH', path, body),
  put: <T>(path: string, body?: unknown) => request<T>('PUT', path, body),
  del: <T>(path: string) => request<T>('DELETE', path),
}
