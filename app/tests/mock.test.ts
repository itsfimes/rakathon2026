import { describe, expect, it } from 'vitest'
import type { Result } from '../src/data/contracts'
import { createMockSession } from '../src/data/mock/provider'

function unwrap<T>(result: Result<T>): T {
  if (!result.ok) throw new Error(result.error.code)
  return result.value
}

describe('shared synthetic store', () => {
  it('provides six matching selectable cases and reachable provenance', async () => {
    const { gateway } = createMockSession({ delayMs: 0 })
    const workspace = unwrap(await gateway.readWorkspace())
    expect(workspace.metadata.provenance).toBe('RAKATHON_SYNTHETIC_FIXTURE_V1')
    expect(workspace.queue).toHaveLength(6)
    for (const row of workspace.queue) {
      const detail = unwrap(await gateway.readCase(row.caseId))
      expect(detail.identity).toMatchObject({ caseId: row.caseId, patientLabel: row.patientLabel, age: row.age, diagnosis: row.diagnosis })
      expect(detail.nextStep).toEqual(row.nextStep)
      if (row.caseId !== workspace.defaultCaseId) expect(JSON.stringify(detail)).not.toContain('Novák')
      expect(detail.mdt.requiredDocumentIds.every(id => detail.documents.some(document => document.id === id))).toBe(true)
    }
  })
  it('preserves symptom-to-KOC T1 and qualified source evidence', async () => {
    const { gateway } = createMockSession({ delayMs: 0 })
    const detail = unwrap(await gateway.readCase('novak'))
    expect(detail.phases[0]).toMatchObject({ startedAt: '2026-01-05', endedAt: '2026-01-07', days: 2, label: 'příznak → předání do KOC' })
    expect(detail.doctor.sourceFields.find(field => field.id === 'novak-finding')).toMatchObject({ status: 'literal', quote: '…v hlavě pankreatu hypoechogenní ložisko…' })
    expect(detail.doctor.sourceFields.find(field => field.id === 'novak-metastases')).toMatchObject({ status: 'uncertain', quote: '…bez jednoznačných známek vzdálených metastáz…' })
    expect(detail.documents.filter(document => document.state === 'available')).toHaveLength(3)
  })
  it('acceptance is shared by queue/detail and old snapshots remain unchanged', async () => {
    const { gateway, demoControls } = createMockSession({ delayMs: 0 })
    const before = unwrap(await gateway.readCase('novak'))
    expect(unwrap(await demoControls.acceptTask(before.nextStep!.id))).toBeUndefined()
    const detail = unwrap(await gateway.readCase('novak'))
    const workspace = unwrap(await gateway.readWorkspace())
    expect(detail.nextStep!.acknowledgement).toBe('accepted')
    expect(detail.nextStep!.acceptedAt).toBe(workspace.asOf)
    expect(detail.nextStep).toEqual(workspace.queue[0]?.nextStep)
    expect(before.nextStep!.acknowledgement).toBe('pending')
    expect(detail.nextStep!.pendingLabel).toBeUndefined()
    expect(detail.priorityExplanation).not.toContain('nikdo nepřevzal')
  })
  it('review is shared without inventing histology or clinical finalization', async () => {
    const { gateway, demoControls } = createMockSession({ delayMs: 0 })
    const before = unwrap(await gateway.readCase('novak'))
    for (const document of before.documents) unwrap(await demoControls.markDocumentReviewed(document.id))
    const detail = unwrap(await gateway.readCase('novak'))
    expect(detail.documents.every(document => document.reviewState === 'reviewed')).toBe(true)
    expect(detail.doctor.sourceFields.every(field => field.reviewState === 'reviewed')).toBe(true)
    expect(detail.documents.find(document => document.kind === 'histology')?.state).toBe('missing')
    expect(detail.doctor.sourceFields.find(field => field.label === 'Histologie')?.status).toBe('absent')
    expect(detail.mdt.finalization.state).toBe('blocked')
    expect(detail.mdt.draft).toEqual(before.mdt.draft)
  })
  it('returns independent deeply frozen snapshots, never mutable store references', async () => {
    const { gateway } = createMockSession({ delayMs: 0 })
    const first = unwrap(await gateway.readCase('novak'))
    const second = unwrap(await gateway.readCase('novak'))
    expect(first).not.toBe(second)
    expect(first.nextStep).not.toBe(second.nextStep)
    expect(() => Reflect.set(first.identity, 'patientLabel', 'tampered')).not.toThrow()
    expect(Reflect.set(first.identity, 'patientLabel', 'tampered')).toBe(false)
    expect(Object.isFrozen(first.doctor.sourceFields)).toBe(true)
    expect(unwrap(await gateway.readCase('novak')).identity.patientLabel).toBe(second.identity.patientLabel)
  })
  it('unknown IDs never select default fixtures or mutate state', async () => {
    const { gateway, demoControls } = createMockSession({ delayMs: 0 })
    const before = unwrap(await gateway.readWorkspace())
    for (const result of [await gateway.readCase('unknown'), await demoControls.acceptTask('unknown'), await demoControls.markDocumentReviewed('unknown')]) {
      expect(result).toMatchObject({ ok: false, error: { code: 'not-found' } })
    }
    expect(unwrap(await gateway.readWorkspace())).toEqual(before)
  })
  it('reset restores seed snapshots without changing source or another session', async () => {
    const { gateway, demoControls } = createMockSession({ delayMs: 0 })
    const before = unwrap(await gateway.readCase('novak'))
    unwrap(await demoControls.acceptTask(before.nextStep!.id))
    unwrap(await demoControls.markDocumentReviewed('novak-imaging'))
    unwrap(await demoControls.reset())
    expect(unwrap(await gateway.readCase('novak'))).toEqual(before)
    expect(gateway.mode).toBe('mock')
    const other = createMockSession({ delayMs: 0 })
    unwrap(await demoControls.acceptTask(before.nextStep!.id))
    expect(unwrap(await other.gateway.readCase('novak'))).toEqual(before)
  })
  it('aborts pre-cancelled and in-flight reads with typed errors', async () => {
    const { gateway } = createMockSession({ delayMs: 10 })
    const controller = new AbortController()
    const pending = gateway.readCase('novak', controller.signal)
    controller.abort()
    expect(await pending).toMatchObject({ ok: false, error: { code: 'aborted' } })
    expect(await gateway.readWorkspace(controller.signal)).toMatchObject({ ok: false, error: { code: 'aborted' } })
    expect(await gateway.readCase('novak', controller.signal)).toMatchObject({ ok: false, error: { code: 'aborted' } })
    expect((await gateway.readCase('dusek')).ok).toBe(true)
  })
})
