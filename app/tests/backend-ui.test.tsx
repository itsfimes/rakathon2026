import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import { createBackendSession } from '../src/data/backend/gateway'
import { caseResponse, complete, jsonResponse, resource, sessionResponse, unavailableSection, workspaceResponse } from './backend-fixtures'

afterEach(() => { cleanup(); window.history.replaceState(null, '', '/'); vi.unstubAllGlobals() })
function transport() {
  const raw = caseResponse()
  raw.sections.observations = unavailableSection()
  raw.sections.conditions = complete([{ ...resource('Condition'), code: { text: 'Synthetic supplied condition' } }])
  raw.sections.diagnosticReports = complete([{ ...resource('DiagnosticReport'), code: { text: 'Synthetic supplied report' }, conclusion: 'Synthetic report conclusion' }])
  return vi.fn<typeof fetch>().mockImplementation(async url => {
    const path = String(url)
    if (path.endsWith('/session')) return jsonResponse(sessionResponse)
    if (path.endsWith('/workspace')) return jsonResponse(workspaceResponse())
    if (path.endsWith('/cases/synthetic-0')) return jsonResponse(raw)
    return jsonResponse({ version: 1, error: { code: 'not_found', message: 'Case not found' } }, 404)
  })
}
async function mount(route: string) {
  window.history.replaceState(null, '', `/#${route}`)
  const fetcher = transport()
  const session = await createBackendSession(undefined, fetcher)
  render(<App boot={Promise.resolve({ status: 'session', session })} />)
  await screen.findByText('Atlas')
  return fetcher
}
async function go(route: string) {
  await act(async () => { window.location.hash = `#${route}`; window.dispatchEvent(new HashChangeEvent('hashchange')) })
}
describe('connected backend nullable role views', () => {
  it('assistant stays unavailable against the backend without any remote assistant request', async () => {
    const fetcher = await mount('koordinator')
    await waitFor(() => expect(document.querySelectorAll('tbody tr')).toHaveLength(6))
    fireEvent.click(screen.getByRole('button', { name: 'Asistent' }))
    const panel = screen.getByRole('region', { name: 'Asistent' })
    expect(within(panel).getByText('Asistent není připojen', { selector: '.assistant-empty__title' })).toBeInTheDocument()
    expect(fetcher).toHaveBeenCalledTimes(2)
  })
  it.each(['koordinator', 'lekar', 'mdt'])('%s lists six summaries with unknowns, no invented phase/diagnosis and no case fanout', async role => {
    const fetcher = await mount(role)
    await waitFor(() => expect(document.querySelectorAll('tbody tr')).toHaveLength(6))
    const text = document.querySelector('main')!.textContent!
    expect(text).toContain('Jméno neuvedeno')
    expect(text).toContain('diagnóza neuvedena')
    expect(text).toContain('úsek neuveden')
    expect(text).not.toContain('0 let')
    expect(text).not.toContain('Jan')
    expect(document.querySelector('.mini-steps')).toBeNull()
    expect(fetcher.mock.calls.map(c => c[0])).toEqual(['/api/v1/session', '/api/v1/workspace'])
    expect(screen.queryByRole('button', { name: 'Obnovit demo' })).not.toBeInTheDocument()
  })
  it.each(['koordinator', 'lekar'])('%s opens the exact case, shows independently available facts and no false empty observations', async role => {
    await mount(`${role}/case/synthetic-0/record`)
    expect((await screen.findAllByText('Synthetic supplied report'))[0]).toBeInTheDocument()
    expect(screen.getAllByText(/Synthetic supplied condition/)[0]).toBeInTheDocument()
    expect(screen.getByText('Nepodařilo se načíst: Pozorování, laboratorní výsledky a měření')).toBeInTheDocument()
    expect(screen.getByText(/Laboratorní výsledky nejsou dostupné/)).toBeInTheDocument()
    expect(screen.queryByText('Žádný laboratorní výsledek není v záznamu.')).not.toBeInTheDocument()
    expect(document.querySelector('main')!.textContent).not.toContain('0 let')
  })
  it('patient Co teď stays first, unknown event/contact/journey are honest and explicit patient record carries supplied facts', async () => {
    await mount('pacient')
    expect(await screen.findByText('Další krok zatím není znám.')).toBeInTheDocument()
    expect(screen.getByText('Další termín zde není uveden')).toBeInTheDocument()
    expect(screen.getByText('Průběh zatím není zaznamenán')).toBeInTheDocument()
    expect(screen.getByText('Vaše koordinační centrum')).toBeInTheDocument()
    expect(document.querySelector('.patient')?.firstElementChild?.textContent).toContain('Co teď')
    await go('pacient/record')
    expect(await screen.findByText('Synthetic report conclusion')).toBeInTheDocument()
    expect(screen.getByText('Synthetic supplied condition')).toBeInTheDocument()
    expect(screen.getByText(/Výsledky nejsou dostupné — zdroj pozorování/)).toBeInTheDocument()
  })
  it('MDT cannot fabricate a meeting preparation or recorded plan', async () => {
    await mount('mdt/case/synthetic-0')
    expect(await screen.findByText('Příprava porady není k dispozici')).toBeInTheDocument()
    expect(screen.queryByText(/Podklady doložené před/)).not.toBeInTheDocument()
    await go('mdt/case/synthetic-0/plan')
    expect(await screen.findByText('Žádný závěr ani plán není zaznamenán.')).toBeInTheDocument()
  })
  it('unknown case stays not found rather than render default data', async () => {
    await mount('koordinator/case/synthetic-unknown')
    await waitFor(() => expect(document.querySelector('main')?.textContent).toContain('Případ nebyl nalezen'))
    expect(screen.queryByText('Synthetic supplied condition')).not.toBeInTheDocument()
  })
})
