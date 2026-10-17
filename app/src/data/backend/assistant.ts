import type { Assistant, AssistantReply, AssistantRequest, AssistantResult, AssistantSourceId } from '../../assistant/contracts'
import { validReply, validRequest } from '../../assistant/validation'
import type { AuthRequestHooks } from './gateway'
import { jsonBody } from './http'
import { object } from './schema'

/** Deliberately no endpoint, credentials, network request or fallback. */
export class UnconfiguredAssistant implements Extract<Assistant, { availability: 'unavailable' }> {
  readonly availability = 'unavailable' as const
  readonly provenance = 'none' as const

  async send(_request: AssistantRequest, signal: AbortSignal): Promise<AssistantResult> {
    return { ok: false, error: { code: signal.aborted ? 'aborted' : 'unavailable' } }
  }
}

export class BackendAssistant implements Extract<Assistant, { availability: 'available' }> {
  readonly availability = 'available' as const
  readonly provenance = 'server' as const

  constructor(private readonly fetcher: typeof fetch = (input, init) => globalThis.fetch(input, init), private readonly hooks: AuthRequestHooks = {}) {}

  async send(request: AssistantRequest, signal: AbortSignal): Promise<AssistantResult> {
    const failed = (code: 'aborted' | 'invalid-request' | 'invalid-response' | 'unavailable'): AssistantResult => ({ ok: false, error: { code } })
    if (signal.aborted) return failed('aborted')
    if (!validRequest(request) || (!!request.context !== !!request.binding)) return failed('invalid-request')
    const token = this.hooks.csrfToken?.() ?? null
    if (this.hooks.csrfToken && !token) return failed(signal.aborted ? 'aborted' : 'unavailable')
    const controller = new AbortController()
    const abort = () => controller.abort()
    signal.addEventListener('abort', abort, { once: true })
    const timer = setTimeout(abort, 90_000)
    try {
      const payload = { role: request.role, text: request.text,
        ...(request.context ? { context: request.context, binding: request.binding } : {}) }
      const body = JSON.stringify(payload)
      if (new TextEncoder().encode(body).byteLength > 16 * 1024) return failed('invalid-request')
      const response = await this.fetcher('/api/v1/assistant', {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal,
        headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...(token ? { 'X-CSRF-Token': token } : {}) }, body,
      })
      if (controller.signal.aborted) return failed('aborted')
      if (response.status === 401) {
        this.hooks.onUnauthorized?.()
        return failed('unavailable')
      }
      if (!response.ok) return failed('unavailable')
      if (!response.headers.get('content-type')?.includes('application/json')) return failed('invalid-response')
      const raw = object(await jsonBody(response, 64 * 1024))
      if (Object.keys(raw).some(key => !['provenance', 'text', 'sources'].includes(key)) || raw.provenance !== 'server' || typeof raw.text !== 'string' || !Array.isArray(raw.sources) || !raw.sources.every(source => typeof source === 'string')) return failed('invalid-response')
      const reply: AssistantReply = { provenance: 'server', text: raw.text, sources: raw.sources as AssistantSourceId[] }
      if (controller.signal.aborted) return failed('aborted')
      return validReply(reply, request, 'server') ? { ok: true, value: reply } : failed('invalid-response')
    } catch { return failed(controller.signal.aborted ? 'aborted' : 'unavailable') }
    finally { clearTimeout(timer); signal.removeEventListener('abort', abort) }
  }
}
