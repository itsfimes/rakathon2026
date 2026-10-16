import { freezeClinicalSnapshot } from '../clinical'
import type { CaseDetail, QueueItem, Workspace } from '../contracts'
import { buildPatientRecord } from '../patientRecord'
import { patientLabel, projectClinical } from './clinicalProjection'
import type { CaseDTO, WorkspaceDTO } from './dto'
import { ageAt } from './values'

export function projectWorkspace(dto: WorkspaceDTO): Workspace {
  const queue: QueueItem[] = dto.patients.map(p => ({ caseId: p.patientId, patientId: p.patientId, patientLabel: p.label || 'Jméno neuvedeno',
    age: ageAt(p.birthDate, dto.fetchedAt), diagnosis: null, priority: null, phase: null, nextStep: null,
  }))
  return freezeClinicalSnapshot({ asOf: dto.fetchedAt, defaultCaseId: queue[0]?.caseId ?? null, queue,
    metadata: { provenance: 'Backend IRIS · single-user-development · čas načtení dat', origin: 'backend' },
  })
}
export function projectCase(dto: CaseDTO): CaseDetail {
  const clinical = projectClinical(dto)
  const record = buildPatientRecord(clinical)
  return freezeClinicalSnapshot({ clinical,
    identity: { caseId: dto.patient.id!, patientId: dto.patient.id!, patientLabel: patientLabel(dto.patient), patientAddressLabel: patientLabel(dto.patient),
      age: ageAt(dto.patient.birthDate, dto.fetchedAt), diagnosis: null, referrer: null, referredAt: null },
    phases: [], nextStep: null, priorityExplanation: null, documents: [],
    patient: { ...(record ? { record } : {}), nextEvent: null, currentInstruction: null, journey: [], coordinator: null },
    doctor: { diagnosisStatus: 'Výchozí diagnóza ve zdroji neuvedena', sourceFields: [], referralStatus: [], obligations: 'Zdroj dat žádné povinnosti nedodal.' },
    mdt: { meetingAt: null, finding: 'Podklady pro přípravu MDT nebyly dodány.', requiredDocumentIds: [],
      finalization: { state: 'blocked', reason: 'Chybí údaje o poradě, požadavcích a místní dostupnosti podkladů.' } },
  })
}
