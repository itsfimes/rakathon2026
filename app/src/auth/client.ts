import { authSessionFrom } from './contracts'
import type { AuthIdentity, AuthResult, AuthSession, DemoAccount } from './contracts'

const LOGIN_HEADER = 'X-Rakathon-Auth'
const CSRF_HEADER = 'X-CSRF-Token'

function aborted(signal?: AbortSignal): boolean {
  return signal?.aborted === true
}

function retryAfter(response: Response): string | null {
  const value = response.headers.get('Retry-After')
  return value && value.trim() ? value.trim() : null
}

async function readJson(response: Response): Promise<unknown | null> {
  if (!response.headers.get('content-type')?.includes('application/json')) return null
  try {
    return (await response.json()) as unknown
  } catch {
    return null
  }
}

async function request(path: string, init: RequestInit, signal?: AbortSignal): Promise<Response> {
  return globalThis.fetch(path, {
    credentials: 'same-origin',
    cache: 'no-store',
    redirect: 'error',
    ...init,
    ...(signal ? { signal } : {}),
  })
}

function baseHeaders(extra?: HeadersInit): HeadersInit {
  return { Accept: 'application/json', ...extra }
}

export async function fetchAuthSession(signal?: AbortSignal): Promise<AuthResult<AuthSession>> {
  if (aborted(signal)) return { ok: false, error: { kind: 'aborted', retryAfter: null } }
  let response: Response
  try {
    response = await request('/api/v1/auth/session', { method: 'GET', headers: baseHeaders() }, signal)
  } catch {
    return aborted(signal) ? { ok: false, error: { kind: 'aborted', retryAfter: null } } : { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  }
  if (aborted(signal)) return { ok: false, error: { kind: 'aborted', retryAfter: null } }
  if (response.status === 401) return fromStaleUnauthorized(await readJson(response))
  if (response.status === 429) return { ok: false, error: { kind: 'limited', retryAfter: retryAfter(response) } }
  if (response.status !== 200) return { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  const session = authSessionFrom(await readJson(response))
  if (!session) return { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  return { ok: true, value: session }
}

function fromStaleUnauthorized(data: unknown): AuthResult<AuthSession> {
  if (data === null || data === undefined) return { ok: true, value: { authenticated: false } }
  const session = authSessionFrom(data)
  if (session) {
    if (session.authenticated) return { ok: false, error: { kind: 'unavailable', retryAfter: null } }
    return { ok: true, value: session }
  }
  if (isLegacyUnauthorized(data)) return { ok: true, value: { authenticated: false } }
  return { ok: false, error: { kind: 'unavailable', retryAfter: null } }
}

function isLegacyUnauthorized(data: unknown): boolean {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return false
  const record = data as Record<string, unknown>
  if (typeof record.error !== 'string' || !record.error) return false
  return record.authenticated === undefined
}

export async function loginRequest(username: string, password: string, signal?: AbortSignal): Promise<AuthResult<AuthIdentity>> {
  if (aborted(signal)) return { ok: false, error: { kind: 'aborted', retryAfter: null } }
  let response: Response
  try {
    response = await request('/api/v1/auth/login', {
      method: 'POST',
      headers: baseHeaders({ 'Content-Type': 'application/json', [LOGIN_HEADER]: '1' }),
      body: JSON.stringify({ username, password }),
    }, signal)
  } catch {
    return aborted(signal) ? { ok: false, error: { kind: 'aborted', retryAfter: null } } : { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  }
  if (aborted(signal)) return { ok: false, error: { kind: 'aborted', retryAfter: null } }
  if (response.status === 401) return { ok: false, error: { kind: 'invalid', retryAfter: null } }
  if (response.status === 400) return { ok: false, error: { kind: 'invalid', retryAfter: null } }
  if (response.status === 429) return { ok: false, error: { kind: 'limited', retryAfter: retryAfter(response) } }
  if (response.status !== 200) return { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  const session = authSessionFrom(await readJson(response))
  if (!session || !session.authenticated) return { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  return { ok: true, value: { ...session.user, csrfToken: session.csrfToken, ...(session.demoView ? { demoView: session.demoView } : {}) } }
}

export async function demoLoginRequest(account: DemoAccount, signal?: AbortSignal): Promise<AuthResult<AuthIdentity>> {
  if (aborted(signal)) return { ok: false, error: { kind: 'aborted', retryAfter: null } }
  let response: Response
  try {
    response = await request('/api/v1/auth/demo-login', {
      method: 'POST',
      headers: baseHeaders({ 'Content-Type': 'application/json', [LOGIN_HEADER]: '1' }),
      body: JSON.stringify({ account }),
    }, signal)
  } catch {
    return aborted(signal) ? { ok: false, error: { kind: 'aborted', retryAfter: null } } : { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  }
  if (aborted(signal)) return { ok: false, error: { kind: 'aborted', retryAfter: null } }
  if (response.status === 401) return { ok: false, error: { kind: 'invalid', retryAfter: null } }
  if (response.status === 400) return { ok: false, error: { kind: 'invalid', retryAfter: null } }
  if (response.status === 429) return { ok: false, error: { kind: 'limited', retryAfter: retryAfter(response) } }
  if (response.status !== 200) return { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  const session = authSessionFrom(await readJson(response))
  if (!session || !session.authenticated) return { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  if (session.demoView !== account) return { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  return { ok: true, value: { ...session.user, csrfToken: session.csrfToken, ...(session.demoView ? { demoView: session.demoView } : {}) } }
}

export async function logoutRequest(csrfToken: string, signal?: AbortSignal): Promise<AuthResult<null>> {
  if (aborted(signal)) return { ok: false, error: { kind: 'aborted', retryAfter: null } }
  let response: Response
  try {
    response = await request('/api/v1/auth/logout', {
      method: 'POST',
      headers: baseHeaders({ [CSRF_HEADER]: csrfToken }),
      body: '',
    }, signal)
  } catch {
    return aborted(signal) ? { ok: false, error: { kind: 'aborted', retryAfter: null } } : { ok: false, error: { kind: 'unavailable', retryAfter: null } }
  }
  if (aborted(signal)) return { ok: false, error: { kind: 'aborted', retryAfter: null } }
  if (response.status === 204 || response.status === 401) return { ok: true, value: null }
  if (response.status === 429) return { ok: false, error: { kind: 'limited', retryAfter: retryAfter(response) } }
  return { ok: false, error: { kind: 'unavailable', retryAfter: null } }
}
