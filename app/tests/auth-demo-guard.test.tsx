import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginBoundary } from '../src/auth/LoginBoundary'
import { authSessionFrom } from '../src/auth/contracts'
import { demoLoginRequest } from '../src/auth/client'
import { jsonResponse } from './backend-fixtures'

const ACCOUNTS = ['koordinator', 'lekar', 'mdt', 'pacient']
const ANON = { authenticated: false, demoAccounts: ACCOUNTS }
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

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals() })

describe('demo contract strictness', () => {
  it('demo login requires the returned view to match the requested account', async () => {
    backendEnv()
    stubFetch(() => jsonResponse({ ...LEKAR, demoView: 'mdt' }))
    await expect(demoLoginRequest('lekar')).resolves.toMatchObject({ ok: false, error: { kind: 'unavailable' } })
    cleanup()
    const noView = { authenticated: true, user: LEKAR.user, csrfToken: LEKAR.csrfToken, demoAccounts: ACCOUNTS }
    stubFetch(() => jsonResponse(noView))
    await expect(demoLoginRequest('lekar')).resolves.toMatchObject({ ok: false, error: { kind: 'unavailable' } })
    cleanup()
    stubFetch(() => jsonResponse({ authenticated: false }))
    await expect(demoLoginRequest('lekar')).resolves.toMatchObject({ ok: false, error: { kind: 'unavailable' } })
    cleanup()
    stubFetch(() => jsonResponse({ ...LEKAR, demoView: 'admin' }))
    await expect(demoLoginRequest('lekar')).resolves.toMatchObject({ ok: false, error: { kind: 'unavailable' } })
    cleanup()
    stubFetch(() => jsonResponse(LEKAR))
    await expect(demoLoginRequest('lekar')).resolves.toMatchObject({ ok: true })
  })
  it('malformed demo payloads never parse', () => {
    expect(authSessionFrom({ authenticated: false, demoAccounts: [] })).toBeNull()
    expect(authSessionFrom({ authenticated: false, demoAccounts: ['lekar', 'lekar'] })).toBeNull()
    expect(authSessionFrom({ authenticated: false, demoAccounts: ['nope'] })).toBeNull()
    expect(authSessionFrom({ authenticated: false, demoAccounts: [null] })).toBeNull()
    expect(authSessionFrom({ authenticated: false, demoView: 'lekar' })).toBeNull()
    expect(authSessionFrom({ ...MDT, demoView: 'lekar', demoAccounts: ['mdt'] })).toBeNull()
    expect(authSessionFrom({ ...MDT, demoView: '' })).toBeNull()
    expect(authSessionFrom({ ...MDT, demoAccounts: [] })).toBeNull()
    expect(authSessionFrom({ ...MDT, demoAccounts: ['mdt', 'mdt'] })).toBeNull()
    expect(authSessionFrom({ ...MDT, demoAccounts: 'mdt' })).toBeNull()
  })
})

describe('shared login in-flight guard', () => {
  it('password then demo in the same tick sends only the password request', async () => {
    backendEnv()
    const fetcher = stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse(ANON)
      if (url === '/api/v1/auth/login') return new Promise<Response>(() => {})
      if (url === '/api/v1/auth/demo-login') return new Promise<Response>(() => {})
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })
    fireEvent.change(screen.getByLabelText(/Přihlašovací jméno/), { target: { value: 'jana.novakova' } })
    fireEvent.change(screen.getByLabelText(/^Heslo/), { target: { value: 'synteticke-heslo-pro-test' } })
    fireEvent.click(screen.getByRole('button', { name: 'Přihlásit' }))
    fireEvent.click(screen.getByRole('button', { name: /Lékař/ }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ověřování…' })).toBeDisabled())
    const authPosts = fetcher.mock.calls.filter(call => String(call[0]) !== '/api/v1/auth/session')
    expect(authPosts).toHaveLength(1)
    expect(String(authPosts[0]?.[0])).toBe('/api/v1/auth/login')
    expect(screen.getByRole('button', { name: /Lékař/ })).toBeDisabled()
  })
  it('demo then password in the same tick sends only the demo request', async () => {
    backendEnv()
    const fetcher = stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse(ANON)
      if (url === '/api/v1/auth/login') return new Promise<Response>(() => {})
      if (url === '/api/v1/auth/demo-login') return new Promise<Response>(() => {})
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })
    fireEvent.click(screen.getByRole('button', { name: /Lékař/ }))
    fireEvent.change(screen.getByLabelText(/Přihlašovací jméno/), { target: { value: 'jana.novakova' } })
    fireEvent.change(screen.getByLabelText(/^Heslo/), { target: { value: 'synteticke-heslo-pro-test' } })
    fireEvent.click(screen.getByRole('button', { name: 'Přihlásit' }))
    await waitFor(() => expect(screen.getByRole('button', { name: /Přihlašování/ })).toBeInTheDocument())
    const authPosts = fetcher.mock.calls.filter(call => String(call[0]) !== '/api/v1/auth/session')
    expect(authPosts).toHaveLength(1)
    expect(String(authPosts[0]?.[0])).toBe('/api/v1/auth/demo-login')
    expect(screen.getByRole('button', { name: 'Přihlásit' })).toBeDisabled()
  })
  it('demo failure shows the demo copy while the password error stays generic', async () => {
    backendEnv()
    stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse(ANON)
      if (url === '/api/v1/auth/demo-login') return jsonResponse({ error: 'not_configured' }, 503)
      if (url === '/api/v1/auth/login') return jsonResponse({ error: 'invalid_credentials' }, 401)
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByRole('heading', { level: 2, name: 'Ukázkové přihlášení' })
    fireEvent.click(screen.getByRole('button', { name: /Lékař/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Ukázkový účet nyní není dostupný. Zkuste to prosím znovu.')
    fireEvent.change(screen.getByLabelText(/Přihlašovací jméno/), { target: { value: 'jana.novakova' } })
    fireEvent.change(screen.getByLabelText(/^Heslo/), { target: { value: 'synteticke-heslo-pro-test' } })
    fireEvent.click(screen.getByRole('button', { name: 'Přihlásit' }))
    await waitFor(() => expect(screen.getAllByRole('alert')).toHaveLength(2))
    const alerts = screen.getAllByRole('alert').map(node => node.textContent)
    expect(alerts).toContain('Přihlášení se nezdařilo. Zkontrolujte jméno a heslo a zkuste to znovu.')
  })
})
