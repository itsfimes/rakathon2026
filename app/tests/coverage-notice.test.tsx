import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { ClinicalCoverage } from '../src/data/clinical'
import type { CollectionCoverage, CoverageReason } from '../src/data/coverage'
import { CoverageNotice } from '../src/features/shared/clinical/CoverageNotice'

afterEach(cleanup)
const complete: ClinicalCoverage = { conditions: 'complete', observations: 'complete', diagnosticReports: 'complete', documents: 'complete' }
const fail = (reason: CoverageReason | null, extra: Partial<CollectionCoverage> = {}): CollectionCoverage =>
  ({ status: 'unavailable', reason, serverTotal: null, receivedCount: null, encounteredCount: null, pagesFetched: null, ...extra })
const text = () => document.body.textContent ?? ''

describe('CoverageNotice', () => {
  it('renders nothing when every section is complete (incl. truthful empty)', () => {
    render(<CoverageNotice coverage={complete} detail={{}} />)
    expect(screen.queryByRole('status')).toBeNull()
    render(<CoverageNotice coverage={undefined} />)
    expect(screen.queryByRole('status')).toBeNull()
  })
  it('names the one missing section, explains an application limit without inferring source contents and shows qualified counters', () => {
    render(<CoverageNotice coverage={{ ...complete, observations: 'unavailable' }} detail={{ observations: fail('resource_limit', { receivedCount: 1000, serverTotal: 1450 }) }} />)
    expect(screen.getByText('Nepodařilo se načíst: Pozorování, laboratorní výsledky a měření')).toBeInTheDocument()
    expect(text()).toContain('Načítání překročilo bezpečnostní limit aplikace. Úplnost této části proto nebylo možné ověřit.')
    expect(text()).not.toMatch(/Zdroj obsahuje víc|Data ve zdroji jsou|načteny celé/)
    expect(text()).toContain('Ostatní dostupné části zůstávají zobrazeny.')
    expect(text()).toContain('Přijato záznamů: 1000; zdroj uvádí celkem: 1450.')
    expect(text()).toContain('nezobrazuje vůbec, ani zčásti')
    expect(text()).toContain('Nelze z toho usuzovat, že údaje neexistují, ani že jsou v pořádku.')
    expect(text()).not.toMatch(/\b450\b|1000\s*\/\s*1450|chybí/)
  })
  it.each<[CoverageReason, RegExp]>([
    ['truncated', /Úplnost této části proto nebylo možné ověřit/], ['deadline_exceeded', /neodpověděl včas/], ['upstream_error', /nepodařilo spolehlivě kontaktovat/],
    ['auth_failed', /nezískala ke zdroji dat přístup/], ['invalid_response', /nešlo bezpečně zpracovat/], ['paging_cycle', /nešlo bezpečně zpracovat/],
  ])('reason %s has a plain-language cause', (reason, expected) => {
    render(<CoverageNotice coverage={{ ...complete, documents: 'unavailable' }} detail={{ documents: fail(reason) }} />)
    expect(text()).toMatch(expected)
    expect(text()).not.toContain(reason)
  })
  it('keeps the legacy combined failure reason unknown rather than claiming a network failure', () => {
    render(<CoverageNotice coverage={{ ...complete, observations: 'unavailable' }} detail={{ observations: fail('upstream_unavailable_or_incomplete') }} />)
    expect(text()).toContain('Přesný důvod není známý.')
    expect(text()).not.toContain('kontaktovat')
  })
  it('unknown reason, missing detail and unknown counters fall back safely, never as zero', () => {
    render(<CoverageNotice coverage={{ ...complete, conditions: 'unavailable', diagnosticReports: 'unavailable' }}
      detail={{ conditions: fail('bogus_reason' as CoverageReason, { receivedCount: -1, serverTotal: null }) }} />)
    expect(screen.getByText('Některé části záznamu se nepodařilo načíst')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(text()).toContain('Onemocnění: ')
    expect(text()).toContain('Zprávy z vyšetření: ')
    expect(text().match(/Přesný důvod není známý/g)).toHaveLength(2)
    expect(text()).not.toMatch(/Přijato|: 0|bogus/)
    expect(text()).toContain('Tyto části se proto nezobrazují')
  })
  it('shows received count alone when the source total is unknown', () => {
    render(<CoverageNotice coverage={{ ...complete, observations: 'unavailable' }} detail={{ observations: fail('truncated', { receivedCount: 50 }) }} />)
    expect(text()).toContain('Přijato záznamů: 50; celkový počet zdroj neuvedl.')
  })
})
