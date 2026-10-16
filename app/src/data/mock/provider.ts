import { failure, success } from '../contracts'
import type { CaseDetail, DemoControls, Gateway, Result, Session, Workspace } from '../contracts'
import { AS_OF, createSeedCases, PROVENANCE, queueClassification } from './fixtures'
import { createScriptedAssistant } from './assistant'
import { buildMdtPreparation } from '../mdtPreparation'
import { buildPatientRecord } from '../patientRecord'
import { createPreparationRequirements, SYNTHETIC_MEETING } from './clinicalFixtures'

function freeze<T>(value: T): T {
  if (value !== null && typeof value === 'object') {
    Object.freeze(value)
    for (const child of Object.values(value)) freeze(child)
  }
  return value
}

const snapshot = <T>(value: T): T => freeze(structuredClone(value))

async function wait(delayMs: number, signal?: AbortSignal): Promise<boolean> {
  if (signal?.aborted) return false
  return new Promise(resolve => {
    const finish = (completed: boolean) => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abort)
      resolve(completed)
    }
    const abort = () => finish(false)
    const timer = setTimeout(() => finish(true), delayMs)
    signal?.addEventListener('abort', abort, { once: true })
  })
}

export interface MockOptions { readonly delayMs?: number }

export function createMockSession(options: MockOptions = {}): Extract<Session, { mode: 'mock' }> {
  const delayMs = options.delayMs ?? 5
  let cases = createSeedCases()
  const aborted = () => failure('aborted', 'Požadavek byl zrušen.')

  const gateway: Gateway = {
    mode: 'mock',
    async readWorkspace(signal?: AbortSignal): Promise<Result<Workspace>> {
      if (!(await wait(delayMs, signal))) return aborted()
      return success(snapshot({
        asOf: AS_OF, defaultCaseId: cases[0]?.identity.caseId ?? null,
        metadata: { provenance: PROVENANCE },
        queue: cases.map(detail => ({
          caseId: detail.identity.caseId, patientId: detail.identity.patientId,
          patientLabel: detail.identity.patientLabel, age: detail.identity.age,
          diagnosis: detail.identity.diagnosis,
          ...queueClassification(detail.identity.caseId), nextStep: detail.nextStep,
        })),
      }))
    },
    async readCase(caseId: string, signal?: AbortSignal): Promise<Result<CaseDetail>> {
      if (!(await wait(delayMs, signal))) return aborted()
      const detail = cases.find(item => item.identity.caseId === caseId)
      if (!detail) return failure('not-found', 'Případ nebyl nalezen.')
      const record = buildPatientRecord(detail.clinical)
      const preparation = detail.clinical && detail.mdt.meetingAt ? buildMdtPreparation({ record: detail.clinical, meetingId: SYNTHETIC_MEETING.id,
        meetingDate: detail.mdt.meetingAt, requirements: createPreparationRequirements() }) : undefined
      return success(snapshot({ ...detail, patient: { ...detail.patient, ...(record ? { record } : {}) }, mdt: { ...detail.mdt, ...(preparation ? { preparation } : {}) } }))
    },
  }
  const demoControls: DemoControls = {
    async acceptTask(taskId: string): Promise<Result<void>> {
      await wait(delayMs)
      const detail = cases.find(item => item.nextStep?.id === taskId)
      if (!detail?.nextStep) return failure('not-found', 'Krok nebyl nalezen.')
      const task = { ...detail.nextStep }
      delete task.pendingLabel
      cases = cases.map(item => item === detail
        ? {
          ...item,
          nextStep: { ...task, acknowledgement: 'accepted', acceptedAt: AS_OF },
          priorityExplanation: 'Převzetí kroku bylo potvrzeno pouze lokálně v ukázce. Pořadí nadále zohledňuje termín práce, ne zdravotní riziko.',
        }
        : item)
      return success(undefined)
    },
    async markDocumentReviewed(documentId: string): Promise<Result<void>> {
      await wait(delayMs)
      const detail = cases.find(item => item.documents.some(document => document.id === documentId))
      if (!detail) return failure('not-found', 'Podklad nebyl nalezen.')
      cases = cases.map(item => item === detail ? {
        ...item,
        documents: item.documents.map(document => document.id === documentId ? { ...document, reviewState: 'reviewed' } : document),
        doctor: {
          ...item.doctor,
          sourceFields: item.doctor.sourceFields.map(field => field.documentId === documentId ? { ...field, reviewState: 'reviewed' } : field),
        },
      } : item)
      return success(undefined)
    },
    async reset(): Promise<Result<void>> {
      await wait(delayMs)
      cases = createSeedCases()
      return success(undefined)
    },
  }
  return Object.freeze({ mode: 'mock', gateway: Object.freeze(gateway), assistant: createScriptedAssistant(), demoControls: Object.freeze(demoControls) })
}
