import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { UploadJob } from '../src/data/backend/uploads'
import { UploadProgress } from '../src/features/doctor/newUploadProgress'

afterEach(() => {
  cleanup()
})

function makeJob(over: Partial<UploadJob> = {}): UploadJob {
  return {
    id: 'a'.repeat(32),
    caseId: 'synthetic-0',
    filename: 'zprava.pdf',
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

describe('upload progress', () => {
  it('shows running known format as current step with contained list', () => {
    render(<UploadProgress job={makeJob({ detectedType: 'pdf', events: [{ label: 'Zkouším dekodér PDF', detail: null }], eventCount: 1 })} />)
    expect(screen.getByRole('status')).toHaveTextContent('Server soubor převádí.')
    const list = document.querySelector('ol.upload-progress__list')
    expect(list).not.toBeNull()
    expect(list?.getAttribute('aria-live')).toBeNull()
    const current = document.querySelector('li[aria-current="step"]')
    expect(current).not.toBeNull()
    expect(document.querySelectorAll('li[aria-current]').length).toBe(1)
  })

  it('warns honestly that unknown format may take longer', () => {
    render(<UploadProgress job={makeJob({ detectedType: '', newFormat: true, events: [], eventCount: 0 })} />)
    expect(screen.getByRole('status')).toHaveTextContent('může to trvat déle')
  })

  it('confirms cached recipe reuse without fake import on complete', () => {
    render(<UploadProgress job={makeJob({ status: 'complete', detectedType: 'pdf', recipeReuse: true, counts: { zaznamy: 3 }, events: [{ label: 'Hotovo', detail: null }], eventCount: 1 })} />)
    expect(screen.getByRole('status')).toHaveTextContent(/hotový ke kontrole/i)
    expect(screen.getByText(/osvědčeným postupem/)).toBeInTheDocument()
    expect(screen.queryByText(/Krok 1/)).toBeNull()
  })

  it('presents terminal human review honestly and hides placeholder markers', () => {
    render(
      <UploadProgress
        job={makeJob({
          status: 'manual-review',
          detectedType: 'nepodporovaný',
          events: [{ label: 'Krok 1', detail: null }, { label: 'Krok 2', detail: null }, { label: 'Dekodér si nevěděl rady', detail: null }],
          eventCount: 3,
        })}
      />,
    )
    expect(screen.getByRole('status')).toHaveTextContent('kontrolu člověkem')
    expect(screen.getByText(/Předáno člověku, nejde o hotový zápis/)).toBeInTheDocument()
    expect(screen.queryByText('Krok 1')).toBeNull()
    expect(screen.getByText('Dekodér si nevěděl rady')).toBeInTheDocument()
    expect(screen.getByText(/Technický průběh \(3\)/)).toBeInTheDocument()
  })

  it('evolves phase text when polled job status changes', () => {
    const view = render(<UploadProgress job={makeJob({ status: 'queued', detectedType: '', events: [], eventCount: 0 })} />)
    expect(screen.getByRole('status')).toHaveTextContent('Čeká ve frontě')
    view.rerender(<UploadProgress job={makeJob({ status: 'running', detectedType: 'pdf', newFormat: true, events: [{ label: 'Krok 1', detail: null }], eventCount: 1 })} />)
    expect(screen.getByRole('status')).toHaveTextContent('může to trvat déle')
    view.rerender(<UploadProgress job={makeJob({ status: 'complete', detectedType: 'pdf', events: [{ label: 'Hotovo', detail: null }], eventCount: 2 })} />)
    expect(screen.getByRole('status')).toHaveTextContent(/hotový ke kontrole/i)
    expect(screen.getAllByRole('status')).toHaveLength(1)
  })

  it('shows only step count when server sent no verbal description', () => {
    render(<UploadProgress job={makeJob({ status: 'running', events: [{ label: 'Krok 1', detail: null }, { label: 'Krok 2', detail: null }], eventCount: 2 })} />)
    expect(screen.getByText(/jen počet mezikroků \(2\)/)).toBeInTheDocument()
  })
})
