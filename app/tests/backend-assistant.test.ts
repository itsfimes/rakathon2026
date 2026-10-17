import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AssistantRequest } from '../src/assistant/contracts'
import { BackendAssistant } from '../src/data/backend/assistant'
import { BackendGateway, createBackendSession } from '../src/data/backend/gateway'
import { caseResponse, jsonResponse, sessionResponse, workspaceResponse } from './backend-fixtures'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
const request: AssistantRequest = { role: 'lekar', text: 'Synthetic question', caseId: 'synthetic-0' }
const answer = { provenance: 'server', text: 'Synthetic answer', sources: ['Patient/synthetic-0'], coverage: { status: 'complete', resources: 1, uploads: 0, failedTypes: [] } }

describe('full-record assistant transport', () => {
  it('reads case responses without previews and sends only the current caseId', async () => {
    const read = await new BackendGateway(true, vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(caseResponse()))).readCase('synthetic-0')
    expect(read.ok).toBe(true)
    if (!read.ok) return
    expect(read.value).not.toHaveProperty('assistantPreview')
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(answer))
    expect(await new BackendAssistant(fetcher).send(request, new AbortController().signal)).toEqual({ ok: true, value: answer })
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/assistant')
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error' })
    expect(JSON.parse(fetcher.mock.calls[0]?.[1]?.body as string)).toEqual(request)
  })
  it('general chat omits caseId and still requires configured healthy capability', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ ...answer, sources: [], coverage: { ...answer.coverage, status: 'general', resources: 0 } }))
    expect(await new BackendAssistant(fetcher).send({ role: 'pacient', text: 'General question' }, new AbortController().signal)).toMatchObject({ ok: true })
    expect(JSON.parse(fetcher.mock.calls[0]?.[1]?.body as string)).toEqual({ role: 'pacient', text: 'General question' })
    const configured = { ...sessionResponse, capabilities: { ...sessionResponse.capabilities, assistant: true } }
    expect((await createBackendSession(undefined, vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(configured)))).assistant.availability).toBe('available')
    expect((await createBackendSession(undefined, vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ ...configured, health: { ipc: 'down', database: 'up' } })))).assistant.availability).toBe('unavailable')
  })
  it('rejects old fields and malformed replies, but accepts server sources and 12000 chars', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ ...answer, text: 'x'.repeat(12000), sources: ['MedicationStatement/m'] }))
    expect(await new BackendAssistant(fetcher).send(request, new AbortController().signal)).toMatchObject({ ok: true })
    fetcher.mockClear()
    expect(await new BackendAssistant(fetcher).send({ ...request, context: {} } as AssistantRequest, new AbortController().signal)).toMatchObject({ ok: false, error: { code: 'invalid-request' } })
    expect(fetcher).not.toHaveBeenCalled()
    for (const response of [{ ...answer, text: 'x'.repeat(12001) }, { ...answer, coverage: undefined }, { ...answer, hidden: 'private' }]) {
      fetcher.mockResolvedValue(jsonResponse(response))
      expect(await new BackendAssistant(fetcher).send(request, new AbortController().signal)).toMatchObject({ ok: false, error: { code: 'invalid-response' } })
    }
  })
  it('reports the stable context_too_large error without exposing provider text', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ error: { code: 'context_too_large', message: 'PRIVATE' } }, 413))
    expect(await new BackendAssistant(fetcher).send(request, new AbortController().signal)).toEqual({ ok: false, error: { code: 'context_too_large' } })
  })
  it('normalizes preabort, late abort and deadline', async () => {
    const controller = new AbortController()
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () => { controller.abort(); return jsonResponse(answer) })
    const assistant = new BackendAssistant(fetcher)
    expect(await assistant.send(request, controller.signal)).toMatchObject({ ok: false, error: { code: 'aborted' } })
    expect(await assistant.send(request, controller.signal)).toMatchObject({ ok: false, error: { code: 'aborted' } })
    expect(fetcher).toHaveBeenCalledOnce()
    vi.useFakeTimers()
    const waiting = new BackendAssistant(vi.fn<typeof fetch>().mockImplementation((_input, init) => new Promise((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new Error('PRIVATE')), { once: true })
    }))).send(request, new AbortController().signal)
    await vi.advanceTimersByTimeAsync(90_000)
    expect(await waiting).toMatchObject({ ok: false, error: { code: 'aborted' } })
  })
  it('default fetch wrappers retain native global receiver', async () => {
    vi.stubGlobal('fetch', function (this: unknown, input: RequestInfo | URL) {
      expect(this).toBe(globalThis)
      const response = String(input).endsWith('/assistant') ? answer : String(input).endsWith('/workspace') ? workspaceResponse() : sessionResponse
      return Promise.resolve(jsonResponse(response))
    })
    expect((await new BackendGateway().readWorkspace()).ok).toBe(true)
    expect(await createBackendSession()).toMatchObject({ connection: 'connected' })
    expect(await new BackendAssistant().send(request, new AbortController().signal)).toMatchObject({ ok: true })
  })
})
