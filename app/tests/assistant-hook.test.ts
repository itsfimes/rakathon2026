import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ASSISTANT_LIMITS } from '../src/assistant/contracts'
import type { Assistant, AssistantRequest, AssistantResult } from '../src/assistant/contracts'
import { ASSISTANT_CONTEXT_TOO_LARGE_MESSAGE, ASSISTANT_FAILURE_MESSAGE, useAssistant } from '../src/assistant/useAssistant'
import type { AssistantOptions } from '../src/assistant/useAssistant'
import { createMockSession } from '../src/data/mock/provider'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
const reply: AssistantResult = { ok: true, value: { provenance: 'server', text: 'Odpověď', sources: ['Patient/selected'], coverage: { status: 'complete', resources: 1, uploads: 0, failedTypes: [] } } }
const options = (assistant: Assistant): AssistantOptions => ({ session: { ...createMockSession(), assistant }, view: 'pacient', caseId: 'selected', version: 0, open: true, contextFresh: true })
function deferredAssistant() {
  const requests: { request: AssistantRequest; signal: AbortSignal; resolve: (value: AssistantResult) => void }[] = []
  const send = vi.fn((request: AssistantRequest, signal: AbortSignal) => new Promise<AssistantResult>(resolve => requests.push({ request, signal, resolve })))
  const assistant: Assistant = { availability: 'available', provenance: 'server', send }
  return { assistant, requests, send }
}
describe('explicit-send assistant state', () => {
  it('automatically includes exact selected caseId only on explicit send, never local metadata or history', async () => {
    const deferred = deferredAssistant()
    const initial = options(deferred.assistant)
    const { result } = renderHook(() => useAssistant(initial))
    act(() => result.current.setInput('Dotaz'))
    expect(deferred.send).not.toHaveBeenCalled()
    act(() => { void result.current.send() })
    expect(deferred.requests[0]!.request).toEqual({ role: 'pacient', text: 'Dotaz', caseId: 'selected' })
    await act(async () => deferred.requests[0]!.resolve(reply))
    expect(result.current.messages).toHaveLength(2)
  })
  it('without a selected case sends a general question; stale details never substitute another case', async () => {
    const deferred = deferredAssistant()
    const initial = { ...options(deferred.assistant), caseId: null, contextFresh: false }
    const { result, rerender } = renderHook((props: AssistantOptions) => useAssistant(props), { initialProps: initial as AssistantOptions })
    act(() => { void result.current.send('Q') })
    expect(deferred.requests[0]!.request).toEqual({ role: 'pacient', text: 'Q' })
    rerender({ ...initial, caseId: 'new-selected', contextFresh: false })
    act(() => { void result.current.send('Q') })
    expect(deferred.requests[1]!.request).toEqual({ role: 'pacient', text: 'Q', caseId: 'new-selected' })
    await act(async () => { deferred.requests[0]!.resolve(reply); deferred.requests[1]!.resolve(reply) })
  })
  it.each(['case', 'role', 'version', 'session', 'close', 'clear', 'reset', 'freshness', 'scope'] as const)('%s aborts and drops late replies even when transport ignores abort', async change => {
    const deferred = deferredAssistant()
    const initial = options(deferred.assistant)
    const { result, rerender } = renderHook((props: AssistantOptions) => useAssistant(props), { initialProps: initial })
    act(() => { void result.current.send('Q') })
    act(() => result.current.setInput('Rozepsaný dotaz'))
    if (change === 'clear') act(() => result.current.clear())
    else if (change === 'close') act(() => result.current.close())
    else rerender({ ...initial,
      ...(change === 'case' ? { caseId: 'another' } : {}), ...(change === 'role' ? { view: 'koordinator' } : {}),
      ...(change === 'version' ? { version: 1 } : {}), ...(change === 'session' ? { session: createMockSession() } : {}),
      ...(change === 'reset' ? { resetKey: 1 } : {}), ...(change === 'freshness' ? { contextFresh: false } : {}),
      ...(change === 'scope' ? { scopeKey: 'v2' } : {}),
    })
    expect(deferred.requests[0]!.signal.aborted).toBe(true)
    expect(result.current.input).toBe('')
    expect(result.current.messages).toEqual([])
    await act(async () => deferred.requests[0]!.resolve(reply))
    expect(result.current.messages).toEqual([])
    expect(result.current.error).toBeNull()
  })
  it('bounds input/history and allows one pending send', async () => {
    const deferred = deferredAssistant()
    const initial = options(deferred.assistant)
    const { result } = renderHook(() => useAssistant(initial))
    act(() => result.current.setInput('x'.repeat(1001)))
    expect(result.current.input).toBe('')
    await act(async () => { await result.current.send(' '); await result.current.send('x'.repeat(1001)) })
    expect(deferred.send).not.toHaveBeenCalled()
    for (let i = 0; i < ASSISTANT_LIMITS.history / 2; i++) {
      act(() => { void result.current.send('Q'); void result.current.send('Q') })
      expect(deferred.send).toHaveBeenCalledTimes(i + 1)
      await act(async () => deferred.requests[i]!.resolve(reply))
    }
    await act(async () => result.current.send('Q'))
    expect(result.current.error).toContain('Limit konverzace')
  })
  it('stop preserves history and a late answer cannot finish a newer send', async () => {
    const deferred = deferredAssistant()
    const initial = options(deferred.assistant)
    const { result } = renderHook(() => useAssistant(initial))
    act(() => { void result.current.send('Q') })
    act(() => result.current.stop())
    act(() => { void result.current.send('Q') })
    await act(async () => deferred.requests[0]!.resolve(reply))
    expect(result.current.pending).toBe(true)
    await act(async () => deferred.requests[1]!.resolve(reply))
    expect(result.current.messages).toHaveLength(3)
  })
  it('shows a safe Czech context-size explanation', async () => {
    const deferred = deferredAssistant()
    const initial = options(deferred.assistant)
    const { result } = renderHook(() => useAssistant(initial))
    act(() => { void result.current.send('Q') })
    await act(async () => deferred.requests[0]!.resolve({ ok: false, error: { code: 'context_too_large' } }))
    expect(result.current.error).toBe(ASSISTANT_CONTEXT_TOO_LARGE_MESSAGE)
  })
  it('unmount aborts without storage/logging and failures do not expose arbitrary text', async () => {
    const deferred = deferredAssistant()
    const initial = options(deferred.assistant)
    const storage = vi.spyOn(Storage.prototype, 'setItem')
    const { result, unmount } = renderHook(() => useAssistant(initial))
    act(() => { void result.current.send('Q') })
    unmount()
    expect(deferred.requests[0]!.signal.aborted).toBe(true)
    await act(async () => deferred.requests[0]!.resolve(reply))
    expect(storage).not.toHaveBeenCalled()
    storage.mockRestore()
    const broken = options({ availability: 'available', provenance: 'server', async send() { throw new Error('PRIVATE') } })
    const next = renderHook(() => useAssistant(broken))
    await act(async () => next.result.current.send('Q'))
    expect(next.result.current.error).toBe(ASSISTANT_FAILURE_MESSAGE)
  })
})
