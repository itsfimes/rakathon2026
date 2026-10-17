import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginBoundary } from '../src/auth/LoginBoundary'
import { fetchAuthSession } from '../src/auth/client'
import { resetBootCache } from '../src/session'
import { caseResponse, jsonResponse, sessionResponse, workspaceResponse } from './backend-fixtures'

const ACCOUNTS = ['koordinator', 'lekar', 'mdt', 'pacient']
const STALE_401 = {
  authenticated: false,
  demoAccounts: ACCOUNTS,
  error: 'invalid_credentials',
}
const LEKAR = {
  authenticated: true,
  user: { id: 'demo-lekar', username: 'ukazka.lekar', role: 'clinician' },
  csrfToken: 'csrf-demo-lekar',
  demoAccounts: ACCOUNTS,
  demoView: 'lekar',
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

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  localStorage.clear()
  sessionStorage.clear()
  resetBootCache()
})
afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals() })

describe('stale cookie session handoff', () => {
  it('retains validated anonymous capabilities from a 401', async () => {
    backendEnv()
    stubFetch(url => (url === '/api/v1/auth/session' ? jsonResponse(STALE_401, 401) : jsonResponse({}, 404)))
    expect(await fetchAuthSession()).toEqual({ ok: true, value: { authenticated: false, demoAccounts: ACCOUNTS } })
    cleanup()
    stubFetch(url => (url === '/api/v1/auth/session' ? jsonResponse({ error: 'invalid_credentials' }, 401) : jsonResponse({}, 404)))
    expect(await fetchAuthSession()).toEqual({ ok: true, value: { authenticated: false } })
    cleanup()
    stubFetch(url => (url === '/api/v1/auth/session' ? new Response(null, { status: 401 }) : jsonResponse({}, 404)))
    expect(await fetchAuthSession()).toEqual({ ok: true, value: { authenticated: false } })
  })
  it('fails unavailable on malformed metadata or authenticated claims', async () => {
    backendEnv()
    stubFetch(url => (url === '/api/v1/auth/session' ? jsonResponse({ authenticated: false, demoAccounts: ['nope'] }, 401) : jsonResponse({}, 404)))
    expect(await fetchAuthSession()).toMatchObject({ ok: false, error: { kind: 'unavailable' } })
    cleanup()
    stubFetch(url => (url === '/api/v1/auth/session' ? jsonResponse(LEKAR, 401) : jsonResponse({}, 404)))
    expect(await fetchAuthSession()).toMatchObject({ ok: false, error: { kind: 'unavailable' } })
  })
  it('mount with a stale cookie shows four demo buttons and demo login creates a real session', async () => {
    backendEnv()
    const requested: string[] = []
    const fetcher = stubFetch((url, init) => {
      requested.push(String(url))
      if (url === '/api/v1/auth/session') return jsonResponse(STALE_401, 401)
      if (url === '/api/v1/auth/demo-login') {
        const account = (JSON.parse(String((init as RequestInit).body)) as { account: string }).account
        expect(account).toBe('lekar')
        return jsonResponse(LEKAR)
      }
      if (url === '/api/v1/session') return jsonResponse(sessionResponse)
      if (url === '/api/v1/workspace') return jsonResponse(workspaceResponse())
      if (url.startsWith('/api/v1/cases/')) return jsonResponse(caseResponse())
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    expect(await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 2, name: 'Přihlášení' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /Pokračovat/ })).toHaveLength(4)
    expect(requested).toEqual(['/api/v1/auth/session'])
    fireEvent.click(screen.getByRole('button', { name: /Lékař/ }))
    expect(await screen.findByText('Přihlášeno: ukazka.lekar')).toBeInTheDocument()
    await waitFor(() => expect(requested).toContain('/api/v1/session'))
    expect(fetcher.mock.calls.map(call => String(call[0]))).toContain('/api/v1/auth/demo-login')
  })
})
