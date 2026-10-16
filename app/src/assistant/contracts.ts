export type AssistantRole = 'koordinator' | 'pacient' | 'lekar' | 'mdt'
export type AssistantSourceId = 'task' | 'documents' | 'patient-instruction' | 'patient-event' | 'patient-contact' | 'referral' | 'obligations' | 'document-metadata'
export type AssistantFieldKey = 'task-title' | 'task-organization' | 'task-due' | 'task-acknowledgement' | 'document-state' | 'instruction' | 'event-title' | 'event-date' | 'event-attendance' | 'event-followup' | 'contact' | 'referral-state' | 'obligations' | 'document-metadata'
export interface AssistantField {
  readonly key: AssistantFieldKey
  readonly source: AssistantSourceId
  readonly value: string
}
export interface AssistantContext {
  readonly role: AssistantRole
  readonly fields: readonly AssistantField[]
}
export interface AssistantRequest {
  readonly role: AssistantRole
  readonly text: string
  readonly context?: AssistantContext
}
export interface AssistantReply {
  readonly provenance: 'scripted' | 'server'
  readonly text: string
  readonly sources: readonly AssistantSourceId[]
}
export type AssistantErrorCode = 'unavailable' | 'aborted' | 'invalid-request' | 'invalid-response' | 'failed'
export type AssistantResult = { readonly ok: true; readonly value: AssistantReply } | { readonly ok: false; readonly error: { readonly code: AssistantErrorCode } }
export type Assistant = {
  readonly availability: 'unavailable'
  readonly provenance: 'none'
  send(request: AssistantRequest, signal: AbortSignal): Promise<AssistantResult>
} | {
  readonly availability: 'available'
  readonly provenance: 'scripted' | 'server'
  send(request: AssistantRequest, signal: AbortSignal): Promise<AssistantResult>
}

export const ASSISTANT_LIMITS = Object.freeze({ input: 1000, output: 6000, fields: 32, field: 320, context: 4000, history: 8 })
export const ASSISTANT_SOURCE_LABELS: Readonly<Record<AssistantSourceId, string>> = Object.freeze({
  task: 'Dodaný další krok', documents: 'Dodané stavy podkladů',
  'patient-instruction': 'Dodaný pokyn pro pacienta', 'patient-event': 'Dodaná událost pro pacienta',
  'patient-contact': 'Dodaný kontakt', referral: 'Dodané stavy odeslání',
  obligations: 'Dodané povinnosti odesílajícího', 'document-metadata': 'Dodaná metadata podkladů',
})
export const ASSISTANT_FIELD_LABELS: Readonly<Record<AssistantFieldKey, string>> = Object.freeze({
  'task-title': 'Další krok', 'task-organization': 'Odpovědná organizace', 'task-due': 'Dodaný termín',
  'task-acknowledgement': 'Stav převzetí', 'document-state': 'Stav podkladu', instruction: 'Pokyn',
  'event-title': 'Událost', 'event-date': 'Datum události', 'event-attendance': 'Účast',
  'event-followup': 'Následující informace', contact: 'Kontakt', 'referral-state': 'Stav odeslání',
  obligations: 'Povinnosti', 'document-metadata': 'Metadata podkladu',
})
