import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it } from 'vitest'
import type { ClinicalFact, ClinicalSource } from '../src/data/clinical'
import { caseDTO } from '../src/data/backend/dto'
import { projectCase } from '../src/data/backend/projection'
import { SOURCE_SUMMARY_LIMITS } from '../src/data/backend/sourceSummary'
import { SourceInspect } from '../src/features/shared/clinical/FactBlock'
import { DetailScopeProvider } from '../src/features/shared/detailScope'
import { caseResponse, complete, resource } from './backend-fixtures'

afterEach(cleanup)
const renderLive = (node: React.ReactElement) => render(<DetailScopeProvider value={{ key: 'k', live: true }}>{node}</DetailScopeProvider>)
const loinc = (code: string, display: string) => ({ text: display, coding: [{ system: 'http://loinc.org', code, display }] })
const bmi = () => ({ ...resource('Observation', '1654'), status: 'final', code: loinc('39156-5', 'Body Mass Index'),
  effectiveDateTime: '2010-09-01T02:28:07Z', issued: '2010-09-01T02:28:07.303Z', valueQuantity: { value: 27.24, unit: 'kg/m2' } })
const bp = () => ({ ...resource('Observation', '1655'), status: 'final', code: loinc('85354-9', 'Blood Pressure'), effectiveDateTime: '2010-09-01T02:28:07Z',
  component: [{ code: loinc('8480-6', 'Systolic Blood Pressure'), valueQuantity: { value: 118, unit: 'mm[Hg]' } },
    { code: loinc('8462-4', 'Diastolic Blood Pressure'), valueQuantity: { value: 84, unit: 'mm[Hg]' } }] })
function project(observations: unknown[], extra: Partial<ReturnType<typeof caseResponse>['sections']> = {}) {
  const raw = caseResponse()
  raw.sections = { ...raw.sections, observations: complete(observations), ...extra }
  return projectCase(caseDTO(raw, 'synthetic-0'))
}
const sourceOf = (sources: readonly ClinicalSource[], fact: ClinicalFact<unknown>) => sources.find(s => s.ref.sourceId === fact.sources[0]!.sourceId && s.ref.version === fact.sources[0]!.version)!

describe('source summary projection', () => {
  it('BMI source carries value, unit, status and the 2010 clinical date distinct from issued', () => {
    const { clinical } = project([bmi()])
    const fact = clinical!.domains.measurements[0]!
    const source = sourceOf(clinical!.sources, fact)
    expect(source.label).toBe('Měření: Body Mass Index')
    expect(source.summary).toEqual({ kind: 'measurement', title: 'Body Mass Index', status: 'final',
      clinicalTime: { kind: 'instant', value: '2010-09-01T02:28:07Z' }, values: [{ label: 'Body Mass Index', value: '27.24', unit: 'kg/m2' }] })
    expect(source.issued).toEqual({ kind: 'instant', value: '2010-09-01T02:28:07.303Z' })
    expect(source.locallyAvailable).toEqual({ kind: 'unknown' })
  })
  it('blood pressure keeps both component values in one source and all component facts point to it', () => {
    const { clinical } = project([bp()])
    const facts = clinical!.domains.measurements
    expect(new Set(facts.map(f => f.sources[0]!.sourceId))).toEqual(new Set(['Observation/1655']))
    expect(sourceOf(clinical!.sources, facts[0]!).summary!.values).toEqual([
      { label: 'Systolic Blood Pressure', value: '118', unit: 'mm[Hg]' }, { label: 'Diastolic Blood Pressure', value: '84', unit: 'mm[Hg]' }])
  })
  it('coded answer without a number, condition and report use only allowlisted fields', () => {
    const coded = { ...resource('Observation', 'coded'), code: { text: 'Tobacco smoking status' }, valueCodeableConcept: { text: 'Never smoker' } }
    const { clinical } = project([coded], {
      conditions: complete([{ ...resource('Condition', 'c1'), code: { text: 'Hypertension' }, clinicalStatus: { coding: [{ code: 'active' }] },
        verificationStatus: { coding: [{ system: 'urn:other', code: 'confirmed' }] }, onsetDateTime: '2009-01-02', recordedDate: '2009-01-03' }]),
      diagnosticReports: complete([{ ...resource('DiagnosticReport', 'r1'), status: 'final', code: { text: 'Lipid Panel' }, effectiveDateTime: '2010-09-01', result: [{ reference: 'Observation/a' }, { reference: 'Observation/b' }] }]),
    })
    const by = (id: string) => clinical!.sources.find(s => s.ref.sourceId === id)!.summary
    expect(by('Observation/coded')!.values).toEqual([{ label: 'Tobacco smoking status', value: 'Never smoker' }])
    expect(by('Condition/c1')).toEqual({ kind: 'condition', title: 'Hypertension', clinicalStatus: 'active', clinicalTime: { kind: 'day', value: '2009-01-02' }, recorded: { kind: 'day', value: '2009-01-03' } })
    expect(by('DiagnosticReport/r1')).toEqual({ kind: 'report', title: 'Lipid Panel', status: 'final', clinicalTime: { kind: 'day', value: '2010-09-01' }, resultCount: 2 })
    expect(JSON.stringify(by('Condition/c1'))).not.toContain('confirmed')
    expect(by('Patient/synthetic-0')).toEqual({ kind: 'patient' })
  })
  it('bounds component fan-out and text length; patient record DTO stays free of summaries', () => {
    const many = { ...bp(), component: Array.from({ length: 30 }, (_, i) => ({ code: { text: `C${i}` }, valueString: 'x'.repeat(500) })) }
    const detail = project([many])
    const summary = detail.clinical!.sources.find(s => s.ref.sourceId === 'Observation/1655')!.summary!
    expect(summary.values).toHaveLength(SOURCE_SUMMARY_LIMITS.values)
    expect(summary.values!.every(v => v.value.length <= SOURCE_SUMMARY_LIMITS.text)).toBe(true)
    expect(JSON.stringify(detail.patient.record)).not.toMatch(/summary|Observation\/1655|full-source-version/)
  })
})

describe('SourceInspect', () => {
  const render1654 = () => {
    const { clinical } = project([bmi()])
    renderLive(<SourceInspect fact={clinical!.domains.measurements[0]!} sources={clinical!.sources} />)
  }
  it('collapsed summary names the record kind; expanded shows readable BMI before identity', async () => {
    render1654()
    const summary = screen.getByText('Zdrojový záznam: měření')
    const details = summary.closest('details')!
    expect(details.open).toBe(false)
    await userEvent.click(summary)
    expect(within(details).getByText('27.24 kg/m2')).toBeInTheDocument()
    expect(details).toHaveTextContent('Body Mass Index')
    expect(details).toHaveTextContent('Údaje ze strukturovaného zdrojového záznamu.')
    expect(details).toHaveTextContent('Stav záznamukonečný')
    expect(details).toHaveTextContent('Změřeno1. 9. 2010')
    expect(details).not.toHaveTextContent('Týká se doby')
    expect(details).toHaveTextContent('ZpřístupněnoDatum zpřístupnění není uvedeno')
    expect(details).toHaveTextContent('Označení záznamuObservation/1654 · verze')
    const text = details.textContent!
    expect(text.indexOf('27.24')).toBeLessThan(text.indexOf('Observation/1654'))
    expect(text).not.toMatch(/2026|PDF není|bez dokumentu|referenční|normální/i)
  })
  it('BP renders both component values; unresolved or ambiguous refs never borrow another record', async () => {
    const { clinical } = project([bp(), bmi()])
    const fact = clinical!.domains.measurements[0]!
    const dup = [...clinical!.sources, { ...sourceOf(clinical!.sources, fact), summary: { kind: 'measurement' as const, title: 'Forged', values: [{ label: 'x', value: '999' }] } }]
    renderLive(<SourceInspect fact={fact} sources={clinical!.sources} />)
    await userEvent.click(screen.getByText('Zdrojový záznam: měření'))
    expect(document.body).toHaveTextContent('Systolic Blood Pressure118 mm[Hg]')
    expect(document.body).toHaveTextContent('Diastolic Blood Pressure84 mm[Hg]')
    expect(document.body).not.toHaveTextContent('27.24')
    cleanup()
    renderLive(<SourceInspect fact={fact} sources={dup} />)
    await userEvent.click(screen.getByText('Zdrojový záznam'))
    expect(document.body).toHaveTextContent('zdroj není jednoznačný')
    expect(document.body).not.toHaveTextContent('999')
  })
})

describe('SourceInspect in a table cell (dialog)', () => {
  const table = (scopeKey = 'a') => {
    const { clinical } = project([bmi()])
    return <DetailScopeProvider value={{ key: scopeKey, live: true }}><table><tbody><tr><td data-testid="cell">
      <SourceInspect fact={clinical!.domains.measurements[0]!} sources={clinical!.sources} presentation="dialog" />
    </td></tr></tbody></table></DetailScopeProvider>
  }
  it('keeps the cell compact and renders the inspector on <body>, outside the table', async () => {
    render(table())
    const cell = screen.getByTestId('cell')
    expect(cell.querySelector('details, dialog')).toBeNull()
    expect(cell).not.toHaveTextContent('27.24')
    const trigger = within(cell).getByRole('button', { name: 'Zdrojový záznam: měření' })
    await userEvent.click(trigger)
    const dialog = screen.getByRole('dialog', { name: 'Měření: Body Mass Index' })
    expect(dialog.parentElement).toBe(document.body)
    expect(cell.contains(dialog)).toBe(false)
    expect(dialog).toHaveTextContent('27.24 kg/m2')
    expect(document.activeElement).toBe(within(dialog).getByRole('heading'))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Zavřít' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })
  it('Escape (native cancel → close) closes and returns focus to the trigger', async () => {
    render(table())
    const trigger = screen.getByRole('button', { name: 'Zdrojový záznam: měření' })
    await userEvent.click(trigger)
    ;(screen.getByRole('dialog') as HTMLDialogElement).close()
    await screen.findByRole('button', { name: 'Zdrojový záznam: měření' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(trigger)
  })
  it('case/scope change removes an open dialog without pulling focus to the stale trigger', async () => {
    const view = render(table('a'))
    await userEvent.click(screen.getByRole('button', { name: 'Zdrojový záznam: měření' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    const outside = document.createElement('button'); document.body.append(outside); outside.focus()
    view.rerender(table('b'))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(outside)
    outside.remove()
  })
  it('row status text is translated, unknown codes stay literal', () => {
    const { clinical } = project([bmi(), { ...bmi(), id: 'odd', status: 'weird-code' }])
    const texts = clinical!.domains.measurements.map(m => (m.value as { examination: string }).examination)
    expect(texts[0]).toContain('Stav: konečný')
    expect(texts[1]).toContain('Stav: weird-code')
  })
})
