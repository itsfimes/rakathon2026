import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createBackendSession } from '../src/data/backend/gateway'
import { createMockSession } from '../src/data/mock/provider'
import type { BootstrapResult } from '../src/data/contracts'
import { DemoEntry } from '../src/features/demo/DemoEntry'
import { caseResponse, jsonResponse, sessionResponse, workspaceResponse } from './backend-fixtures'

const fetcher = vi.fn<typeof fetch>()
beforeEach(() => {
  window.history.replaceState(null, '', '/')
  sessionStorage.clear(); localStorage.clear()
  fetcher.mockReset().mockImplementation(async input => {
    const url = String(input)
    if (url === '/api/v1/session') return jsonResponse(sessionResponse)
    if (url === '/api/v1/workspace') return jsonResponse(workspaceResponse())
    if (url.startsWith('/api/v1/cases/')) return jsonResponse(caseResponse(decodeURIComponent(url.split('/').pop()!)))
    throw new Error(`Unexpected request ${url}`)
  })
})
afterEach(cleanup)
const backendBoot = async (): Promise<BootstrapResult> => ({ status: 'session', session: await createBackendSession(undefined, fetcher) })
const SECRET = 'synthetic-Pa55-not-real'

async function enter(role: string, name = 'kdokoli', password = SECRET) {
  const user = userEvent.setup()
  const nameField = screen.getByLabelText('Jméno (libovolné)')
  const passField = screen.getByLabelText('Heslo (libovolné, nezadávejte skutečné)')
  if (name) await user.type(nameField, name)
  if (password) await user.type(passField, password)
  await user.click(screen.getByRole('radio', { name: new RegExp(role) }))
  await user.keyboard('{Enter}')
  return user
}
const roleNav = () => screen.queryByRole('navigation', { name: 'Pohled podle role' })

describe('demo login entry', { timeout: 30000 }, () => {
  it('shows a clearly labelled demo login with four roles, patient preselected', () => {
    render(<DemoEntry boot={backendBoot()} />)
    expect(screen.getByRole('heading', { name: 'Demo přihlášení' })).toBeInTheDocument()
    expect(screen.getAllByRole('radio')).toHaveLength(4)
    expect(screen.getByRole('radio', { name: /Pacient/ })).toBeChecked()
    expect(roleNav()).toBeNull()
  })
  it.each([['Pacient', 'pacient'], ['Koordinátor', 'koordinator'], ['Lékař', 'lekar'], ['MDT', 'mdt']])('%s entry shows only that role, no role picker', async (label, id) => {
    render(<DemoEntry boot={backendBoot()} />)
    await enter(label)
    expect(roleNav()).toBeNull()
    expect(document.querySelector('main > section.view')!.id).toBe(id)
    expect(window.location.hash).toBe(`#${id}`)
  })
  it('blank name and password still continue; credentials are never stored, logged or sent', async () => {
    const log = vi.spyOn(console, 'log'); const info = vi.spyOn(console, 'info')
    render(<DemoEntry boot={backendBoot()} />)
    await enter('Koordinátor', '', '')
    await screen.findByRole('button', { name: 'Ukončit ukázku' })
    cleanup()
    render(<DemoEntry boot={backendBoot()} />)
    await enter('Lékař', 'jmeno.prijmeni', SECRET)
    await screen.findByRole('button', { name: 'Ukončit ukázku' })
    await waitFor(() => expect(fetcher).toHaveBeenCalled())
    const sent = JSON.stringify(fetcher.mock.calls)
    expect(sent).not.toContain(SECRET)
    expect(sent).not.toContain('jmeno.prijmeni')
    expect(fetcher.mock.calls.some(([url]) => /auth|login/.test(String(url)))).toBe(false)
    expect(fetcher.mock.calls.every(([, init]) => !init?.method || init.method === 'GET')).toBe(true)
    expect(JSON.stringify({ ...localStorage })).not.toContain(SECRET)
    expect(JSON.stringify({ ...sessionStorage })).not.toContain(SECRET)
    expect(document.body.innerHTML).not.toContain(SECRET)
    expect(JSON.stringify([log.mock.calls, info.mock.calls])).not.toContain(SECRET)
  })
  it('a typed hash for another role is redirected back to the chosen role', async () => {
    render(<DemoEntry boot={backendBoot()} />)
    await enter('Pacient')
    await screen.findByRole('button', { name: 'Ukončit ukázku' })
    window.location.hash = '#koordinator'
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await waitFor(() => expect(document.querySelector('main > section.view')!.id).toBe('pacient'))
  })
  it('Ukončit ukázku returns to an empty login and re-entry starts fresh at the role list', async () => {
    render(<DemoEntry boot={backendBoot()} />)
    const user = await enter('Koordinátor')
    await screen.findByRole('button', { name: 'Ukončit ukázku' })
    window.location.hash = '#koordinator/case/synthetic-1'
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await user.click(await screen.findByRole('button', { name: 'Ukončit ukázku' }))
    expect(screen.getByRole('heading', { name: 'Demo přihlášení' })).toBeInTheDocument()
    expect(screen.getByLabelText('Jméno (libovolné)')).toHaveValue('')
    expect(screen.getByLabelText('Heslo (libovolné, nezadávejte skutečné)')).toHaveValue('')
    expect(window.location.hash).toBe('')
    await enter('Lékař')
    await screen.findByRole('button', { name: 'Ukončit ukázku' })
    expect(document.querySelector('main > section.view')!.id).toBe('lekar')
    expect(window.location.hash).toBe('#lekar')
  })
  it('explicit mock mode stays mock behind the demo entry', async () => {
    render(<DemoEntry boot={Promise.resolve({ status: 'session', session: createMockSession() })} />)
    await enter('MDT')
    const bar = await screen.findByRole('banner')
    expect(within(bar).getByRole('button', { name: 'Obnovit demo' })).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('DEMO')
  })
})
