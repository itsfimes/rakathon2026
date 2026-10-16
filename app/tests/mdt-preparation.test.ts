import { describe, expect, it } from 'vitest'
import type { ClinicalFact, ClinicalRecord, ClinicalSource, ClinicalTime, LabPayload } from '../src/data/clinical'
import { buildMdtPreparation } from '../src/data/mdtPreparation'
import type { PreparationRequirement } from '../src/data/mdtPreparation'

const day = (value: string): ClinicalTime => ({ kind: 'day', value })
const source = (available: ClinicalTime = day('2026-10-20')): ClinicalSource => ({ ref: { sourceId: 'SYNTHETIC-source', version: '1' }, label: 'SYNTHETIC controlled source', issued: day('2026-10-18'), locallyAvailable: available })
const fact = (): ClinicalFact<LabPayload> => ({ id: 'fact-a', value: { test: 'Modelový test', value: '10' }, sources: [source().ref], effective: day('2026-10-01'), knowledge: 'recorded', presence: 'present', verification: 'preliminary', conflictIds: [] })
const record = (facts: readonly ClinicalFact<LabPayload>[] = [fact()], sources: readonly ClinicalSource[] = [source()]): ClinicalRecord => ({ revision: 'revision-1', sources,
  domains: { identity: [], personalSocial: [], history: [], medications: [], symptoms: [], measurements: [], labs: facts, imagingProcedures: [], oncologyHistology: [], supportiveCare: [], referralContinuity: [], mdtPlan: [] } })
const prepare = (r = record(), requirements: readonly ClinicalFact<PreparationRequirement>[] = [], meetingDate = '2026-10-21') => buildMdtPreparation({ record: r, requirements, meetingDate, meetingId: 'SYNTHETIC-meeting' })
const requirement = (state: PreparationRequirement['state'] = 'available'): ClinicalFact<PreparationRequirement> => ({ ...fact(), id: 'requirement-a', value: { documentKind: 'histology', state } })

describe('known-local-availability cutoff in Europe/Prague', () => {
  it.each([
    [day('2026-10-20'), null], [day('2026-10-21'), 'same-day-order-unknown'], [day('2026-10-22'), 'after-cutoff'],
    [{ kind: 'month', value: '2026-09' }, null], [{ kind: 'month', value: '2026-10' }, 'availability-overlaps-cutoff'], [{ kind: 'month', value: '2026-11' }, 'after-cutoff'],
    [{ kind: 'unknown' }, 'availability-unestablished'], [{ kind: 'approximate', label: 'Asi před poradou' }, 'availability-unestablished'],
    [{ kind: 'instant', value: '2026-10-20T21:59:59Z' }, null], [{ kind: 'instant', value: '2026-10-20T22:00:00Z' }, 'same-day-order-unknown'],
    [{ kind: 'instant', value: '2026-10-21T00:15:00+03:00' }, null], [{ kind: 'instant', value: '2026-10-20T23:30:00-02:00' }, 'same-day-order-unknown'],
  ] as const)('availability %j gives %s without machine-timezone assumptions', (available, reason) => {
    const s = { ...source(available), issued: { kind: 'unknown' as const } }
    const result = prepare(record([fact()], [s]))
    expect(result.facts.labs).toHaveLength(reason ? 0 : 1)
    expect(result.exclusions).toEqual(reason ? [{ factId: 'fact-a', reason }] : [])
  })

  it('uses the Prague DST offset on the meeting calendar date, not a constant +02 offset', () => {
    for (const [instant, included] of [['2026-10-25T22:59:59Z', true], ['2026-10-25T23:00:00Z', false]] as const) {
      const r = record([fact()], [source({ kind: 'instant', value: instant })])
      expect(prepare(r, [], '2026-10-26').facts.labs.length).toBe(included ? 1 : 0)
    }
  })

  it.each(['2026-02-29', '2026-04-31', '2026-13-01', '2026-00-01', '2026-01-00', '0000-01-01', '21.10.2026'])('rejects impossible/noncanonical meeting calendar %s without throwing', date => {
    const result = prepare(record(), [requirement()], date)
    expect(result.status).toBe('invalid-meeting-date')
    expect(result.facts.labs).toEqual([])
    expect(result.sources).toEqual([])
    expect(result.requirements).toEqual([])
    expect(result.exclusions.every(item => item.reason === 'invalid-meeting-date')).toBe(true)
  })

  it.each([
    day('2026-02-30'), { kind: 'month', value: '2026-13' },
    { kind: 'instant', value: '2026-02-30T12:00:00Z' }, { kind: 'instant', value: '2026-10-18T24:00:00Z' },
    { kind: 'instant', value: '2026-10-18T12:00:61Z' }, { kind: 'instant', value: '2026-10-18T12:00:00+25:00' },
    { kind: 'instant', value: '2026-10-18T12:00:00' },
  ] as const)('strictly rejects invalid source time %j', available => {
    expect(prepare(record([fact()], [source(available)])).exclusions[0]?.reason).toBe('invalid-source-time')
  })

  it('accepts leap dates, rejects impossible issued/effective dates, and never equates issue with receipt', () => {
    expect(prepare(record([fact()], [{ ...source(day('2024-02-29')), issued: day('2024-02-28') }])).facts.labs).toHaveLength(1)
    expect(prepare(record([fact()], [{ ...source(), issued: day('2026-02-30') }])).exclusions[0]?.reason).toBe('invalid-source-time')
    expect(prepare(record([{ ...fact(), effective: day('2026-02-30') }])).exclusions[0]?.reason).toBe('invalid-effective-time')
    expect(prepare(record([fact()], [source({ kind: 'unknown' })])).exclusions[0]?.reason).toBe('availability-unestablished')
    expect(prepare(record([fact()], [{ ...source(), issued: day('2026-10-21') }])).exclusions[0]?.reason).toBe('contradictory-source-time')
    expect(prepare(record([fact()], [{ ...source({ kind: 'instant', value: '2026-10-20T09:00:00Z' }), issued: { kind: 'instant', value: '2026-10-20T10:00:00Z' } }])).exclusions[0]?.reason).toBe('contradictory-source-time')
  })

  it('old event time does not rescue late receipt; future effective plans and approximate/unknown effective times are allowed', () => {
    expect(prepare(record([fact()], [source(day('2026-10-22'))])).facts.labs).toEqual([])
    for (const effective of [day('2026-11-01'), { kind: 'approximate', label: 'Přibližně v létě' }, { kind: 'unknown' }] as const) {
      const result = prepare(record([{ ...fact(), effective }]))
      expect(result.facts.labs[0]?.effective).toEqual(effective)
    }
  })
})

describe('exact version references and content-free exclusions', () => {
  it('resolves all references, with no fallback to another version or first ambiguous match', () => {
    const a = fact()
    const cases = [
      { facts: [{ ...a, sources: [] }], sources: [source()], reason: 'empty-source-refs' },
      { facts: [{ ...a, sources: undefined } as unknown as ClinicalFact<LabPayload>], sources: [source()], reason: 'empty-source-refs' },
      { facts: [{ ...a, sources: [{ sourceId: '', version: '1' }] }], sources: [source()], reason: 'invalid-source-ref' },
      { facts: [{ ...a, sources: [{ sourceId: 'SYNTHETIC-source', version: '' }] }], sources: [source()], reason: 'invalid-source-ref' },
      { facts: [{ ...a, sources: [a.sources[0]!, a.sources[0]!] }], sources: [source()], reason: 'duplicate-source-ref' },
      { facts: [{ ...a, sources: [{ ...a.sources[0]!, version: '2' }] }], sources: [source()], reason: 'unresolved-source-ref' },
      { facts: [a], sources: [source(), source()], reason: 'ambiguous-source-ref' },
      { facts: [a], sources: [], reason: 'unresolved-source-ref' },
      { facts: [a, { ...a }], sources: [source()], reason: 'ambiguous-fact-id' },
    ]
    for (const item of cases) {
      const result = prepare(record(item.facts, item.sources))
      expect(result.facts.labs).toEqual([])
      expect(result.exclusions[0]?.reason).toBe(item.reason)
    }
    const late = { ...source(day('2026-10-22')), ref: { sourceId: 'second', version: '1' } }
    expect(prepare(record([{ ...a, sources: [...a.sources, late.ref] }], [source(), late])).exclusions[0]?.reason).toBe('after-cutoff')
  })

  it('only referenced eligible source versions survive, with no late values/labels/quotes or excluded partner IDs', () => {
    const late = { ...source(day('2026-10-23')), ref: { sourceId: 'late-version', version: '2' }, label: 'LATE PRIVATE SOURCE NAME' }
    const a = { ...fact(), conflictIds: ['late-fact'] }
    const b = { ...fact(), id: 'late-fact', sources: [late.ref], value: { test: 'LATE CLINICAL VALUE' }, conflictIds: ['fact-a'] }
    const result = prepare(record([a, b], [source(), late, { ...source(), ref: { sourceId: 'unreferenced', version: '1' }, label: 'UNREFERENCED NAME' }]))
    expect(result.facts.labs[0]).toMatchObject({ conflict: 'unresolved', conflictIds: [] })
    expect(result.sources).toEqual([source()])
    expect(result.exclusions).toEqual([{ factId: 'late-fact', reason: 'after-cutoff' }])
    expect(Object.keys(result.exclusions[0]!).sort()).toEqual(['factId', 'reason'])
    for (const value of ['LATE PRIVATE SOURCE NAME', 'LATE CLINICAL VALUE', 'UNREFERENCED NAME', 'late-version']) expect(JSON.stringify(result)).not.toContain(value)
    expect(result.facts.labs[0]!.conflictIds).not.toContain('late-fact')
  })

  it('retains both eligible conflicting statements and all orthogonal clinical states without choosing a truth', () => {
    const a = { ...fact(), knowledge: 'unknown' as const, presence: 'denied' as const, verification: 'suspected' as const, conflictIds: ['fact-b'] }
    const b = { ...fact(), id: 'fact-b', value: { test: 'Different supplied statement' }, conflictIds: ['fact-a'] }
    const result = prepare(record([a, b]))
    expect(result.facts.labs).toHaveLength(2)
    expect(result.facts.labs[0]).toMatchObject({ knowledge: 'unknown', presence: 'denied', verification: 'suspected', conflict: 'unresolved', conflictIds: ['fact-b'] })
    expect(result.facts.labs[1]).toMatchObject({ verification: 'preliminary', conflict: 'unresolved', conflictIds: ['fact-a'] })
  })
})

describe('requirements, immutability and revision', () => {
  it('requires provenanced explicit requirement states; absent evidence is not missing, empty is not complete', () => {
    expect(prepare().counts).toEqual({ total: 0, available: 0, missing: 0, uncertain: 0, completeness: 'unestablished' })
    expect(prepare(record(), [{ ...requirement(), sources: [] }]).counts.completeness).toBe('unestablished')
    expect(prepare(record(), [requirement('missing')]).counts).toEqual({ total: 1, available: 0, missing: 1, uncertain: 0, completeness: 'incomplete' })
    expect(prepare(record(), [requirement()]).counts.completeness).toBe('complete')
    expect(prepare(record(), [{ ...requirement(), knowledge: 'not-recorded' }]).documents).toEqual([{ kind: 'histology', state: 'uncertain' }])
    expect(prepare(record(), [requirement(), { ...requirement(), id: 'unprovenanced', sources: [] }]).counts.completeness).toBe('unestablished')
  })

  it('conflicting requirement states remain uncertain and late requirements leak neither values nor sources', () => {
    const late = { ...source(day('2026-10-22')), ref: { sourceId: 'late-requirement-source', version: '1' }, label: 'LATE REQUIREMENT NAME' }
    const result = prepare(record([fact()], [source(), late]), [requirement(), { ...requirement('missing'), id: 'other' }, { ...requirement(), id: 'late-req', sources: [late.ref] }])
    expect(result.documents).toEqual([{ kind: 'histology', state: 'uncertain' }])
    expect(result.counts).toMatchObject({ total: 2, available: 1, missing: 1, completeness: 'incomplete' })
    expect(result.exclusions).toContainEqual({ factId: 'late-req', reason: 'after-cutoff' })
    expect(JSON.stringify(result)).not.toContain('LATE REQUIREMENT NAME')
  })

  it('returns detached recursively frozen structures without freezing input; revisions depend on input/meeting/policy, not time', () => {
    const mutable = structuredClone(record())
    const result = prepare(mutable, [requirement()])
    expect(Object.isFrozen(mutable)).toBe(false)
    expect(result.facts.labs[0]!.value).not.toBe(mutable.domains.labs[0]!.value)
    Reflect.set(mutable.domains.labs[0]!.value, 'test', 'changed after projection')
    expect(result.facts.labs[0]!.value.test).toBe('Modelový test')
    const assertFrozen = (value: unknown) => {
      if (value && typeof value === 'object') { expect(Object.isFrozen(value)).toBe(true); Object.values(value).forEach(assertFrozen) }
    }
    assertFrozen(result)
    expect(prepare(record()).revision).toBe(prepare(structuredClone(record())).revision)
    expect(prepare({ ...record(), revision: 'new' }).revision).not.toBe(result.revision)
    expect(prepare(record(), [], '2026-10-22').revision).not.toBe(result.revision)
  })
})
