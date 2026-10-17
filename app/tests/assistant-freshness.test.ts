import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import { useAssistant } from '../src/assistant/useAssistant'
import type { CaseDetail, Result } from '../src/data/contracts'
import { failure, success } from '../src/data/contracts'
import { createSeedCases } from '../src/data/mock/fixtures'
import { createMockSession } from '../src/data/mock/provider'
import { useResource } from '../src/hooks/useResource'

afterEach(() => cleanup())

it('a replacement loader is not fresh merely because case and revision are unchanged', async () => {
  const detail = createSeedCases()[0]!
  let resolveFirst!: (value: Result<CaseDetail>) => void
  let resolveSecond!: (value: Result<CaseDetail>) => void
  const first = () => new Promise<Result<CaseDetail>>(resolve => { resolveFirst = resolve })
  const second = () => new Promise<Result<CaseDetail>>(resolve => { resolveSecond = resolve })
  const { result, rerender } = renderHook(({ load }) => useResource('same-case', 0, load), { initialProps: { load: first } })
  await act(async () => resolveFirst(success(detail)))
  expect(result.current.status === 'ready' && result.current.fresh).toBe(true)
  rerender({ load: second })
  expect(result.current.status === 'ready' && result.current.fresh).toBe(false)
  await act(async () => resolveSecond(success(detail)))
  expect(result.current.status === 'ready' && result.current.fresh).toBe(true)
})

it('retained same-case snapshot stays visible but is not reselectable until the matching revision succeeds', async () => {
  const detail = createSeedCases()[0]!
  const session = createMockSession()
  const pending: ((value: Result<CaseDetail>) => void)[] = []
  const load = () => new Promise<Result<CaseDetail>>(resolve => pending.push(resolve))
  const { result, rerender } = renderHook(({ version }: { version: number }) => {
    const resource = useResource(detail.identity.caseId, version, load)
    const fresh = resource.status === 'ready' && resource.fresh
    const assistant = useAssistant({ session, caseId: detail.identity.caseId, view: 'pacient', version, open: true, contextFresh: fresh })
    return { resource, assistant }
  }, { initialProps: { version: 0 } })
  expect(result.current.assistant.caseId).toBe(detail.identity.caseId)
  await act(async () => pending[0]!(success(detail)))
  expect(result.current.resource).toEqual({ status: 'ready', value: detail, fresh: true })
  rerender({ version: 1 })
  expect(result.current.resource).toEqual({ status: 'ready', value: detail, fresh: false })
  expect(result.current.assistant.messages).toEqual([])
  // A superseded refresh may finish even if its transport ignores abort.
  rerender({ version: 2 })
  await act(async () => pending[1]!(success(detail)))
  expect(result.current.assistant.caseId).toBe(detail.identity.caseId)
  const updated = { ...detail, patient: { ...detail.patient, currentInstruction: 'Nově dodaný pokyn' } }
  await act(async () => pending[2]!(success(updated)))
  expect(result.current.assistant.caseId).toBe(detail.identity.caseId)
  rerender({ version: 3 })
  await act(async () => pending[3]!(failure('unavailable', 'Nedostupné')))
  expect(result.current.assistant.caseId).toBe(detail.identity.caseId)
})
