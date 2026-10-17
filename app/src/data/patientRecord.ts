import { freezeClinicalSnapshot } from './clinical'
import type { ClinicalCoverage, ClinicalFact, ClinicalRecord, ClinicalTime, HistoryPayload, MeasurementPayload, MedicationPayload, SourceRef } from './clinical'

export interface PatientSourceDescription { readonly label: string; readonly issued: ClinicalTime }
export interface PatientRecordEntry<T> {
  readonly value: T
  readonly effective: ClinicalTime
  readonly sources: readonly PatientSourceDescription[]
  readonly sourceStatus: 'resolved' | 'unestablished'
  readonly knowledge: 'recorded' | 'unknown' | 'not-recorded'
  readonly presence: 'present' | 'denied' | 'unspecified'
  readonly verification: 'suspected' | 'preliminary' | 'confirmed' | 'unspecified'
  readonly conflict: 'none' | 'unresolved'
}
export interface PatientResult {
  readonly suppliedNote?: string | undefined
  readonly test: string
  readonly value?: string | undefined
  readonly unit?: string | undefined
  readonly referenceRange?: string | undefined
  readonly abnormalFlag?: string | undefined
  readonly sampleAt?: ClinicalTime | undefined
  readonly resultAt?: ClinicalTime | undefined
  readonly sediment?: string | undefined
  readonly culture?: { readonly organism: string; readonly quantity?: string | undefined; readonly susceptibility: readonly { readonly agent: string; readonly result: string; readonly mic?: string | undefined; readonly unit?: string | undefined }[] } | undefined
}
export interface PatientMedication {
  readonly name: string
  readonly strength?: string | undefined
  readonly dose?: string | undefined
  readonly frequency?: string | undefined
  readonly schedule?: MedicationPayload['schedule']
  readonly statement: MedicationPayload['statement']
  readonly suppliedIndication?: string | undefined
  readonly instruction?: string | undefined
  readonly stopAt?: ClinicalTime | undefined
  readonly restartAt?: ClinicalTime | undefined
  readonly courseStart?: ClinicalTime | undefined
  readonly courseEnd?: ClinicalTime | undefined
  readonly recommendedChange?: string | undefined
  readonly interaction?: string | undefined
}
export interface PatientReport { readonly type: string; readonly finding?: string | undefined; readonly conclusion?: string | undefined; readonly date?: ClinicalTime | undefined }
export interface PatientHistory { readonly category: HistoryPayload['category']; readonly description: string; readonly code?: string | undefined; readonly onset?: ClinicalTime | undefined }
export interface PatientPersonSupport {
  readonly description?: string | undefined
  readonly maritalStatus?: string | undefined
  readonly livingSituation?: string | undefined
  readonly support?: string | undefined
  readonly occupation?: string | undefined
  readonly sickLeave?: string | undefined
  readonly smoking?: string | undefined
  readonly alcohol?: string | undefined
  readonly independence?: string | undefined
  readonly reportedAnxiety?: string | undefined
  readonly supportNeed?: string | undefined
  readonly psychologyConclusion?: string | undefined
  readonly psychotherapyRecommendation?: string | undefined
  readonly psychiatryRecommendation?: string | undefined
  readonly painFollowup?: string | undefined
}
export interface PatientSymptom {
  readonly type: string
  readonly site?: string | undefined
  readonly character?: string | undefined
  readonly onset?: ClinicalTime | undefined
  readonly course?: string | undefined
  readonly fever?: boolean | undefined
  readonly jaundice?: boolean | undefined
  readonly darkUrine?: boolean | undefined
  readonly appetite?: string | undefined
  readonly nausea?: boolean | undefined
  readonly weightLoss?: string | undefined
  readonly sleep?: string | undefined
  readonly function?: string | undefined
  readonly nrs?: number | undefined
}
export interface PatientMeasurement {
  readonly type: MeasurementPayload['type']
  readonly value: string
  readonly unit?: string | undefined
  readonly examination?: string | undefined
}
export interface PatientSharingWish { readonly text: string; readonly state: 'recorded' | 'declined' | 'unknown'; readonly scope?: string | undefined; readonly recordedAt?: ClinicalTime | undefined }
export interface PatientRecord {
  readonly coverage?: ClinicalCoverage
  readonly collectionCoverage?: ClinicalRecord['collectionCoverage']
  readonly revision: string
  readonly results: readonly PatientRecordEntry<PatientResult>[]
  readonly reports: readonly PatientRecordEntry<PatientReport>[]
  readonly medications: readonly PatientRecordEntry<PatientMedication>[]
  readonly history: readonly PatientRecordEntry<PatientHistory>[]
  readonly allergies: readonly PatientRecordEntry<PatientHistory>[]
  readonly symptoms: readonly PatientRecordEntry<PatientSymptom>[]
  readonly measurements: readonly PatientRecordEntry<PatientMeasurement>[]
  readonly personSupport: readonly PatientRecordEntry<PatientPersonSupport>[]
  readonly sharingWishes: readonly PatientRecordEntry<PatientSharingWish>[]
  readonly omittedCount: number
  readonly limitations: readonly string[]
}
export const PATIENT_RECORD_LIMITS = Object.freeze({ entriesPerSection: 40, text: 2000, nestedEntries: 20 })

function patientTime(value: ClinicalTime): ClinicalTime {
  if (value.kind === 'unknown') return { kind: 'unknown' }
  if (value.kind === 'approximate') return { kind: 'approximate', label: value.label }
  return { kind: value.kind, value: value.value }
}
const optionalTime = (value: ClinicalTime | undefined) => value ? patientTime(value) : undefined

/** Explicit DTO, not a clinician object spread. No identity IDs, internal review or conflict IDs. */
export function buildPatientRecord(record: ClinicalRecord | undefined): PatientRecord | undefined {
  if (!record) return undefined
  const entriesPerSection = record.collectionCoverage ? 1000 : PATIENT_RECORD_LIMITS.entriesPerSection
  let omittedCount = 0
  const resolve = (ref: SourceRef) => record.sources.filter(source => source.ref.sourceId === ref.sourceId && source.ref.version === ref.version)
  const entry = <T,>(fact: ClinicalFact<unknown>, value: T, label: string): PatientRecordEntry<T> => {
    const resolved = fact.sources.map(resolve)
    return { value, effective: patientTime(fact.effective),
      sources: resolved.flatMap(matches => matches.length === 1 ? [{ label, issued: patientTime(matches[0]!.issued) }] : []),
      sourceStatus: resolved.length > 0 && resolved.every(matches => matches.length === 1) ? 'resolved' : 'unestablished',
      knowledge: fact.knowledge, presence: fact.presence, verification: fact.verification, conflict: fact.conflictIds.length ? 'unresolved' : 'none',
    }
  }
  const bounded = (value: unknown): boolean => {
    if (typeof value === 'string') return value.length <= PATIENT_RECORD_LIMITS.text
    if (Array.isArray(value)) return value.length <= PATIENT_RECORD_LIMITS.nestedEntries && value.every(bounded)
    return !value || typeof value !== 'object' || Object.values(value).every(bounded)
  }
  const section = <T,>(entries: readonly PatientRecordEntry<T>[]) => entries.filter(item => {
    if (bounded(item)) return true
    omittedCount++
    return false
  }).filter((_item, index) => {
    if (index < entriesPerSection) return true
    omittedCount++
    return false
  })
  const d = record.domains
  const results = section(d.labs.map(fact => {
    const v = fact.value
    return entry<PatientResult>(fact, { test: v.test, value: v.value, unit: v.unit, referenceRange: v.referenceRange, abnormalFlag: v.abnormalFlag, suppliedNote: v.suppliedNote,
      sampleAt: optionalTime(v.sampleAt), resultAt: optionalTime(v.resultAt), sediment: v.sediment,
      culture: v.culture ? { organism: v.culture.organism, quantity: v.culture.quantity, susceptibility: v.culture.susceptibility.map(item => ({ agent: item.agent, result: item.result, mic: item.mic, unit: item.unit })) } : undefined,
    }, 'Dodaný laboratorní zdroj')
  }))
  const reports = section([
    ...d.imagingProcedures.map(fact => entry<PatientReport>(fact, { type: fact.value.type, finding: fact.value.findings, conclusion: fact.value.conclusion, date: optionalTime(fact.value.date) }, 'Dodaný zprávový zdroj')),
    ...d.oncologyHistology.map(fact => entry<PatientReport>(fact, { type: fact.value.kind, finding: fact.value.description, conclusion: fact.value.staging, date: optionalTime(fact.value.reportAt) }, 'Dodaný histologický nebo odborný zdroj')),
  ])
  const medications = section(d.medications.map(fact => {
    const v = fact.value
    return entry<PatientMedication>(fact, { name: v.name, strength: v.strength, dose: v.dose, frequency: v.frequency, schedule: v.schedule, statement: v.statement,
      suppliedIndication: v.suppliedIndication, instruction: v.instruction, stopAt: optionalTime(v.stopAt), restartAt: optionalTime(v.restartAt),
      courseStart: optionalTime(v.courseStart), courseEnd: optionalTime(v.courseEnd), recommendedChange: v.recommendedChange, interaction: v.interaction,
    }, 'Dodaný lékový záznam')
  }))
  const historyEntry = (fact: ClinicalFact<HistoryPayload>) => entry<PatientHistory>(fact, { category: fact.value.category, description: fact.value.description, code: fact.value.code, onset: optionalTime(fact.value.onset) }, 'Dodaný anamnestický zdroj')
  const history = section(d.history.filter(fact => fact.value.category !== 'allergy').map(historyEntry))
  const allergies = section(d.history.filter(fact => fact.value.category === 'allergy').map(historyEntry))
  const symptoms = section(d.symptoms.map(fact => {
    const v = fact.value
    return entry<PatientSymptom>(fact, { type: v.type, site: v.site, character: v.character, onset: optionalTime(v.onset), course: v.course,
      fever: v.fever, jaundice: v.jaundice, darkUrine: v.darkUrine, appetite: v.appetite, nausea: v.nausea, weightLoss: v.weightLoss,
      sleep: v.sleep, function: v.function, nrs: v.nrs,
    }, 'Dodaný záznam o obtížích')
  }))
  const measurements = section(d.measurements.map(fact => entry<PatientMeasurement>(fact,
    { type: fact.value.type, value: fact.value.value, unit: fact.value.unit, examination: fact.value.examination }, 'Dodaný záznam měření')))
  const personSupport = section([
    ...d.personalSocial.map(fact => {
      const v = fact.value
      return entry<PatientPersonSupport>(fact, { maritalStatus: v.maritalStatus, livingSituation: v.livingSituation, support: v.support, occupation: v.occupation, sickLeave: v.sickLeave, smoking: v.smoking, alcohol: v.alcohol, independence: v.independence }, 'Dodaný osobní a sociální záznam')
    }),
    ...d.supportiveCare.map(fact => {
      const v = fact.value
      return entry<PatientPersonSupport>(fact, { description: v.description, reportedAnxiety: v.reportedAnxiety, supportNeed: v.supportNeed, psychologyConclusion: v.psychologyConclusion, psychotherapyRecommendation: v.psychotherapyRecommendation, psychiatryRecommendation: v.psychiatryRecommendation, painFollowup: v.painFollowup }, 'Dodaný záznam podpory')
    }),
  ])
  const sharingWishes = section(d.identity.flatMap(fact => [...(fact.value.sharingWish ? [fact.value.sharingWish] : []), ...(fact.value.consents ?? [])].map(wish =>
    entry<PatientSharingWish>(fact, { text: wish.text, state: wish.state, scope: wish.scope, recordedAt: optionalTime(wish.recordedAt) }, 'Dodaný záznam přání a souhlasu'))))
  return freezeClinicalSnapshot({ ...(record.collectionCoverage ? { collectionCoverage: record.collectionCoverage } : {}), ...(record.coverage ? { coverage: { conditions: record.coverage.conditions, observations: record.coverage.observations,
    diagnosticReports: record.coverage.diagnosticReports, documents: record.coverage.documents } } : {}),
    revision: record.revision, results, reports, medications, history, allergies, symptoms, measurements, personSupport, sharingWishes, omittedCount,
    limitations: ['Pouze dodané údaje, nikoli nové pokyny nebo ověření léčby.', 'Zaznamenané přání ke sdílení není oprávnění k přístupu. Nadlimitní položky nejsou zobrazeny.'],
  })
}
