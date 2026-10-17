export type AssistantRole = 'koordinator' | 'pacient' | 'lekar' | 'mdt'
export interface AssistantRequest {
  readonly role: AssistantRole
  readonly text: string
  readonly caseId?: string
}
export interface AssistantCoverage {
  readonly status: 'general' | 'complete' | 'partial'
  readonly resources: number
  readonly uploads: number
  readonly failedTypes: readonly string[]
  readonly unreadableAttachments?: number
  readonly uploadsWithUnavailableArtifacts?: number
}
export interface AssistantReply {
  readonly provenance: 'scripted' | 'server'
  readonly text: string
  readonly sources: readonly string[]
  readonly coverage: AssistantCoverage
}
export type AssistantErrorCode = 'unavailable' | 'aborted' | 'invalid-request' | 'invalid-response' | 'failed' | 'context_too_large'
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
export const ASSISTANT_LIMITS = Object.freeze({ input: 1000, output: 12000, sources: 50, history: 8 })
