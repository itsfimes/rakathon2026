import { ASSISTANT_LIMITS } from './contracts'
import type { AssistantCoverage, AssistantReply, AssistantRequest, AssistantRole } from './contracts'

export function isAssistantRole(value: string): value is AssistantRole {
  return ['koordinator', 'pacient', 'lekar', 'mdt'].includes(value)
}
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value)
const exactKeys = (value: object, allowed: readonly string[]) => Object.keys(value).every(key => allowed.includes(key))
const count = (value: unknown) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0

export function validCoverage(value: unknown): value is AssistantCoverage {
  if (!object(value) || !exactKeys(value, ['status', 'resources', 'uploads', 'failedTypes', 'unreadableAttachments', 'uploadsWithUnavailableArtifacts'])) return false
  return ['general', 'complete', 'partial'].includes(value.status as string) && count(value.resources) && count(value.uploads)
    && Array.isArray(value.failedTypes) && value.failedTypes.length <= 21 && new Set(value.failedTypes).size === value.failedTypes.length
    && value.failedTypes.every(type => typeof type === 'string' && /^[A-Za-z]{1,64}$/.test(type))
    && (value.unreadableAttachments === undefined || count(value.unreadableAttachments))
    && (value.uploadsWithUnavailableArtifacts === undefined || count(value.uploadsWithUnavailableArtifacts))
}

export function validRequest(request: AssistantRequest): boolean {
  return !!request && exactKeys(request, ['role', 'text', 'caseId']) && isAssistantRole(request.role)
    && typeof request.text === 'string' && !!request.text.trim() && request.text.length <= ASSISTANT_LIMITS.input
    && (!Object.hasOwn(request, 'caseId') || (typeof request.caseId === 'string' && /^[A-Za-z0-9.-]{1,64}$/.test(request.caseId) && /[A-Za-z0-9]/.test(request.caseId)))
}

export function validReply(reply: unknown, provenance: 'scripted' | 'server'): reply is AssistantReply {
  return object(reply) && exactKeys(reply, ['provenance', 'text', 'sources', 'coverage']) && reply.provenance === provenance
    && typeof reply.text === 'string' && !!reply.text.trim() && reply.text.length <= ASSISTANT_LIMITS.output
    && Array.isArray(reply.sources) && reply.sources.length <= ASSISTANT_LIMITS.sources && new Set(reply.sources).size === reply.sources.length
    && reply.sources.every(source => typeof source === 'string' && !!source.trim() && source.length <= 256)
    && validCoverage(reply.coverage)
}
