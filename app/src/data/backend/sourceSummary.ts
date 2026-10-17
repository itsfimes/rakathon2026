import type { SourceSummary, SourceSummaryValue } from '../clinical'
import type { Condition, Document, Observation, Patient, Report } from './schema'
import { clinicalTime, conceptText, valueText } from './values'

/** Hard bounds so one odd resource cannot grow the source view. */
export const SOURCE_SUMMARY_LIMITS = Object.freeze({ values: 12, text: 200 })
const cut = (value: string | undefined): string | undefined => {
  const trimmed = value?.trim()
  return trimmed ? trimmed.slice(0, SOURCE_SUMMARY_LIMITS.text) : undefined
}
/** Drops undefined keys so the frozen snapshot carries only supplied fields. */
function compact(summary: { [K in keyof SourceSummary]: SourceSummary[K] | undefined }): SourceSummary {
  return Object.fromEntries(Object.entries(summary).filter(([, value]) => value !== undefined && !(Array.isArray(value) && value.length === 0))) as unknown as SourceSummary
}
function observationValues(r: Observation): SourceSummaryValue[] {
  return [r, ...(r.component ?? [])].flatMap((item, index) => {
    const value = cut(valueText(item))
    if (value === undefined) return []
    const label = cut(conceptText(item.code)) ?? (index === 0 ? 'Hodnota' : 'Složka bez názvu')
    const unit = cut(item.valueQuantity?.unit)
    return [{ label, value, ...(unit ? { unit } : {}) }]
  }).slice(0, SOURCE_SUMMARY_LIMITS.values)
}
export function sourceSummary(r: Patient | Condition | Observation | Report | Document): SourceSummary {
  switch (r.resourceType) {
    case 'Observation': {
      const o = r as Observation
      const laboratory = o.category?.some(c => c.coding?.some(x => x.system === 'http://terminology.hl7.org/CodeSystem/observation-category' && x.code === 'laboratory')) ?? false
      return compact({ kind: laboratory ? 'laboratory' : 'measurement', title: cut(conceptText(o.code)), status: cut(o.status),
        clinicalTime: clinicalTime(o.effectiveDateTime ?? o.effectivePeriod?.start), values: observationValues(o),
        clinicalStatus: undefined, recorded: undefined, resultCount: undefined })
    }
    case 'Condition': {
      const c = r as Condition
      return compact({ kind: 'condition', title: cut(conceptText(c.code)), clinicalStatus: cut(conceptText(c.clinicalStatus)),
        clinicalTime: clinicalTime(c.onsetDateTime ?? c.onsetPeriod?.start), recorded: c.recordedDate ? clinicalTime(c.recordedDate) : undefined,
        status: undefined, values: undefined, resultCount: undefined })
    }
    case 'DiagnosticReport': {
      const d = r as Report
      return compact({ kind: 'report', title: cut(conceptText(d.code)), status: cut(d.status),
        clinicalTime: clinicalTime(d.effectiveDateTime ?? d.effectivePeriod?.start), resultCount: d.result?.length,
        clinicalStatus: undefined, recorded: undefined, values: undefined })
    }
    case 'DocumentReference': {
      const d = r as Document
      return compact({ kind: 'document', title: cut(conceptText(d.type) ?? d.description), status: cut(d.status),
        clinicalTime: clinicalTime(d.context?.period?.start ?? d.date), clinicalStatus: undefined, recorded: undefined, values: undefined, resultCount: undefined })
    }
    default: return { kind: 'patient' }
  }
}
