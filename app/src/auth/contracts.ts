export interface AuthUser {
  readonly id: string
  readonly username: string
  readonly role: string
}

export interface AuthIdentity extends AuthUser {
  readonly csrfToken: string
}

export type AuthSession =
  | { readonly authenticated: false }
  | { readonly authenticated: true; readonly user: AuthUser; readonly csrfToken: string }

export type AuthFailureKind = 'invalid' | 'limited' | 'unavailable' | 'aborted'

export interface AuthFailure {
  readonly kind: AuthFailureKind
  readonly retryAfter: string | null
}

export type AuthResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly error: AuthFailure }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function userFrom(value: unknown): AuthUser | null {
  if (!isRecord(value)) return null
  const { id, username, role } = value
  if (typeof id !== 'string' || !id || typeof username !== 'string' || !username) return null
  if (typeof role !== 'string' || !role) return null
  return { id, username, role }
}

export function authSessionFrom(value: unknown): AuthSession | null {
  if (!isRecord(value) || value.authenticated !== true) {
    if (isRecord(value) && value.authenticated === false) return { authenticated: false }
    return null
  }
  const user = userFrom(value.user)
  if (!user || typeof value.csrfToken !== 'string' || !value.csrfToken) return null
  return { authenticated: true, user, csrfToken: value.csrfToken }
}
