export type ClinicalTime =
  | { readonly kind: 'day'; readonly value: string }
  | { readonly kind: 'instant'; readonly value: string }
  | { readonly kind: 'month'; readonly value: string }
  | { readonly kind: 'approximate'; readonly label: string }
  | { readonly kind: 'unknown' }
export interface SourceRef { readonly sourceId: string; readonly version: string }
export interface ClinicalSource {
  readonly ref: SourceRef
  readonly label: string
  readonly issued: ClinicalTime
  readonly locallyAvailable: ClinicalTime
  readonly review?: 'unreviewed' | 'reviewed'
}
export interface ClinicalFact<T> {
  readonly id: string
  readonly value: T
  readonly sources: readonly SourceRef[]
  readonly effective: ClinicalTime
  readonly knowledge: 'recorded' | 'unknown' | 'not-recorded'
  readonly presence: 'present' | 'denied' | 'unspecified'
  readonly verification: 'suspected' | 'preliminary' | 'confirmed' | 'unspecified'
  readonly conflictIds: readonly string[]
  readonly review?: 'unreviewed' | 'reviewed'
}
export interface RecordedConsent {
  readonly text: string
  readonly state: 'recorded' | 'declined' | 'unknown'
  readonly scope?: string
  readonly recordedAt?: ClinicalTime
}
export interface IdentityPayload {
  readonly name?: string
  readonly birthDate?: ClinicalTime
  readonly age?: number
  readonly sex?: string
  readonly nationalIdentifier?: string
  readonly insuranceIdentifier?: string
  readonly insurer?: string
  readonly address?: string
  readonly contact?: string
  readonly contactPerson?: { readonly name?: string; readonly relationship: string; readonly contact?: string }
  readonly sharingWish?: RecordedConsent
  readonly consents?: readonly RecordedConsent[]
}
export interface PersonalSocialPayload {
  readonly maritalStatus?: string
  readonly livingSituation?: string
  readonly support?: string
  readonly occupation?: string
  readonly sickLeave?: string
  readonly smoking?: string
  readonly alcohol?: string
  readonly independence?: string
}
export interface HistoryPayload {
  readonly category: 'condition' | 'operation' | 'family' | 'allergy' | 'mental-health' | 'cardiac'
  readonly description: string
  readonly code?: string
  readonly onset?: ClinicalTime
}
export interface MedicationPayload {
  readonly name: string
  readonly strength?: string
  readonly dose?: string
  readonly frequency?: string
  readonly schedule?: 'regular' | 'as-needed' | 'course'
  readonly statement: 'reported-taking' | 'recommended' | 'periprocedure-instruction' | 'completed-course' | 'interaction'
  readonly suppliedIndication?: string
  readonly courseStart?: ClinicalTime
  readonly courseEnd?: ClinicalTime
  readonly stopAt?: ClinicalTime
  readonly restartAt?: ClinicalTime
  readonly instruction?: string
  readonly recommendedChange?: string
  readonly interaction?: string
}
export interface SymptomPayload {
  readonly type: string
  readonly site?: string
  readonly character?: string
  readonly onset?: ClinicalTime
  readonly course?: string
  readonly fever?: boolean
  readonly jaundice?: boolean
  readonly darkUrine?: boolean
  readonly appetite?: string
  readonly nausea?: boolean
  readonly weightLoss?: string
  readonly sleep?: string
  readonly function?: string
  readonly nrs?: number
}
export interface MeasurementPayload {
  readonly type: 'height' | 'weight' | 'blood-pressure' | 'pulse' | 'temperature' | 'examination'
  readonly value: string
  readonly unit?: string
  readonly examination?: string
}
export interface CultureResult {
  readonly organism: string
  readonly quantity?: string
  readonly susceptibility: readonly { readonly agent: string; readonly result: 'susceptible' | 'intermediate' | 'resistant' | 'not-supplied'; readonly mic?: string; readonly unit?: string }[]
}
export interface LabPayload {
  readonly suppliedNote?: string
  readonly test: string
  readonly panel?: 'blood-count' | 'liver-biliary' | 'inflammation' | 'renal' | 'electrolytes-metabolic' | 'pancreatic' | 'tumour-markers' | 'urinalysis' | 'culture' | 'other'
  readonly value?: string
  readonly unit?: string
  readonly referenceRange?: string
  readonly abnormalFlag?: 'high' | 'low' | 'normal' | 'abnormal' | 'not-supplied'
  readonly sampleAt?: ClinicalTime
  readonly resultAt?: ClinicalTime
  readonly sediment?: string
  readonly culture?: CultureResult
}
export interface ImagingProcedurePayload {
  readonly type: string
  readonly format: 'text-report'
  readonly date?: ClinicalTime
  readonly site?: string
  readonly indication?: string
  readonly findings?: string
  readonly conclusion?: string
  readonly lesion?: { readonly site: string; readonly dimensions?: string; readonly vessels?: string; readonly ducts?: string; readonly nodes?: string; readonly distantFindings?: string }
  readonly biopsy?: { readonly method: string; readonly sampleCount?: number; readonly sampleSite?: string; readonly complications?: string }
}
export interface OncologyHistologyPayload {
  readonly kind: 'suspicion' | 'histology' | 'specialist-conclusion'
  readonly description: string
  readonly site?: string
  readonly type?: string
  readonly grade?: string
  readonly perineuralInvasion?: string
  readonly ihc?: readonly { readonly marker: string; readonly result: string }[]
  readonly diagnosisCode?: string
  readonly morphologyCode?: string
  readonly sampleAt?: ClinicalTime
  readonly reportAt?: ClinicalTime
  readonly staging?: string
  readonly resectability?: string
}
export interface SupportiveCarePayload {
  readonly description: string
  readonly reportedAnxiety?: string
  readonly supportNeed?: string
  readonly hads?: { readonly anxiety?: number; readonly depression?: number; readonly date?: ClinicalTime }
  readonly distress?: { readonly value: string; readonly scale?: string }
  readonly psychologyConclusion?: string
  readonly psychotherapyRecommendation?: string
  readonly psychiatryRecommendation?: string
  readonly painFollowup?: string
}
export interface ReferralContinuityPayload {
  readonly referrer?: string
  readonly site?: string
  readonly reason?: string
  readonly kocRequest?: string
  readonly specialistQuestion?: string
  readonly examinations?: readonly { readonly description: string; readonly state: 'requested' | 'done' | 'report-available' | 'unknown' }[]
  readonly accessDifficulties?: string
  readonly consultations?: readonly string[]
}
export interface MdtPlanPayload {
  readonly kind: 'meeting' | 'conclusion' | 'recommendation' | 'task' | 'appointment'
  readonly description: string
  readonly meetingDate?: ClinicalTime
  readonly attendees?: readonly { readonly name: string; readonly specialty: string }[]
  readonly clinicalSummary?: string
  readonly conclusion?: string
  readonly recommendedTreatment?: string
  readonly support?: string
  readonly followups?: readonly { readonly description: string; readonly date?: ClinicalTime }[]
  readonly owners?: readonly { readonly organization: string; readonly person?: string; readonly responsibility: string }[]
  readonly reportRecipient?: string
  readonly scheduledAt?: ClinicalTime
  readonly state?: 'planned' | 'completed' | 'proposed' | 'recorded'
}
export interface ClinicalDomains {
  readonly identity: readonly ClinicalFact<IdentityPayload>[]
  readonly personalSocial: readonly ClinicalFact<PersonalSocialPayload>[]
  readonly history: readonly ClinicalFact<HistoryPayload>[]
  readonly medications: readonly ClinicalFact<MedicationPayload>[]
  readonly symptoms: readonly ClinicalFact<SymptomPayload>[]
  readonly measurements: readonly ClinicalFact<MeasurementPayload>[]
  readonly labs: readonly ClinicalFact<LabPayload>[]
  readonly imagingProcedures: readonly ClinicalFact<ImagingProcedurePayload>[]
  readonly oncologyHistology: readonly ClinicalFact<OncologyHistologyPayload>[]
  readonly supportiveCare: readonly ClinicalFact<SupportiveCarePayload>[]
  readonly referralContinuity: readonly ClinicalFact<ReferralContinuityPayload>[]
  readonly mdtPlan: readonly ClinicalFact<MdtPlanPayload>[]
}
export interface ClinicalRecord {
  readonly coverage?: ClinicalCoverage
  readonly revision: string
  readonly sources: readonly ClinicalSource[]
  readonly domains: ClinicalDomains
}
export interface ClinicalCoverage {
  readonly conditions: 'complete' | 'unavailable'
  readonly observations: 'complete' | 'unavailable'
  readonly diagnosticReports: 'complete' | 'unavailable'
  readonly documents: 'complete' | 'unavailable'
}

/** Detach first: projections must neither freeze nor retain references into their inputs. */
export function freezeClinicalSnapshot<T>(value: T): T {
  const copy = structuredClone(value)
  const freeze = (item: unknown) => {
    if (!item || typeof item !== 'object') return
    Object.freeze(item)
    Object.values(item).forEach(freeze)
  }
  freeze(copy)
  return copy
}
