import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginBoundary } from '../src/auth/LoginBoundary'
import { fetchAuthSession, loginRequest, logoutRequest } from '../src/auth/client'
import { createRequestScope } from '../src/auth/requestScope'
import { bootOnce, resetBootCache } from '../src/session'
import { jsonResponse, sessionResponse, workspaceResponse } from './backend-fixtures'

const AUTHED = {
  authenticated: true,
  user: { id: 'u-1', username: 'jana.novakova', role: 'viewer' },
  csrfToken: 'csrf-token-abc',
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

const authedFetch = (session = AUTHED) => stubFetch(url => {
  if (url === '/api/v1/auth/session') return jsonResponse(session)
  if (url === '/api/v1/session') return jsonResponse(sessionResponse)
  if (url === '/api/v1/workspace') {
    return jsonResponse({ ...workspaceResponse(), patients: [],
      coverage: { status: 'unavailable', serverTotal: null, reason: 'upstream_unavailable_or_incomplete' } }, 503)
  }
  return jsonResponse({ version: 1, error: { code: 'not_found', message: 'missing' } }, 404)
})

async function loginAs(username = 'jana.novakova', password = PASSWORD) {
  fireEvent.change(screen.getByLabelText(/Přihlašovací jméno/), { target: { value: username } })
  fireEvent.change(screen.getByLabelText(/^Heslo/), { target: { value: password } })
  fireEvent.click(screen.getByRole('button', { name: 'Přihlásit' }))
}

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  localStorage.clear()
  sessionStorage.clear()
  resetBootCache()
})
afterEach(() => { cleanup(); vi.unstubAllEnvs(); vi.unstubAllGlobals() })

describe('auth client contract', () => {
  it('session check treats missing cookie as logged out and expired cookie as logged out', async () => {
    backendEnv()
    stubFetch(url => (url === '/api/v1/auth/session' ? jsonResponse({ authenticated: false }) : jsonResponse({}, 404)))
    expect(await fetchAuthSession()).toEqual({ ok: true, value: { authenticated: false } })
    cleanup()
    stubFetch(url => (url === '/api/v1/auth/session' ? jsonResponse({ error: 'invalid_credentials' }, 401) : jsonResponse({}, 404)))
    expect(await fetchAuthSession()).toEqual({ ok: true, value: { authenticated: false } })
  })
  it('login posts JSON with the marker header, same-origin credentials and no forged Origin', async () => {
    backendEnv()
    const fetcher = stubFetch(() => jsonResponse(AUTHED))
    const result = await loginRequest('jana.novakova', PASSWORD)
    expect(result).toMatchObject({ ok: true, value: { username: 'jana.novakova', csrfToken: 'csrf-token-abc' } })
    const init = fetcher.mock.calls[0]?.[1] as RequestInit & { headers: Record<string, string> }
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/auth/login')
    expect(init.credentials).toBe('same-origin')
    expect(init.headers['X-Rakathon-Auth']).toBe('1')
    expect(init.headers['Content-Type']).toBe('application/json')
    expect(init.headers).not.toHaveProperty('Origin')
    expect(init.headers).not.toHaveProperty('origin')
    expect(JSON.parse(String(init.body))).toEqual({ username: 'jana.novakova', password: PASSWORD })
  })
  it('maps invalid, rate-limited and unavailable login failures without echoing secrets', async () => {
    backendEnv()
    stubFetch(() => jsonResponse({ error: 'invalid_credentials' }, 401))
    expect(await loginRequest('jana.novakova', PASSWORD)).toMatchObject({ ok: false, error: { kind: 'invalid' } })
    cleanup()
    stubFetch(() => new Response(JSON.stringify({ error: 'rate_limited' }), { status: 429, headers: { 'Content-Type': 'application/json', 'Retry-After': '5' } }))
    expect(await loginRequest('jana.novakova', PASSWORD)).toMatchObject({ ok: false, error: { kind: 'limited', retryAfter: '5' } })
    cleanup()
    stubFetch(() => jsonResponse({ error: 'not_configured' }, 503))
    const failed = await loginRequest('jana.novakova', PASSWORD)
    expect(failed).toMatchObject({ ok: false, error: { kind: 'unavailable' } })
    expect(JSON.stringify(failed)).not.toContain(PASSWORD)
  })
  it('logout sends the CSRF header and treats revocation as success', async () => {
    backendEnv()
    const fetcher = stubFetch(() => new Response(null, { status: 204 }))
    expect(await logoutRequest('csrf-token-abc')).toEqual({ ok: true, value: null })
    const init = fetcher.mock.calls[0]?.[1] as RequestInit & { headers: Record<string, string> }
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/auth/logout')
    expect(init.headers['X-CSRF-Token']).toBe('csrf-token-abc')
    expect(init.credentials).toBe('same-origin')
  })
})

describe('login gate', () => {
  it('shows login first with zero clinical requests', async () => {
    backendEnv()
    const fetcher = stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse({ authenticated: false })
      throw new Error(`clinical request before login: ${url}`)
    })
    render(<LoginBoundary />)
    expect(await screen.findByRole('heading', { level: 2, name: 'Přihlášení' })).toBeInTheDocument()
    expect(fetcher).toHaveBeenCalledTimes(1)
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/auth/session')
  })
  it('signed-in clinical outage keeps identity and logout, never loops to login', async () => {
    backendEnv()
    const fetcher = authedFetch()
    render(<LoginBoundary />)
    expect(await screen.findByText('Přihlášeno: jana.novakova')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Odhlásit' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2, name: 'Přihlášení' })).toBeNull()
    expect(await screen.findByText('Data se nepodařilo načíst')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: 'Přihlášení' })).getByText(/Přihlášení ověřuje server/)).toBeInTheDocument()
    expect(fetcher.mock.calls.map(call => String(call[0]))).toContain('/api/v1/auth/session')
  })
  it('bad credentials show a generic error without enumeration', async () => {
    backendEnv()
    stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse({ authenticated: false })
      if (url === '/api/v1/auth/login') return jsonResponse({ error: 'invalid_credentials' }, 401)
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByRole('heading', { level: 2, name: 'Přihlášení' })
    await loginAs()
    expect(await screen.findByRole('alert')).toHaveTextContent('Přihlášení se nezdařilo. Zkontrolujte jméno a heslo a zkuste to znovu.')
    expect(document.body.textContent).not.toContain('neexistuje')
    expect(screen.queryByText('Přihlášeno: jana.novakova')).toBeNull()
  })
  it('logout clears clinical data, aborts inflight work and shows login', async () => {
    backendEnv()
    let aborted = false
    const requested: string[] = []
    const fetcher = stubFetch((url, init) => {
      requested.push(url)
      if (url === '/api/v1/auth/session') return jsonResponse(AUTHED)
      if (url === '/api/v1/session') return jsonResponse(sessionResponse)
      if (url === '/api/v1/workspace') {
        return new Promise<Response>((_, reject) => {
          init.signal?.addEventListener('abort', () => {
            aborted = true
            reject(new DOMException('aborted', 'AbortError'))
          })
        })
      }
      if (url === '/api/v1/auth/logout') return new Response(null, { status: 204 })
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByText('Přihlášeno: jana.novakova')
    await waitFor(() => expect(requested).toContain('/api/v1/workspace'))
    fireEvent.click(screen.getByRole('button', { name: 'Odhlásit' }))
    const confirm = await screen.findByRole('dialog', { name: 'Opravdu se chcete odhlásit?' })
    fireEvent.click(within(confirm).getByRole('button', { name: 'Zrušit' }))
    expect(confirm).not.toHaveAttribute('open')
    expect(screen.getByText('Přihlášeno: jana.novakova')).toBeInTheDocument()
    expect(fetcher.mock.calls.map(call => String(call[0]))).not.toContain('/api/v1/auth/logout')
    fireEvent.click(screen.getByRole('button', { name: 'Odhlásit' }))
    const reconfirm = await screen.findByRole('dialog', { name: 'Opravdu se chcete odhlásit?' })
    fireEvent.click(within(reconfirm).getByRole('button', { name: 'Odhlásit se' }))
    expect(await screen.findByRole('heading', { level: 2, name: 'Přihlášení' })).toBeInTheDocument()
    expect(screen.queryByText('Přihlášeno: jana.novakova')).toBeNull()
    await waitFor(() => expect(aborted).toBe(true))
    const logout = fetcher.mock.calls.find(call => String(call[0]) === '/api/v1/auth/logout')
    expect((logout?.[1] as RequestInit & { headers: Record<string, string> }).headers['X-CSRF-Token']).toBe('csrf-token-abc')
  })
  it('failed logout hides data, warns and offers retry', async () => {
    backendEnv()
    let logoutCalls = 0
    stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse(AUTHED)
      if (url === '/api/v1/session') return jsonResponse(sessionResponse)
      if (url === '/api/v1/workspace') return jsonResponse(workspaceResponse())
      if (url === '/api/v1/auth/logout') {
        logoutCalls += 1
        if (logoutCalls === 1) return Promise.reject(new Error('network down'))
        return new Response(null, { status: 204 })
      }
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByText('Přihlášeno: jana.novakova')
    fireEvent.click(screen.getByRole('button', { name: 'Odhlásit' }))
    const failedConfirm = await screen.findByRole('dialog', { name: 'Opravdu se chcete odhlásit?' })
    fireEvent.click(within(failedConfirm).getByRole('button', { name: 'Odhlásit se' }))
    const warning = await screen.findByRole('alert')
    expect(warning).toHaveTextContent('Odhlášení se na serveru nepodařilo potvrdit')
    expect(screen.queryByText('Přihlášeno: jana.novakova')).toBeNull()
    expect(screen.getByRole('heading', { level: 2, name: 'Přihlášení' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Zkusit znovu' }))
    await waitFor(() => expect(logoutCalls).toBe(2))
    await waitFor(() => expect(screen.queryByText(/Odhlášení se na serveru nepodařilo/)).toBeNull())
  })
  it('expired clinical session returns to login while denied access keeps the session', async () => {
    backendEnv()
    const expired = stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse(AUTHED)
      if (url === '/api/v1/session') return jsonResponse(sessionResponse)
      if (url === '/api/v1/workspace') return jsonResponse({ error: 'auth_failed' }, 401)
      if (url.startsWith('/api/v1/cases/')) return jsonResponse({ error: 'auth_failed' }, 401)
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByText('Přihlášeno: jana.novakova')
    await waitFor(() => expect(screen.getByRole('heading', { level: 2, name: 'Přihlášení' })).toBeInTheDocument())
    expect(screen.getByText('Relace vypršela. Přihlaste se prosím znovu.')).toBeInTheDocument()
    expect(expired.mock.calls.map(call => String(call[0]))).not.toContain('/api/v1/auth/logout')
    cleanup()
    stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse(AUTHED)
      if (url === '/api/v1/session') return jsonResponse(sessionResponse)
      if (url === '/api/v1/workspace') return jsonResponse({ error: 'denied' }, 403)
      if (url.startsWith('/api/v1/cases/')) return jsonResponse({ error: 'denied' }, 403)
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByText('Přihlášeno: jana.novakova')
    expect(await screen.findByText('Data se nepodařilo načíst')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2, name: 'Přihlášení' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Odhlásit' })).toBeInTheDocument()
  })
  it('stale answers lose to newer requests and pending blocks double posts', async () => {
    const scope = createRequestScope()
    const seen: string[] = []
    const first = scope.begin()
    const second = scope.begin()
    first(() => { seen.push('first') })
    second(() => { seen.push('second') })
    expect(seen).toEqual(['second'])
    backendEnv()
    let logins = 0
    stubFetch(url => {
      if (url === '/api/v1/auth/session') return jsonResponse({ authenticated: false })
      if (url === '/api/v1/auth/login') {
        logins += 1
        return new Promise<Response>(() => {})
      }
      throw new Error(`unexpected ${url}`)
    })
    render(<LoginBoundary />)
    await screen.findByRole('heading', { level: 2, name: 'Přihlášení' })
    const form = screen.getByLabelText('Přihlašovací formulář') as HTMLFormElement
    fireEvent.change(screen.getByLabelText(/Přihlašovací jméno/), { target: { value: 'jana.novakova' } })
    fireEvent.change(screen.getByLabelText(/^Heslo/), { target: { value: PASSWORD } })
    fireEvent.submit(form)
    fireEvent.submit(form)
    await waitFor(() => expect(screen.getByRole('button', { name: 'Ověřování…' })).toBeDisabled())
    expect(logins).toBe(1)
  })
  it('role views never change the server role and storage stays clear of secrets', async () => {
    backendEnv()
    authedFetch()
    render(<LoginBoundary />)
    await screen.findByText('Přihlášeno: jana.novakova')
    for (const hash of ['#lekar', '#mdt', '#pacient']) {
      window.location.hash = hash
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    }
    await waitFor(() => expect(screen.getByText('Přihlášeno: jana.novakova')).toBeInTheDocument())
    expect(document.body.textContent).not.toMatch(/Role (admin|koordinator|lekar|mdt)/)
    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(window.location.hash).not.toContain('csrf')
    expect(document.cookie).not.toContain('csrf-token')
  })
  it('mock mode stays an unlabeled demo with no auth network', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'mock')
    vi.stubEnv('VITE_BACKEND_API_BASE', undefined)
    const fetcher = stubFetch(url => { throw new Error(`network used in mock mode: ${url}`) })
    render(<LoginBoundary />)
    expect(await screen.findByText('DEMO · SYNTETICKÁ DATA · bez backendu')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2, name: 'Přihlášení' })).toBeNull()
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('unconfigured backend fails closed with a descriptive error and no requests', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'backend')
    vi.stubEnv('VITE_BACKEND_API_BASE', undefined)
    const fetcher = stubFetch(url => { throw new Error(`request while unconfigured: ${url}`) })
    render(<LoginBoundary />)
    expect(await screen.findByText('Backend · není nakonfigurován')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2, name: 'Přihlášení' })).toBeNull()
    expect(fetcher).not.toHaveBeenCalled()
  })
  it('boot cache resets so the next user never inherits clinical data', () => {
    const first = bootOnce()
    expect(bootOnce()).toBe(first)
    resetBootCache()
    expect(bootOnce()).not.toBe(first)
    resetBootCache()
  })
})
