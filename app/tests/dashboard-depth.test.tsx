import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { App } from '../src/App'
import type { BootstrapResult, CaseDocument, Session, SourceField } from '../src/data/contracts'
import { createMockSession } from '../src/data/mock/provider'
import { SourceReviewPanel } from '../src/features/doctor/SourceReviewPanel'
import { DocumentEvidence } from '../src/features/shared/DocumentEvidence'
import { DetailScopeProvider } from '../src/features/shared/detailScope'
import type { DemoActions } from '../src/hooks/useDemoActions'

const boot = (value: Session): Promise<BootstrapResult> => Promise.resolve({ status: 'session', session: value })
const LIVE = { key: 'k', live: true }
const source = { title: 'Zpráva CT', date: '2026-01-12', page: 2 }
const doc = (over: Partial<CaseDocument>): CaseDocument => ({ id: 'd1', kind: 'imaging', label: 'Zobrazení', state: 'available', stateLabel: 'Máme', sources: [source], reviewState: 'unreviewed', ...over })
const field = (over: Partial<SourceField>): SourceField => ({ id: 'f1', documentId: 'd1', label: 'Nález', status: 'literal', statusLabel: 'Doslovně ve zdroji', reviewState: 'unreviewed', ...over })
const noActions = { available: false, busy: false } as unknown as DemoActions

async function go(hash: string) {
  await act(async () => {
    window.location.hash = hash
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
}
const summaries = () => [...document.querySelectorAll('main details > summary')]
const openDetails = () => document.querySelectorAll('main details[open]').length

beforeEach(() => window.history.replaceState(null, '', '/'))
afterEach(() => cleanup())

describe('supplied evidence components', () => {
  it('document: state always visible, sources on demand with metadata-only note; no source -> plain empty state', async () => {
    const user = userEvent.setup()
    render(<DetailScopeProvider value={LIVE}><DocumentEvidence documents={[doc({}), doc({ id: 'd2', label: 'Histologie', state: 'missing', stateLabel: 'Chybí', sources: [] })]} /></DetailScopeProvider>)
    expect(screen.getByText('Chybí')).toBeVisible()
    expect(screen.getByText('Zdroj nebyl dodán.')).toBeInTheDocument()
    expect(document.querySelectorAll('details')).toHaveLength(1)
    const summary = screen.getByText('Zdroje (1)')
    // jsdom does not implement keyboard activation of <summary>; native Enter/Space is verified in the browser check.
    await user.click(summary)
    expect(summary.closest('details')).toHaveAttribute('open')
    expect(screen.getByText('Zpráva CT · 12. 1. 2026 · str. 2')).toBeVisible()
    expect(screen.getByText(/Plné znění dokumentu tu není k dispozici/)).toBeVisible()
    expect(document.querySelectorAll('a, summary button')).toHaveLength(0)
  })

  it('excerpts are matched to their document id only', () => {
    render(<DetailScopeProvider value={LIVE}><DocumentEvidence documents={[doc({}), doc({ id: 'd2', label: 'Jiný' })]}
      fields={[field({ quote: 'citace A', source }), field({ id: 'f2', documentId: 'd2', quote: 'citace B' }), field({ id: 'f3', documentId: 'zzz', quote: 'cizí' })]} /></DetailScopeProvider>)
    const [first, second] = screen.getAllByRole('listitem').filter(item => item.classList.contains('evidence__item'))
    expect(first!.textContent).toContain('citace A')
    expect(first!.textContent).not.toContain('citace B')
    expect(second!.textContent).toContain('citace B')
    expect(second!.textContent).toContain('zdroj výňatku nebyl dodán')
    expect(document.body.textContent).not.toContain('cizí')
  })

  it('doctor: value + certainty visible; quote-only and metadata-only handled honestly', () => {
    render(<DetailScopeProvider value={LIVE}><SourceReviewPanel actions={noActions} documents={[]} fields={[
      field({ value: 'ložisko', quote: 'doslovně', source }),
      field({ id: 'q', label: 'Jen citace', quote: 'bez zdroje', status: 'uncertain', statusLabel: 'Nejednoznačné' }),
      field({ id: 'm', label: 'Jen zdroj', value: 'hodnota', source }),
      field({ id: 'n', label: 'Nic', status: 'absent', statusLabel: 'Chybí' }),
    ]} /></DetailScopeProvider>)
    expect(screen.getByText('ložisko')).toBeVisible()
    expect(screen.getByText('Nejednoznačné')).toBeVisible()
    expect(screen.getByText(/viz doslovný výňatek/)).toBeVisible()
    expect(screen.getByText('Zdroj výňatku nebyl dodán.')).toBeInTheDocument()
    expect(screen.getByText('Doslovný výňatek nebyl dodán.')).toBeInTheDocument()
    expect(screen.getAllByText('Doslovný výňatek')).toHaveLength(2)
    expect(screen.getByText('Ve zdroji není uvedeno.')).toBeVisible()
  })

  it('doctor: one local review action per supplied document, scope stated before it', async () => {
    const calls: string[] = []
    const actions = { available: true, busy: false, markReviewed: (id: string) => calls.push(id) } as unknown as DemoActions
    render(<DetailScopeProvider value={LIVE}><SourceReviewPanel actions={actions}
      documents={[doc({}), doc({ id: 'd2', label: 'Histologie', reviewState: 'reviewed' })]}
      fields={[field({}), field({ id: 'f2' }), field({ id: 'f3', documentId: 'd2' }), field({ id: 'f4', documentId: 'unknown' })]} /></DetailScopeProvider>)
    const buttons = screen.getAllByRole('button', { name: /Označit podklad/ })
    expect(buttons).toHaveLength(1)
    expect(buttons[0]).toHaveAccessibleName('Označit podklad jako zkontrolovaný: Zobrazení')
    expect(buttons[0]).toHaveAccessibleDescription(/celý podklad.*Není to klinické schválení/)
    const note = screen.getByText(/celý podklad/)
    expect(note.compareDocumentPosition(buttons[0]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(document.body.textContent).not.toContain('unknown')
    await userEvent.setup().click(buttons[0]!)
    expect(calls).toEqual(['d1'])
  })

  it('disclosures show a decorative open/closed marker and stay native', async () => {
    render(<DetailScopeProvider value={LIVE}><DocumentEvidence documents={[doc({})]} /></DetailScopeProvider>)
    const summary = document.querySelector('summary')!
    expect(summary.querySelector('.disclosure__marker svg')).toHaveAttribute('aria-hidden', 'true')
    expect(summary.querySelectorAll('button, a, [tabindex]')).toHaveLength(0)
    await userEvent.setup().click(summary)
    expect(summary.parentElement).toHaveAttribute('open')
  })

  it('not live: no expandable body is rendered, only an explanation', () => {
    render(<DetailScopeProvider value={{ key: 'k', live: false }}><DocumentEvidence documents={[doc({})]} fields={[field({ quote: 'skryto', source })]} /></DetailScopeProvider>)
    expect(document.querySelector('details')).toBeNull()
    expect(screen.getByText(/podrobnosti se zobrazí po načtení/)).toBeInTheDocument()
    expect(document.body.textContent).not.toContain('skryto')
  })
})

describe('expansion lifecycle in the app', { timeout: 15000 }, () => {
  it('patient never receives clinician excerpts; event details expand natively', async () => {
    const user = userEvent.setup()
    window.history.replaceState(null, '', '/?role=pacient')
    render(<App boot={boot(createMockSession({ delayMs: 0 }))} />)
    const summary = await screen.findByText('Původní záznam o termínu', undefined, { timeout: 5000 })
    await user.click(summary)
    expect(summary.closest('details')).toHaveAttribute('open')
    expect(document.body.textContent).not.toMatch(/hypoechogenní|Doslovný výňatek|Zdroje a výňatky/)
  })

  it('return path: the detail return link goes back to the list and focuses the opened row', async () => {
    const user = userEvent.setup()
    render(<App boot={boot(createMockSession({ delayMs: 0 }))} />)
    await user.click(await screen.findByRole('link', { name: 'Tomáš Dušek' }))
    await screen.findByRole('heading', { level: 2, name: /Tomáš Dušek ·/ })
    for (const summary of summaries()) await user.click(summary)
    await user.click(screen.getByRole('link', { name: 'Zpět na frontu případů' }))
    await waitFor(() => expect(screen.getByRole('link', { name: 'Tomáš Dušek' })).toHaveFocus())
    expect(openDetails()).toBe(0)
  })

  it('case A -> B and role change close every open detail', async () => {
    const user = userEvent.setup()
    window.history.replaceState(null, '', '/#koordinator/case/novak')
    render(<App boot={boot(createMockSession({ delayMs: 0 }))} />)
    await screen.findByRole('heading', { level: 2, name: /Jan Novák ·/ })
    await waitFor(() => expect(summaries().length).toBeGreaterThan(0))
    for (const summary of summaries()) await user.click(summary)
    expect(openDetails()).toBeGreaterThan(0)
    await go('koordinator/case/dusek')
    await screen.findByRole('heading', { level: 2, name: /Tomáš Dušek ·/ })
    await waitFor(() => expect(summaries().length).toBeGreaterThan(0))
    expect(openDetails()).toBe(0)
    await user.click(summaries()[0]!)
    await go('koordinator/case/novak/record')
    await waitFor(() => expect(summaries().length).toBeGreaterThan(0))
    expect(openDetails()).toBe(0)
    await user.click(summaries()[0]!)
    await go('mdt/case/novak')
    await screen.findByRole('heading', { level: 1, name: /MDT: příprava porady 21\. 10\. 2026/ })
    await waitFor(() => expect(summaries().length).toBeGreaterThan(0))
    expect(openDetails()).toBe(0)
  })

  it('same-case local change and reset collapse details; retained snapshot shows no body', async () => {
    const user = userEvent.setup()
    window.history.replaceState(null, '', '/#koordinator/case/novak')
    render(<App boot={boot(createMockSession({ delayMs: 30 }))} />)
    await screen.findByRole('heading', { level: 2, name: /Jan Novák ·/ }, { timeout: 3000 })
    await waitFor(() => expect(summaries().length).toBeGreaterThan(0))
    await user.click(summaries()[0]!)
    expect(openDetails()).toBe(1)
    await user.click(await screen.findByRole('button', { name: 'Potvrdit převzetí (lokálně v demu)' }))
    // while the change and the refresh are pending: no details element at all, explanation shown
    expect(document.querySelector('main details')).toBeNull()
    expect(screen.getAllByText(/podrobnosti se zobrazí po načtení/).length).toBeGreaterThan(0)
    await waitFor(() => expect(summaries().length).toBeGreaterThan(0))
    expect(openDetails()).toBe(0)

    await user.click(summaries()[0]!)
    expect(openDetails()).toBe(1)
    act(() => { screen.getByRole('button', { name: /Obnovit demo/ }).click() })
    expect(openDetails()).toBe(0)
    // Reset returns the case page to its list; reopening the case starts collapsed.
    await go('koordinator/case/novak')
    await waitFor(() => expect(summaries().length).toBeGreaterThan(0))
    expect(openDetails()).toBe(0)
  })

  it('failed refresh of the same case never shows an expandable stale body', async () => {
    const base = createMockSession({ delayMs: 0 })
    let fail = false
    const gateway = { ...base.gateway, mode: base.gateway.mode, readWorkspace: base.gateway.readWorkspace.bind(base.gateway),
      readCase: (id: string, signal?: AbortSignal) => fail ? Promise.resolve({ ok: false as const, error: { code: 'unavailable' as const, message: 'x' } }) : base.gateway.readCase(id, signal) }
    const user = userEvent.setup()
    window.history.replaceState(null, '', '/#koordinator/case/novak')
    render(<App boot={boot({ ...base, gateway })} />)
    await screen.findByRole('heading', { level: 2, name: /Jan Novák ·/ })
    await waitFor(() => expect(summaries().length).toBeGreaterThan(0))
    await user.click(summaries()[0]!)
    fail = true
    await user.click(await screen.findByRole('button', { name: 'Potvrdit převzetí (lokálně v demu)' }))
    await waitFor(() => expect(document.querySelector('main details')).toBeNull())
    expect(document.body.textContent).not.toMatch(/Plné znění dokumentu tu není/)
  })
})
