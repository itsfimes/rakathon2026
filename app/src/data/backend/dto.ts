import { array, boolean, condition, document, id, invalid, literal, nullable, number, object, observation, patient, report, text } from './schema'
import type { Decoder } from './schema'
import { validDay } from './values'

export interface Coverage { readonly status: 'complete' | 'unavailable'; readonly serverTotal: number | null; readonly reason: string | null }
export interface Section<T> extends Coverage { readonly items: readonly T[] }
const total: Decoder<number | null> = value => { const n = nullable(number)(value); return n === null || (Number.isSafeInteger(n) && n >= 0) ? n : invalid() }
export function coverage(value: unknown): Coverage {
  const v = object(value)
  const status = v.status === 'complete' || v.status === 'unavailable' ? v.status : invalid()
  const reason = nullable(text)(v.reason)
  if (status === 'complete' ? reason !== null : reason !== 'upstream_unavailable_or_incomplete') invalid()
  return { status, serverTotal: total(v.serverTotal), reason }
}
export function fetchedAt(value: unknown): string {
  const v = text(value)
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(v) && validDay(v.slice(0, 10)) && Number.isFinite(Date.parse(v)) ? v : invalid()
}
export function workspaceDTO(value: unknown) {
  const v = object(value)
  literal(1)(v.version)
  const patients = array(item => {
    const p = object(item)
    return { patientId: id(p.patientId), label: nullable(text)(p.label), birthDate: nullable(text)(p.birthDate) }
  })(v.patients)
  const c = coverage(v.coverage)
  if (new Set(patients.map(p => p.patientId)).size !== patients.length || (c.status === 'unavailable' && patients.length)) invalid()
  return { version: 1 as const, fetchedAt: fetchedAt(v.fetchedAt), patients, coverage: c }
}
function section<T extends { readonly resourceType?: string; readonly id?: string; readonly subject?: { readonly reference?: string } }>(
  value: unknown, decode: Decoder<T>, type: string, patientId: string,
): Section<T> {
  const v = object(value)
  const c = coverage(v)
  array(raw => {
    const item = object(raw)
    for (const key of ['subject', 'patient']) if (Object.hasOwn(item, key) && object(item[key]).reference !== `Patient/${patientId}`) invalid()
    return true
  })(v.items)
  const items = array(decode)(v.items)
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
  return { version: 1 as const, fetchedAt: fetchedAt(v.fetchedAt), patient: p, sections: {
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
  for (const key of ['tasks', 'vectors', 'ingestion', 'screening', 'assistant']) literal(false)(boolean(c[key]))
  const h = object(v.health)
  const health = (x: unknown) => x === 'up' || x === 'down' ? x : invalid()
  return { health: { ipc: health(h.ipc), database: health(h.database) } }
}
export type CaseDTO = ReturnType<typeof caseDTO>
export type WorkspaceDTO = ReturnType<typeof workspaceDTO>
