import type { ClinicalTime, LabPayload, MeasurementPayload } from '../clinical'
import type { Concept, ObservationValue, Quantity } from './schema'

export function validDay(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [y, m, d] = value.split('-').map(Number) as [number, number, number]
  const date = new Date(0)
  date.setUTCFullYear(y, m - 1, d); date.setUTCHours(0, 0, 0, 0)
  return y > 0 && date.getUTCFullYear() === y && date.getUTCMonth() === m - 1 && date.getUTCDate() === d
}
export function ageAt(birth: string | null | undefined, fetched: string): number | null {
  const day = fetched.slice(0, 10)
  if (!birth || !validDay(birth) || !validDay(day) || birth > day) return null
  return Number(day.slice(0, 4)) - Number(birth.slice(0, 4)) - (day.slice(5) < birth.slice(5) ? 1 : 0)
}
export function clinicalTime(value: string | undefined): ClinicalTime {
  if (!value) return { kind: 'unknown' }
  if (validDay(value)) return { kind: 'day', value }
  if (/^\d{4}-(0[1-9]|1[0-2])$/.test(value) && Number(value.slice(0, 4)) > 0) return { kind: 'month', value }
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && validDay(value.slice(0, 10)) && Number.isFinite(Date.parse(value))) return { kind: 'instant', value }
  return { kind: 'approximate', label: value }
}
export const conceptText = (v: Concept | undefined): string | undefined => v?.text || v?.coding?.map(c => c.display || c.code).filter(Boolean).join(' · ') || undefined
export const codes = (v: Concept | undefined): readonly string[] => v?.coding?.flatMap(c => c.code ? [c.code] : []) ?? []
export const quantityText = (q: Quantity | undefined): string | undefined => q?.value === undefined ? undefined : `${q.value}${q.unit ? ` ${q.unit}` : ''}`
export function valueText(v: ObservationValue): string | undefined {
  if (v.valueQuantity?.value !== undefined) return String(v.valueQuantity.value)
  if (v.valueString !== undefined) return v.valueString
  if (v.valueBoolean !== undefined) return v.valueBoolean ? 'true' : 'false'
  if (v.valueInteger !== undefined) return String(v.valueInteger)
  if (v.valueCodeableConcept) return conceptText(v.valueCodeableConcept)
  if (v.valueRange) return [quantityText(v.valueRange.low), quantityText(v.valueRange.high)].filter(x => x !== undefined).join(' – ')
  if (v.valueRatio) return [quantityText(v.valueRatio.numerator), quantityText(v.valueRatio.denominator)].filter(x => x !== undefined).join(' / ')
  return undefined
}
export function rangeText(v: ObservationValue): string | undefined {
  return v.referenceRange?.map(r => [r.text, quantityText(r.low), quantityText(r.high), conceptText(r.type)].filter(Boolean).join(' · ')).join('; ') || undefined
}
export function flag(v: ObservationValue): LabPayload['abnormalFlag'] {
  const map: Record<string, NonNullable<LabPayload['abnormalFlag']>> = { H: 'high', HH: 'high', L: 'low', LL: 'low', N: 'normal', A: 'abnormal', AA: 'abnormal' }
  const known = v.interpretation?.flatMap(c => c.coding?.filter(x => x.system === 'http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation').flatMap(x => x.code && map[x.code] ? [map[x.code]!] : []) ?? []) ?? []
  return new Set(known).size === 1 ? known[0] : undefined
}
export function vitalType(v: Concept | undefined): MeasurementPayload['type'] {
  const map: Record<string, MeasurementPayload['type']> = { '8302-2': 'height', '29463-7': 'weight', '85354-9': 'blood-pressure', '8480-6': 'blood-pressure', '8462-4': 'blood-pressure', '8867-4': 'pulse', '8310-5': 'temperature' }
  return v?.coding?.find(c => c.system === 'http://loinc.org' && c.code && map[c.code])?.code
    ? map[v.coding.find(c => c.system === 'http://loinc.org' && c.code && map[c.code])!.code!]! : 'examination'
}
