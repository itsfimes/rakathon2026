import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildAssistantContext } from '../src/assistant/context'
import type { AssistantPreview, AssistantRequest } from '../src/assistant/contracts'
import { BackendAssistant } from '../src/data/backend/assistant'
import { BackendGateway, createBackendSession } from '../src/data/backend/gateway'
import { caseResponse, jsonResponse, sessionResponse, workspaceResponse } from './backend-fixtures'

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })
const preview: AssistantPreview = {
  context: { role: 'pacient', fields: [{ key: 'record.coverage', source: 'record-coverage', value: 'Zprávy: načteno' }] },
  binding: { caseId: 'synthetic-0', token: `1000.${'a'.repeat(64)}` },
}
const request: AssistantRequest = { role: 'pacient', text: 'Synthetic question', ...preview }
const answer = { provenance: 'server', text: 'Synthetic answer', sources: ['record-coverage'] }

describe('configured bounded assistant transport', () => {
  it('sends the exact opt-in preview with transport binding and no raw clinical data', async () => {
    const raw = { ...caseResponse(), assistantPreview: { pacient: preview } }
    const read = await new BackendGateway(true, vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(raw))).readCase('synthetic-0')
    expect(read.ok).toBe(true)
    if (!read.ok) return
    expect(read.value.nextStep).toBeNull()
    const context = buildAssistantContext('pacient', read.value, true)
    expect(context).toEqual(preview.context)
    expect(buildAssistantContext('pacient', read.value, false)).toBeNull()
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(answer))
    expect(await new BackendAssistant(fetcher).send({ ...request, context: context! }, new AbortController().signal)).toMatchObject({ ok: true, value: answer })
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/assistant')
    const init = fetcher.mock.calls[0]?.[1]
    expect(init).toMatchObject({ method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error' })
    expect(JSON.parse(init?.body as string)).toEqual(request)
  })

  it('general chat omits all case/context fields and requires configured healthy capability', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ ...answer, sources: [] }))
    expect(await new BackendAssistant(fetcher).send({ role: 'pacient', text: 'General question' }, new AbortController().signal)).toMatchObject({ ok: true })
    expect(JSON.parse(fetcher.mock.calls[0]?.[1]?.body as string)).toEqual({ role: 'pacient', text: 'General question' })
    const configured = { ...sessionResponse, capabilities: { ...sessionResponse.capabilities, assistant: true } }
    expect((await createBackendSession(undefined, vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(configured)))).assistant.availability).toBe('available')
    expect((await createBackendSession(undefined, vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ ...configured, health: { ipc: 'down', database: 'up' } })))).assistant.availability).toBe('unavailable')
  })

  it('rejects unbound context, forged sources, oversize output and unknown response fields', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(answer))
    expect(await new BackendAssistant(fetcher).send({ role: 'pacient', text: 'Q', context: preview.context }, new AbortController().signal)).toMatchObject({ ok: false, error: { code: 'invalid-request' } })
    expect(fetcher).not.toHaveBeenCalled()
    for (const response of [{ ...answer, sources: ['task'] }, { ...answer, text: 'x'.repeat(6001) }, { ...answer, hidden: 'private' }]) {
      fetcher.mockResolvedValue(jsonResponse(response))
      expect(await new BackendAssistant(fetcher).send(request, new AbortController().signal)).toMatchObject({ ok: false, error: { code: 'invalid-response' } })
    }
  })

  it('validates server preview role, field allowlist and exact transport case', async () => {
    for (const assistantPreview of [
      { pacient: { ...preview, binding: { ...preview.binding, caseId: 'other' } } },
      { mdt: preview },
      { pacient: { ...preview, context: { ...preview.context, fields: [{ key: 'diagnosis', source: 'diagnoses', value: 'private' }] } } },
      { pacient: { ...preview, context: { ...preview.context, fields: [{ ...preview.context.fields[0], value: 'x'.repeat(321) }] } } },
    ]) {
      expect(await new BackendGateway(true, vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ ...caseResponse(), assistantPreview }))).readCase('synthetic-0')).toMatchObject({ ok: false })
    }
  })

  it('normalizes preabort, late abort and deadline without leaking raw errors', async () => {
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

  it('default fetch wrappers retain native global receiver for reads, bootstrap and assistant', async () => {
    vi.stubGlobal('fetch', function (this: unknown, input: RequestInfo | URL) {
      expect(this).toBe(globalThis)
      const response = String(input).endsWith('/assistant') ? { ...answer, sources: [] }
        : String(input).endsWith('/workspace') ? workspaceResponse() : sessionResponse
      return Promise.resolve(jsonResponse(response))
    })
    expect((await new BackendGateway().readWorkspace()).ok).toBe(true)
    expect(await createBackendSession()).toMatchObject({ connection: 'connected' })
    expect(await new BackendAssistant().send({ role: 'pacient', text: 'Q' }, new AbortController().signal)).toMatchObject({ ok: true })
  })
})
