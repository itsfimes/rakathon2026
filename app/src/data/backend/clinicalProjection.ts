import { freezeClinicalSnapshot } from '../clinical'
import type { ClinicalDomains, ClinicalFact, ClinicalRecord, ClinicalSource, ClinicalTime, HistoryPayload, ImagingProcedurePayload, LabPayload, MeasurementPayload, ReportMetadata, SourceRef } from '../clinical'
import type { CaseDTO } from './dto'
import type { Condition, Document, Observation, Patient, Report } from './schema'
import { ageAt, clinicalTime, codes, conceptText, flag, rangeText, valueText, vitalType } from './values'
import { invalid } from './schema'
import type { CollectionCoverage } from '../coverage'
import { SOURCE_KIND_LABEL, sourceStatusText } from '../sourceText'
import { sourceSummary } from './sourceSummary'

type Resource = Patient | Condition | Observation | Report | Document
const unknown: ClinicalTime = { kind: 'unknown' }
export function patientLabel(p: Patient): string {
  const n = p.name?.[0]
  return n?.text || [...(n?.given ?? []), n?.family].filter(Boolean).join(' ') || 'Jméno neuvedeno'
}
const sourceRef = (r: Resource): SourceRef => ({ sourceId: `${r.resourceType}/${r.id}`, version: r.meta?.versionId || 'unknown' })
/** Opaque local invalidation token, not an identifier or a security credential. */
function revision(fetchedAt: string, resources: readonly Resource[], coverage: unknown): string {
  let a = 2166136261, b = 5381
  for (const char of JSON.stringify({ resources, coverage })) {
    a = Math.imul(a ^ char.charCodeAt(0), 16777619)
    b = Math.imul(b, 33) ^ char.charCodeAt(0)
  }
  return `backend:${fetchedAt}:${(a >>> 0).toString(16)}${(b >>> 0).toString(16)}`
}
function fact<T>(r: Resource, value: T, effective: ClinicalTime, suffix = ''): ClinicalFact<T> {
  return { id: `${r.resourceType}/${r.id}${suffix}`, value, sources: [sourceRef(r)], effective,
    knowledge: 'recorded', presence: 'unspecified', verification: 'unspecified', conflictIds: [] }
}
function conditionFact(r: Condition): ClinicalFact<HistoryPayload> {
  const recognized = new Set(['confirmed', 'provisional', 'differential', 'unconfirmed', 'refuted', 'entered-in-error'])
  const verification = new Set(r.verificationStatus?.coding?.flatMap(c =>
    c.system === 'http://terminology.hl7.org/CodeSystem/condition-ver-status' && c.code && recognized.has(c.code) ? [c.code] : []) ?? [])
  const status = verification.size === 1 ? [...verification][0] : undefined
  const v = status === 'confirmed' ? 'confirmed' : status === 'provisional' ? 'preliminary'
    : status === 'differential' || status === 'unconfirmed' ? 'suspected' : 'unspecified'
  const details = [conceptText(r.code) ?? 'Onemocnění bez uvedeného názvu',
    conceptText(r.clinicalStatus) && `Klinický stav: ${conceptText(r.clinicalStatus)}`,
    conceptText(r.verificationStatus) && `Ověření: ${conceptText(r.verificationStatus)}`,
    conceptText(r.severity) && `Závažnost ze zdroje: ${conceptText(r.severity)}`,
    r.bodySite?.map(conceptText).filter(Boolean).join(' · '),
    r.abatementDateTime && `Ukončení dle zdroje: ${r.abatementDateTime}`,
    r.onsetPeriod?.end && `Konec období začátku: ${r.onsetPeriod.end}`,
    r.recordedDate && `Zaznamenáno: ${r.recordedDate}`,
    r.evidence?.flatMap(e => [...(e.code?.map(conceptText) ?? []), ...(e.detail?.map(d => d.display) ?? [])]).filter(Boolean).join(' · '),
  ].filter(Boolean).join(' · ')
  const onset = clinicalTime(r.onsetDateTime ?? r.onsetPeriod?.start)
  return { ...fact(r, { category: 'condition', description: details, ...(codes(r.code).length ? { code: codes(r.code).join(' · ') } : {}), onset }, onset),
    verification: v, presence: status === 'refuted' ? 'denied' : !status || status === 'entered-in-error' ? 'unspecified' : 'present' }
}
/** Keeps only supplied values; empty lists and blank strings are dropped, never replaced. */
function reportMeta(entries: { [K in keyof ReportMetadata]-?: ReportMetadata[K] | undefined }): ReportMetadata | undefined {
  const meta = Object.fromEntries(Object.entries(entries).filter(([, value]) =>
    value !== undefined && value !== '' && !(Array.isArray(value) && value.length === 0))) as ReportMetadata
  return Object.keys(meta).length ? meta : undefined
}
const listOf = (values: readonly (string | undefined)[] | undefined) => values?.filter((value): value is string => !!value)
const optionalTime = (value: string | undefined) => value ? clinicalTime(value) : undefined
function reportFact(r: Report): ClinicalFact<ImagingProcedurePayload> {
  const effective = clinicalTime(r.effectiveDateTime ?? r.effectivePeriod?.start)
  const conclusion = [r.conclusion, r.conclusionCode?.map(conceptText).filter(Boolean).join(' · ')].filter(Boolean).join(' · ')
  const meta = reportMeta({
    status: r.status, documentStatus: undefined, category: r.category?.map(conceptText).filter(Boolean).join(' · '),
    items: listOf(r.result?.map(x => x.display)),
    attachments: r.presentedForm?.map(a => ({ ...(a.title ? { title: a.title } : {}), ...(a.contentType ? { contentType: a.contentType } : {}),
      ...(a.creation ? { created: clinicalTime(a.creation) } : {}) })).filter(a => Object.keys(a).length),
    authors: undefined, periodEnd: optionalTime(r.effectivePeriod?.end), contentSupplied: undefined,
  })
  return fact(r, { type: conceptText(r.code) ?? 'Zpráva z vyšetření', format: 'text-report', date: effective,
    ...(conclusion ? { conclusion } : {}), ...(meta ? { meta } : {}),
  }, effective)
}
function documentFact(r: Document): ClinicalFact<ImagingProcedurePayload> {
  const attachments = r.content?.map(c => ({ ...(c.attachment?.title ? { title: c.attachment.title } : {}),
    ...(c.attachment?.contentType ? { contentType: c.attachment.contentType } : {}),
    ...(c.format?.display ?? c.format?.code ? { format: (c.format?.display ?? c.format?.code)! } : {}),
    ...(c.attachment?.creation ? { created: clinicalTime(c.attachment.creation) } : {}) })).filter(a => Object.keys(a).length)
  const meta = reportMeta({
    status: r.status, documentStatus: r.docStatus, category: r.category?.map(conceptText).filter(Boolean).join(' · '),
    items: undefined, attachments, authors: listOf(r.author?.map(a => a.display)),
    periodEnd: optionalTime(r.context?.period?.end), contentSupplied: false,
  })
  return fact(r, { type: conceptText(r.type) || r.description || attachments?.[0]?.title || 'Metadata dokumentu', format: 'text-report', date: clinicalTime(r.date),
    ...(r.description ? { findings: r.description } : {}), ...(meta ? { meta } : {}),
  }, clinicalTime(r.context?.period?.start ?? r.date))
}
function observationFacts(r: Observation): { labs: ClinicalFact<LabPayload>[]; measurements: ClinicalFact<MeasurementPayload>[] } {
  const laboratory = r.category?.some(c => c.coding?.some(x => x.system === 'http://terminology.hl7.org/CodeSystem/observation-category' && x.code === 'laboratory')) ?? false
  const effective = clinicalTime(r.effectiveDateTime ?? r.effectivePeriod?.start)
  const labs: ClinicalFact<LabPayload>[] = [], measurements: ClinicalFact<MeasurementPayload>[] = []
  for (const [index, item] of [r, ...(r.component ?? [])].entries()) {
    const label = conceptText(item.code) ?? 'Pozorování bez uvedeného názvu'
    const value = valueText(item)
    const unit = item.valueQuantity?.unit
    const range = rangeText(item)
    if (laboratory) labs.push(fact(r, { test: label, suppliedNote: [r.status && `Stav: ${sourceStatusText(r.status)}`, item.interpretation?.map(conceptText).filter(Boolean).join(' · '),
      conceptText(r.dataAbsentReason), r.effectivePeriod?.end && `Konec období: ${r.effectivePeriod.end}`].filter(Boolean).join(' · '),
      ...(value !== undefined ? { value } : {}), ...(unit !== undefined ? { unit } : {}),
      ...(range ? { referenceRange: range } : {}), ...(flag(item) ? { abnormalFlag: flag(item)! } : {}),
    }, effective, `/${index}`))
    else measurements.push(fact(r, { type: vitalType(item.code), value: value ?? conceptText(r.dataAbsentReason) ?? 'Hodnota neuvedena', ...(unit !== undefined ? { unit } : {}),
      examination: [label, r.category?.map(conceptText).filter(Boolean).join(' · '), r.status && `Stav: ${sourceStatusText(r.status)}`, range && `Rozmezí ze zdroje: ${range}`,
        item.interpretation?.map(conceptText).filter(Boolean).join(' · '), r.dataAbsentReason && conceptText(r.dataAbsentReason),
      ].filter(Boolean).join(' · '),
    }, effective, `/${index}`))
  }
  return { labs, measurements }
}
export function projectClinical(dto: CaseDTO): ClinicalRecord {
  const p = dto.patient, s = dto.sections
  if (s.observations.items.reduce((sum, item) => sum + 1 + (item.component?.length ?? 0), 0) > 1000) invalid()
  const resources = [p, ...s.conditions.items, ...s.observations.items, ...s.diagnosticReports.items, ...s.documents.items]
  const sources: ClinicalSource[] = resources.map(r => {
    const summary = sourceSummary(r)
    return { ref: sourceRef(r), label: summary.title ? `${SOURCE_KIND_LABEL[summary.kind]}: ${summary.title}` : SOURCE_KIND_LABEL[summary.kind], summary,
    issued: clinicalTime('issued' in r ? r.issued : 'date' in r ? r.date : undefined), locallyAvailable: unknown,
  }})
  const age = ageAt(p.birthDate, dto.fetchedAt)
  const observations = s.observations.items.map(observationFacts)
  const domains: ClinicalDomains = {
    identity: [fact(p, { name: patientLabel(p), ...(p.birthDate ? { birthDate: clinicalTime(p.birthDate) } : {}), ...(age !== null ? { age } : {}),
      ...(p.gender ? { sex: p.gender } : {}),
      ...(p.telecom?.length ? { contact: p.telecom.map(t => [t.system, t.value, t.use].filter(Boolean).join(' · ')).join('; ') } : {}),
      ...(p.address?.length ? { address: p.address.map(a => a.text || [...(a.line ?? []), a.city, a.district, a.state, a.postalCode, a.country].filter(Boolean).join(', ')).join('; ') } : {}),
    }, unknown)],
    history: s.conditions.items.map(conditionFact), labs: observations.flatMap(x => x.labs), measurements: observations.flatMap(x => x.measurements),
    imagingProcedures: [...s.diagnosticReports.items.map(reportFact), ...s.documents.items.map(documentFact)],
    medications: [], personalSocial: [], symptoms: [], oncologyHistology: [], supportiveCare: [], referralContinuity: [], mdtPlan: [],
  }
  const coverageOf = (section: CollectionCoverage): CollectionCoverage => ({ status: section.status, reason: section.reason, serverTotal: section.serverTotal,
    receivedCount: section.receivedCount, encounteredCount: section.encounteredCount, pagesFetched: section.pagesFetched })
  const collectionCoverage = { conditions: coverageOf(s.conditions), observations: coverageOf(s.observations), diagnosticReports: coverageOf(s.diagnosticReports), documents: coverageOf(s.documents) }
  return freezeClinicalSnapshot({ revision: revision(dto.fetchedAt, resources, collectionCoverage), sources, domains,
    collectionCoverage,
    coverage: { conditions: s.conditions.status, observations: s.observations.status, diagnosticReports: s.diagnosticReports.status, documents: s.documents.status },
  })
}
