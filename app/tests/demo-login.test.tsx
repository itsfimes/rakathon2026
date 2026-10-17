import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginBoundary } from '../src/auth/LoginBoundary'
import { authSessionFrom } from '../src/auth/contracts'
import { demoLoginRequest } from '../src/auth/client'
import { caseResponse, jsonResponse, sessionResponse, workspaceResponse } from './backend-fixtures'

const ACCOUNTS = ['koordinator', 'lekar', 'mdt', 'pacient']
const ANON = { authenticated: false, demoAccounts: ACCOUNTS }
const LEKAR = {
  authenticated: true,
  user: { id: 'demo-lekar', username: 'ukazka.lekar', role: 'clinician' },
  csrfToken: 'csrf-demo',
  demoAccounts: ACCOUNTS,
  demoView: 'lekar',
}
const PASSWORD = 'synteticke-heslo-pro-test'

function backendEnv() {
  vi.stubEnv('VITE_DATA_MODE', 'backend')
  vi.stubEnv('VITE_BACKEND_API_BASE', '/api/v1')
}

function stubFetch(handler: (url: string, init: RequestInit) => Response | Promise<Response>) {
  const fetcher = vi.fn(async (input: unknown, init?: RequestInit) => handler(String(input), init ?? {}))
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}

function clinicalFetch(authBody: unknown = LEKAR, initialSession: unknown = ANON) {
  return stubFetch(url => {
    if (url === '/api/v1/auth/session') return jsonResponse(initialSession)
    if (url === '/api/v1/auth/demo-login') return jsonResponse(authBody)
    if (url === '/api/v1/auth/login') return jsonResponse(authBody)
    if (url === '/api/v1/session') return jsonResponse(sessionResponse)
    if (url === '/api/v1/workspace') return jsonResponse(workspaceResponse())
    if (url.startsWith('/api/v1/cases/')) return jsonResponse(caseResponse())
    if (url === '/api/v1/auth/logout') return new Response(null, { status: 204 })
    throw new Error(`unexpected ${url}`)
  })
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals() })

describe('demo capability parsing', () => {
  it('accepts the advertised accounts and the matching locked view', () => {
    expect(authSessionFrom(ANON)).toEqual({ authenticated: false, demoAccounts: ACCOUNTS })
    expect(authSessionFrom(LEKAR)).toMatchObject({ authenticated: true, demoView: 'lekar' })
  })
  it('rejects present malformed accounts and a view outside the advertised set', () => {
    expect(authSessionFrom({ authenticated: false })).toEqual({ authenticated: false })
    expect(authSessionFrom({ authenticated: false, demoAccounts: ['lekar', 'admin'] })).toBeNull()
    expect(authSessionFrom({ authenticated: false, demoAccounts: 'lekar' })).toBeNull()
    expect(authSessionFrom({ authenticated: false, demoAccounts: [] })).toBeNull()
    expect(authSessionFrom({ authenticated: false, demoAccounts: ['lekar', 'lekar'] })).toBeNull()
    expect(authSessionFrom({ authenticated: false, demoAccounts: [1] })).toBeNull()
    expect(authSessionFrom({ authenticated: false, demoAccounts: ['unknown'] })).toBeNull()
    expect(authSessionFrom({ authenticated: false, demoView: 'lekar' })).toBeNull()
    expect(authSessionFrom({ ...LEKAR, demoView: 'pacient', demoAccounts: ['lekar'] })).toBeNull()
    expect(authSessionFrom({ ...LEKAR, demoView: 'admin' })).toBeNull()
    expect(authSessionFrom({ ...LEKAR, demoView: 'lekar', demoAccounts: ['mdt'] })).toBeNull()
    expect(authSessionFrom({ ...LEKAR, demoAccounts: ['lekar', 'admin'] })).toBeNull()
    expect(authSessionFrom({ ...LEKAR, demoAccounts: 'lekar' })).toBeNull()
    expect(authSessionFrom({ ...LEKAR, demoAccounts: [] })).toBeNull()
    expect(authSessionFrom({ ...LEKAR, demoAccounts: ['lekar', 'lekar'] })).toBeNull()
    expect(authSessionFrom({ ...LEKAR, demoView: 1 })).toBeNull()
    expect(authSessionFrom({ ...LEKAR, demoAccounts: ['koordinator', 'lekar', 'mdt', 'pacient'], demoView: 'lekar' })).toMatchObject({ demoView: 'lekar' })
  })
  it('demo login posts exactly the account with the marker header and no secrets', async () => {
    backendEnv()
    const fetcher = stubFetch(() => jsonResponse(LEKAR))
    const result = await demoLoginRequest('lekar')
    expect(result).toMatchObject({ ok: true, value: { username: 'ukazka.lekar', demoView: 'lekar' } })
    const init = fetcher.mock.calls[0]?.[1] as RequestInit & { headers: Record<string, string> }
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/auth/demo-login')
    expect(init.credentials).toBe('same-origin')
    expect(init.headers['X-Rakathon-Auth']).toBe('1')
    expect(JSON.parse(String(init.body))).toEqual({ account: 'lekar' })
    expect(JSON.stringify(result)).not.toContain(PASSWORD)
  })
})

describe('demo role cards at login', () => {
  it('shows four Czech role cards first while the password form stays usable', async () => {
    backendEnv()
    const fetcher = stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse(ANON)
      throw new Error(`clinical request before login: ${url}`)
    })
    render(<LoginBoundary />)
    expect(await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })).toBeInTheDocument()
    for (const name of ['Koordinátor', 'Pacient', 'Lékař', 'MDT']) {
      expect(screen.getByRole('button', { name: new RegExp(name) })).toBeInTheDocument()
    }
    expect(screen.getByLabelText('Přihlašovací formulář')).toBeInTheDocument()
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
  })
  it('hides the cards when the server advertises nothing', async () => {
    backendEnv()
    stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse({ authenticated: false })
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByRole('heading', { level: 2, name: 'Přihlášení' })
    expect(screen.queryByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Lékař/ })).toBeNull()
  })
  it('one click signs in, locks the view and clamps cross-view hashes without extra clinical reads', async () => {
    backendEnv()
    const fetcher = clinicalFetch()
    render(<LoginBoundary />)
    await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })
    fireEvent.click(screen.getByRole('button', { name: /Lékař/ }))
    expect(await screen.findByText('Přihlášeno: ukazka.lekar')).toBeInTheDocument()
    const posted = fetcher.mock.calls.find(call => String(call[0]) === '/api/v1/auth/demo-login')
    expect(JSON.parse(String((posted?.[1] as RequestInit).body))).toEqual({ account: 'lekar' })
    expect(screen.getByText(/Pohled:/)).toHaveTextContent('Lékař')
    expect(screen.queryByRole('navigation', { name: 'Pohled podle role' })).toBeNull()
    expect(window.location.hash).toBe('#lekar')
    await act(async () => {
      window.location.hash = '#pacient/record'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await waitFor(() => expect(window.location.hash).toBe('#lekar'))
    expect(screen.getByText(/Pohled:/)).toHaveTextContent('Lékař')
    expect(fetcher.mock.calls.map(call => String(call[0])).filter(url => url.startsWith('/api/v1/cases/'))).toEqual([])
    expect(document.cookie).not.toContain('csrf-demo')
  })
  it('password login without a locked view keeps a usable default view and no switcher', async () => {
    backendEnv()
    const plain = {
      authenticated: true,
      user: { id: 'u-9', username: 'jana.novakova', role: 'viewer' },
      csrfToken: 'csrf-plain',
      demoAccounts: ACCOUNTS,
    }
    clinicalFetch(plain)
    render(<LoginBoundary />)
    await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })
    fireEvent.change(screen.getByLabelText(/Přihlašovací jméno/), { target: { value: 'jana.novakova' } })
    fireEvent.change(screen.getByLabelText(/^Heslo/), { target: { value: PASSWORD } })
    fireEvent.click(screen.getByRole('button', { name: 'Přihlásit' }))
    expect(await screen.findByText('Přihlášeno: jana.novakova')).toBeInTheDocument()
    expect(await screen.findByText(/Pohled:/)).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Pohled podle role' })).toBeNull()
    expect(await screen.findByText('Backend IRIS · vývojové připojení')).toBeInTheDocument()
  })
  it('logout clears the locked dashboard and offers the cards again', async () => {
    backendEnv()
    clinicalFetch()
    render(<LoginBoundary />)
    await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })
    fireEvent.click(screen.getByRole('button', { name: /Lékař/ }))
    expect(await screen.findByText('Přihlášeno: ukazka.lekar')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Odhlásit' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })).toBeInTheDocument()
    expect(screen.queryByText('Přihlášeno: ukazka.lekar')).toBeNull()
    expect(window.location.hash).toBe('')
  })
})
