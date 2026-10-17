import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import type { Assistant, AssistantRequest, AssistantResult } from '../src/assistant/contracts'
import { ASSISTANT_PROMPTS } from '../src/assistant/prompts'
import type { BootstrapResult, Session } from '../src/data/contracts'
import { UnconfiguredAssistant } from '../src/data/backend/assistant'
import { UnconfiguredBackendGateway } from '../src/data/backend/unconfigured'
import { createMockSession } from '../src/data/mock/provider'

const boot = (value: Session): Promise<BootstrapResult> => Promise.resolve({ status: 'session', session: value })

function spyMock() {
  const base = createMockSession({ delayMs: 0 })
  const requests: AssistantRequest[] = []
  const assistant: Assistant = {
    availability: 'available', provenance: 'scripted',
    send: vi.fn((request: AssistantRequest, signal: AbortSignal): Promise<AssistantResult> => { requests.push(request); return base.assistant.send(request, signal) }),
  }
  return { session: { ...base, assistant }, requests, send: assistant.send }
}

async function openAssistant(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: 'Asistent' }))
  return screen.getByRole('region', { name: 'Asistent' })
}

beforeEach(() => window.history.replaceState(null, '', '/'))
afterEach(() => cleanup())

describe('assistant panel', { timeout: 15000 }, () => {
  it('backend default: opens inline, says not connected, sends nothing', async () => {
    const user = userEvent.setup()
    render(<App boot={boot({ mode: 'backend', gateway: new UnconfiguredBackendGateway(), assistant: new UnconfiguredAssistant() })} />)
    const trigger = await screen.findByRole('button', { name: 'Asistent' })
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    const panel = await openAssistant(user)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(within(panel).getByRole('heading', { name: 'Asistent' })).toBeInTheDocument()
    expect(within(panel).getAllByText(/Asistent není připojen/).length).toBeGreaterThan(0)
    // Unavailable: a plain explanation, no disabled chat scaffold and no "loading" wording.
    expect(within(panel).queryByRole('textbox')).toBeNull()
    expect(within(panel).queryByRole('checkbox')).toBeNull()
    expect(within(panel).queryByRole('button', { name: /Vložit|Odeslat/ })).toBeNull()
    expect(within(panel).getByText(/není nakonfigurován, proto tu nejde nic odeslat/)).toBeInTheDocument()
    expect(panel.textContent).not.toMatch(/načít/)
    await user.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByLabelText('Váš dotaz')).toBeNull()
  })

  it('typing and opting into context never send; preview is the exact payload', async () => {
    const user = userEvent.setup()
    const { session, requests, send } = spyMock()
    window.location.hash = 'koordinator/case/novak'
    render(<App boot={boot(session)} />)
    await screen.findByRole('heading', { level: 2, name: /Jan Novák · 60 let/ })
    const panel = await openAssistant(user)
    await user.type(within(panel).getByLabelText('Váš dotaz'), 'ahoj')
    await user.click(within(panel).getByRole('checkbox', { name: 'Připojit údaje případu' }))
    expect(send).not.toHaveBeenCalled()
    await user.click(within(panel).getByRole('button', { name: 'Zobrazit údaje' }))
    await waitFor(() => expect(within(panel).getByRole('heading', { name: /Údaje k připojení/ })).toHaveFocus())
    expect(within(panel).getByRole('checkbox')).toBeChecked()
    const preview = within(panel).getAllByRole('definition').map(node => node.textContent)
    expect(preview.length).toBeGreaterThan(0)
    expect(panel.textContent).not.toMatch(/Novák|Jan |C25|let\b/)

    await user.click(within(panel).getByRole('button', { name: 'Zpět ke konverzaci' }))
    await waitFor(() => expect(within(panel).getByRole('button', { name: 'Zobrazit údaje' })).toHaveFocus())
    const prompt = ASSISTANT_PROMPTS.koordinator[0]!
    await user.click(within(panel).getByRole('button', { name: `Vložit do pole: „${prompt}“` }))
    expect(within(panel).getByLabelText('Váš dotaz')).toHaveValue(prompt)
    expect(within(panel).getByLabelText('Váš dotaz')).toHaveFocus()
    expect(send).not.toHaveBeenCalled()
    await user.click(within(panel).getByRole('button', { name: 'Odeslat dotaz' }))
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1))
    expect(requests[0]!.context!.fields.map(field => field.value)).toEqual(preview)
    const log = await within(panel).findByRole('list', { name: 'Konverzace' })
    expect(within(log).getByText(/Pouze opis dodaných údajů/)).toBeInTheDocument()
    expect(panel.textContent).not.toContain('RAKATHON_SCRIPTED_ASSISTANT_V1')
    expect(within(panel).getByText(/^Zdroj: /)).toBeInTheDocument()
    expect(within(panel).queryAllByRole('link')).toHaveLength(0)
  })

  it('free text without context is answered with the unsupported-dotaz reply; collapsing clears the conversation', async () => {
    const user = userEvent.setup()
    const { session } = spyMock()
    window.location.hash = 'pacient'
    render(<App boot={boot(session)} />)
    await screen.findByRole('heading', { level: 1, name: /co vás čeká/ })
    const trigger = screen.getByRole('button', { name: 'Asistent' })
    let panel = await openAssistant(user)
    await user.type(within(panel).getByLabelText('Váš dotaz'), 'Kdy budou výsledky?')
    await user.click(within(panel).getByRole('button', { name: 'Odeslat dotaz' }))
    expect(await within(panel).findByText(/Tento volný dotaz asistent nepodporuje/)).toBeInTheDocument()
    expect(within(panel).getByRole('status')).toHaveTextContent('Odpověď 1 je připravena v konverzaci.')
    expect(within(panel).getByRole('status')).not.toHaveFocus()
    expect(within(panel).getByRole('list', { name: 'Konverzace' }).closest('[role="status"],[aria-live]')).toBeNull()
    await user.click(trigger)
    panel = await openAssistant(user)
    expect(within(panel).queryByText('Kdy budou výsledky?')).toBeNull()
  })

  it('pending keeps focus on the initiating control, blocks repeats, and completes without moving focus', async () => {
    const user = userEvent.setup()
    const base = createMockSession({ delayMs: 0 })
    const releases: Array<() => void> = []
    const send = vi.fn((request: AssistantRequest, signal: AbortSignal) => new Promise<AssistantResult>(resolve => {
      releases.push(() => resolve(base.assistant.send(request, signal)))
    }))
    window.location.hash = 'pacient'
    render(<App boot={boot({ ...base, assistant: { availability: 'available', provenance: 'scripted', send } })} />)
    await screen.findByRole('heading', { level: 1, name: /co vás čeká/ })
    const panel = await openAssistant(user)
    await user.click(within(panel).getByRole('button', { name: /^Vložit do pole: / }))
    const prompt = within(panel).getByRole('button', { name: 'Odeslat dotaz' })
    await user.click(prompt)
    expect(prompt).toHaveFocus()
    expect(prompt).toHaveAttribute('aria-disabled', 'true')
    expect(prompt).not.toBeDisabled()
    expect(within(panel).getByRole('status')).toHaveTextContent('Čeká se na odpověď…')
    await user.click(prompt)
    await user.keyboard('{Enter}')
    expect(send).toHaveBeenCalledTimes(1)
    await act(async () => { releases[0]!() })
    expect(await within(panel).findByText(/Odpověď 1 je připravena v konverzaci/)).toBeInTheDocument()
    expect(prompt).toHaveFocus()
    expect(within(panel).queryByRole('button', { name: /^Vložit do pole: / })).toBeNull()

    // Free text: the submit button keeps focus while the input clears and the request runs.
    await user.type(within(panel).getByLabelText('Váš dotaz'), 'Kdy?')
    const submit = within(panel).getByRole('button', { name: 'Odeslat dotaz' })
    await user.click(submit)
    expect(submit).toHaveFocus()
    expect(submit).not.toBeDisabled()
    expect(submit).toHaveAttribute('aria-disabled', 'true')
    await user.click(submit)
    expect(send).toHaveBeenCalledTimes(2)
    const stop = within(panel).getByRole('button', { name: 'Zastavit' })
    await user.click(stop)
    // Stop exists only while a request runs; focus moves to the input instead of the vanished button.
    expect(within(panel).queryByRole('button', { name: 'Zastavit' })).toBeNull()
    expect(within(panel).getByLabelText('Váš dotaz')).toHaveFocus()
    expect(within(panel).getByRole('status')).toHaveTextContent('Dotaz byl zastaven')
    const clear = within(panel).getByRole('button', { name: 'Vymazat konverzaci' })
    await user.click(clear)
    expect(clear).toHaveFocus()
    expect(clear).toHaveAttribute('aria-disabled', 'true')
    expect(send).toHaveBeenCalledTimes(2)
  })

  it('sending from the context inspection switches back to the conversation; pending and reply visible, focus stays on send', async () => {
    const user = userEvent.setup()
    const base = createMockSession({ delayMs: 0 })
    const releases: Array<() => void> = []
    const requests: AssistantRequest[] = []
    const send = vi.fn((request: AssistantRequest, signal: AbortSignal) => new Promise<AssistantResult>(resolve => {
      requests.push(request)
      releases.push(() => resolve(base.assistant.send(request, signal)))
    }))
    window.location.hash = 'koordinator/case/novak'
    render(<App boot={boot({ ...base, assistant: { availability: 'available', provenance: 'scripted', send } })} />)
    await screen.findByRole('heading', { level: 2, name: /Jan Novák · 60 let/ })
    const panel = await openAssistant(user)
    await user.click(within(panel).getByRole('checkbox', { name: 'Připojit údaje případu' }))
    const inspect = within(panel).getByRole('button', { name: 'Zobrazit údaje' })
    await user.click(inspect)
    await user.click(within(panel).getByRole('button', { name: 'Zpět ke konverzaci' }))
    await waitFor(() => expect(inspect).toHaveFocus())
    await user.click(inspect)
    expect(within(panel).getByRole('heading', { name: /Údaje k připojení/ })).toBeInTheDocument()
    await waitFor(() => expect(within(panel).getByRole('heading', { name: /Údaje k připojení/ })).toHaveFocus())
    await user.type(within(panel).getByLabelText('Váš dotaz'), ASSISTANT_PROMPTS.koordinator[0]!)
    const submit = within(panel).getByRole('button', { name: 'Odeslat dotaz' })
    await user.click(submit)
    expect(within(panel).queryByRole('heading', { name: /Údaje k připojení/ })).toBeNull()
    expect(within(panel).getByRole('status')).toHaveTextContent('Čeká se na odpověď…')
    expect(submit).toHaveFocus()
    await user.click(submit)
    expect(send).toHaveBeenCalledTimes(1)
    expect(requests[0]!.context).toBeDefined()
    await act(async () => { releases[0]!() })
    const log = await within(panel).findByRole('list', { name: 'Konverzace' })
    expect(within(log).getByText(/Pouze opis dodaných údajů/)).toBeInTheDocument()
    expect(submit).toHaveFocus()
    expect(within(panel).getByRole('checkbox')).toBeChecked()
  })

  it('a route change clears the assistant; the new page heading keeps focus', async () => {
    const user = userEvent.setup()
    const { session } = spyMock()
    window.location.hash = 'koordinator/case/novak'
    render(<App boot={boot(session)} />)
    await screen.findByRole('heading', { level: 2, name: /Jan Novák · 60 let/ })
    const panel = await openAssistant(user)
    await user.click(within(panel).getByRole('checkbox'))
    await user.type(within(panel).getByLabelText('Váš dotaz'), 'x')
    await act(async () => {
      window.location.hash = 'koordinator/case/dusek'
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'Koordinátor: detail případu' })).toHaveFocus())
    expect(screen.getByRole('button', { name: 'Asistent' })).not.toHaveFocus()
    await screen.findByRole('heading', { level: 2, name: /Tomáš Dušek/ })
    const cleared = screen.getByRole('region', { name: 'Asistent' })
    expect(within(cleared).getByLabelText('Váš dotaz')).toHaveValue('')
    expect(within(cleared).getByRole('checkbox')).not.toBeChecked()
  })

  it('demo reset clears the conversation and context immediately and returns the detail to its list', async () => {
    const user = userEvent.setup()
    const { session } = spyMock()
    window.location.hash = 'koordinator/case/novak'
    render(<App boot={boot(session)} />)
    await screen.findByRole('heading', { level: 2, name: /Jan Novák · 60 let/ })
    const panel = await openAssistant(user)
    await waitFor(() => expect(within(panel).getByRole('checkbox')).toBeEnabled())
    await user.click(within(panel).getByRole('checkbox'))
    await user.type(within(panel).getByLabelText('Váš dotaz'), 'y')
    act(() => { screen.getByRole('button', { name: 'Obnovit demo' }).click() })
    expect(within(panel).queryByLabelText('Váš dotaz')?.getAttribute('value') ?? '').toBe('')
    expect(window.location.hash).toBe('#koordinator')
    expect(await screen.findByRole('heading', { level: 1, name: 'Koordinátor: fronta případů' })).toBeInTheDocument()
  })
})
