import { describe, expect, it } from 'vitest'
import type { AssistantRequest } from '../src/assistant/contracts'
import { validCoverage, validReply, validRequest } from '../src/assistant/validation'

const coverage = { status: 'complete', resources: 32, uploads: 2, failedTypes: [] }
const reply = { provenance: 'server', text: 'Odpověď', sources: ['Patient/p', 'MedicationRequest/m', 'upload/123'], coverage }

describe('server-assembled assistant contract', () => {
  it('accepts only role, question and an optional exact case identifier', () => {
    expect(validRequest({ role: 'lekar', text: 'Q', caseId: 'patient-1.2' })).toBe(true)
    expect(validRequest({ role: 'pacient', text: 'Q' })).toBe(true)
    for (const extra of [{ context: {} }, { binding: {} }, { userId: 'admin' }, { history: [] }]) {
      expect(validRequest({ role: 'pacient', text: 'Q', ...extra } as AssistantRequest)).toBe(false)
    }
    for (const caseId of ['', '.', '..', '...', '--', '.-.', 'a/b', 'a b', 'x'.repeat(65), null, undefined]) {
      expect(validRequest({ role: 'pacient', text: 'Q', caseId } as AssistantRequest)).toBe(false)
    }
    expect(validRequest({ role: 'lekar', text: 'x'.repeat(1001) })).toBe(false)
  })
  it('accepts server labels without a client field allowlist, up to 50 sources and 12000 chars', () => {
    expect(validReply(reply, 'server')).toBe(true)
    expect(validReply({ ...reply, text: 'x'.repeat(12000), sources: Array.from({ length: 50 }, (_, i) => `Observation/${i}`) }, 'server')).toBe(true)
    for (const invalid of [{ ...reply, text: 'x'.repeat(12001) }, { ...reply, sources: ['x', 'x'] }, { ...reply, sources: Array.from({ length: 51 }, (_, i) => `${i}`) }, { ...reply, coverage: undefined }, { ...reply, hidden: true }]) {
      expect(validReply(invalid, 'server')).toBe(false)
    }
    expect(validReply(reply, 'scripted')).toBe(false)
  })
  it('validates coverage and does not invent counts or missing types', () => {
    expect(validCoverage({ ...coverage, status: 'partial', failedTypes: ['ImagingStudy'], unreadableAttachments: 1 })).toBe(true)
    for (const invalid of [{ ...coverage, resources: -1 }, { ...coverage, uploads: 1.5 }, { ...coverage, failedTypes: ['secret/type'] }, { ...coverage, status: 'invented' }]) expect(validCoverage(invalid)).toBe(false)
  })
})
