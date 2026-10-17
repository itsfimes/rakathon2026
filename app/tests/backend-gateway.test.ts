import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildAssistantContext } from '../src/assistant/context'
import { BackendGateway, createBackendSession, validApiBase } from '../src/data/backend/gateway'
import { caseDTO } from '../src/data/backend/dto'
import { ageAt, clinicalTime } from '../src/data/backend/values'
import { caseResponse, complete, fetched, jsonResponse, resource, sessionResponse, unavailableSection, workspaceResponse } from './backend-fixtures'

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals() })
const transport = (value: unknown, status = 200) => vi.fn<typeof fetch>().mockResolvedValue(jsonResponse(value, status))
async function detail(raw = caseResponse()) {
  const result = await new BackendGateway(true, transport(raw)).readCase('synthetic-0')
  if (!result.ok) throw new Error(result.error.code)
  return result.value
}

describe('versioned same-origin backend reads', () => {
  it('reads only bounded summaries for all six patients, with unknown workflow and zero case fanout', async () => {
    const fetcher = transport(workspaceResponse())
    const result = await new BackendGateway(true, fetcher).readWorkspace()
    expect(result).toMatchObject({ ok: true, value: { asOf: fetched, queue: Array.from({ length: 6 }, () => ({ age: null, diagnosis: null, nextStep: null, phase: null, priority: null })) } })
    expect(fetcher).toHaveBeenCalledOnce()
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/workspace')
    expect(fetcher.mock.calls[0]?.[1]).toMatchObject({ credentials: 'same-origin', cache: 'no-store', redirect: 'error', headers: { Accept: 'application/json' } })
  })
  it('503 coverage is unavailable, never a successful empty workspace or mock fallback', async () => {
    const value = { ...workspaceResponse(), patients: [], coverage: { status: 'unavailable', serverTotal: null, reason: 'upstream_unavailable_or_incomplete' } }
    for (const status of [200, 503]) expect(await new BackendGateway(true, transport(value, status)).readWorkspace()).toMatchObject({ ok: false, error: { code: 'unavailable' } })
  })
  it('404 and invalid exact IDs never fall back and invalid IDs do not request', async () => {
    const fetcher = transport({ version: 1, error: { code: 'not_found', message: 'Case not found' } }, 404)
    const gateway = new BackendGateway(true, fetcher)
    expect(await gateway.readCase('synthetic-unknown')).toMatchObject({ ok: false, error: { code: 'not-found' } })
    for (const id of ['../other', 'a/b', '', 'a'.repeat(65), 'patient?x=1']) expect(await gateway.readCase(id)).toMatchObject({ ok: false, error: { code: 'not-found' } })
    expect(fetcher).toHaveBeenCalledOnce()
  })
  it.each(['patient', 'subject', 'conflicting-patient'])('rejects foreign %s rather than show another patient', async variant => {
    const raw = caseResponse()
    if (variant === 'patient') raw.patient.id = 'synthetic-other'
    else raw.sections.conditions = complete([{ ...resource('Condition'), ...(variant === 'subject' ? { subject: { reference: 'Patient/synthetic-other' } } : { patient: { reference: 'Patient/synthetic-other' } }) }])
    expect(await new BackendGateway(true, transport(raw)).readCase('synthetic-0')).toMatchObject({ ok: false, error: { code: 'unavailable' } })
  })
  it.each([0, 2, null, '1'])('rejects unsupported version %s', async version => {
    expect(await new BackendGateway(true, transport({ ...caseResponse(), version })).readCase('synthetic-0')).toMatchObject({ ok: false, error: { code: 'unavailable' } })
  })
  it('rejects malformed, oversized, non-finite, duplicate, unbound and wrong-type resource data', async () => {
    const bad = [
      { ...resource('Condition'), code: { text: 'x'.repeat(4097) } },
      { ...resource('Observation') }, { resourceType: 'Condition', id: 'x' },
      { ...resource('Condition'), code: { coding: Array(51).fill({ code: 'x' }) } },
    ]
    for (const value of bad) {
      const raw = caseResponse(); raw.sections.conditions = complete([value])
      expect(await new BackendGateway(true, transport(raw)).readCase('synthetic-0')).toMatchObject({ ok: false, error: { code: 'unavailable' } })
    }
    const raw = caseResponse(); raw.sections.observations = complete([{ ...resource('Observation'), valueQuantity: { value: Infinity } }])
    expect(() => caseDTO(raw, 'synthetic-0')).toThrow('Invalid backend response')
    raw.sections.conditions = complete([resource('Condition'), resource('Condition')])
    expect(() => caseDTO(raw, 'synthetic-0')).toThrow('Invalid backend response')
  })
  it('normalizes network/JSON errors without raw narratives or exception text', async () => {
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new Error('PRIVATE-RAW-PHI'))
    const result = await new BackendGateway(true, fetcher).readWorkspace()
    expect(result).toMatchObject({ ok: false, error: { code: 'unavailable' } })
    expect(JSON.stringify(result)).not.toContain('PRIVATE')
    expect(await new BackendGateway(true, transport('not a DTO')).readWorkspace()).toMatchObject({ ok: false })
  })
  it('propagates AbortSignal and rejects pre-aborted and late-aborted reads', async () => {
    const c = new AbortController()
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async (_url, init) => {
      expect(init?.signal).toBe(c.signal); c.abort(); return jsonResponse(caseResponse())
    })
    const g = new BackendGateway(true, fetcher)
    expect(await g.readCase('synthetic-0', c.signal)).toMatchObject({ ok: false, error: { code: 'aborted' } })
    expect(await g.readWorkspace(c.signal)).toMatchObject({ ok: false, error: { code: 'aborted' } })
    expect(await g.readSession(c.signal)).toMatchObject({ ok: false, error: { code: 'aborted' } })
    expect(fetcher).toHaveBeenCalledOnce()
  })
  it('distinguishes configured healthy and unavailable development sessions; never exposes controls or assistant', async () => {
    const healthy = await createBackendSession(undefined, transport(sessionResponse))
    expect(healthy).toMatchObject({ mode: 'backend', connection: 'connected', assistant: { availability: 'unavailable' } })
    expect(healthy).not.toHaveProperty('demoControls')
    const fetcher = transport({ ...sessionResponse, health: { ipc: 'up', database: 'down' } })
    const down = await createBackendSession(undefined, fetcher)
    expect(down).toMatchObject({ connection: 'unavailable' })
    expect(await down.gateway.readWorkspace()).toMatchObject({ ok: false, error: { code: 'unavailable' } })
    expect(fetcher).toHaveBeenCalledOnce()
  })
  it.each(['', 'https://example.test/api/v1', '//example.test/api/v1', '/api/v1/', '/api/v1?x=1'])('rejects non-fixed API base %s', value => expect(validApiBase(value)).toBe(false))
})

describe('faithful source facts and patient allowlist', () => {
  it('leaves absent clinical/workflow/dates unknown with no MDT or assistant context', async () => {
    const d = await detail()
    expect(d.identity).toMatchObject({ age: null, diagnosis: null, referrer: null, referredAt: null })
    expect(d).toMatchObject({ nextStep: null, phases: [], patient: { nextEvent: null, currentInstruction: null, coordinator: null, journey: [] } })
    expect(d.mdt).not.toHaveProperty('preparation')
    expect(d.clinical?.domains.mdtPlan).toEqual([])
    expect(d.clinical?.sources[0]).toMatchObject({ ref: { version: 'unknown' }, issued: { kind: 'unknown' }, locallyAvailable: { kind: 'unknown' } })
    for (const role of ['koordinator', 'lekar', 'pacient', 'mdt'] as const) expect(buildAssistantContext(role, d, true)).toBeNull()
  })
  it.each(['confirmed', 'provisional', 'differential', 'unconfirmed', 'refuted'])('preserves Condition verification %s independent of active status', async code => {
    const raw = caseResponse()
    raw.sections.conditions = complete([{ ...resource('Condition'), code: { text: 'Synthetic condition' }, clinicalStatus: { coding: [{ code: 'active' }] }, verificationStatus: { coding: [{ system: 'http://terminology.hl7.org/CodeSystem/condition-ver-status', code }] }, onsetDateTime: '2025-03' }])
    const d = await detail(raw), f = d.clinical!.domains.history[0]!
    expect(d.identity.diagnosis).toBeNull()
    expect(f.verification).toBe(code === 'confirmed' ? 'confirmed' : code === 'provisional' ? 'preliminary' : ['differential', 'unconfirmed'].includes(code) ? 'suspected' : 'unspecified')
    expect(f.presence).toBe(code === 'refuted' ? 'denied' : 'present')
    expect(f.effective).toEqual({ kind: 'month', value: '2025-03' })
    expect(f.value.description).toContain(code)
  })
  it('active without verification never means confirmed and five conditions never select a primary diagnosis', async () => {
    const raw = caseResponse()
    raw.sections.conditions = complete(Array.from({ length: 5 }, (_, i) => ({ ...resource('Condition', `synthetic-${i}`), clinicalStatus: { coding: [{ code: 'active' }] } })))
    const d = await detail(raw)
    expect(d.clinical!.domains.history).toHaveLength(5)
    expect(d.clinical!.domains.history.every(f => f.verification === 'unspecified')).toBe(true)
    expect(d.identity.diagnosis).toBeNull()
  })
  it('keeps reports, independent unavailable observations, exact dates/versions and unknown local availability', async () => {
    const raw = caseResponse()
    raw.sections.observations = unavailableSection()
    raw.sections.diagnosticReports = complete([{ ...resource('DiagnosticReport'), code: { text: 'Synthetic pathology' }, conclusion: 'Synthetic supplied conclusion', issued: '2025-03-04T09:10:00Z', effectiveDateTime: '2025-02' }])
    const d = await detail(raw)
    expect(d.clinical?.coverage).toMatchObject({ observations: 'unavailable', diagnosticReports: 'complete' })
    expect(d.clinical?.sources[1]).toMatchObject({ ref: { version: 'full-source-version-123456789' }, issued: { kind: 'instant', value: '2025-03-04T09:10:00Z' }, locallyAvailable: { kind: 'unknown' } })
    expect(d.clinical?.domains.imagingProcedures[0]?.effective).toEqual({ kind: 'month', value: '2025-02' })
    expect(d.patient.record?.reports[0]?.value.conclusion).toBe('Synthetic supplied conclusion')
    expect(d.patient.record?.coverage?.observations).toBe('unavailable')
    expect(Object.isFrozen(d.clinical?.domains)).toBe(true)
    expect(Object.isFrozen(d.patient.record?.coverage)).toBe(true)
  })
  it('preserves zero/false, supplied units/ranges/flags, and generic unknown observations rather than inventing labs', async () => {
    const raw = caseResponse()
    raw.sections.observations = complete([
      { ...resource('Observation', 'synthetic-lab'), category: [{ coding: [{ system: 'http://terminology.hl7.org/CodeSystem/observation-category', code: 'laboratory' }] }], code: { text: 'Synthetic zero' }, valueQuantity: { value: 0, unit: 'unit' }, referenceRange: [{ low: { value: 0 }, high: { value: 4 } }], interpretation: [{ coding: [{ system: 'http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation', code: 'L' }] }] },
      { ...resource('Observation', 'synthetic-other'), code: { text: 'Synthetic boolean' }, valueBoolean: false, category: [{ text: 'Supplied other category' }] },
    ])
    const d = await detail(raw)
    expect(d.clinical?.domains.labs[0]?.value).toMatchObject({ value: '0', unit: 'unit', referenceRange: '0 · 4', abnormalFlag: 'low' })
    expect(d.clinical?.domains.measurements[0]?.value).toMatchObject({ type: 'examination', value: 'false', examination: expect.stringContaining('Supplied other category') })
    expect(d.patient.record?.results[0]?.value.value).toBe('0')
    expect(d.patient.record?.measurements[0]?.value.value).toBe('false')
  })
  it('drops narratives, identifiers, attachment URLs/data and raw internal metadata from patient DTO, detaches sources', async () => {
    const raw = caseResponse()
    raw.patient.identifier = [{ value: 'PRIVATE-ID' }]; raw.patient.text = { div: '<script>PRIVATE</script>' }
    raw.sections.documents = complete([{ ...resource('DocumentReference'), description: 'Synthetic supplied description', date: '2025-04-05', content: [{ attachment: { title: 'Synthetic title', url: 'https://example.test/PRIVATE', data: 'PRIVATE-DATA' } }] }])
    const normalized = caseDTO(raw, 'synthetic-0')
    expect(normalized.patient).not.toHaveProperty('identifier')
    const d = await detail(raw)
    expect(d.patient.record?.reports[0]?.value.finding).toBe('Synthetic supplied description')
    expect(d.clinical?.domains.imagingProcedures[0]?.value.meta).toMatchObject({ attachments: [{ title: 'Synthetic title' }], contentSupplied: false })
    const serialized = JSON.stringify(d.patient.record)
    for (const forbidden of ['PRIVATE', 'sourceId', 'versionId', 'patientId', 'conflictIds', 'locallyAvailable']) expect(serialized).not.toContain(forbidden)
    expect(Object.isFrozen(raw)).toBe(false)
  })
  it('computes age zero only from full valid calendar dates and never substitutes January 1 for partial birth dates', () => {
    expect(ageAt('2026-10-16', fetched)).toBe(0)
    expect(ageAt('2000-10-17', fetched)).toBe(25)
    expect(ageAt('2000-10-16', fetched)).toBe(26)
    for (const birth of ['2026', '2026-03', '2025-02-29', '2026-02-31', '0000-01-01', '2027-01-01']) expect(ageAt(birth, fetched)).toBeNull()
    expect(ageAt('2024-02-29', fetched)).toBe(2)
    expect(clinicalTime('2025')).toEqual({ kind: 'approximate', label: '2025' })
    expect(clinicalTime('2025-01-01T10:00')).toEqual({ kind: 'approximate', label: '2025-01-01T10:00' })
  })
})
