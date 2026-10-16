import type { Assistant, AssistantPreview, AssistantRole } from '../assistant/contracts'
import type { ClinicalRecord } from './clinical'
import type { CollectionCoverage } from './coverage'
import type { MdtPreparation } from './mdtPreparation'
import type { PatientRecord } from './patientRecord'

export type DataMode = 'backend' | 'mock'
export type ErrorCode = 'configuration-error' | 'backend-unconfigured' | 'unavailable' | 'not-found' | 'aborted'
export interface DataError {
  readonly code: ErrorCode
  readonly message: string
  readonly coverage?: CollectionCoverage
}
export type Result<T> = { readonly ok: true; readonly value: T } | { readonly ok: false; readonly error: DataError }
export const success = <T>(value: T): Result<T> => ({ ok: true, value })
export const failure = (code: ErrorCode, message: string): Result<never> => ({ ok: false, error: { code, message } })

export type PhaseId = 'T1' | 'T2' | 'T3'
export type ProgressState = 'done' | 'now' | 'later'
export type Priority = 'high' | 'medium' | 'low'
export interface Diagnosis { readonly code: string; readonly label: string }
export interface Owner { readonly organization: string; readonly name?: string }
export interface NextStep {
  readonly id: string
  readonly title: string
  readonly shortTitle: string
  readonly owner: Owner
  readonly dueAt: string
  readonly requestedAt: string
  readonly acknowledgement: 'pending' | 'accepted' | 'awaiting-information' | 'new'
  readonly acceptedAt?: string
  readonly pendingLabel?: string
}
export interface QueueItem {
  readonly caseId: string
  readonly patientId: string
  readonly patientLabel: string
  readonly age: number | null
  readonly diagnosis: Diagnosis | null
  readonly priority: Priority | null
  readonly phase: PhaseId | null
  readonly phaseDay?: number
  readonly nextStep: NextStep | null
}
export interface Workspace {
  readonly asOf: string
  readonly defaultCaseId: string | null
  readonly queue: readonly QueueItem[]
  readonly metadata: { readonly provenance: string; readonly origin?: 'backend' }
  readonly collectionCoverage?: CollectionCoverage
}
export interface Identity {
  readonly caseId: string
  readonly patientId: string
  readonly patientLabel: string
  readonly patientAddressLabel: string
  readonly age: number | null
  readonly diagnosis: Diagnosis | null
  readonly referrer: { readonly name: string; readonly specialty: string; readonly viewLabel: string } | null
  readonly referredAt: string | null
  readonly acceptedAt?: string
}
export interface Phase {
  readonly id: PhaseId
  readonly label: string
  readonly state: ProgressState
  readonly startedAt?: string
  readonly endedAt?: string
  readonly days?: number
}
export interface SourceMetadata {
  readonly title: string
  readonly date: string
  readonly page?: number
}
export type DocumentState = 'available' | 'missing' | 'uncertain'
export interface CaseDocument {
  readonly id: string
  readonly kind: 'imaging' | 'markers' | 'fitness' | 'staging' | 'histology'
  readonly label: string
  readonly coordinatorLabel?: string
  readonly state: DocumentState
  readonly stateLabel: string
  readonly sources: readonly SourceMetadata[]
  readonly reviewState: 'unreviewed' | 'reviewed'
}
export interface JourneyItem {
  readonly historical?: boolean
  readonly id: string
  readonly title: string
  readonly date?: string
  readonly state: ProgressState
  readonly note?: string
}
export interface PatientView {
  readonly record?: PatientRecord
  readonly nextEvent: {
    readonly date: string
    readonly title: string
    readonly attendance: 'not-required' | 'required' | 'to-be-confirmed'
    readonly attendanceLabel: string
    readonly followup: string
  } | null
  readonly currentInstruction: string | null
  readonly journey: readonly JourneyItem[]
  readonly coordinator: { readonly name: string; readonly contact?: string; readonly help: string } | null
}
export interface SourceField {
  readonly id: string
  readonly documentId: string
  readonly label: string
  readonly value?: string
  readonly quote?: string
  readonly source?: SourceMetadata
  readonly status: 'literal' | 'uncertain' | 'absent' | 'awaiting'
  readonly statusLabel: string
  readonly reviewState: 'unreviewed' | 'reviewed'
}
export interface DoctorView {
  readonly diagnosisStatus: string
  readonly sourceFields: readonly SourceField[]
  readonly referralStatus: readonly JourneyItem[]
  readonly obligations: string
}
export interface MdtView {
  readonly preparation?: MdtPreparation
  readonly meetingAt: string | null
  readonly finding: string
  readonly requiredDocumentIds: readonly string[]
  readonly draft?: {
    readonly decision?: string
    readonly treatmentModality?: string
    readonly treatmentStart?: string
    readonly treatmentOwner?: string
    readonly uncertainties: readonly string[]
  }
  readonly finalization: { readonly state: 'blocked'; readonly reason: string }
}
export interface CaseDetail {
  readonly assistantPreview?: Readonly<Partial<Record<AssistantRole, AssistantPreview>>>
  readonly clinical?: ClinicalRecord
  readonly identity: Identity
  readonly phases: readonly Phase[]
  readonly nextStep: NextStep | null
  readonly priorityExplanation: string | null
  readonly documents: readonly CaseDocument[]
  readonly patient: PatientView
  readonly doctor: DoctorView
  readonly mdt: MdtView
}
export interface Gateway {
  readonly mode: DataMode
  readWorkspace(signal?: AbortSignal): Promise<Result<Workspace>>
  readCase(caseId: string, signal?: AbortSignal): Promise<Result<CaseDetail>>
}
export interface DemoControls {
  acceptTask(taskId: string): Promise<Result<void>>
  markDocumentReviewed(documentId: string): Promise<Result<void>>
  reset(): Promise<Result<void>>
}
export type Session =
  | { readonly mode: 'backend'; readonly gateway: Gateway; readonly assistant: Assistant; readonly connection?: 'connected' | 'unavailable' }
  | { readonly mode: 'mock'; readonly gateway: Gateway; readonly assistant: Assistant; readonly demoControls: DemoControls }
export type BootstrapResult =
  | { readonly status: 'configuration-error'; readonly error: DataError }
  | { readonly status: 'session'; readonly session: Session }
