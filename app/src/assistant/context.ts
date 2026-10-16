import type { CaseDetail, CaseDocument } from '../data/contracts'
import type { ViewId } from '../lib/roles'
import type { AssistantContext, AssistantField, AssistantFieldKey, AssistantSourceId } from './contracts'
import { isAssistantRole, validContext } from './validation'

const acknowledgement = { pending: 'Nepřevzato', accepted: 'Převzato', 'awaiting-information': 'Čeká na doplnění', new: 'Nový' } as const
const referralState = { done: 'Dokončeno', now: 'Nyní', later: 'Později' } as const
const documentType: Readonly<Record<CaseDocument['kind'], string>> = {
  imaging: 'Zobrazovací vyšetření', markers: 'Nádorové markery', fitness: 'Celkový stav', staging: 'Staging', histology: 'Histologie',
}
const documentState: Readonly<Record<CaseDocument['state'], string>> = { available: 'Dostupné', missing: 'Chybí', uncertain: 'Nejisté' }

function documentSummary(document: Pick<CaseDocument, 'kind' | 'state'>): string | undefined {
  if (!Object.hasOwn(documentType, document.kind) || !Object.hasOwn(documentState, document.state)) return undefined
  return `${documentType[document.kind]}: ${documentState[document.state]}`
}

/** Only this projection can become the preview AND the wire context. No local identifiers. */
export function buildAssistantContext(view: ViewId, detail: CaseDetail | null, fresh: boolean): AssistantContext | null {
  if (!detail || !fresh || !isAssistantRole(view) || !detail.nextStep) return null
  const fields: AssistantField[] = []
  const add = (key: AssistantFieldKey, source: AssistantSourceId, value: string | null | undefined) => {
    if (value?.trim()) fields.push(Object.freeze({ key, source, value }))
  }
  if (view === 'koordinator') {
    add('task-title', 'task', detail.nextStep.title)
    add('task-organization', 'task', detail.nextStep.owner.organization)
    add('task-due', 'task', detail.nextStep.dueAt)
    add('task-acknowledgement', 'task', acknowledgement[detail.nextStep.acknowledgement])
    for (const document of detail.documents) add('document-state', 'documents', documentSummary(document))
  } else if (view === 'pacient') {
    add('instruction', 'patient-instruction', detail.patient.currentInstruction)
    add('event-title', 'patient-event', detail.patient.nextEvent?.title)
    add('event-date', 'patient-event', detail.patient.nextEvent?.date)
    add('event-attendance', 'patient-event', detail.patient.nextEvent?.attendanceLabel)
    add('event-followup', 'patient-event', detail.patient.nextEvent?.followup)
    add('contact', 'patient-contact', detail.patient.coordinator?.contact)
  } else if (view === 'lekar') {
    for (const item of detail.doctor.referralStatus) add('referral-state', 'referral', `${item.title}: ${referralState[item.state]}`)
    add('obligations', 'obligations', detail.doctor.obligations)
  } else {
    if (!detail.mdt.preparation) return null
    for (const document of detail.mdt.preparation.documents) {
      add('document-metadata', 'document-metadata', documentSummary(document))
    }
  }
  const context = Object.freeze({ role: view, fields: Object.freeze(fields) })
  return validContext(context) ? context : null
}
