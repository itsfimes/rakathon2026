import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import type { AssistantRequest, AssistantResult } from '../src/assistant/contracts'
import type { AssistantOptions } from '../src/assistant/useAssistant'
import type { BootstrapResult, CaseDetail, Gateway, Result, Session, Workspace } from '../src/data/contracts'
import { success } from '../src/data/contracts'
import { createMockSession } from '../src/data/mock/provider'
import type { ResourceState } from '../src/hooks/useResource'

const resource = vi.hoisted(() => ({ detail: { status: 'idle' } as ResourceState<CaseDetail>, workspace: { status: 'idle' } as ResourceState<Workspace>, options: null as AssistantOptions | null }))
vi.mock('../src/hooks/useCaseData', () => ({
  useCaseDetail: (gateway: Gateway | null, id: string | null) => gateway && id ? resource.detail : { status: 'idle' },
  useWorkspace: (gateway: Gateway | null) => gateway ? resource.workspace : { status: 'idle' },
}))
vi.mock('../src/assistant/useAssistant', async importOriginal => {
  const original = await importOriginal<typeof import('../src/assistant/useAssistant')>()
  return { ...original, useAssistant(options: AssistantOptions) { resource.options = options; return original.useAssistant(options) } }
})

async function setup() {
  const base = createMockSession({ delayMs: 0 })
  const detail = await base.gateway.readCase('novak')
  const workspace = await base.gateway.readWorkspace()
  if (!detail.ok || !workspace.ok) throw new Error('Expected synthetic fixture')
  resource.detail = { status: 'ready', value: detail.value, fresh: true }
  resource.workspace = { status: 'ready', value: workspace.value, fresh: true }
  const pending: { request: AssistantRequest; signal: AbortSignal; resolve: (reply: AssistantResult) => void }[] = []
  const session: Session = { ...base, assistant: { availability: 'available', provenance: 'scripted',
    send: vi.fn((request: AssistantRequest, signal: AbortSignal) => new Promise<AssistantResult>(resolve => pending.push({ request, signal, resolve }))),
  } }
  const boot: Promise<BootstrapResult> = Promise.resolve({ status: 'session', session })
  const app = render(<App boot={boot} />)
  await screen.findByRole('heading', { level: 2, name: /Jan Novák/ })
  return { ...app, detail: detail.value, boot, pending }
}
async function sendPending() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Asistent' }))
  const dialog = screen.getByRole('region', { name: 'Asistent' })
  await user.click(within(dialog).getByRole('checkbox', { name: 'Připojit údaje případu' }))
  fireEvent.change(within(dialog).getByLabelText('Váš dotaz'), { target: { value: 'dotaz' } })
  await user.click(within(dialog).getByRole('button', { name: 'Odeslat dotaz' }))
  fireEvent.change(within(dialog).getByLabelText('Váš dotaz'), { target: { value: 'rozepsáno' } })
  return dialog
}
const reply: AssistantResult = { ok: true, value: { provenance: 'scripted', text: 'LATE IGNORED ANSWER', sources: [] } }
beforeEach(() => {
  window.history.replaceState(null, '', '/#koordinator/case/novak/record')
  resource.detail = { status: 'idle' }; resource.workspace = { status: 'idle' }; resource.options = null
})
afterEach(() => cleanup())

describe('App route/preparation lifecycle identity', () => {
  it('same-route preparation revision clears/aborts assistant and remounts disclosures without changing session/version', async () => {
    const app = await setup()
    const disclosure = document.querySelector('main details')!
    expect(disclosure).not.toBeNull()
    disclosure.setAttribute('open', '')
    const dialog = await sendPending()
    expect(app.pending).toHaveLength(1)
    const before = resource.options!
    expect(before.scopeKey).toContain(app.detail.mdt.preparation!.revision.replaceAll('"', '\\"'))
    resource.detail = { status: 'ready', fresh: true, value: { ...app.detail, mdt: { ...app.detail.mdt, preparation: { ...app.detail.mdt.preparation!, revision: 'same-route-v2' } } } }
    app.rerender(<App boot={app.boot} />)
    expect(resource.options!.session).toBe(before.session)
    expect(resource.options!.version).toBe(before.version)
    expect(resource.options!.scopeKey).not.toBe(before.scopeKey)
    expect(app.pending[0]!.signal.aborted).toBe(true)
    expect(within(dialog).getByLabelText('Váš dotaz')).toHaveValue('')
    expect(within(dialog).getByRole('checkbox')).not.toBeChecked()
    expect(within(dialog).queryByText('dotaz')).toBeNull()
    expect(disclosure.isConnected).toBe(false)
    expect(document.querySelector('main details[open]')).toBeNull()
    await act(async () => app.pending[0]!.resolve(reply))
    expect(dialog.textContent).not.toContain('LATE IGNORED ANSWER')
    expect(app.pending[0]!.request).not.toHaveProperty('scopeKey')
  })

  it('retained preparation is not current/selectable; freshness loss aborts and ignored late responses stay discarded', async () => {
    const app = await setup()
    const dialog = await sendPending()
    resource.detail = { status: 'ready', value: app.detail, fresh: false }
    app.rerender(<App boot={app.boot} />)
    expect(app.pending[0]!.signal.aborted).toBe(true)
    expect(resource.options).toMatchObject({ contextFresh: false, context: null })
    expect(resource.options!.scopeKey).toContain('unavailable')
    expect(document.querySelector('main details')).toBeNull()
    await act(async () => app.pending[0]!.resolve(reply))
    expect(dialog.textContent).not.toContain('LATE IGNORED ANSWER')
    resource.detail = { status: 'ready', value: app.detail, fresh: true }
    app.rerender(<App boot={app.boot} />)
    expect(resource.options!.contextFresh).toBe(true)
    expect(within(dialog).getByRole('checkbox')).not.toBeChecked()
  })

  it('a mismatched ready identity cannot become fresh context or poison the patient preview', async () => {
    const app = await setup()
    resource.detail = { status: 'ready', fresh: true, value: { ...app.detail, identity: { ...app.detail.identity, caseId: 'wrong-case' } } }
    app.rerender(<App boot={app.boot} />)
    expect(resource.options).toMatchObject({ caseId: 'novak', contextFresh: false, context: null })
    await act(async () => {
      window.history.replaceState({}, '', '/#pacient/record')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(resource.options!.caseId).toBe('novak')
    expect(resource.options!.contextFresh).toBe(false)
  })

  it('a local mutation in flight prevents attachment even when the resource itself remains fresh', async () => {
    const app = await setup()
    let finish!: (value: Result<void>) => void
    const base = resource.options!.session!
    if (base.mode !== 'mock') throw new Error('Expected mock')
    const session: Session = { ...base, demoControls: { ...base.demoControls, acceptTask: () => new Promise(resolve => { finish = resolve }) } }
    const boot: Promise<BootstrapResult> = Promise.resolve({ status: 'session', session })
    app.rerender(<App boot={boot} />)
    await waitFor(() => expect(resource.options!.session).toBe(session))
    // The local acceptance action lives on the process overview, not on the record section.
    await act(async () => {
      window.history.replaceState({}, '', '/#koordinator/case/novak')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    await userEvent.setup().click(await screen.findByRole('button', { name: 'Potvrdit převzetí (lokálně v demu)' }))
    expect(resource.options).toMatchObject({ contextFresh: false, context: null })
    expect(resource.options!.scopeKey).toContain('unavailable')
    await act(async () => finish(success(undefined)))
  })
})
