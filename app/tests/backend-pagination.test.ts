import { describe, expect, it, vi } from 'vitest'
import { BackendGateway } from '../src/data/backend/gateway'
import { caseDTO, workspaceDTO } from '../src/data/backend/dto'
import { projectCase } from '../src/data/backend/projection'
import { caseResponse, complete, jsonResponse, resource, workspaceResponse } from './backend-fixtures'

function pagedCase() {
  const raw = caseResponse()
  raw.sections.observations = { ...complete(Array.from({ length: 88 }, (_, i) => ({ ...resource('Observation', `obs-${i}`),
    category: [{ coding: [{ system: 'http://terminology.hl7.org/CodeSystem/observation-category', code: 'laboratory' }] }],
    code: { text: `Synthetic test ${i}` }, valueQuantity: { value: 0, unit: 'test' }, effectiveDateTime: '2026-01',
    ...(i === 0 ? { component: [{ code: { text: 'Boolean component' }, valueBoolean: false }] } : {}),
  }))), serverTotal: null, receivedCount: 88, encounteredCount: 88, pagesFetched: 2 }
  return raw
}

describe('bounded complete root collection mapping', () => {
  it('decodes and maps all 88 resources and a component, preserving zero/false/unit/date and honest coverage', async () => {
    const raw = pagedCase()
    const result = await new BackendGateway(true, vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(raw))).readCase('synthetic-0')
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(result.value.clinical?.domains.labs).toHaveLength(89)
    expect(result.value.clinical?.domains.labs[0]?.value).toMatchObject({ value: '0', unit: 'test' })
    expect(result.value.clinical?.domains.labs[1]?.value).toMatchObject({ value: 'false' })
    expect(result.value.clinical?.domains.labs[0]?.effective).toEqual({ kind: 'month', value: '2026-01' })
    expect(result.value.patient.record?.results).toHaveLength(89)
    expect(result.value.patient.record?.collectionCoverage?.observations).toMatchObject({ status: 'complete', receivedCount: 88, encounteredCount: 88, pagesFetched: 2, serverTotal: null })
    expect(JSON.stringify(result.value.patient.record?.collectionCoverage)).not.toContain('obs-')
  })

  it('accepts root workspace88 and estimates but still rejects nested51 and root501', () => {
    const workspace = workspaceResponse()
    workspace.patients = Array.from({ length: 88 }, (_, i) => ({ patientId: `p-${i}`, label: null, birthDate: null }))
    expect(workspaceDTO(workspace).patients).toHaveLength(88)
    const raw = pagedCase()
    raw.sections.observations.serverTotal = 999
    expect(caseDTO(raw, 'synthetic-0').sections.observations.items).toHaveLength(88)
    raw.sections.observations.items = [{ ...resource('Observation'), component: Array(51).fill({ valueBoolean: false }) }]
    expect(() => caseDTO(raw, 'synthetic-0')).toThrow()
    raw.sections.observations.items = Array.from({ length: 501 }, (_, i) => resource('Observation', `obs-${i}`))
    expect(() => caseDTO(raw, 'synthetic-0')).toThrow()
  })

  it('preflights root-plus-component fanout1000 before allocating clinical facts', () => {
    const raw = pagedCase()
    raw.sections.observations.items = Array.from({ length: 20 }, (_, i) => ({ ...resource('Observation', `obs-${i}`), component: Array(50).fill({ valueBoolean: false }) }))
    expect(() => caseDTO(raw, 'synthetic-0')).toThrow()
    raw.sections.observations.items = Array.from({ length: 20 }, (_, i) => ({ ...resource('Observation', `obs-${i}`), component: Array(49).fill({ valueBoolean: false }) }))
    raw.sections.observations.receivedCount = 20
    expect(projectCase(caseDTO(raw, 'synthetic-0')).clinical?.domains.measurements).toHaveLength(1000)
  })

  it('retains typed failure reason and verified counters, old v1 nullable counters and no incomplete items', () => {
    const raw = caseResponse()
    raw.sections.observations = { ...complete(), status: 'unavailable', reason: 'auth_failed', serverTotal: 88, receivedCount: 50, encounteredCount: 50, pagesFetched: 1 }
    const dto = caseDTO(raw, 'synthetic-0')
    expect(projectCase(dto).clinical?.collectionCoverage?.observations).toMatchObject({ reason: 'auth_failed', receivedCount: 50, serverTotal: 88 })
    expect(dto.sections.observations.items).toEqual([])
    expect(caseDTO(caseResponse(), 'synthetic-0').sections.observations.receivedCount).toBeNull()
    raw.sections.observations.items = [resource('Observation')]
    expect(() => caseDTO(raw, 'synthetic-0')).toThrow()
  })

  it('local revision invalidates literal value and coverage changes even when versions/fetched time stay unchanged', () => {
    const raw = pagedCase()
    const before = projectCase(caseDTO(raw, 'synthetic-0')).clinical!.revision
    raw.sections.observations.items[0] = { ...resource('Observation', 'obs-0'), valueBoolean: false }
    const after = projectCase(caseDTO(raw, 'synthetic-0')).clinical!.revision
    expect(after).not.toBe(before)
    raw.sections.observations.serverTotal = 100
    expect(projectCase(caseDTO(raw, 'synthetic-0')).clinical!.revision).not.toBe(after)
  })

  it('workspace unavailable retains reason/counters for a later warning view, never a successful empty list', async () => {
    const raw = { ...workspaceResponse(), patients: [], coverage: { status: 'unavailable', reason: 'resource_limit', serverTotal: 1000, receivedCount: 500, encounteredCount: 501, pagesFetched: 10 } }
    const result = await new BackendGateway(true, vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(raw, 503))).readWorkspace()
    expect(result).toMatchObject({ ok: false, error: { coverage: raw.coverage } })
  })
})
