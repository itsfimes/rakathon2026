export interface AuthUser {
  readonly id: string
  readonly username: string
  readonly role: string
}

export interface AuthIdentity extends AuthUser {
  readonly csrfToken: string
  readonly demoView?: DemoAccount
}

export const DEMO_ACCOUNTS = ['koordinator', 'lekar', 'mdt', 'pacient'] as const
export type DemoAccount = (typeof DEMO_ACCOUNTS)[number]

export function isDemoAccount(value: unknown): value is DemoAccount {
  return typeof value === 'string' && (DEMO_ACCOUNTS as readonly string[]).includes(value)
}

function demoAccountsFrom(value: unknown): readonly DemoAccount[] | null | undefined {
  if (value === undefined) return undefined
  if (!Array.isArray(value) || value.length === 0) return null
  const accounts: DemoAccount[] = []
  for (const item of value) {
    if (!isDemoAccount(item) || accounts.includes(item)) return null
    accounts.push(item)
  }
  return accounts
}

function demoViewFrom(value: unknown, accounts: readonly DemoAccount[] | undefined): DemoAccount | null | undefined {
  if (value === undefined) return undefined
  if (!isDemoAccount(value)) return null
  if (!accounts || !accounts.includes(value)) return null
  return value
}

export interface AnonymousSession {
  readonly authenticated: false
  readonly demoAccounts?: readonly DemoAccount[]
}

export interface AuthenticatedSession {
  readonly authenticated: true
  readonly user: AuthUser
  readonly csrfToken: string
  readonly demoAccounts?: readonly DemoAccount[]
  readonly demoView?: DemoAccount
}

export type AuthSession = AnonymousSession | AuthenticatedSession

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
  if (!isRecord(value)) return null
  if (value.authenticated === false) {
    const hasAccounts = Object.hasOwn(value, 'demoAccounts') && value.demoAccounts !== undefined
    const accounts = demoAccountsFrom(value.demoAccounts)
    if (hasAccounts && accounts == null) return null
    if (Object.hasOwn(value, 'demoView') && value.demoView !== undefined) return null
    const session: AnonymousSession = { authenticated: false }
    return accounts ? { ...session, demoAccounts: accounts } : session
  }
  if (value.authenticated !== true) return null
  const user = userFrom(value.user)
  if (!user || typeof value.csrfToken !== 'string' || !value.csrfToken) return null
  const hasAccounts = Object.hasOwn(value, 'demoAccounts') && value.demoAccounts !== undefined
  const hasView = Object.hasOwn(value, 'demoView') && value.demoView !== undefined
  const accounts = demoAccountsFrom(value.demoAccounts)
  if (hasAccounts && accounts == null) return null
  const view = demoViewFrom(value.demoView, accounts ?? undefined)
  if (hasView && view == null) return null
  return {
    authenticated: true,
    user,
    csrfToken: value.csrfToken,
    ...(accounts ? { demoAccounts: accounts } : {}),
    ...(view ? { demoView: view } : {}),
  }
}
