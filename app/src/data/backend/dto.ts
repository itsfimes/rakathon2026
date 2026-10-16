import { collection, boolean, condition, document, id, invalid, literal, nullable, number, object, observation, patient, report, text } from './schema'
import type { CollectionCoverage, CoverageReason } from '../coverage'
import type { Decoder } from './schema'
import { validDay } from './values'
import { assistantPreviews } from './assistantPreview'

export type Coverage = CollectionCoverage
export interface Section<T> extends Coverage { readonly items: readonly T[] }
const total: Decoder<number | null> = value => { const n = nullable(number)(value); return n === null || (Number.isSafeInteger(n) && n >= 0) ? n : invalid() }
export function coverage(value: unknown): Coverage {
  const v = object(value)
  const status = v.status === 'complete' || v.status === 'unavailable' ? v.status : invalid()
  const reason = nullable(text)(v.reason)
  const reasons: readonly string[] = ['upstream_error', 'auth_failed', 'invalid_response', 'unsafe_paging_link', 'paging_cycle', 'duplicate_resource', 'inconsistent_total', 'deadline_exceeded', 'resource_limit', 'truncated', 'upstream_unavailable_or_incomplete']
  if (status === 'complete' ? reason !== null : reason === null || !reasons.includes(reason)) invalid()
  const counter = (key: string, max: number) => {
    const n = v[key] === undefined ? null : total(v[key])
    return n === null || n <= max ? n : invalid()
  }
  return { status, serverTotal: total(v.serverTotal), reason: reason as CoverageReason | null,
    receivedCount: counter('receivedCount', 500), encounteredCount: counter('encounteredCount', 501), pagesFetched: counter('pagesFetched', 10) }
}
export function fetchedAt(value: unknown): string {
  const v = text(value)
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(v) && validDay(v.slice(0, 10)) && Number.isFinite(Date.parse(v)) ? v : invalid()
}
export function workspaceDTO(value: unknown) {
  const v = object(value)
  literal(1)(v.version)
  const patients = collection(item => {
    const p = object(item)
    return { patientId: id(p.patientId), label: nullable(text)(p.label), birthDate: nullable(text)(p.birthDate) }
  })(v.patients)
  const c = coverage(v.coverage)
  if (c.status === 'complete' && c.receivedCount !== null && c.receivedCount !== patients.length) invalid()
  if (new Set(patients.map(p => p.patientId)).size !== patients.length || (c.status === 'unavailable' && patients.length)) invalid()
  return { version: 1 as const, fetchedAt: fetchedAt(v.fetchedAt), patients, coverage: c }
}
function section<T extends { readonly resourceType?: string; readonly id?: string; readonly subject?: { readonly reference?: string } }>(
  value: unknown, decode: Decoder<T>, type: string, patientId: string,
): Section<T> {
  const v = object(value)
  const c = coverage(v)
  collection(raw => {
    const item = object(raw)
    for (const key of ['subject', 'patient']) if (Object.hasOwn(item, key) && object(item[key]).reference !== `Patient/${patientId}`) invalid()
    return true
  })(v.items)
  if (type === 'Observation') {
    let facts = 0
    for (const raw of v.items as unknown[]) {
      const component = object(raw).component
      if (component !== undefined && (!Array.isArray(component) || component.length > 50)) invalid()
      facts += 1 + (Array.isArray(component) ? component.length : 0)
      if (facts > 1000) invalid()
    }
  }
  const items = collection(decode)(v.items)
  if (c.status === 'complete' && c.receivedCount !== null && c.receivedCount !== items.length) invalid()
  if (c.status === 'unavailable' && items.length) invalid()
  const seen = new Set<string>()
  for (const item of items) {
    if (item.resourceType !== type || !item.id || seen.has(item.id) || item.subject?.reference !== `Patient/${patientId}`) invalid()
    seen.add(item.id)
  }
  return { ...c, items }
}
export function caseDTO(value: unknown, expectedId: string) {
  const v = object(value)
  literal(1)(v.version)
  const p = patient(v.patient)
  if (p.resourceType !== 'Patient' || p.id !== expectedId) invalid()
  const s = object(v.sections)
  return { version: 1 as const, fetchedAt: fetchedAt(v.fetchedAt), patient: p, assistantPreview: assistantPreviews(v.assistantPreview, expectedId), sections: {
    conditions: section(s.conditions, condition, 'Condition', expectedId),
    observations: section(s.observations, observation, 'Observation', expectedId),
    diagnosticReports: section(s.diagnosticReports, report, 'DiagnosticReport', expectedId),
    documents: section(s.documents, document, 'DocumentReference', expectedId),
  } }
}
export function sessionDTO(value: unknown) {
  const v = object(value)
  literal(1)(v.version); literal('single-user-development')(v.access); literal('iris-fhir')(v.storage)
  const c = object(v.capabilities)
  literal(true)(c.workspaceRead); literal(true)(c.caseRead)
  for (const key of ['tasks', 'vectors', 'ingestion', 'screening']) literal(false)(boolean(c[key]))
  const assistant = boolean(c.assistant)
  const h = object(v.health)
  const health = (x: unknown) => x === 'up' || x === 'down' ? x : invalid()
  return { assistant, health: { ipc: health(h.ipc), database: health(h.database) } }
}
export type CaseDTO = ReturnType<typeof caseDTO>
export type WorkspaceDTO = ReturnType<typeof workspaceDTO>
