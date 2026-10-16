import { ASSISTANT_LIMITS } from './contracts'
import type { AssistantContext, AssistantField, AssistantFieldKey, AssistantReply, AssistantRequest, AssistantRole, AssistantSourceId } from './contracts'

const fields: Readonly<Record<AssistantRole, Partial<Record<AssistantFieldKey, AssistantSourceId>>>> = {
  koordinator: { 'task-title': 'task', 'task-organization': 'task', 'task-due': 'task', 'task-acknowledgement': 'task', 'document-state': 'documents', 'record.coverage': 'record-coverage' },
  pacient: { instruction: 'patient-instruction', 'event-title': 'patient-event', 'event-date': 'patient-event', 'event-attendance': 'patient-event', 'event-followup': 'patient-event', contact: 'patient-contact', 'record.coverage': 'record-coverage', 'record.reportsSummary': 'record-report-metadata' },
  lekar: { 'referral-state': 'referral', obligations: 'obligations', 'record.coverage': 'record-coverage', 'record.reportsSummary': 'record-report-metadata' },
  mdt: { 'document-metadata': 'document-metadata', 'record.coverage': 'record-coverage', 'record.reportsSummary': 'record-report-metadata' },
}

export function isAssistantRole(value: string): value is AssistantRole {
  return Object.hasOwn(fields, value)
}

const exactKeys = (value: object, allowed: readonly string[]) => Object.keys(value).every(key => allowed.includes(key))

export function validContext(context: AssistantContext): boolean {
  if (!context || !isAssistantRole(context.role) || !exactKeys(context, ['role', 'fields']) || !Array.isArray(context.fields)) return false
  if (!context.fields.length || context.fields.length > ASSISTANT_LIMITS.fields) return false
  let length = 0
  for (const field of context.fields as readonly AssistantField[]) {
    if (!field || !exactKeys(field, ['key', 'source', 'value']) || !Object.hasOwn(fields[context.role], field.key)) return false
    if (fields[context.role][field.key] !== field.source || typeof field.value !== 'string' || !field.value.trim() || field.value.length > ASSISTANT_LIMITS.field) return false
    length += field.value.length
  }
  return length <= ASSISTANT_LIMITS.context
}

export function validRequest(request: AssistantRequest): boolean {
  return !!request && exactKeys(request, ['role', 'text', 'context', 'binding']) && isAssistantRole(request.role)
    && typeof request.text === 'string' && !!request.text.trim() && request.text.length <= ASSISTANT_LIMITS.input
    && (request.context === undefined || (!!request.context && request.context.role === request.role && validContext(request.context)))
    && (request.binding === undefined || (!!request.context && !!request.binding && exactKeys(request.binding, ['caseId', 'token']) && typeof request.binding.caseId === 'string' && typeof request.binding.token === 'string' && /^[A-Za-z0-9.-]{1,64}$/.test(request.binding.caseId) && /^[0-9]{1,12}\.[a-f0-9]{64}$/.test(request.binding.token)))
}

export function validReply(reply: AssistantReply, request: AssistantRequest, provenance: 'scripted' | 'server'): boolean {
  return !!reply && exactKeys(reply, ['provenance', 'text', 'sources']) && reply.provenance === provenance
    && typeof reply.text === 'string' && !!reply.text.trim() && reply.text.length <= ASSISTANT_LIMITS.output
    && Array.isArray(reply.sources) && reply.sources.length <= 8 && new Set(reply.sources).size === reply.sources.length
    && reply.sources.every(source => request.context?.fields.some(field => field.source === source))
}
