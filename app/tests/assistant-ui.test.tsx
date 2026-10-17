import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import type { Assistant, AssistantRequest, AssistantResult } from '../src/assistant/contracts'
import type { BootstrapResult, Session } from '../src/data/contracts'
import { UnconfiguredAssistant } from '../src/data/backend/assistant'
import { UnconfiguredBackendGateway } from '../src/data/backend/unconfigured'
import { createMockSession } from '../src/data/mock/provider'

const boot = (value: Session): Promise<BootstrapResult> => Promise.resolve({ status: 'session', session: value })
const answer: AssistantResult = { ok: true, value: { provenance: 'server', text: 'Dostupné údaje pacienta.', sources: ['Patient/novak', 'Condition/c'], coverage: { status: 'partial', resources: 21, uploads: 3, failedTypes: ['ImagingStudy'], unreadableAttachments: 2 } } }
function sessionWithAssistant(result = answer) {
  const requests: AssistantRequest[] = []
  const assistant: Assistant = { availability: 'available', provenance: 'server', send: vi.fn(async request => { requests.push(request); return result }) }
  return { session: { ...createMockSession({ delayMs: 0 }), assistant }, requests, send: assistant.send }
}
async function openAssistant(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: 'Asistent' }))
  return screen.getByRole('dialog', { name: 'Asistent' })
}
beforeEach(() => window.history.replaceState(null, '', '/'))
afterEach(() => cleanup())

describe('assistant dialog', { timeout: 15000 }, () => {
  it('unconfigured backend sends nothing and Escape closes/restores focus', async () => {
    const user = userEvent.setup()
    render(<App boot={boot({ mode: 'backend', gateway: new UnconfiguredBackendGateway(), assistant: new UnconfiguredAssistant() })} />)
    const dialog = await openAssistant(user)
    expect(dialog).toHaveAttribute('open')
    expect(within(dialog).getByRole('heading', { name: 'Asistent' })).toHaveFocus()
    expect(within(dialog).queryByRole('textbox')).toBeNull()
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    await waitFor(() => expect(dialog).not.toHaveAttribute('open'))
    expect(screen.getByRole('button', { name: 'Asistent' })).toHaveFocus()
  })
  it('discloses full-record egress before sending and shows server coverage and source labels', async () => {
    const user = userEvent.setup()
    const { session, requests, send } = sessionWithAssistant()
    window.location.hash = 'koordinator/case/novak'
    render(<App boot={boot(session)} />)
    const dialog = await openAssistant(user)
    expect(within(dialog).getByText(/do Azure AI automaticky předá celý dostupný záznam/)).toHaveTextContent(/FHIR, dokumenty a přepisy/)
    expect(within(dialog).queryByRole('checkbox')).toBeNull()
    expect(within(dialog).queryByRole('button', { name: 'Zobrazit údaje' })).toBeNull()
    await user.type(within(dialog).getByLabelText('Váš dotaz'), 'Shrň záznam.')
    expect(send).not.toHaveBeenCalled()
    await user.click(within(dialog).getByRole('button', { name: 'Odeslat dotaz' }))
    await within(dialog).findByText('Dostupné údaje pacienta.')
    expect(requests).toEqual([{ role: 'koordinator', text: 'Shrň záznam.', caseId: 'novak' }])
    expect(within(dialog).getByText(/Pokrytí: částečné/)).toHaveTextContent('FHIR záznamy: 21 · Nahrané soubory: 3.')
    expect(within(dialog).getByText(/Nedostupné typy: ImagingStudy/)).toBeInTheDocument()
    expect(within(dialog).getByText(/Serverem předané zdroje:/)).toHaveTextContent('Patient/novak, Condition/c')
    expect(within(dialog).queryAllByRole('link')).toHaveLength(0)
  })
  it.each(['koordinator', 'lekar', 'mdt', 'pacient'] as const)('%s list/overview exposes the assistant in general mode without fallback', async role => {
    const user = userEvent.setup()
    const { session, requests } = sessionWithAssistant({ ok: true, value: { provenance: 'server', text: 'Obecná odpověď.', sources: [], coverage: { status: 'general', resources: 0, uploads: 0, failedTypes: [] } } })
    window.location.hash = role
    render(<App boot={boot(session)} />)
    const dialog = await openAssistant(user)
    expect(within(dialog).getByText(/Není vybrán pacient/)).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('Váš dotaz'), 'Obecný dotaz')
    await user.click(within(dialog).getByRole('button', { name: 'Odeslat dotaz' }))
    await within(dialog).findByText('Obecná odpověď.')
    expect(requests).toEqual([{ role, text: 'Obecný dotaz' }])
    expect(within(dialog).getByText('Obecný dotaz bez záznamu pacienta.')).toBeInTheDocument()
  })
  it.each([
    ['koordinator', 'koordinator/case/novak'], ['lekar', 'lekar/case/novak'],
    ['mdt', 'mdt/case/novak'], ['pacient', 'pacient/record'],
  ] as const)('%s opened case/own record exposes the assistant with the viewed caseId', async (role, route) => {
    const user = userEvent.setup()
    const { session, requests } = sessionWithAssistant()
    const readCase = vi.fn((...args: Parameters<typeof session.gateway.readCase>) => session.gateway.readCase(...args))
    window.location.hash = route
    render(<App boot={boot({ ...session, gateway: { ...session.gateway, readCase } })} />)
    await waitFor(() => expect(readCase).toHaveBeenCalledWith('novak', expect.anything()))
    await act(async () => { await readCase.mock.results[0]!.value })
    const dialog = await openAssistant(user)
    expect(within(dialog).getByText(/Vybraný pacient: novak/)).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('Váš dotaz'), 'Shrň záznam.')
    await user.click(within(dialog).getByRole('button', { name: 'Odeslat dotaz' }))
    await within(dialog).findByText('Dostupné údaje pacienta.')
    expect(requests).toEqual([{ role, text: 'Shrň záznam.', caseId: 'novak' }])
  })
  it('shows a clear context-size error without provider details', async () => {
    const user = userEvent.setup()
    const { session } = sessionWithAssistant({ ok: false, error: { code: 'context_too_large' } })
    window.location.hash = 'lekar/case/novak'
    render(<App boot={boot(session)} />)
    const dialog = await openAssistant(user)
    await user.type(within(dialog).getByLabelText('Váš dotaz'), 'Q')
    await user.click(within(dialog).getByRole('button', { name: 'Odeslat dotaz' }))
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(/záznam vybraného pacienta je příliš rozsáhlý/)
  })
  it('patient default preview never counts as an explicit assistant selection', async () => {
    const user = userEvent.setup()
    const { session, requests } = sessionWithAssistant()
    const readCase = vi.fn((...args: Parameters<typeof session.gateway.readCase>) => session.gateway.readCase(...args))
    window.location.hash = 'pacient'
    render(<App boot={boot({ ...session, gateway: { ...session.gateway, readCase } })} />)
    await waitFor(() => expect(readCase).toHaveBeenCalledWith('novak', expect.anything()))
    const dialog = await openAssistant(user)
    expect(within(dialog).getByText(/Není vybrán pacient/)).toBeInTheDocument()
    await user.type(within(dialog).getByLabelText('Váš dotaz'), 'Obecný dotaz')
    await user.click(within(dialog).getByRole('button', { name: 'Odeslat dotaz' }))
    await within(dialog).findByText('Dostupné údaje pacienta.')
    expect(requests).toEqual([{ role: 'pacient', text: 'Obecný dotaz' }])
  })
  it('keeps send focus while pending, blocks repeats, and supports stop', async () => {
    const user = userEvent.setup()
    const base = createMockSession({ delayMs: 0 })
    let resolve!: (result: AssistantResult) => void
    const send = vi.fn(() => new Promise<AssistantResult>(done => { resolve = done }))
    render(<App boot={boot({ ...base, assistant: { availability: 'available', provenance: 'server', send } })} />)
    const dialog = await openAssistant(user)
    await user.type(within(dialog).getByLabelText('Váš dotaz'), 'Q')
    const submit = within(dialog).getByRole('button', { name: 'Odeslat dotaz' })
    await user.click(submit)
    expect(submit).toHaveFocus()
    expect(submit).toHaveAttribute('aria-disabled', 'true')
    await user.click(submit)
    expect(send).toHaveBeenCalledOnce()
    await user.click(within(dialog).getByRole('button', { name: 'Zastavit' }))
    expect(within(dialog).getByLabelText('Váš dotaz')).toHaveFocus()
    await act(async () => resolve(answer))
    expect(within(dialog).queryByText('Dostupné údaje pacienta.')).toBeNull()
  })
  it('case switch closes and clears the conversation', async () => {
    const user = userEvent.setup()
    const { session } = sessionWithAssistant()
    window.location.hash = 'koordinator/case/novak'
    render(<App boot={boot(session)} />)
    const dialog = await openAssistant(user)
    await user.type(within(dialog).getByLabelText('Váš dotaz'), 'Rozepsaný dotaz')
    await act(async () => { window.location.hash = 'koordinator/case/dusek'; window.dispatchEvent(new HashChangeEvent('hashchange')) })
    fireEvent(dialog, new Event('animationend'))
    await waitFor(() => expect(dialog).not.toHaveAttribute('open'))
    const reopened = await openAssistant(user)
    expect(within(reopened).getByLabelText('Váš dotaz')).toHaveValue('')
    expect(within(reopened).getByText(/Vybraný pacient: dusek/)).toBeInTheDocument()
  })
})
