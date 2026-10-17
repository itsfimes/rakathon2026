import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { ClinicalDomains, ClinicalFact, ClinicalSource, ImagingProcedurePayload } from '../src/data/clinical'
import { ClinicalRecordBody } from '../src/features/shared/clinical/ClinicalRecordBody'
import { DetailScopeProvider } from '../src/features/shared/detailScope'

afterEach(() => cleanup())

const empty: ClinicalDomains = { identity: [], personalSocial: [], history: [], medications: [], symptoms: [], measurements: [], labs: [],
  imagingProcedures: [], oncologyHistology: [], supportiveCare: [], referralContinuity: [], mdtPlan: [] }
const source: ClinicalSource = { ref: { sourceId: 'SYNTHETIC-report', version: '1' }, label: 'SYNTHETIC zdroj', issued: { kind: 'instant', value: '2012-01-17T07:56:49+00:00' }, locallyAvailable: { kind: 'unknown' } }
const report = (id: string, value: Partial<ImagingProcedurePayload>): ClinicalFact<ImagingProcedurePayload> => ({
  id, value: { type: 'Synthetic panel', format: 'text-report', date: { kind: 'day', value: '2012-01-17' }, ...value },
  sources: [source.ref], effective: { kind: 'day', value: '2012-01-17' }, knowledge: 'recorded', presence: 'unspecified', verification: 'unspecified', conflictIds: [],
})
function show(facts: readonly ClinicalFact<ImagingProcedurePayload>[]) {
  render(<DetailScopeProvider value={{ key: 'k', live: true }}>
    <ClinicalRecordBody domains={{ ...empty, imagingProcedures: facts }} sources={[source]} idPrefix="t" />
  </DetailScopeProvider>)
  return screen.getAllByRole('region', { name: 'Zprávy z vyšetření a výkony' })[0]!
}

describe('report hierarchy', () => {
  it('metadata-only report: no "Nález", literal status/category in the leading line, names behind a closed disclosure', () => {
    const panel = show([report('a', { meta: { status: 'final', category: 'Laboratory', items: ['Total Cholesterol', 'Triglycerides'],
      attachments: [{ title: 'Synthetic attachment', contentType: 'application/pdf' }] } })])
    expect(within(panel).queryByText('Nález')).toBeNull()
    const line = panel.querySelector('.report-line')!
    expect(line).toHaveTextContent('Datum vyšetření: 17. 1. 2012')
    expect(line).toHaveTextContent('Stav ve zdroji: final')
    expect(line).toHaveTextContent('Kategorie: Laboratory')
    const summary = within(panel).getByText('Položky a přílohy zprávy (3)')
    expect(summary.closest('details')).not.toHaveAttribute('open')
    expect(panel.textContent).not.toContain('2012-01-17T07:56')
    expect(panel.textContent).not.toContain('Datum vyšetření: 17. 1. 2012Datum')
  })

  it('a real conclusion stays prominent next to metadata', () => {
    const panel = show([report('b', { conclusion: 'Synthetic literal conclusion', meta: { status: 'final' } })])
    expect(within(panel).getByText('Závěr')).toBeInTheDocument()
    expect(within(panel).getByText('Synthetic literal conclusion')).toBeInTheDocument()
    expect(within(panel).queryByText(/Položky a přílohy zprávy/)).toBeNull()
  })

  it('document metadata without content is stated; missing date is not invented', () => {
    const panel = show([report('c', { date: { kind: 'unknown' }, meta: { contentSupplied: false, authors: ['Synthetic author'] } })])
    expect(panel.querySelector('.report-line')).toHaveTextContent('Datum vyšetření: datum neuvedeno')
    expect(panel.querySelector('.report-line')).toHaveTextContent('Autor: Synthetic author')
    expect(within(panel).getByText('Obsah přílohy nebyl zdrojem dodán.')).toBeInTheDocument()
  })
})
