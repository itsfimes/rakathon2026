import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import type { BootstrapResult, Gateway, Session } from '../src/data/contracts'
import { createMockSession } from '../src/data/mock/provider'
import { routeHref } from '../src/lib/routes'

const boot = (session: Session): Promise<BootstrapResult> => Promise.resolve({ status: 'session', session })
async function go(hash: string) {
  await act(async () => {
    window.history.replaceState({}, '', `/#${hash}`)
    window.dispatchEvent(new PopStateEvent('popstate'))
  })
}
function trackedSession() {
  const base = createMockSession({ delayMs: 0 })
  const readCase = vi.fn((id: string, signal?: AbortSignal) => base.gateway.readCase(id, signal))
  const gateway: Gateway = { ...base.gateway, readCase }
  return { session: { ...base, gateway }, readCase }
}
beforeEach(() => window.history.replaceState(null, '', '/'))
afterEach(() => cleanup())

describe('mechanical section route integration', () => {
  it.each(['koordinator', 'lekar'] as const)('%s sections read only the exact case once and focus on same-role section navigation', async view => {
    const { session, readCase } = trackedSession()
    window.history.replaceState(null, '', `/${routeHref({ view, page: 'detail', caseId: 'simkova', section: 'record' })}`)
    render(<App boot={boot(session)} />)
    await screen.findByText(/Alena Šimková · 64 let/)
    expect(readCase.mock.calls.map(call => call[0])).toEqual(['simkova'])
    for (const section of ['care', 'person', 'overview'] as const) {
      document.getElementById(`t-${view}`)!.blur()
      await go(routeHref({ view, page: 'detail', caseId: 'simkova', section }).slice(1))
      await waitFor(() => expect(document.getElementById(`t-${view}`)).toHaveFocus())
      expect(readCase.mock.calls.map(call => call[0])).toEqual(['simkova'])
      expect(document.body.textContent).not.toContain('Jan Novák')
    }
  })

  it.each(['koordinator', 'lekar', 'mdt', 'koordinator/case/novak/unknown', 'lekar/case/novak/record/extra', 'pacient/unknown', 'mdt/unknown', 'mdt/plan', 'specimen/unknown'])('%s never reads or defaults a case', async hash => {
    const { session, readCase } = trackedSession()
    window.history.replaceState(null, '', `/#${hash}`)
    render(<App boot={boot(session)} />)
    await screen.findByText('Atlas')
    if (hash.includes('/')) {
      expect(await screen.findByRole('alert')).toHaveTextContent(/Neplatný odkaz|Neznámá sekce/)
      expect(document.body.textContent).not.toContain('Jan Novák')
    } else await screen.findByRole('link', { name: 'Jan Novák' })
    expect(readCase).not.toHaveBeenCalled()
  })

  it.each(['pacient/record', 'mdt/case/novak', 'mdt/case/novak/plan'])('direct %s uses one existing case read, not a new snapshot request', async hash => {
    const { session, readCase } = trackedSession()
    window.history.replaceState(null, '', `/#${hash}`)
    render(<App boot={boot(session)} />)
    await waitFor(() => expect(readCase.mock.calls.map(call => call[0])).toEqual(['novak']))
    await screen.findByRole('heading', { level: 1, name: hash.startsWith('pacient') ? /Pan Novák: moje zdravotní údaje/ : hash.endsWith('/plan') ? 'MDT: zaznamenaný plán po poradě' : 'MDT: příprava porady 21. 10. 2026' })
  })

  it('patient record preserves the clinician preview and an explicit matching MDT plan avoids duplicate case reads', async () => {
    const { session, readCase } = trackedSession()
    window.history.replaceState(null, '', '/#lekar/case/simkova/person')
    render(<App boot={boot(session)} />)
    await screen.findByText(/Alena Šimková · 64 let/)
    await go('pacient/record')
    expect(await screen.findByRole('heading', { level: 1, name: /Paní Šimková/ })).toBeInTheDocument()
    await go('mdt/case/simkova/plan')
    expect(await screen.findByText(/Alena Šimková · 64 let/)).toBeInTheDocument()
    expect(readCase.mock.calls.map(call => call[0])).toEqual(['simkova'])
  })

  it('invalid role subpage has an honest return to its own landing, with no invalid-page case read', async () => {
    const { session, readCase } = trackedSession()
    window.history.replaceState(null, '', '/#pacient/unknown')
    render(<App boot={boot(session)} />)
    const link = await screen.findByRole('link', { name: 'Zpět na hlavní pohled' })
    expect(link).toHaveAttribute('href', '#pacient')
    expect(readCase).not.toHaveBeenCalled()
    await act(async () => link.click())
    expect(window.location.hash).toBe('#pacient')
    expect(await screen.findByRole('heading', { level: 1, name: /Pan Novák/ })).toBeInTheDocument()
    expect(readCase.mock.calls.map(call => call[0])).toEqual(['novak'])
  })
})
