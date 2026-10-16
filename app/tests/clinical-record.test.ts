import { describe, expect, it } from 'vitest'
import { buildAssistantContext } from '../src/assistant/context'
import type { ClinicalFact, IdentityPayload } from '../src/data/clinical'
import { buildMdtPreparation } from '../src/data/mdtPreparation'
import { createClinicalRecord, createPreparationRequirements, SYNTHETIC_MEETING } from '../src/data/mock/clinicalFixtures'
import { AS_OF, createSeedCases } from '../src/data/mock/fixtures'
import { createMockSession } from '../src/data/mock/provider'
import { buildPatientRecord, PATIENT_RECORD_LIMITS } from '../src/data/patientRecord'

describe('clinical demonstration and provider boundary', () => {
  it('covers twelve named domains with explicitly synthetic sources and orthogonal clinical states', () => {
    const r = createClinicalRecord()
    expect(Object.keys(r.domains)).toEqual(['identity', 'personalSocial', 'history', 'medications', 'symptoms', 'measurements', 'labs', 'imagingProcedures', 'oncologyHistology', 'supportiveCare', 'referralContinuity', 'mdtPlan'])
    expect(Object.values(r.domains).every(facts => facts.length > 0)).toBe(true)
    expect(r.sources.every(s => s.ref.sourceId.startsWith('SYNTHETIC-') && s.label.startsWith('SYNTHETIC'))).toBe(true)
    expect(r.domains.history.find(f => f.value.category === 'allergy')?.presence).toBe('denied')
    expect(r.domains.history.some(f => f.verification === 'suspected')).toBe(true)
    expect(r.domains.history.some(f => f.verification === 'confirmed')).toBe(true)
    expect(r.domains.symptoms[0]!.effective.kind).toBe('approximate')
    expect(r.domains.measurements[0]!.effective).toEqual({ kind: 'unknown' })
    expect(r.domains.measurements[1]!.effective).toEqual({ kind: 'month', value: '2026-07' })
    expect(new Set(r.domains.medications.map(f => f.value.statement))).toEqual(new Set(['reported-taking', 'recommended', 'periprocedure-instruction']))
    expect(r.domains.labs[0]!.value.sampleAt).not.toEqual(r.domains.labs[0]!.value.resultAt)
    expect(r.domains.labs[1]!.value.culture?.susceptibility[0]?.result).toBe('not-supplied')
    expect(r.domains.imagingProcedures[0]!.value.biopsy?.sampleCount).toBe(2)
    expect(r.domains.oncologyHistology[1]!.value.ihc).toHaveLength(1)
    expect(JSON.stringify(r)).not.toMatch(/nationalIdentifier|https?:|@|\+420/)
  })

  it('prepares at readCase with coherent dates, excluding late support/conclusion and retaining known future tasks', async () => {
    const { gateway } = createMockSession({ delayMs: 0 })
    const read = await gateway.readCase('novak')
    if (!read.ok) throw new Error(read.error.code)
    const d = read.value
    const p = d.mdt.preparation!
    expect(p.meetingDate).toBe(SYNTHETIC_MEETING.date)
    expect(d.mdt.meetingAt).toBe('2026-10-21')
    expect(d.clinical!.domains.mdtPlan[0]!.value.meetingDate).toEqual({ kind: 'day', value: d.mdt.meetingAt })
    expect(AS_OF).toBe('2026-10-27')
    expect(d.clinical!.sources.every(s => s.locallyAvailable.kind === 'day' && s.locallyAvailable.value <= AS_OF)).toBe(true)
    expect(p.facts.supportiveCare.map(f => f.id)).toEqual(['SYNTHETIC-support-basic'])
    expect(p.facts.mdtPlan.some(f => f.value.kind === 'conclusion')).toBe(false)
    expect(p.taskPlan[0]!.effective).toEqual({ kind: 'day', value: '2026-10-22' })
    for (const factId of ['SYNTHETIC-support-later', 'SYNTHETIC-support-followup']) expect(p.exclusions).toContainEqual({ factId, reason: 'after-cutoff' })
    const apixaban = p.facts.medications.filter(f => f.id.startsWith('SYNTHETIC-apixaban'))
    expect(apixaban).toHaveLength(2)
    expect(apixaban.every(f => f.conflict === 'unresolved' && f.conflictIds.length === 1)).toBe(true)
    expect(Object.isFrozen(p.facts.medications[0]!.value)).toBe(true)
    expect(Object.isFrozen(d.patient.record!.personSupport)).toBe(true)
    expect(d.patient.record!.personSupport.some(f => f.value.description?.includes('až po MDT'))).toBe(true)
  })

  it('other cases have no invented expanded clinical/patient/preparation fallback', async () => {
    const { gateway } = createMockSession({ delayMs: 0 })
    for (const seed of createSeedCases().slice(1)) {
      const read = await gateway.readCase(seed.identity.caseId)
      if (!read.ok) throw new Error(read.error.code)
      expect(read.value.clinical).toBeUndefined()
      expect(read.value.patient.record).toBeUndefined()
      expect(read.value.mdt.preparation).toBeUndefined()
      expect(buildAssistantContext('mdt', read.value, true)).toBeNull()
    }
  })
})

describe('explicit bounded patient projection', () => {
  it('absence is undefined; dates, denial, proposed/reported medication and unchosen conflicts survive', () => {
    expect(buildPatientRecord(undefined)).toBeUndefined()
    const p = buildPatientRecord(createClinicalRecord())!
    expect(p.results[0]!.value).toMatchObject({ value: '25', unit: 'µmol/l', sampleAt: { kind: 'day', value: '2026-10-18' }, resultAt: { kind: 'day', value: '2026-10-20' } })
    expect(p.allergies[0]!.presence).toBe('denied')
    expect(p.history.some(f => f.verification === 'suspected')).toBe(true)
    const meds = p.medications.filter(f => f.value.name.startsWith('Apixaban'))
    expect(meds.map(f => f.value.strength)).toEqual(['2,5 mg', '5 mg'])
    expect(meds.every(f => f.conflict === 'unresolved' && f.value.statement === 'reported-taking')).toBe(true)
    expect(p.medications.some(f => f.value.statement === 'recommended')).toBe(true)
    expect(p.medications.some(f => f.value.statement === 'periprocedure-instruction')).toBe(true)
    expect(p.sharingWishes[0]!.value.state).toBe('recorded')
    expect(p.omittedCount).toBe(0)
  })

  it('excludes identity/internal review/conflict IDs, arbitrary source labels and nested extras', () => {
    const r = createClinicalRecord()
    const poison = 'PRIVATE-ID-REVIEW-SOURCE'
    const identity: ClinicalFact<IdentityPayload> = { ...r.domains.identity[0]!, value: { ...r.domains.identity[0]!.value, name: poison, nationalIdentifier: poison, insuranceIdentifier: poison, address: poison } }
    const labs = r.domains.labs.map(f => ({ ...f, review: 'reviewed' as const, conflictIds: [poison], internalNote: poison,
      effective: { kind: 'day' as const, value: '2026-10-18', privateField: poison }, value: { ...f.value, clinicianOnly: poison } }))
    const p = buildPatientRecord({ ...r, sources: r.sources.map(s => ({ ...s, label: poison, internalReview: poison })), domains: { ...r.domains, identity: [identity], labs } })!
    for (const forbidden of [poison, 'nationalIdentifier', 'insuranceIdentifier', 'conflictIds', 'internalNote', 'internalReview', 'clinicianOnly', 'privateField', 'sourceId', 'reviewed']) expect(JSON.stringify(p)).not.toContain(forbidden)
    expect(p.results[0]!.conflict).toBe('unresolved')
    expect(p.results[0]!.sources[0]!.label).toBe('Dodaný laboratorní zdroj')
    expect(Object.keys(p.results[0]!.sources[0]!).sort()).toEqual(['issued', 'label'])
  })

  it('bounds sections/text without silently truncating clinical values and detaches/freezes recursively', () => {
    const r = structuredClone(createClinicalRecord())
    const lab = r.domains.labs[0]!
    const p = buildPatientRecord({ ...r, domains: { ...r.domains,
      labs: [...Array.from({ length: PATIENT_RECORD_LIMITS.entriesPerSection + 2 }, (_, i) => ({ ...lab, id: `lab-${i}` })), { ...lab, value: { ...lab.value, value: 'x'.repeat(PATIENT_RECORD_LIMITS.text + 1) } }],
    } })!
    expect(p.results).toHaveLength(PATIENT_RECORD_LIMITS.entriesPerSection)
    expect(p.omittedCount).toBe(3)
    expect(p.results[0]!.value).not.toBe(lab.value)
    expect(Object.isFrozen(r)).toBe(false)
    Reflect.set(lab.value, 'test', 'mutated input')
    expect(p.results[0]!.value.test).toBe('Modelový bilirubin')
    const checkFrozen = (v: unknown) => { if (v && typeof v === 'object') { expect(Object.isFrozen(v)).toBe(true); Object.values(v).forEach(checkFrozen) } }
    checkFrozen(p)
  })

  it('missing or ambiguous patient source versions expose uncertainty instead of an unrelated description', () => {
    const r = createClinicalRecord()
    expect(buildPatientRecord({ ...r, sources: [] })!.results[0]).toMatchObject({ sourceStatus: 'unestablished', sources: [] })
    const duplicate = r.sources.find(s => s.ref.sourceId === 'SYNTHETIC-results')!
    expect(buildPatientRecord({ ...r, sources: [...r.sources, duplicate] })!.results[0]).toMatchObject({ sourceStatus: 'unestablished', sources: [] })
  })
})

it('MDT assistant uses only prepared document enums; poisoned live summaries/docs/new clinical fields never enter context', () => {
  const base = createSeedCases()[0]!
  const preparation = buildMdtPreparation({ record: base.clinical!, meetingId: SYNTHETIC_MEETING.id, meetingDate: SYNTHETIC_MEETING.date, requirements: createPreparationRequirements() })
  const poison = 'LATE-PRIVATE-LIVE-CONTENT'
  const detail = { ...base, priorityExplanation: poison,
    documents: base.documents.map(d => ({ ...d, state: 'missing' as const, label: poison, stateLabel: poison, sources: [{ title: poison, date: '2026-10-26' }] })),
    mdt: { ...base.mdt, finding: poison, draft: { decision: poison, uncertainties: [poison] }, preparation }, patient: { ...base.patient, record: buildPatientRecord(base.clinical)! },
  }
  const context = buildAssistantContext('mdt', detail, true)!
  expect(context.fields).toHaveLength(preparation.documents.length)
  expect(context.fields.find(f => f.value.startsWith('Histologie:'))!.value).toBe('Histologie: Dostupné')
  for (const value of [poison, 'Apixaban', 'hads', 'SYNTHETIC', 'sources', 'revision', 'conflict']) expect(JSON.stringify(context)).not.toContain(value)
  expect(buildAssistantContext('mdt', { ...detail, mdt: base.mdt }, true)).toBeNull()
})
