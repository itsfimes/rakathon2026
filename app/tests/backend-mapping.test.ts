import { describe, expect, it } from 'vitest'
import { caseDTO } from '../src/data/backend/dto'
import { projectCase } from '../src/data/backend/projection'
import { caseResponse, complete, resource } from './backend-fixtures'

const verificationSystem = 'http://terminology.hl7.org/CodeSystem/condition-ver-status'

describe('backend clinical mapping provenance regressions', () => {
  it.each(['dateTime', 'period'] as const)('keeps effective %s distinct from specimen collection and report production', precision => {
    const raw = caseResponse()
    raw.sections.observations = complete([{ ...resource('Observation'), code: { text: 'Synthetic laboratory test' },
      category: [{ coding: [{ system: 'http://terminology.hl7.org/CodeSystem/observation-category', code: 'laboratory' }] }],
      ...(precision === 'dateTime' ? { effectiveDateTime: '2025-03-04T09:00:00Z' } : { effectivePeriod: { start: '2025-03-04T09:00:00Z', end: '2025-03-05T09:00:00Z' } }),
      issued: '2025-03-06T10:00:00Z', valueQuantity: { value: 0, unit: 'synthetic unit' },
    }])
    const detail = projectCase(caseDTO(raw, 'synthetic-0'))
    const fact = detail.clinical!.domains.labs[0]!
    expect(fact.effective).toEqual({ kind: 'instant', value: '2025-03-04T09:00:00Z' })
    expect(fact.value).not.toHaveProperty('sampleAt')
    expect(fact.value).not.toHaveProperty('resultAt')
    expect(JSON.stringify(fact.value)).not.toContain('Odběr')
    const source = detail.clinical!.sources.find(item => item.ref.sourceId === fact.sources[0]!.sourceId)!
    expect(source.issued).toEqual({ kind: 'instant', value: '2025-03-06T10:00:00Z' })
    const patientResult = detail.patient.record!.results[0]!
    expect(patientResult.effective).toEqual(fact.effective)
    expect(patientResult.value.sampleAt).toBeUndefined()
    expect(patientResult.value.resultAt).toBeUndefined()
    expect(patientResult.sources[0]!.issued).toEqual(source.issued)
  })

  it('uses only supplied display labels from structured references without redacting literal clinical text', () => {
    const raw = caseResponse()
    raw.sections.conditions = complete([{ ...resource('Condition'), code: { text: 'Synthetic supplied condition' }, evidence: [{
      code: [{ text: 'Synthetic evidence finding' }], detail: [
        { reference: 'Observation/synthetic-evidence-machine-id' },
        { reference: 'Observation/synthetic-evidence-labelled-id', display: 'Synthetic evidence display' },
      ],
    }] }])
    raw.sections.diagnosticReports = complete([{ ...resource('DiagnosticReport'), code: { text: 'Synthetic report' },
      conclusion: 'Literal supplied finding mentioning Observation/literal-clinical-text', result: [
        { reference: 'Observation/synthetic-result-machine-id' },
        { reference: 'Observation/synthetic-result-labelled-id', display: 'Synthetic result display' },
      ],
    }])
    raw.sections.documents = complete([{ ...resource('DocumentReference'), description: 'Synthetic supplied document description', author: [
      { reference: 'Practitioner/synthetic-author-machine-id' },
      { reference: 'Practitioner/synthetic-author-labelled-id', display: 'Synthetic author display' },
    ] }])
    const dto = caseDTO(raw, 'synthetic-0')
    expect(dto.sections.conditions.items[0]!.evidence![0]!.detail![0]!.reference).toBe('Observation/synthetic-evidence-machine-id')
    const detail = projectCase(dto)
    const prose = JSON.stringify({ history: detail.patient.record!.history, reports: detail.patient.record!.reports })
    for (const id of ['synthetic-evidence-machine-id', 'synthetic-evidence-labelled-id', 'synthetic-result-machine-id', 'synthetic-result-labelled-id', 'synthetic-author-machine-id', 'synthetic-author-labelled-id']) expect(prose).not.toContain(id)
    for (const literal of ['Synthetic supplied condition', 'Synthetic evidence finding', 'Synthetic evidence display', 'Synthetic result display',
      'Synthetic author display', 'Synthetic supplied document description', 'Literal supplied finding mentioning Observation/literal-clinical-text']) expect(prose).toContain(literal)
    expect(detail.clinical!.domains.imagingProcedures[0]!.value.findings).toContain('Synthetic result display')
  })

  it.each([
    { label: 'custom confirmed', coding: [{ system: 'https://synthetic.example/status', code: 'confirmed', display: 'Synthetic custom confirmed label' }] },
    { label: 'custom refuted', coding: [{ system: 'https://synthetic.example/status', code: 'refuted', display: 'Synthetic custom refuted label' }] },
    { label: 'missing-system confirmed', coding: [{ code: 'confirmed' }] },
    { label: 'missing-system refuted', coding: [{ code: 'refuted' }] },
    { label: 'contradictory recognized codes', coding: [{ system: verificationSystem, code: 'confirmed' }, { system: verificationSystem, code: 'refuted' }] },
  ])('$label cannot imply confirmation or denial and retains literal supplied status information', ({ coding }) => {
    const raw = caseResponse()
    raw.sections.conditions = complete([{ ...resource('Condition'), code: { text: 'Synthetic condition' },
      clinicalStatus: { coding: [{ code: 'active' }] }, verificationStatus: { coding },
    }])
    const detail = projectCase(caseDTO(raw, 'synthetic-0'))
    const fact = detail.clinical!.domains.history[0]!
    expect(fact.verification).toBe('unspecified')
    expect(fact.presence).toBe('unspecified')
    expect(fact.value.description).toContain('Klinický stav: active')
    for (const item of coding) expect(fact.value.description).toContain('display' in item ? item.display : item.code)
    expect(detail.patient.record!.history[0]!.verification).toBe('unspecified')
    expect(detail.patient.record!.history[0]!.presence).toBe('unspecified')
  })

  it.each([
    { code: 'confirmed', verification: 'confirmed', presence: 'present' },
    { code: 'refuted', verification: 'unspecified', presence: 'denied' },
    { code: 'provisional', verification: 'preliminary', presence: 'present' },
    { code: 'differential', verification: 'suspected', presence: 'present' },
    { code: 'entered-in-error', verification: 'unspecified', presence: 'unspecified' },
  ])('recognizes only unambiguous standard verification $code', ({ code, verification, presence }) => {
    const raw = caseResponse()
    raw.sections.conditions = complete([{ ...resource('Condition'), verificationStatus: { coding: [
      { system: verificationSystem, code }, { system: verificationSystem, code },
    ] } }])
    const fact = projectCase(caseDTO(raw, 'synthetic-0')).clinical!.domains.history[0]!
    expect(fact.verification).toBe(verification)
    expect(fact.presence).toBe(presence)
  })
})
