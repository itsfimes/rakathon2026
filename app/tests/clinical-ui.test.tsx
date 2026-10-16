import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { App } from '../src/App'
import type { BootstrapResult, CaseDetail, Gateway, Session } from '../src/data/contracts'
import { success } from '../src/data/contracts'
import { createMockSession } from '../src/data/mock/provider'

const boot = (session: Session): Promise<BootstrapResult> => Promise.resolve({ status: 'session', session })
const mock = () => boot(createMockSession({ delayMs: 0 }))
async function go(hash: string) {
  await act(async () => {
    window.location.hash = hash
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
}
const sectionNav = () => within(screen.getByRole('navigation', { name: 'Části případu' }))
const firstRegion = async (name: string | RegExp) => (await screen.findAllByRole('region', { name }, { timeout: 5000 }))[0]!
const text = () => document.querySelector('main')!.textContent ?? ''
beforeEach(() => window.history.replaceState(null, '', '/'))
afterEach(() => cleanup())

describe('clinician case sections', { timeout: 20000 }, () => {
  it('record section shows typed values with literal times, orthogonal states and both conflicting claims', async () => {
    const user = userEvent.setup()
    window.history.replaceState(null, '', '/#koordinator/case/novak/record')
    render(<App boot={mock()} />)
    const labs = await firstRegion('Laboratoř')
    const row = within(labs).getByText('Modelový bilirubin').closest('tr')!
    expect(row).toHaveTextContent('25 µmol/l')
    expect(row).toHaveTextContent('Pouze modelový rozsah 5–21')
    expect(row).toHaveTextContent('Nad rozmezím (dle zdroje)')
    expect(row).toHaveTextContent('Odběr: 18. 10. 2026')
    expect(row).toHaveTextContent('Výsledek: 20. 10. 2026')
    expect(row).toHaveTextContent('Předběžné')
    const conflict = screen.getByText('Nevyřešený rozpor v lécích').closest('section')!
    expect(conflict).toHaveTextContent('Apixaban — syntetické tvrzení A')
    expect(conflict).toHaveTextContent('Apixaban — syntetické tvrzení B')
    expect(within(conflict).getAllByText('Rozpor mezi záznamy · nevyřešeno')).toHaveLength(2)
    expect(text()).toContain('Výslovně popřeno')
    expect(text()).toContain('přibližně: Přibližně několik týdnů před vyšetřením')
    expect(text()).toContain('červenec 2026 (jen měsíc)')
    expect(text()).toContain('datum neuvedeno')
    expect(text()).toContain('Podezření, nepotvrzeno')
    expect(text()).not.toMatch(/\bT\d+N\d+M\d+\b/)
    const summary = within(row).getByText('Zdroj a časy (1)')
    await user.click(summary)
    const body = summary.closest('details')!
    expect(body).toHaveTextContent('SYNTHETIC-results · verze 1')
    expect(body).toHaveTextContent('Vydáno20. 10. 2026')
    expect(body).toHaveTextContent('Místně k dispozici20. 10. 2026')
    // Section change closes the disclosure (route scope).
    await go('koordinator/case/novak/care')
    await go('koordinator/case/novak/record')
    await firstRegion('Laboratoř')
    expect(document.querySelectorAll('main details[open]')).toHaveLength(0)
  })

  it('overview lists unresolved items with links; care shows the recorded plan; person hides identifiers until asked', async () => {
    const user = userEvent.setup()
    window.history.replaceState(null, '', '/#lekar/case/novak')
    render(<App boot={mock()} />)
    const attention = await firstRegion(/Upozornění v záznamu/)
    expect(attention).toHaveTextContent('Apixaban — syntetické tvrzení A')
    expect(within(attention).getAllByRole('link', { name: 'Zdravotní údaje a výsledky' }).length).toBeGreaterThan(0)
    expect(sectionNav().getByRole('link', { name: /Přehled/ })).toHaveAttribute('aria-current', 'page')
    expect(text()).toContain('Nejde o roli ošetřujícího lékaře')
    await user.click(sectionNav().getByRole('link', { name: /Průběh a plán/ }))
    expect(window.location.hash).toBe('#lekar/case/novak/care')
    expect(await screen.findByText('Modelový závěr, nikoli klinické doporučení.')).toBeInTheDocument()
    expect(await firstRegion('Dokumenty podle času')).toHaveTextContent('23. 10. 2026')
    await user.click(sectionNav().getByRole('link', { name: /Osoba a podpora/ }))
    const summary = await screen.findByText('Zobrazit citlivé identifikační a kontaktní údaje')
    expect(summary.closest('details')).not.toHaveAttribute('open')
    expect(text()).toContain('Zaznamenané přání není oprávnění k přístupu')
  })

  it('a case without a structured record is honest in every record section, never a fallback', async () => {
    window.history.replaceState(null, '', '/#koordinator/case/dusek/record')
    render(<App boot={mock()} />)
    expect(await screen.findByText('Rozšířený klinický záznam není k dispozici')).toBeInTheDocument()
    expect(text()).not.toContain('Apixaban')
  })

  it('return link from a deeper section goes back to the list and focuses the row', async () => {
    const user = userEvent.setup()
    render(<App boot={mock()} />)
    await user.click(await screen.findByRole('link', { name: 'Jan Novák' }))
    await screen.findByText(/Jan Novák · 60 let/)
    await user.click(sectionNav().getByRole('link', { name: /Zdravotní údaje a výsledky/ }))
    await firstRegion('Laboratoř')
    await user.click(sectionNav().getByRole('link', { name: /Osoba a podpora/ }))
    await user.click(screen.getByRole('link', { name: 'Zpět na frontu případů' }))
    await waitFor(() => expect(window.location.hash).toBe('#koordinator'))
    await waitFor(() => expect(screen.getByRole('link', { name: 'Jan Novák' })).toHaveFocus())
  })

  it('doctor list stays a neutral demo list', async () => {
    window.history.replaceState(null, '', '/#lekar')
    render(<App boot={mock()} />)
    await screen.findByRole('link', { name: 'Jan Novák' })
    expect(text()).not.toMatch(/Moji|Moje odeslan/)
  })
})

describe('patient record', { timeout: 20000 }, () => {
  it('shows supplied values in plain words without internal identifiers or review state', async () => {
    window.history.replaceState(null, '', '/#pacient')
    render(<App boot={mock()} />)
    expect(await screen.findByText('Termíny podle dřívějšího záznamu. Aktuální průběh zde není potvrzen.')).toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('link', { name: 'Otevřít moje zdravotní údaje' }))
    expect(window.location.hash).toBe('#pacient/record')
    const results = await firstRegion('Výsledky vyšetření')
    expect(results).toHaveTextContent('Modelový bilirubin')
    expect(results).toHaveTextContent('25 µmol/l')
    expect(results).toHaveTextContent('Zpráva uvádí: nad rozmezím')
    expect(text()).toContain('Apixaban — syntetické tvrzení A')
    expect(text()).toContain('Apixaban — syntetické tvrzení B')
    expect(text()).toContain('Některé záznamy o lécích se liší')
    expect(text()).toContain('Ve zprávě popřeno')
    expect(text()).toContain('Zaznamenané přání není oprávnění')
    expect(text()).not.toMatch(/SYNTHETIC-(basic|results|apixaban)|verze 1|zkontrolov|unreviewed|Rodné číslo|Číslo pojištěnce/i)
  })

  it('missing patient record is honest', async () => {
    window.history.replaceState(null, '', '/#lekar/case/simkova')
    render(<App boot={mock()} />)
    await screen.findByText(/Alena Šimková · 64 let/)
    await go('pacient/record')
    expect(await screen.findByText('Zdravotní údaje zatím nejsou k dispozici')).toBeInTheDocument()
  })
})

describe('MDT preparation versus recorded plan', { timeout: 20000 }, () => {
  function poisoned() {
    const base = createMockSession({ delayMs: 0 })
    const gateway: Gateway = { ...base.gateway, readWorkspace: signal => base.gateway.readWorkspace(signal), readCase: async (id, signal) => {
      const result = await base.gateway.readCase(id, signal)
      if (!result.ok) return result
      const live = result.value
      const poison = 'LIVE-POISON'
      const value: CaseDetail = { ...live,
        nextStep: { ...live.nextStep!, title: poison, shortTitle: poison },
        documents: live.documents.map(document => ({ ...document, label: poison, stateLabel: poison })),
        doctor: { ...live.doctor, sourceFields: live.doctor.sourceFields.map(field => ({ ...field, label: poison })) },
        mdt: { ...live.mdt, finding: poison, draft: { decision: poison, uncertainties: [poison] } },
      }
      return success(value)
    } }
    return { ...base, gateway }
  }

  it('preparation renders only the frozen snapshot: no live fields, no late content, counts from the snapshot', async () => {
    window.history.replaceState(null, '', '/#mdt/case/novak')
    render(<App boot={boot(poisoned())} />)
    expect(await screen.findByRole('heading', { level: 1, name: 'MDT: příprava porady 21. 10. 2026' })).toBeInTheDocument()
    expect(screen.getByText('Podklady doložené před 21. 10. 2026; u stejného dne není pořadí ověřeno.')).toBeInTheDocument()
    expect(text()).not.toContain('LIVE-POISON')
    expect(text()).not.toContain('SYNTHETIC podpora zaznamenaná až po MDT')
    expect(text()).not.toContain('Modelový závěr, nikoli klinické doporučení.')
    const req = await firstRegion(/Požadované podklady/)
    expect(req).toHaveTextContent('Úplnost nelze potvrdit')
    expect(await firstRegion(/Vyřazeno z přípravy/)).toHaveTextContent('k dispozici až po dni porady')
    expect(screen.getByRole('button', { name: /Finalizovat závěr/ })).toBeDisabled()
  })

  it('recorded plan page shows the later current entries, explicitly labelled', async () => {
    window.history.replaceState(null, '', '/#mdt/case/novak/plan')
    render(<App boot={boot(poisoned())} />)
    expect(await screen.findByText('Modelový závěr, nikoli klinické doporučení.')).toBeInTheDocument()
    expect(text()).toContain('Obsahuje i údaje vzniklé po přípravě porady')
    expect(text()).not.toContain('LIVE-POISON')
  })

  it('case without preparation is unavailable, never a live fallback', async () => {
    window.history.replaceState(null, '', '/#koordinator/case/dusek')
    render(<App boot={mock()} />)
    await screen.findByText(/Tomáš Dušek · 57 let/)
    await go('mdt/case/dusek')
    expect(await screen.findByText('Příprava porady není k dispozici')).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: /Požadované podklady/ })).toBeNull()
  })
})
