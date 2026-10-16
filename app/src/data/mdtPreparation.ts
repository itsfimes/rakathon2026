import { freezeClinicalSnapshot } from './clinical'
import type { ClinicalDomains, ClinicalFact, ClinicalRecord, ClinicalSource, ClinicalTime, MdtPlanPayload, SourceRef } from './clinical'
import type { CaseDocument, DocumentState } from './contracts'

export interface PreparationRequirement { readonly documentKind: CaseDocument['kind']; readonly state: DocumentState }
export type PreparedFact<T> = ClinicalFact<T> & { readonly conflict: 'none' | 'unresolved' }
export type PreparedDomains = { readonly [K in keyof ClinicalDomains]: readonly PreparedFact<ClinicalDomains[K][number]['value']>[] }
export type PreparationExclusionReason = 'invalid-meeting-date' | 'invalid-effective-time' | 'ambiguous-fact-id' | 'invalid-source-ref'
  | 'empty-source-refs' | 'duplicate-source-ref' | 'unresolved-source-ref' | 'ambiguous-source-ref' | 'invalid-source-time'
  | 'contradictory-source-time' | 'availability-unestablished' | 'same-day-order-unknown' | 'after-cutoff' | 'availability-overlaps-cutoff'
export interface MdtPreparationInput {
  readonly record: ClinicalRecord
  readonly meetingId: string
  readonly meetingDate: string
  readonly requirements: readonly ClinicalFact<PreparationRequirement>[]
}
export interface MdtPreparation {
  readonly revision: string
  readonly meetingId: string
  readonly meetingDate: string
  readonly policy: { readonly id: 'before-meeting-day-v1'; readonly timeZone: 'Europe/Prague'; readonly description: string }
  readonly status: 'ready' | 'invalid-meeting-date'
  readonly facts: PreparedDomains
  readonly sources: readonly ClinicalSource[]
  readonly requirements: readonly PreparedFact<PreparationRequirement>[]
  readonly documents: readonly { readonly kind: CaseDocument['kind']; readonly state: DocumentState }[]
  readonly counts: { readonly total: number; readonly available: number; readonly missing: number; readonly uncertain: number; readonly completeness: 'complete' | 'incomplete' | 'unestablished' }
  readonly taskPlan: readonly PreparedFact<MdtPlanPayload>[]
  readonly exclusions: readonly { readonly factId: string; readonly reason: PreparationExclusionReason }[]
  readonly limitations: readonly string[]
}

interface TimeRange { readonly first: string; readonly last: string; readonly instant?: number }
const monthDays = (year: number, month: number) => [31, year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1] ?? 0
const validDay = (value: string) => {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number) as [number, number, number]
  return year > 0 && month >= 1 && month <= 12 && day >= 1 && day <= monthDays(year, month)
}
const pragueDay = new Intl.DateTimeFormat('en-CA-u-ca-iso8601', { timeZone: 'Europe/Prague', year: 'numeric', month: '2-digit', day: '2-digit' })

function timeRange(time: ClinicalTime): TimeRange | 'invalid' | 'unestablished' {
  if (!time || typeof time !== 'object') return 'invalid'
  if (time.kind === 'unknown' || time.kind === 'approximate') return 'unestablished'
  if (time.kind === 'day') return validDay(time.value) ? { first: time.value, last: time.value } : 'invalid'
  if (time.kind === 'month') {
    if (!/^\d{4}-\d{2}$/.test(time.value) || !validDay(`${time.value}-01`)) return 'invalid'
    const [year, month] = time.value.split('-').map(Number) as [number, number]
    return { first: `${time.value}-01`, last: `${time.value}-${monthDays(year, month)}` }
  }
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.\d{1,3})?)?(Z|[+-]\d{2}:\d{2})$/.exec(time.value)
  if (!match || !validDay(match[1]!) || Number(match[2]) > 23 || Number(match[3]) > 59 || Number(match[4] ?? 0) > 59) return 'invalid'
  const offset = match[5]!
  if (offset !== 'Z' && (Number(offset.slice(1, 3)) > 23 || Number(offset.slice(4)) > 59)) return 'invalid'
  const instant = Date.parse(time.value)
  if (!Number.isFinite(instant)) return 'invalid'
  const parts = pragueDay.formatToParts(instant)
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find(item => item.type === type)!.value
  const day = `${part('year').padStart(4, '0')}-${part('month')}-${part('day')}`
  return validDay(day) ? { first: day, last: day, instant } : 'invalid'
}

const refKey = (ref: SourceRef) => JSON.stringify([ref.sourceId, ref.version])
const validRef = (ref: SourceRef) => !!ref && typeof ref.sourceId === 'string' && !!ref.sourceId.trim() && typeof ref.version === 'string' && !!ref.version.trim()

function sourceExclusion(source: ClinicalSource, meetingDate: string): PreparationExclusionReason | null {
  const available = timeRange(source.locallyAvailable)
  const issued = timeRange(source.issued)
  if (available === 'invalid' || issued === 'invalid') return 'invalid-source-time'
  if (available === 'unestablished') return 'availability-unestablished'
  if (issued !== 'unestablished' && (issued.first > available.last || (issued.instant !== undefined && available.instant !== undefined && issued.instant > available.instant))) return 'contradictory-source-time'
  if (available.last < meetingDate) return null
  if (available.first === meetingDate && available.last === meetingDate) return 'same-day-order-unknown'
  return available.first > meetingDate ? 'after-cutoff' : 'availability-overlaps-cutoff'
}

/** Conservative date-only snapshot. No live text summaries, wall clock or effective-time cutoff. */
export function buildMdtPreparation(input: MdtPreparationInput): MdtPreparation {
  const { record, meetingId, meetingDate, requirements } = input
  const sources = new Map<string, ClinicalSource[]>()
  for (const source of record.sources) {
    if (!validRef(source.ref)) continue
    const key = refKey(source.ref)
    sources.set(key, [...(sources.get(key) ?? []), source])
  }
  const all: readonly ClinicalFact<unknown>[] = [...Object.values(record.domains).flat(), ...requirements]
  const idCounts = new Map<string, number>()
  all.forEach(fact => idCounts.set(fact.id, (idCounts.get(fact.id) ?? 0) + 1))
  const reasons = new Map<ClinicalFact<unknown>, PreparationExclusionReason>()
  const eligibleIds = new Set<string>()
  for (const fact of all) {
    let reason: PreparationExclusionReason | null = !validDay(meetingDate) ? 'invalid-meeting-date'
      : !fact.id.trim() || idCounts.get(fact.id)! > 1 ? 'ambiguous-fact-id'
        : timeRange(fact.effective) === 'invalid' ? 'invalid-effective-time'
          : !Array.isArray(fact.sources) || fact.sources.length === 0 ? 'empty-source-refs' : null
    const refs = new Set<string>()
    for (const ref of Array.isArray(fact.sources) ? fact.sources : []) {
      if (reason) break
      if (!validRef(ref)) { reason = 'invalid-source-ref'; break }
      const key = refKey(ref)
      if (refs.has(key)) { reason = 'duplicate-source-ref'; break }
      refs.add(key)
      const versions = sources.get(key)
      reason = !versions ? 'unresolved-source-ref' : versions.length !== 1 ? 'ambiguous-source-ref' : sourceExclusion(versions[0]!, meetingDate)
    }
    if (reason) reasons.set(fact, reason)
    else eligibleIds.add(fact.id)
  }
  const project = <T,>(facts: readonly ClinicalFact<T>[]): readonly PreparedFact<T>[] => facts.filter(fact => !reasons.has(fact)).map(fact => ({
    id: fact.id, value: fact.value, sources: fact.sources, effective: fact.effective, knowledge: fact.knowledge, presence: fact.presence,
    verification: fact.verification, ...(fact.review ? { review: fact.review } : {}),
    conflictIds: fact.conflictIds.filter(id => eligibleIds.has(id)), conflict: fact.conflictIds.length ? 'unresolved' : 'none',
  }))
  const d = record.domains
  const facts: PreparedDomains = {
    identity: project(d.identity), personalSocial: project(d.personalSocial), history: project(d.history), medications: project(d.medications),
    symptoms: project(d.symptoms), measurements: project(d.measurements), labs: project(d.labs), imagingProcedures: project(d.imagingProcedures),
    oncologyHistology: project(d.oncologyHistology), supportiveCare: project(d.supportiveCare), referralContinuity: project(d.referralContinuity), mdtPlan: project(d.mdtPlan),
  }
  const projectedRequirements = project(requirements)
  const requirementState = (fact: PreparedFact<PreparationRequirement>): DocumentState => fact.knowledge === 'recorded' && fact.presence === 'present' && fact.conflict === 'none' ? fact.value.state : 'uncertain'
  const states = projectedRequirements.map(requirementState)
  const counts = { total: states.length, available: states.filter(state => state === 'available').length,
    missing: states.filter(state => state === 'missing').length, uncertain: states.filter(state => state === 'uncertain').length }
  const documents = new Map<CaseDocument['kind'], DocumentState>()
  projectedRequirements.forEach(fact => {
    const kind = fact.value.documentKind
    const state = requirementState(fact)
    const previous = documents.get(kind)
    documents.set(kind, previous !== undefined && previous !== state ? 'uncertain' : state)
  })
  const referenced = new Set([...Object.values(facts).flat(), ...projectedRequirements].flatMap(fact => fact.sources.map(refKey)))
  return freezeClinicalSnapshot({
    revision: JSON.stringify([record.revision, meetingId, meetingDate, 'before-meeting-day-v1', 'Europe/Prague']), meetingId, meetingDate,
    policy: { id: 'before-meeting-day-v1', timeZone: 'Europe/Prague', description: 'Pouze prokazatelně místně dostupné před dnem porady; pořadí událostí v den porady neznáme.' },
    status: validDay(meetingDate) ? 'ready' : 'invalid-meeting-date', facts,
    sources: record.sources.filter(source => validRef(source.ref) && referenced.has(refKey(source.ref))), requirements: projectedRequirements,
    documents: [...documents].map(([kind, state]) => ({ kind, state })),
    counts: { ...counts, completeness: counts.missing ? 'incomplete' : !counts.total || counts.uncertain || projectedRequirements.length !== requirements.length ? 'unestablished' : 'complete' },
    taskPlan: facts.mdtPlan.filter(fact => fact.value.kind === 'task' || fact.value.kind === 'appointment' || fact.value.kind === 'recommendation'),
    exclusions: all.flatMap(fact => reasons.has(fact) ? [{ factId: fact.id, reason: reasons.get(fact)! }] : []),
    limitations: ['Datum porady nemá známý čas. Konzervativní hranice není klinické schválení.', 'Neznámá dostupnost není důkaz chybějícího výsledku. Neprovádí se klinická interpretace ani řešení rozporů.'],
  })
}
