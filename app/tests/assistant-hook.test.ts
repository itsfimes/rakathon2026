import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildAssistantContext } from '../src/assistant/context'
import { ASSISTANT_LIMITS } from '../src/assistant/contracts'
import type { Assistant, AssistantRequest, AssistantResult } from '../src/assistant/contracts'
import { ASSISTANT_PROMPTS } from '../src/assistant/prompts'
import { ASSISTANT_FAILURE_MESSAGE, useAssistant } from '../src/assistant/useAssistant'
import type { AssistantOptions } from '../src/assistant/useAssistant'
import { UnconfiguredAssistant } from '../src/data/backend/assistant'
import { createSeedCases } from '../src/data/mock/fixtures'
import { createMockSession } from '../src/data/mock/provider'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const detail = createSeedCases()[0]!
const prompt = ASSISTANT_PROMPTS.pacient[0]!
const reply: AssistantResult = { ok: true, value: { provenance: 'scripted', text: 'Skriptovaná odpověď', sources: [] } }
const options = (assistant?: Assistant): AssistantOptions => ({
  session: assistant ? { ...createMockSession(), assistant } : createMockSession(), view: 'pacient',
  caseId: detail.identity.caseId, version: 0, open: true, contextFresh: true,
  context: buildAssistantContext('pacient', detail, true),
})
function deferredAssistant() {
  const requests: { request: AssistantRequest; signal: AbortSignal; resolve: (value: AssistantResult) => void }[] = []
  const send = vi.fn((request: AssistantRequest, signal: AbortSignal) => new Promise<AssistantResult>(resolve => requests.push({ request, signal, resolve })))
  const assistant: Assistant = { availability: 'available', provenance: 'scripted', send }
  return { assistant, requests, send }
}

describe('explicit headless assistant state', () => {
  it('starts off, sends nothing automatically, and transmits only exact preview after explicit opt-in, never local keys/history', async () => {
    const deferred = deferredAssistant()
    const props = options(deferred.assistant)
    const { result } = renderHook(() => useAssistant(props))
    expect(result.current.contextSelected).toBe(false)
    expect(result.current.messages).toEqual([])
    expect(deferred.send).not.toHaveBeenCalled()
    act(() => result.current.setInput(prompt))
    act(() => { void result.current.send() })
    expect(deferred.requests[0]!.request).toEqual({ role: 'pacient', text: prompt })
    await act(async () => deferred.requests[0]!.resolve(reply))
    act(() => result.current.selectContext(true))
    const preview = result.current.contextPreview
    act(() => { void result.current.send(prompt) })
    expect(deferred.requests[1]!.request).toEqual({ role: 'pacient', text: prompt, context: preview })
    expect(deferred.requests[1]!.request.context).not.toBe(preview)
    expect(Object.keys(deferred.requests[1]!.request).sort()).toEqual(['context', 'role', 'text'])
    await act(async () => deferred.requests[1]!.resolve(reply))
    expect(result.current.messages).toHaveLength(4)
  })

  it('bounds input and history and permits only one pending explicit send', async () => {
    const deferred = deferredAssistant()
    const optionsStable = options(deferred.assistant)
    const { result } = renderHook(() => useAssistant(optionsStable))
    act(() => result.current.setInput('x'.repeat(ASSISTANT_LIMITS.input + 1)))
    expect(result.current.input).toBe('')
    await act(async () => { await result.current.send(' '); await result.current.send('x'.repeat(ASSISTANT_LIMITS.input + 1)) })
    expect(deferred.send).not.toHaveBeenCalled()
    for (let i = 0; i < ASSISTANT_LIMITS.history / 2; i++) {
      act(() => { void result.current.send(prompt); void result.current.send(prompt) })
      expect(deferred.send).toHaveBeenCalledTimes(i + 1)
      await act(async () => deferred.requests[i]!.resolve(reply))
    }
    await act(async () => result.current.send(prompt))
    expect(result.current.messages).toHaveLength(ASSISTANT_LIMITS.history)
    expect(deferred.send).toHaveBeenCalledTimes(4)
    expect(result.current.error).toContain('Limit konverzace')
  })

  it('bound server preview is sent unchanged and a replacement binding aborts stale replies', async () => {
    const deferred = deferredAssistant()
    const initial: AssistantOptions = { ...options(deferred.assistant), context: { role: 'pacient', fields: [{ key: 'record.coverage', source: 'record-coverage', value: 'Zprávy: načteno' }] },
      binding: { caseId: detail.identity.caseId, token: `1000.${'a'.repeat(64)}` } }
    const { result, rerender } = renderHook((props: AssistantOptions) => useAssistant(props), { initialProps: initial })
    act(() => result.current.selectContext(true))
    act(() => { void result.current.send(prompt) })
    expect(deferred.requests[0]!.request).toEqual({ role: 'pacient', text: prompt, context: initial.context, binding: initial.binding })
    rerender({ ...initial, binding: { ...initial.binding!, token: `1001.${'b'.repeat(64)}` } })
    expect(deferred.requests[0]!.signal.aborted).toBe(true)
    await act(async () => deferred.requests[0]!.resolve(reply))
    expect(result.current.messages).toEqual([])
    expect(result.current.contextSelected).toBe(false)
  })

  it.each(['case', 'role', 'version', 'session', 'close', 'clear', 'reset', 'freshness', 'scope'] as const)('%s clears all state, aborts, and ignores transport that ignores abort', async change => {
    const deferred = deferredAssistant()
    const initial = options(deferred.assistant)
    const { result, rerender } = renderHook((props: AssistantOptions) => useAssistant(props), { initialProps: initial })
    act(() => result.current.selectContext(true))
    act(() => { void result.current.send(prompt) })
    act(() => result.current.setInput('Rozepsaný dotaz'))
    expect(result.current.pending).toBe(true)
    if (change === 'clear') act(() => result.current.clear())
    else if (change === 'close') act(() => result.current.close())
    else rerender({ ...initial,
      ...(change === 'case' ? { caseId: 'another' } : {}),
      ...(change === 'role' ? { view: 'koordinator' } : {}),
      ...(change === 'version' ? { version: 1 } : {}),
      ...(change === 'session' ? { session: createMockSession() } : {}),
      ...(change === 'reset' ? { resetKey: 1 } : {}),
      ...(change === 'freshness' ? { contextFresh: false } : {}),
      ...(change === 'scope' ? { scopeKey: 'same-route-preparation-v2' } : {}),
    })
    expect(deferred.requests[0]!.signal.aborted).toBe(true)
    expect(result.current.input).toBe('')
    expect(result.current.messages).toEqual([])
    expect(result.current.contextSelected).toBe(false)
    expect(result.current.pending).toBe(false)
    await act(async () => deferred.requests[0]!.resolve(reply))
    expect(result.current.messages).toEqual([])
    expect(result.current.error).toBeNull()
  })

  it('controlled closed state clears/aborts and reopening has no retained context or transcript', async () => {
    const deferred = deferredAssistant()
    const initial = options(deferred.assistant)
    const { result, rerender } = renderHook((props: AssistantOptions) => useAssistant(props), { initialProps: initial })
    act(() => result.current.selectContext(true))
    act(() => { void result.current.send(prompt) })
    rerender({ ...initial, open: false })
    expect(deferred.requests[0]!.signal.aborted).toBe(true)
    expect(result.current.contextAvailable).toBe(false)
    act(() => result.current.selectContext(true))
    await act(async () => result.current.send(prompt))
    rerender(initial)
    await act(async () => deferred.requests[0]!.resolve(reply))
    expect(result.current.messages).toEqual([])
    expect(result.current.contextSelected).toBe(false)
  })

  it('unmount aborts, ignores deferred reply and a new mount starts empty; no storage or logging', async () => {
    const deferred = deferredAssistant()
    const initial = options(deferred.assistant)
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    const log = vi.spyOn(console, 'log')
    const { result, unmount } = renderHook(() => useAssistant(initial))
    act(() => result.current.selectContext(true))
    act(() => { void result.current.send(prompt) })
    unmount()
    expect(deferred.requests[0]!.signal.aborted).toBe(true)
    await act(async () => deferred.requests[0]!.resolve(reply))
    const next = renderHook(() => useAssistant(initial))
    expect(next.result.current.messages).toEqual([])
    expect(next.result.current.input).toBe('')
    expect(next.result.current.contextSelected).toBe(false)
    expect(storage).not.toHaveBeenCalled()
    expect(log).not.toHaveBeenCalled()
    storage.mockRestore()
    log.mockRestore()
  })

  it('Stop is safe, preserves visible history and an ignored-abort answer cannot finish a newer send', async () => {
    const deferred = deferredAssistant()
    const initial = options(deferred.assistant)
    const { result } = renderHook(() => useAssistant(initial))
    act(() => { result.current.stop(); void result.current.send(prompt) })
    act(() => result.current.stop())
    expect(deferred.requests[0]!.signal.aborted).toBe(true)
    expect(result.current.pending).toBe(false)
    act(() => { void result.current.send(prompt) })
    await act(async () => deferred.requests[0]!.resolve(reply))
    expect(result.current.pending).toBe(true)
    expect(result.current.messages).toHaveLength(2)
    await act(async () => deferred.requests[1]!.resolve(reply))
    expect(result.current.pending).toBe(false)
    expect(result.current.messages).toHaveLength(3)
  })

  it.each(['exception', 'provider-error', 'oversized', 'unknown-source', 'wrong-provenance'] as const)('sanitizes %s without displaying arbitrary exception/provider content', async failure => {
    const secret = 'PRIVATE ERROR CONTENT'
    const assistant: Assistant = { availability: 'available', provenance: 'scripted', async send() {
      if (failure === 'exception') throw new Error(secret)
      if (failure === 'provider-error') return { ok: false, error: { code: 'failed', message: secret } }
      return { ok: true, value: { provenance: failure === 'wrong-provenance' ? 'server' : 'scripted',
        text: failure === 'oversized' ? 'x'.repeat(ASSISTANT_LIMITS.output + 1) : secret,
        sources: failure === 'unknown-source' ? ['task'] : [],
      } }
    } }
    const initial = options(assistant)
    const { result } = renderHook(() => useAssistant(initial))
    await act(async () => result.current.send(prompt))
    expect(result.current.error).toBe(ASSISTANT_FAILURE_MESSAGE)
    expect(JSON.stringify(result.current.messages)).not.toContain(secret)
    expect(result.current.pending).toBe(false)
  })

  it('backend capability does not send; stale/missing context cannot be reselected', async () => {
    const assistant = new UnconfiguredAssistant()
    const send = vi.spyOn(assistant, 'send')
    const initial = { ...options(assistant), contextFresh: false }
    const { result } = renderHook(() => useAssistant(initial))
    act(() => result.current.selectContext(true))
    expect(result.current.contextAvailable).toBe(false)
    expect(result.current.selectedContext).toBeNull()
    await act(async () => result.current.send(prompt))
    expect(send).not.toHaveBeenCalled()
    expect(result.current.available).toBe(false)
  })
})
