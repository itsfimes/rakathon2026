import { describe, expect, it } from 'vitest'
import { buildAssistantContext } from '../src/assistant/context'
import { ASSISTANT_LIMITS } from '../src/assistant/contracts'
import type { AssistantContext, AssistantRequest, AssistantRole } from '../src/assistant/contracts'
import { validContext, validReply, validRequest } from '../src/assistant/validation'
import type { CaseDetail, CaseDocument } from '../src/data/contracts'
import { buildMdtPreparation } from '../src/data/mdtPreparation'
import { createPreparationRequirements, SYNTHETIC_MEETING } from '../src/data/mock/clinicalFixtures'
import { createSeedCases } from '../src/data/mock/fixtures'

const withPreparation = (seed: CaseDetail): CaseDetail => seed.clinical && seed.mdt.meetingAt ? { ...seed, mdt: { ...seed.mdt, preparation: buildMdtPreparation({ record: seed.clinical,
  meetingId: SYNTHETIC_MEETING.id, meetingDate: seed.mdt.meetingAt, requirements: createPreparationRequirements() }) } } : seed
const detail = withPreparation(createSeedCases()[0]!)
const expectedDocumentType = { imaging: 'Zobrazovací vyšetření', markers: 'Nádorové markery', fitness: 'Celkový stav', staging: 'Staging', histology: 'Histologie' }
const expectedDocumentState = { available: 'Dostupné', missing: 'Chybí', uncertain: 'Nejisté' }
const expectedDocumentValue = (document: Pick<CaseDocument, 'kind' | 'state'>) => `${expectedDocumentType[document.kind]}: ${expectedDocumentState[document.state]}`

describe('minimal assistant projection', () => {
  it.each(['koordinator', 'pacient', 'lekar', 'mdt'] as const)('%s excludes identity, history, clinical detail, person owner and local keys', role => {
    const context = buildAssistantContext(role, detail, true)!
    const wire = JSON.stringify(context)
    for (const value of [detail.identity.patientLabel, detail.identity.patientId, detail.identity.caseId,
      detail.identity.referrer!.name, detail.nextStep!.owner.name, detail.patient.coordinator!.name,
      detail.identity.diagnosis!.label, detail.priorityExplanation, detail.mdt.finding, detail.doctor.diagnosisStatus,
      ...detail.doctor.sourceFields.flatMap(field => [field.quote, field.value]),
    ]) {
      if (value) expect(wire).not.toContain(value)
    }
    expect(Object.keys(context).sort()).toEqual(['fields', 'role'])
    expect(context.fields.every(field => Object.keys(field).sort().join(',') === 'key,source,value')).toBe(true)
    expect(validContext(context)).toBe(true)
    expect(Object.isFrozen(context.fields)).toBe(true)
  })

  it('patient receives only the patient projection, never shared task, documents or doctor/MDT fields', () => {
    const context = buildAssistantContext('pacient', detail, true)!
    expect(context.fields).toEqual([
      { key: 'instruction', source: 'patient-instruction', value: detail.patient.currentInstruction },
      { key: 'event-title', source: 'patient-event', value: detail.patient.nextEvent!.title },
      { key: 'event-date', source: 'patient-event', value: detail.patient.nextEvent!.date },
      { key: 'event-attendance', source: 'patient-event', value: detail.patient.nextEvent!.attendanceLabel },
      { key: 'event-followup', source: 'patient-event', value: detail.patient.nextEvent!.followup },
      ...(detail.patient.coordinator!.contact ? [{ key: 'contact', source: 'patient-contact', value: detail.patient.coordinator!.contact }] : []),
    ])
  })

  it('coordinator contains operational task/organization/due/ack and document states only', () => {
    const context = buildAssistantContext('koordinator', detail, true)!
    expect(context.fields.slice(0, 4).map(field => field.value)).toEqual([
      detail.nextStep!.title, detail.nextStep!.owner.organization, detail.nextStep!.dueAt,
      { pending: 'Nepřevzato', accepted: 'Převzato', 'awaiting-information': 'Čeká na doplnění', new: 'Nový' }[detail.nextStep!.acknowledgement],
    ])
    expect(context.fields.slice(4)).toEqual(detail.documents.map(document => ({ key: 'document-state', source: 'documents', value: expectedDocumentValue(document) })))
  })

  it('referrer omits referral notes/dates and MDT omits findings/draft/meeting/clinical source fields', () => {
    const referral = buildAssistantContext('lekar', detail, true)!
    expect(referral.fields).toEqual([
      ...detail.doctor.referralStatus.map(item => ({ key: 'referral-state', source: 'referral', value: `${item.title}: ${{ done: 'Dokončeno', now: 'Nyní', later: 'Později' }[item.state]}` })),
      { key: 'obligations', source: 'obligations', value: detail.doctor.obligations },
    ])
    const mdt = buildAssistantContext('mdt', detail, true)!
    expect(mdt.fields.every(field => field.key === 'document-metadata' && field.source === 'document-metadata')).toBe(true)
    expect(mdt.fields).toEqual(detail.mdt.preparation!.documents.map(document => ({ key: 'document-metadata', source: 'document-metadata', value: expectedDocumentValue(document) })))
  })

  it.each(['koordinator', 'mdt'] as const)('%s preserves structural type/state for every seeded case without patient identity text', role => {
    const cases = createSeedCases().map(withPreparation)
    for (const seeded of cases) {
      const context = buildAssistantContext(role, seeded, true)!
      if (role === 'mdt' && !seeded.mdt.preparation) { expect(context).toBeNull(); continue }
      expect(context).not.toBeNull()
      const documentFields = context.fields.filter(field => field.source === (role === 'mdt' ? 'document-metadata' : 'documents'))
      expect(documentFields.map(field => field.value)).toEqual((role === 'mdt' ? seeded.mdt.preparation!.documents : seeded.documents).map(expectedDocumentValue))
      for (const other of cases) expect(JSON.stringify(context)).not.toContain(other.identity.patientLabel)
    }
  })

  it.each(['koordinator', 'mdt'] as const)('%s excludes malicious document labels/state labels and all source metadata rather than redacting names', role => {
    const identityText = 'Tomáš Dušek / PRIVATE DOCUMENT IDENTITY'
    const poisoned = { ...detail, documents: detail.documents.map(document => ({
      ...document, label: identityText, coordinatorLabel: identityText, stateLabel: identityText,
      sources: [{ title: identityText, date: identityText, page: 999999 }],
    })) }
    const context = buildAssistantContext(role, poisoned, true)!
    const original = buildAssistantContext(role, detail, true)!
    expect(context).toEqual(original)
    expect(JSON.stringify(context)).not.toContain(identityText)
    expect(JSON.stringify(context)).not.toContain('999999')
    expect(context.fields.filter(field => field.source === (role === 'mdt' ? 'document-metadata' : 'documents')).map(field => field.value)).toEqual((role === 'mdt' ? detail.mdt.preparation!.documents : detail.documents).map(expectedDocumentValue))
  })

  it('no case, specimen, stale snapshot and oversized context fail closed rather than silently truncate', () => {
    expect(buildAssistantContext('pacient', null, true)).toBeNull()
    expect(buildAssistantContext('specimen', detail, true)).toBeNull()
    expect(buildAssistantContext('pacient', detail, false)).toBeNull()
    expect(buildAssistantContext('pacient', { ...detail, patient: { ...detail.patient, currentInstruction: 'x'.repeat(ASSISTANT_LIMITS.field + 1) } }, true)).toBeNull()
  })
})

describe('bounded request and source contracts', () => {
  const context: AssistantContext = { role: 'pacient', fields: [{ key: 'instruction', source: 'patient-instruction', value: 'Pokyn' }] }
  const request: AssistantRequest = { role: 'pacient', text: 'Dotaz', context }
  it('accepts exact allowed schema and rejects extra hidden context/history/identifiers and cross-role fields', () => {
    expect(validRequest(request)).toBe(true)
    expect(validRequest({ ...request, caseId: 'secret' } as AssistantRequest)).toBe(false)
    expect(validRequest({ ...request, history: [] } as AssistantRequest)).toBe(false)
    expect(validRequest({ ...request, role: 'mdt' })).toBe(false)
    expect(validRequest({ ...request, role: 'specimen' as AssistantRole })).toBe(false)
    expect(validContext({ ...context, caseId: 'secret' } as AssistantContext)).toBe(false)
    expect(validContext({ ...context, fields: [{ ...context.fields[0]!, source: 'task' }] })).toBe(false)
    expect(validContext({ ...context, fields: [{ key: 'task-title', source: 'task', value: 'Skrytý krok' }] })).toBe(false)
  })

  it('rejects blank/oversized input, empty/too many/oversized fields and oversized aggregate', () => {
    expect(validRequest({ ...request, text: ' ' })).toBe(false)
    expect(validRequest({ ...request, text: 'x'.repeat(ASSISTANT_LIMITS.input + 1) })).toBe(false)
    expect(validRequest({ ...request, text: 'x'.repeat(ASSISTANT_LIMITS.input) })).toBe(true)
    expect(validContext({ ...context, fields: [] })).toBe(false)
    expect(validContext({ ...context, fields: Array.from({ length: ASSISTANT_LIMITS.fields + 1 }, () => context.fields[0]!) })).toBe(false)
    expect(validContext({ ...context, fields: [{ ...context.fields[0]!, value: 'x'.repeat(ASSISTANT_LIMITS.field + 1) }] })).toBe(false)
    expect(validContext({ ...context, fields: Array.from({ length: 20 }, () => ({ ...context.fields[0]!, value: 'x'.repeat(300) })) })).toBe(false)
  })

  it('replies are bounded plain text with provenance and only supplied allowlisted sources, no URLs/actions', () => {
    const reply = { provenance: 'scripted' as const, text: 'Odpověď', sources: ['patient-instruction'] as const }
    expect(validReply(reply, request, 'scripted')).toBe(true)
    expect(validReply({ ...reply, sources: ['task'] }, request, 'scripted')).toBe(false)
    expect(validReply(reply, { role: 'pacient', text: 'Dotaz' }, 'scripted')).toBe(false)
    expect(validReply(reply, request, 'server')).toBe(false)
    expect(validReply({ ...reply, text: 'x'.repeat(ASSISTANT_LIMITS.output + 1) }, request, 'scripted')).toBe(false)
    expect(validReply({ ...reply, href: 'https://example.com' } as typeof reply, request, 'scripted')).toBe(false)
  })
})
