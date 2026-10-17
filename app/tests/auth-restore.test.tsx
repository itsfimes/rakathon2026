import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginBoundary } from '../src/auth/LoginBoundary'
import { caseResponse, jsonResponse, sessionResponse, workspaceResponse } from './backend-fixtures'

const ACCOUNTS = ['koordinator', 'lekar', 'mdt', 'pacient']
const LEKAR = {
  authenticated: true,
  user: { id: 'demo-lekar', username: 'ukazka.lekar', role: 'clinician' },
  csrfToken: 'csrf-demo',
  demoAccounts: ACCOUNTS,
  demoView: 'lekar',
}
const MDT = {
  authenticated: true,
  user: { id: 'demo-mdt', username: 'ukazka.mdt', role: 'clinician' },
  csrfToken: 'csrf-mdt',
  demoAccounts: ACCOUNTS,
  demoView: 'mdt',
}

function backendEnv() {
  vi.stubEnv('VITE_DATA_MODE', 'backend')
  vi.stubEnv('VITE_BACKEND_API_BASE', '/api/v1')
}

function stubFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const fetcher = vi.fn(async (input: unknown, init?: RequestInit) => handler(String(input), init ?? {}))
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}

function clinicalFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  return stubFetch(handler)
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals() })

describe('session restore deep links', () => {
  it('reload keeps a valid same-view detail hash', async () => {
    backendEnv()
    window.history.replaceState(null, '', '/#lekar/case/synthetic-0')
    const requested: string[] = []
    clinicalFetch(url => {
      requested.push(url)
      if (url === '/api/v1/auth/session') return jsonResponse(LEKAR)
      if (url === '/api/v1/session') return jsonResponse(sessionResponse)
      if (url === '/api/v1/workspace') return jsonResponse(workspaceResponse())
      if (url.startsWith('/api/v1/cases/')) return jsonResponse(caseResponse())
      if (url === '/api/v1/auth/logout') return new Response(null, { status: 204 })
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    expect(await screen.findByText('Přihlášeno: ukazka.lekar')).toBeInTheDocument()
    await waitFor(() => expect(window.location.hash).toBe('#lekar/case/synthetic-0'))
    expect(requested).toContain('/api/v1/session')
    await waitFor(() => expect(requested.filter(url => url.startsWith('/api/v1/cases/') && url.includes('synthetic-0')).length).toBeGreaterThan(0))
  })
  it('reload replaces a cross-view hash before clinical reads', async () => {
    backendEnv()
    window.history.replaceState(null, '', '/#pacient/record')
    const requested: string[] = []
    clinicalFetch(url => {
      requested.push(url)
      if (url === '/api/v1/auth/session') return jsonResponse(LEKAR)
      if (url === '/api/v1/session') return jsonResponse(sessionResponse)
      if (url === '/api/v1/workspace') return jsonResponse(workspaceResponse())
      if (url.startsWith('/api/v1/cases/')) return jsonResponse(caseResponse())
      if (url === '/api/v1/auth/logout') return new Response(null, { status: 204 })
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    expect(await screen.findByText('Přihlášeno: ukazka.lekar')).toBeInTheDocument()
    await waitFor(() => expect(window.location.hash).toBe('#lekar'))
    expect(requested).toContain('/api/v1/session')
    expect(requested.filter(url => url.includes('pacient')).filter(url => url.startsWith('/api/v1/cases/'))).toEqual([])
  })
})

describe('logout then different account', () => {
  it('starts at the new root with fresh clinical bootstrap and matching CSRF', async () => {
    backendEnv()
    const requested: string[] = []
    const logoutCsrf: string[] = []
    clinicalFetch((url, init) => {
      requested.push(url)
      if (url === '/api/v1/auth/session') return jsonResponse({ authenticated: false, demoAccounts: ACCOUNTS })
      if (url === '/api/v1/auth/demo-login') {
        const account = (JSON.parse(String((init as RequestInit).body)) as { account: string }).account
        return jsonResponse(account === 'mdt' ? MDT : LEKAR)
      }
      if (url === '/api/v1/auth/login') return jsonResponse(LEKAR)
      if (url === '/api/v1/session') return jsonResponse(sessionResponse)
      if (url === '/api/v1/workspace') return jsonResponse(workspaceResponse())
      if (url.startsWith('/api/v1/cases/')) return jsonResponse(caseResponse())
      if (url === '/api/v1/auth/logout') {
        const headers = (init as RequestInit).headers as Record<string, string | undefined>
        logoutCsrf.push(String(headers['X-CSRF-Token']))
        return new Response(null, { status: 204 })
      }
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })
    fireEvent.click(screen.getByRole('button', { name: /Lékař/ }))
    expect(await screen.findByText('Přihlášeno: ukazka.lekar')).toBeInTheDocument()
    await waitFor(() => expect(window.location.hash).toBe('#lekar'))
    const sessionsAfterFirst = requested.filter(url => url === '/api/v1/session').length
    expect(sessionsAfterFirst).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Odhlásit' }))
    const firstConfirm = await screen.findByRole('dialog', { name: 'Opravdu se chcete odhlásit?' })
    fireEvent.click(within(firstConfirm).getByRole('button', { name: 'Odhlásit se' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })).toBeInTheDocument()
    expect(window.location.hash).toBe('')
    expect(screen.queryByText('Přihlášeno: ukazka.lekar')).toBeNull()
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: /MDT/ }))
    expect(await screen.findByText('Přihlášeno: ukazka.mdt')).toBeInTheDocument()
    await waitFor(() => expect(window.location.hash).toBe('#mdt'))
    expect(screen.queryByText('Přihlášeno: ukazka.lekar')).toBeNull()
    const sessionsAfterSecond = requested.filter(url => url === '/api/v1/session').length
    expect(sessionsAfterSecond).toBeGreaterThan(sessionsAfterFirst)
    fireEvent.click(screen.getByRole('button', { name: 'Odhlásit' }))
    const secondConfirm = await screen.findByRole('dialog', { name: 'Opravdu se chcete odhlásit?' })
    fireEvent.click(within(secondConfirm).getByRole('button', { name: 'Odhlásit se' }))
    await waitFor(() => expect(logoutCsrf).toContain('csrf-mdt'))
    expect(logoutCsrf.at(-1)).toBe('csrf-mdt')
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
})
