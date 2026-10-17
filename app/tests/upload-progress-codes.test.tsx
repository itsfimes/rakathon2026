import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { UploadJob } from '../src/data/backend/uploads'
import { UploadProgress } from '../src/features/doctor/newUploadProgress'

afterEach(() => {
  cleanup()
})

function makeJob(over: Partial<UploadJob> = {}): UploadJob {
  return {
    id: 'c'.repeat(32),
    caseId: 'synthetic-0',
    filename: 'zprava.hpx',
    sha256: 'abc',
    sourceUrn: 'urn:test:1',
    detectedType: '',
    status: 'running',
    createdAt: '2026-10-16T12:00:00Z',
    events: [],
    eventCount: 0,
    counts: {},
    recipeReuse: false,
    newFormat: false,
    plannerMode: 'none',
    model: { providerId: 'rakathon-azure', model: 'gpt-6-luna-dz-eu', mode: 'none' },
    ...over,
  }
}

describe('upload progress from actual event codes', () => {
  it('marks decoding done from decode_done and conversion current from fhir_start while running', () => {
    render(<UploadProgress job={makeJob({
      detectedType: 'hpx',
      newFormat: true,
      plannerMode: 'planner',
      events: [
        { label: 'Zjištěn nový formát', detail: null, code: 'new_format_detected', status: 'ok' },
        { label: 'Postup navržený pomocníkem', detail: null, code: 'planner_recipe', status: 'ok' },
        { label: 'Rozluštění dokončeno', detail: null, code: 'decode_done', status: 'ok' },
        { label: 'Převod do zdravotního formátu', detail: null, code: 'fhir_start', status: 'ok' },
      ],
      eventCount: 4,
    })} />)
    expect(screen.getByRole('status')).toHaveTextContent('převádí rozluštěný text')
    expect(screen.getByText('Rozluštění dokončeno')).toBeInTheDocument()
    expect(screen.queryByText(/Krok \d/)).toBeNull()
  })

  it('never marks decoding done for failed, stale or no-agent attempts', () => {
    render(<UploadProgress job={makeJob({
      status: 'failed',
      newFormat: true,
      plannerMode: 'fallback',
      events: [
        { label: 'Postup navržený pomocníkem', detail: null, code: 'planner_recipe', status: 'failed' },
        { label: 'Opakovaný formát, osvědčený postup', detail: null, code: 'cache_reuse', status: 'stale' },
        { label: 'Záložní luštění bez pomocníka', detail: null, code: 'planner_fallback', status: 'no-agent' },
      ],
      eventCount: 3,
    })} />)
    expect(screen.getByRole('status')).toHaveTextContent('nezdařil')
    expect(screen.getByText(/Rozluštění zůstalo nedokončené/)).toBeInTheDocument()
    expect(screen.getByText(/nezdařilo se/)).toBeInTheDocument()
    expect(screen.getByText(/zastaralé/)).toBeInTheDocument()
    expect(screen.getByText(/bez pomocníka AI/)).toBeInTheDocument()
  })

  it('humanizes unknown codes instead of generic step markers', () => {
    render(<UploadProgress job={makeJob({
      events: [{ label: 'Krok 1', detail: null, code: 'mystery_xyz', status: 'tried' }],
      eventCount: 1,
    })} />)
    expect(screen.getByText('mystery xyz')).toBeInTheDocument()
    expect(screen.queryByText('Krok 1')).toBeNull()
  })

  it('distinguishes review states from a plain finished conversion', () => {
    const base = makeJob({ status: 'complete', detectedType: 'pdf', eventCount: 1, events: [{ label: 'Převod dokončen', detail: null, code: 'decode_done', status: 'ok' }] })
    const draft = render(<UploadProgress job={{ ...base, review: { state: 'draft', revision: 2, valid: false, updatedAt: 't', reviewedBy: null } }} />)
    expect(screen.getByText(/Rozpracovaná ruční kontrola/)).toBeInTheDocument()
    expect(screen.getByText(/uložená verze neplatná/)).toBeInTheDocument()
    draft.unmount()
    cleanup()
    render(<UploadProgress job={{ ...base, review: { state: 'imported', revision: 3, valid: true, updatedAt: 't', reviewedBy: 'demo.lekar' } }} />)
    expect(screen.getByText(/Importováno do záznamu/)).toBeInTheDocument()
    draft.unmount()
    cleanup()
    render(<UploadProgress job={{ ...base, review: { state: 'import-uncertain', revision: 3, valid: true, updatedAt: 't', reviewedBy: null } }} />)
    expect(screen.getByText(/nejistý/)).toBeInTheDocument()
  })

  it('keeps cache reuse honest on a finished conversion', () => {
    render(<UploadProgress job={makeJob({
      status: 'complete',
      detectedType: 'hpx',
      recipeReuse: true,
      plannerMode: 'cache',
      events: [
        { label: 'Opakovaný formát, osvědčený postup', detail: null, code: 'cache_reuse', status: 'ok' },
        { label: 'Rozluštění dokončeno', detail: null, code: 'decode_done', status: 'ok' },
      ],
      eventCount: 2,
    })} />)
    expect(screen.getByRole('status')).toHaveTextContent(/hotový ke kontrole/i)
    expect(screen.getByText(/osvědčeným postupem/)).toBeInTheDocument()
  })
})
