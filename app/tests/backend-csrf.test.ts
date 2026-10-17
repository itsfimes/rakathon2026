import { describe, expect, it, vi } from 'vitest'
import type { AssistantRequest } from '../src/assistant/contracts'
import { BackendAssistant } from '../src/data/backend/assistant'
import { createBackendSession } from '../src/data/backend/gateway'
import { caseResponse, jsonResponse, sessionResponse, workspaceResponse } from './backend-fixtures'

const bound: AssistantRequest = { role: 'pacient', text: 'Synthetic question',
  caseId: 'synthetic-0' }
const general: AssistantRequest = { role: 'pacient', text: 'Synthetic general question' }
const answer = { provenance: 'server', text: 'Synthetic answer', sources: ['Patient/synthetic-0'], coverage: { status: 'complete', resources: 1, uploads: 0, failedTypes: [] } }
const generalAnswer = { ...answer, sources: [] as string[], coverage: { ...answer.coverage, status: 'general', resources: 0 } }

type CallInit = { headers: Record<string, string>; body?: unknown }
const initOf = (fetcher: ReturnType<typeof vi.fn<typeof fetch>>, call = 0) =>
  fetcher.mock.calls[call]?.[1] as CallInit

describe('authenticated assistant transport', () => {
  it('sends a fresh CSRF token per request and never puts it in the URL or body', async () => {
    const supplier = vi.fn(() => 'csrf-token')
    supplier.mockReturnValueOnce('csrf-first').mockReturnValue('csrf-second')
    const fetcher = vi.fn<typeof fetch>().mockImplementation(() => Promise.resolve(jsonResponse(generalAnswer)))
    const assistant = new BackendAssistant(fetcher, { csrfToken: supplier })
    expect(await assistant.send(general, new AbortController().signal)).toMatchObject({ ok: true })
    expect(await assistant.send(general, new AbortController().signal)).toMatchObject({ ok: true })
    expect(supplier).toHaveBeenCalledTimes(2)
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/assistant')
    expect(initOf(fetcher, 0).headers['X-CSRF-Token']).toBe('csrf-first')
    expect(initOf(fetcher, 1).headers['X-CSRF-Token']).toBe('csrf-second')
    for (const call of [0, 1]) {
      expect(initOf(fetcher, call).headers).not.toHaveProperty('Origin')
      expect(initOf(fetcher, call).headers).not.toHaveProperty('origin')
      expect(JSON.parse(String(initOf(fetcher, call).body))).toEqual(general)
      expect(String(initOf(fetcher, call).body)).not.toContain('csrf')
    }
  })

  it('fails closed without any request when the supplier has no token', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(answer))
    const assistant = new BackendAssistant(fetcher, { csrfToken: () => null })
    expect(await assistant.send(bound, new AbortController().signal)).toMatchObject({ ok: false, error: { code: 'unavailable' } })
    const controller = new AbortController()
    controller.abort()
    expect(await assistant.send(bound, controller.signal)).toMatchObject({ ok: false, error: { code: 'aborted' } })
    expect(fetcher).not.toHaveBeenCalled()
  })

  it('stays compatible without a supplier and omits the header', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(generalAnswer))
    expect(await new BackendAssistant(fetcher).send(general, new AbortController().signal)).toMatchObject({ ok: true })
    expect(initOf(fetcher).headers).not.toHaveProperty('X-CSRF-Token')
  })

  it('ends the session on 401 but keeps it on 403, 409 and 429', async () => {
    const onUnauthorized = vi.fn()
    const hooks = { csrfToken: () => 'csrf-token', onUnauthorized }
    for (const status of [401, 403, 409, 429]) {
      const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ error: 'denied' }, status))
      expect(await new BackendAssistant(fetcher, hooks).send(general, new AbortController().signal))
        .toMatchObject({ ok: false, error: { code: 'unavailable' } })
    }
    expect(onUnauthorized).toHaveBeenCalledTimes(1)
  })

  it('wires session hooks into a capable assistant and reads real typed data', async () => {
    const capable = { ...sessionResponse, capabilities: { ...sessionResponse.capabilities, assistant: true } }
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (input: unknown) => {
      const url = String(input)
      if (url === '/api/v1/session') return jsonResponse(capable)
      if (url === '/api/v1/workspace') return jsonResponse(workspaceResponse())
      if (url === '/api/v1/cases/synthetic-0') return jsonResponse(caseResponse())
      if (url === '/api/v1/assistant') return jsonResponse(generalAnswer)
      throw new Error(`unexpected ${url}`)
    })
    const onUnauthorized = vi.fn()
    const session = await createBackendSession(undefined, fetcher, { csrfToken: () => 'csrf-live', onUnauthorized })
    expect(session).toMatchObject({ mode: 'backend', connection: 'connected', assistant: { availability: 'available' } })
    const workspace = await session.gateway.readWorkspace()
    expect(workspace).toMatchObject({ ok: true })
    if (workspace.ok) expect(workspace.value.queue).toHaveLength(6)
    const detail = await session.gateway.readCase('synthetic-0')
    expect(detail).toMatchObject({ ok: true })
    if (detail.ok) expect(detail.value.identity.caseId).toBe('synthetic-0')
    expect(await session.assistant.send(general, new AbortController().signal)).toMatchObject({ ok: true })
    expect(initOf(fetcher, fetcher.mock.calls.length - 1).headers['X-CSRF-Token']).toBe('csrf-live')
    expect(onUnauthorized).not.toHaveBeenCalled()
  })

  it('respects a false capability even for a well-formed view-role request', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(sessionResponse))
    const session = await createBackendSession(undefined, fetcher, { csrfToken: () => 'csrf-token' })
    expect(session.assistant.availability).toBe('unavailable')
    expect(await session.assistant.send(bound, new AbortController().signal))
      .toMatchObject({ ok: false, error: { code: 'unavailable' } })
    expect(fetcher).toHaveBeenCalledOnce()
  })
})
