import type { Assistant, AssistantRequest, AssistantResult } from '../../assistant/contracts'

/** Deliberately no endpoint, credentials, network request or fallback. */
export class UnconfiguredAssistant implements Extract<Assistant, { availability: 'unavailable' }> {
  readonly availability = 'unavailable' as const
  readonly provenance = 'none' as const

  async send(_request: AssistantRequest, signal: AbortSignal): Promise<AssistantResult> {
    return { ok: false, error: { code: signal.aborted ? 'aborted' : 'unavailable' } }
  }
}
