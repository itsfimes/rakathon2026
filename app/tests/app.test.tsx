import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { App } from '../src/App'
import { UnconfiguredBackendGateway } from '../src/data/backend/unconfigured'
import { UnconfiguredAssistant } from '../src/data/backend/assistant'
import { failure, success } from '../src/data/contracts'
import type { BootstrapResult, CaseDetail, Gateway, Result, Session, Workspace } from '../src/data/contracts'
import { createMockSession } from '../src/data/mock/provider'
import { calendarTile, formatDayMonth, formatLongDate } from '../src/lib/format'
import { bootOnce } from '../src/session'

const FIXTURE_NAMES = ['Novák', 'Šimková', 'Dušek', 'Králová', 'Říha', 'Veselý', 'Lenka Horká', 'Svoboda']

const session = (value: Session): Promise<BootstrapResult> => Promise.resolve({ status: 'session', session: value })
const mockBoot = () => session(createMockSession({ delayMs: 0 }))
const backendBoot = () => session({ mode: 'backend', gateway: new UnconfiguredBackendGateway(), assistant: new UnconfiguredAssistant() })

async function go(hash: string) {
  await act(async () => {
    window.location.hash = hash
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  })
}

function expectNoFixtureText() {
  for (const name of FIXTURE_NAMES) expect(document.body.textContent).not.toContain(name)
}

beforeEach(() => window.history.replaceState(null, '', '/'))
afterEach(() => cleanup())

describe('bootstrap and source states', () => {
  it('configuration error renders the shell with no data', async () => {
    render(<App boot={Promise.resolve({ status: 'configuration-error', error: { code: 'configuration-error', message: 'VITE_DATA_MODE je neplatné.' } })} />)
    expect(await screen.findByText('Atlas')).toBeInTheDocument()
    expectNoFixtureText()
  })

  it('unexpected bootstrap rejection shows no data, not fixtures', async () => {
    render(<App boot={Promise.reject(new Error('selhalo'))} />)
    expect(await screen.findByText('Atlas')).toBeInTheDocument()
    expectNoFixtureText()
  })

  it('backend unconfigured: unavailable (not empty) in every view, roles still navigable', async () => {
    render(<App boot={backendBoot()} />)
    expect(await screen.findByText('Atlas')).toBeInTheDocument()
    for (const hash of ['koordinator', 'pacient', 'lekar', 'mdt']) {
      await go(hash)
      expect(await screen.findByText('Data nejsou k dispozici')).toBeInTheDocument()
      expect(screen.queryByText('Fronta je prázdná')).toBeNull()
      expect(screen.queryByRole('button', { name: /Obnovit demo/ })).toBeNull()
      expectNoFixtureText()
    }
    await go('specimen')
    expect(await screen.findByRole('heading', { level: 1, name: 'Vizuální jazyk' })).toBeInTheDocument()
    expect(screen.queryByText(/Stav k/)).toBeNull()
  })

  it('mock mode renders patient data with a demo reset control', async () => {
    render(<App boot={mockBoot()} />)
    expect(await screen.findByRole('button', { name: 'Obnovit demo' })).toBeInTheDocument()
    const failing: Gateway = {
      mode: 'mock',
      readWorkspace: async () => failure('unavailable', 'Zdroj neodpověděl.'),
      readCase: async () => failure('unavailable', 'Zdroj neodpověděl.'),
    }
    cleanup()
    render(<App boot={session({ ...createMockSession(), gateway: failing })} />)
    expect(await screen.findByText('Data se nepodařilo načíst')).toBeInTheDocument()
  })
})

describe('roles, lists, case pages and history', () => {
  it('?role selects the view, role hashes navigate and focus the heading, in-page fragments keep the route', async () => {
    window.history.replaceState(null, '', '/?role=mdt')
    render(<App boot={mockBoot()} />)
    expect(await screen.findByRole('heading', { level: 1, name: 'MDT: pacienti pro MDT' })).toBeInTheDocument()
    await go('lekar')
    const heading = await screen.findByRole('heading', { level: 1, name: 'Lékař: ukázkový seznam případů' })
    await waitFor(() => expect(heading).toHaveFocus())
    await go('obsah')
    expect(screen.getByRole('heading', { level: 1, name: 'Lékař: ukázkový seznam případů' })).toBeInTheDocument()
    await go('')
    expect(await screen.findByRole('heading', { level: 1, name: 'MDT: pacienti pro MDT' })).toBeInTheDocument()
  })

  it('clinician lists read the workspace once and no case; the queue never shares the page with a detail', async () => {
    const base = createMockSession({ delayMs: 0 })
    const reads: string[] = []
    const gateway: Gateway = { mode: 'mock', readWorkspace: signal => base.gateway.readWorkspace(signal),
      readCase: (id, signal) => { reads.push(id); return base.gateway.readCase(id, signal) } }
    render(<App boot={session({ ...base, gateway })} />)
    const links = await screen.findAllByRole('link', { name: /^(Jan|Alena|Tomáš|Marie|Pavel|Karel) / })
    expect(links).toHaveLength(6)
    expect(links[0]).toHaveAttribute('href', '#koordinator/case/novak')
    expect(screen.queryByRole('button', { name: 'Potvrdit převzetí (lokálně v demu)' })).toBeNull()
    await go('lekar')
    const doctorLinks = await screen.findAllByRole('link', { name: /^(Jan|Alena|Tomáš|Marie|Pavel|Karel) / })
    expect(doctorLinks[1]).toHaveAttribute('href', '#lekar/case/simkova')
    expect(doctorLinks[1]).toHaveAttribute('id', 'case-row-lekar-simkova')
    expect(document.body.textContent).toMatch(/Nejde o seznam vašich pacientů/)
    await go('specimen')
    await screen.findByRole('heading', { level: 1, name: 'Vizuální jazyk' })
    expect(reads).toEqual([])
  })

  it('a row link opens a separate case page; Back returns to the list with focus on that row', async () => {
    const user = userEvent.setup()
    render(<App boot={mockBoot()} />)
    await user.click(await screen.findByRole('link', { name: 'Alena Šimková' }))
    expect(window.location.hash).toBe('#koordinator/case/simkova')
    expect(await screen.findByRole('heading', { level: 2, name: /Alena Šimková · 64 let/ })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2, name: /Případy podle priority/ })).toBeNull()
    await waitFor(() => expect(screen.getByRole('heading', { level: 1, name: 'Koordinátor: detail případu' })).toHaveFocus())
    await user.click(screen.getByRole('link', { name: 'Zpět na frontu případů' }))
    await waitFor(() => expect(window.location.hash).toBe('#koordinator'))
    await waitFor(() => expect(screen.getByRole('link', { name: 'Alena Šimková' })).toHaveFocus())
  })

  it('patient preview follows the last explicitly opened clinician case; reset clears it', async () => {
    const user = userEvent.setup()
    render(<App boot={mockBoot()} />)
    await go('lekar')
    await user.click(await screen.findByRole('link', { name: 'Alena Šimková' }))
    await screen.findByText(/Alena Šimková · 64 let/)
    await go('pacient')
    expect(await screen.findByRole('heading', { level: 1, name: 'Paní Šimková: co vás čeká' })).toBeInTheDocument()
    expect(screen.queryByText(/Pan Novák/)).toBeNull()
    await user.click(screen.getByRole('button', { name: /Obnovit demo/ }))
    expect(await screen.findByRole('heading', { level: 1, name: /Pan Novák/ })).toBeInTheDocument()
  })

  it('malformed and unknown case links are honest; a valid role hash reaches that role list', async () => {
    window.history.replaceState(null, '', '/#lekar/case/%E0%A4%A')
    render(<App boot={mockBoot()} />)
    expect(await screen.findByText('Neplatný odkaz na případ')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Zpět na seznam případů' })).toHaveAttribute('href', '#lekar')
    expect(screen.queryByText(/Jan Novák/)).toBeNull()
    await go('koordinator/case/neexistuje')
    expect(await screen.findByText('Případ nebyl nalezen')).toBeInTheDocument()
    expect(screen.queryByText(/Jan Novák/)).toBeNull()
    await go('koordinator')
    expect(window.location.hash).toBe('#koordinator')
    expect(await screen.findByRole('heading', { level: 1, name: 'Koordinátor: fronta případů' })).toBeInTheDocument()
  })

  it('a late answer for a previous case never appears under the new case', async () => {
    const base = createMockSession({ delayMs: 0 })
    const pending = new Map<string, (value: Result<CaseDetail>) => void>()
    const gateway: Gateway = {
      mode: 'mock',
      readWorkspace: signal => base.gateway.readWorkspace(signal),
      readCase: (caseId: string) => new Promise(resolve => {
        pending.set(caseId, value => resolve(value))
      }),
    }
    window.history.replaceState(null, '', '/#koordinator/case/novak')
    render(<App boot={session({ ...base, gateway })} />)
    await waitFor(() => expect(pending.has('novak')).toBe(true))
    await go('koordinator/case/dusek')
    const tomas = await base.gateway.readCase('dusek')
    const jan = await base.gateway.readCase('novak')
    await act(async () => { if (tomas.ok) pending.get('dusek')?.(success(tomas.value)) })
    await act(async () => { if (jan.ok) pending.get('novak')?.(success(jan.value)) })
    expect(await screen.findByRole('heading', { level: 2, name: /Tomáš Dušek · 57 let/ })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { level: 2, name: /Jan Novák · 60 let/ })).toBeNull()
  })
})

describe('local demo actions', () => {
  it('acceptance and review sync across views, reset restores, finalisation stays disabled', async () => {
    const user = userEvent.setup()
    window.history.replaceState(null, '', '/#koordinator/case/novak')
    render(<App boot={mockBoot()} />)
    const accept = await screen.findByRole('button', { name: 'Potvrdit převzetí (lokálně v demu)' })
    await user.click(accept)
    expect(await screen.findByText(/Převzetí zaznamenáno lokálně v demu/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('Převzato 27. 10.').length).toBeGreaterThanOrEqual(1))

    await go('lekar/case/novak')
    const review = await screen.findByRole('button', { name: 'Označit podklad jako zkontrolovaný: Zobrazení (UZ 6. 1., CT 12. 1.)' })
    await user.click(review)
    expect(await screen.findByText(/označen jako zkontrolovaný lokálně v demu/)).toBeInTheDocument()

    // MDT preparation is a frozen snapshot: live local review/acceptance changes never appear in it.
    await go('mdt/case/novak')
    expect(await screen.findByRole('heading', { level: 1, name: 'MDT: příprava porady 21. 10. 2026' })).toBeInTheDocument()
    expect(screen.queryByText('Zkontrolováno (lokálně v demu)')).toBeNull()
    expect(screen.queryByText('Převzato 27. 10.')).toBeNull()
    expect(screen.getByRole('button', { name: /Finalizovat závěr/ })).toBeDisabled()
    expect(document.body.textContent).not.toMatch(/(?<!ne)podepsáno|odesláno vlastníkovi|uloženo na server/i)

    await user.click(screen.getByRole('button', { name: /Obnovit demo/ }))
    expect(await screen.findByText('Demo obnoveno do výchozího stavu.')).toBeInTheDocument()
    await go('lekar/case/novak')
    await screen.findByRole('button', { name: 'Označit podklad jako zkontrolovaný: Zobrazení (UZ 6. 1., CT 12. 1.)' })
    expect(screen.queryByText('Zkontrolováno (lokálně v demu)')).toBeNull()
    expect(screen.getByRole('button', { name: 'Obnovit demo' })).toBeInTheDocument()
  })

  it('real operations are unavailable, never fake success', async () => {
    window.history.replaceState(null, '', '/#koordinator/case/novak')
    render(<App boot={mockBoot()} />)
    expect(await screen.findByRole('button', { name: 'Urgovat vlastníka kroku' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Informovat odesílajícího lékaře' })).toBeDisabled()
  })
})

describe('patient graphics and keyboard', () => {
  it('calendar and journey render from case data with Czech dates', async () => {
    window.history.replaceState(null, '', '/?role=pacient')
    render(<App boot={mockBoot()} />)
    // The January demo date is before the record's 27. 10. 2026 "as of" day: shown as an earlier record, not a current promise.
    const event = await screen.findByRole('heading', { level: 2, name: 'Dříve uvedený termín: úterý 13. ledna 2026' })
    const next = screen.getByRole('heading', { level: 2, name: 'Co teď' })
    expect(next.compareDocumentPosition(event) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getByText('Aktuální termín zde není potvrzen.')).toBeInTheDocument()
    expect(screen.getByText('Další krok zatím není znám.')).toBeInTheDocument()
    expect(screen.getByText('Dříve uvedený pokyn')).toBeInTheDocument()
    expect(screen.queryByText('Termíny níže jsou ze starší části ukázky')).toBeNull()
    expect(screen.queryByText(/proběhl/)).toBeNull()
    const journey = screen.getByRole('list', { name: 'Vaše cesta' })
    expect(within(journey).getAllByRole('listitem')).toHaveLength(6)
    const earlierMeeting = within(journey).getByText('13. 1. · Porada lékařů').closest('li')
    expect(earlierMeeting).not.toHaveAttribute('aria-current')
    expect(earlierMeeting).toHaveClass('is-now')
    expect(earlierMeeting).toHaveTextContent('Dříve uvedeno · aktuální stav zde není potvrzen')
  })

  it('date formatting never shifts the calendar day', () => {
    expect(formatLongDate('2026-01-13')).toBe('Úterý 13. ledna 2026')
    expect(formatDayMonth('2026-01-09T20:00:00+01:00')).toBe('9. 1.')
    expect(calendarTile('2026-01-13')).toEqual({ month: 'leden', day: '13', weekday: 'úterý' })
    expect(calendarTile('not a date')).toBeNull()
  })

  it('a plain pointer click anywhere in a row opens that case page; one tab stop per row', async () => {
    const user = userEvent.setup()
    render(<App boot={mockBoot()} />)
    const row = (await screen.findByRole('link', { name: 'Tomáš Dušek' })).closest('tr')!
    expect(row).not.toHaveAttribute('tabindex')
    expect(within(row).getAllByRole('link')).toHaveLength(1)
    expect(within(row).queryAllByRole('button')).toHaveLength(0)
    await user.click(within(row).getByText(/^T\d/))
    expect(await screen.findByRole('heading', { level: 2, name: /Tomáš Dušek ·/ })).toBeInTheDocument()
    expect(window.location.hash).toBe('#koordinator/case/dusek')
  })

  it('modifier clicks keep native link behaviour; Enter on the row link opens the case', async () => {
    const user = userEvent.setup()
    render(<App boot={mockBoot()} />)
    const link = await screen.findByRole('link', { name: 'Alena Šimková' })
    await user.keyboard('{Control>}')
    await user.click(within(link.closest('tr')!).getByText(/^T\d/))
    await user.keyboard('{/Control}')
    expect(window.location.hash).not.toContain('case')
    const ctrlClick = new MouseEvent('click', { bubbles: true, cancelable: true, ctrlKey: true, button: 0 })
    link.dispatchEvent(ctrlClick)
    expect(ctrlClick.defaultPrevented).toBe(false)
    link.focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('heading', { level: 2, name: /Alena Šimková ·/ })).toBeInTheDocument()
  })

  it('skip link moves focus to the content without changing the route', async () => {
    const user = userEvent.setup()
    window.history.replaceState(null, '', '/#lekar/case/novak')
    render(<App boot={mockBoot()} />)
    await screen.findByRole('heading', { level: 1, name: 'Lékař: odeslaný pacient' })
    await user.tab()
    const skip = screen.getByRole('link', { name: 'Přeskočit na obsah' })
    expect(skip).toHaveFocus()
    expect(skip).toHaveAttribute('href', '#obsah')
    await user.keyboard('{Enter}')
    expect(document.getElementById('obsah')).toHaveFocus()
    expect(window.location.hash).toBe('#lekar/case/novak')
  })
})

describe('workspace counts', () => {
  it('queue count comes from the queue array', async () => {
    const base = createMockSession({ delayMs: 0 })
    const gateway: Gateway = {
      mode: 'mock',
      readWorkspace: async (): Promise<Result<Workspace>> => {
        const result = await base.gateway.readWorkspace()
        return result.ok ? success({ ...result.value, queue: result.value.queue.slice(0, 2) }) : result
      },
      readCase: (id, signal) => base.gateway.readCase(id, signal),
    }
    render(<App boot={session({ ...base, gateway })} />)
    const heading = await screen.findByRole('heading', { level: 2, name: /Případy podle priority/ })
    expect(heading).toHaveTextContent('2')
  })
})

it('bootstraps once per page, shared by every caller', () => {
  expect(bootOnce()).toBe(bootOnce())
})
