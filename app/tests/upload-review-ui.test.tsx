import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { UploadCapability, UploadJob, UploadReviewSummary } from '../src/data/backend/uploads'
import type { ReviewResult, UploadReview } from '../src/data/backend/uploadReview'
import { ReviewDialog } from '../src/features/doctor/ReviewDialog'
import { UploadPanel } from '../src/features/doctor/UploadPanel'

afterEach(() => {
  cleanup()
})

const JOB_ID = 'b'.repeat(32)
const CASE = 'synthetic-0'
const CANDIDATE = '{"resourceType":"Bundle","type":"collection","entry":[]}'

function validationBody(valid: boolean) {
  return {
    valid,
    issues: valid ? [] : [{ code: 'invalid_candidate', path: 'entry[0]', message: 'Chybí povinné pole.' }],
    counts: { Observation: 2 },
    patientRef: `Patient/${CASE}`,
    sourceUrn: 'urn:test:1',
    sourceSha256: 'abc',
    modelDraftAvailable: true,
    sourceMethod: null,
    transcriptionUntrusted: false,
    updatedAt: '2026-10-16T12:00:00Z',
    reviewedBy: null,
  }
}

function reviewBody(revision: number, candidate: string, valid: boolean, state: string): UploadReview {
  return {
    jobId: JOB_ID,
    revision,
    state: state as UploadReview['state'],
    candidateText: candidate,
    validation: validationBody(valid) as UploadReview['validation'],
    counts: { Observation: 2 },
    patientRef: `Patient/${CASE}`,
    sourceUrn: 'urn:test:1',
    sourceSha256: 'abc',
    caseId: CASE,
    modelDraftAvailable: true,
    modelDraftReason: null,
    sourceMethod: null,
    transcriptionUntrusted: false,
    updatedAt: '2026-10-16T12:00:00Z',
    reviewedBy: null,
    importReceipt: state === 'imported' ? { stored: 2 } : null,
    approvalId: state === 'imported' ? 'approval-1' : null,
  }
}

function jobFixture(status: UploadJob['status'], withReview: boolean): UploadJob {
  return {
    id: JOB_ID,
    caseId: CASE,
    filename: 'zprava.pdf',
    sha256: 'abc',
    sourceUrn: 'urn:test:1',
    detectedType: 'pdf',
    status,
    createdAt: '2026-10-16T12:00:00Z',
    events: [{ label: 'Převod do zdravotního formátu', detail: null, code: 'fhir_start', status: 'ok' }],
    eventCount: 1,
    counts: {},
    recipeReuse: false,
    newFormat: false,
    plannerMode: 'none',
    model: { providerId: 'rakathon-azure', model: 'gpt-6-luna-dz-eu', mode: 'none' },
    review: withReview ? { state: 'draft', revision: 0, valid: false, updatedAt: 't', reviewedBy: null } : undefined,
  }
}

interface Scenario {
  current: UploadReview
  enabled: boolean
  reason: string | null
  modelText: string | null
  draftCalls: unknown[]
  approveCalls: unknown[]
  draftImpl?: (revision: number, text: string) => ReviewResult<UploadReview>
  approveImpl?: (revision: number) => ReviewResult<UploadReview>
}

function stubCapability(scenario: Scenario): UploadCapability {
  return {
    capabilities: async () => ({ ok: true, value: { enabled: true, maxFileBytes: 5242880, reason: null, aiAvailable: true } }),
    listCase: async caseId => ({ ok: true, value: caseId === CASE ? [jobFixture('manual-review', true)] : [] }),
    fetchJob: async () => ({ ok: false, error: { code: 'not-found', message: 'Záznam nebyl nalezen.' } }),
    upload: async () => ({ ok: false, error: { code: 'denied', message: 'Soubor se nepodařilo odeslat.' } }),
    fetchReview: async () => ({
      ok: true,
      value: { review: scenario.current, approvalEnabled: scenario.enabled, approvalReason: scenario.reason as null },
    }),
    fetchModelText: async () => ({ ok: true, value: scenario.modelText }),
    saveDraft: async (_jobId, revision, candidateText) => {
      scenario.draftCalls.push({ revision, candidateText })
      if (scenario.draftImpl) return scenario.draftImpl(revision, candidateText)
      return { ok: true, value: reviewBody(revision + 1, candidateText, false, 'draft') }
    },
    approveReview: async (_jobId, revision) => {
      scenario.approveCalls.push({ revision, patientConfirmed: true })
      if (scenario.approveImpl) return scenario.approveImpl(revision)
      return { ok: true, value: reviewBody(revision + 1, scenario.current.candidateText, true, 'imported') }
    },
    originalUrl: jobId => `/api/v1/uploads/${jobId}/original`,
    exportUrl: jobId => `/api/v1/uploads/${jobId}/export`,
  }
}

function openDialog(scenario: Scenario, job: UploadJob = jobFixture('manual-review', true)) {
  const focus = { current: null as HTMLElement | null }
  const onClose = vi.fn()
  const onChanged = vi.fn()
  render(<ReviewDialog capability={stubCapability(scenario)} caseId={CASE} job={job} returnFocus={focus} onClose={onClose} onChanged={onChanged} />)
  return { onClose, onChanged }
}

async function editor(): Promise<HTMLElement> {
  return screen.findByLabelText('Kandidát FHIR ve formátu JSON')
}

describe('upload review dialog', () => {
  it('opens from an explicit card button as an accessible dialog with read-only source and model', async () => {
    const scenario: Scenario = { current: reviewBody(0, CANDIDATE, false, 'draft'), enabled: false, reason: 'invalid_candidate', modelText: 'syrový výstup', draftCalls: [], approveCalls: [] }
    const capability = stubCapability(scenario)
    render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    await screen.findByText('zprava.pdf')
    fireEvent.click(screen.getByRole('button', { name: 'Zkontrolovat / upravit' }))
    const dialog = await screen.findByRole('dialog', { name: 'Kontrola a úprava převodu' })
    expect(within(dialog).getByRole('heading', { name: 'Kontrola a úprava převodu' })).toHaveFocus()
    expect(within(dialog).getByRole('link', { name: /Stáhnout originál/ })).toHaveAttribute('download')
    expect(within(dialog).getByText('syrový výstup')).toBeInTheDocument()
    expect(within(dialog).getAllByRole('textbox')).toHaveLength(1)
  })

  it('lets an invalid draft be saved while approval stays blocked with a reason', async () => {
    const scenario: Scenario = { current: reviewBody(0, CANDIDATE, false, 'draft'), enabled: false, reason: 'invalid_candidate', modelText: null, draftCalls: [], approveCalls: [] }
    openDialog(scenario)
    const box = await editor()
    fireEvent.change(box, { target: { value: `${CANDIDATE} ` } })
    const save = screen.getByRole('button', { name: 'Uložit k další kontrole' })
    expect(save).toBeEnabled()
    fireEvent.click(save)
    await waitFor(() => expect(scenario.draftCalls).toHaveLength(1))
    const approve = screen.getByRole('button', { name: 'Schválit a importovat' })
    expect(approve).toBeDisabled()
    expect(screen.getByText(/Uložená verze není platná/)).toBeInTheDocument()
    expect(scenario.approveCalls).toHaveLength(0)
  })

  it('requires explicit patient confirmation for a valid saved draft and shows a receipt when imported', async () => {
    const scenario: Scenario = {
      current: reviewBody(2, CANDIDATE, true, 'draft'), enabled: true, reason: null, modelText: null, draftCalls: [], approveCalls: [],
      approveImpl: revision => {
        scenario.current = reviewBody(revision + 1, CANDIDATE, true, 'imported')
        return { ok: true, value: scenario.current }
      },
    }
    const { onChanged } = openDialog(scenario)
    const user = userEvent.setup()
    await editor()
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull())
    const approve = screen.getByRole('button', { name: 'Schválit a importovat' })
    expect(approve).toBeDisabled()
    expect(screen.getByText(/výslovné potvrzení/)).toBeInTheDocument()
    const confirm = screen.getByRole('checkbox', { name: /Potvrzuji, že záznam patří případu/ })
    await user.click(confirm)
    await waitFor(() => expect(confirm).toBeChecked())
    expect(screen.getByRole('button', { name: 'Schválit a importovat' })).toBeEnabled()
    await user.click(screen.getByRole('button', { name: 'Schválit a importovat' }))
    await waitFor(() => expect(scenario.approveCalls).toEqual([{ revision: 2, patientConfirmed: true }]))
    await waitFor(() => expect(screen.getByText(/Importováno do záznamu případu/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Schválit a importovat' })).toBeDisabled()
    expect(screen.getByRole('link', { name: /Stáhnout balíček/ })).toBeInTheDocument()
  })

  it('marks edited text as unverified and clears the confirmation', async () => {
    const scenario: Scenario = { current: reviewBody(2, CANDIDATE, true, 'draft'), enabled: true, reason: null, modelText: null, draftCalls: [], approveCalls: [] }
    const { onChanged } = openDialog(scenario)
    const user = userEvent.setup()
    const box = await editor()
    await waitFor(() => expect(onChanged).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull())
    const confirm = screen.getByRole('checkbox', { name: /Potvrzuji, že záznam patří případu/ })
    await user.click(confirm)
    await waitFor(() => expect(confirm).toBeChecked())
    fireEvent.change(box, { target: { value: `${CANDIDATE} ` } })
    expect(screen.getByText('Změny nejsou uložené ani ověřené. Nejprve je uložte.')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /Potvrzuji, že záznam patří případu/ })).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Schválit a importovat' })).toBeDisabled()
  })

  it('keeps unsaved text on a version conflict and reloads only through an explicit warned action', async () => {
    const edited = `${CANDIDATE} `
    const scenario: Scenario = {
      current: reviewBody(0, CANDIDATE, true, 'draft'), enabled: true, reason: null, modelText: null, draftCalls: [], approveCalls: [],
      draftImpl: () => ({ ok: false, error: { code: 'conflict', message: 'Server má novější verzi.', currentRevision: 3 } }),
    }
    openDialog(scenario)
    const box = await editor()
    fireEvent.change(box, { target: { value: edited } })
    fireEvent.click(screen.getByRole('button', { name: 'Uložit k další kontrole' }))
    await waitFor(() => expect(screen.getByText('Server má novější verzi. Vaše rozepsané změny zůstávají, načtěte znovu a pak uložte.')).toBeInTheDocument())
    expect(screen.getByLabelText('Kandidát FHIR ve formátu JSON')).toHaveValue(edited)
    scenario.current = reviewBody(3, 'nova', true, 'draft')
    fireEvent.click(screen.getByRole('button', { name: /Načíst znovu ze serveru \(zahodí rozepsané změny\)/ }))
    await waitFor(() => expect(screen.getByLabelText('Kandidát FHIR ve formátu JSON')).toHaveValue('nova'))
  })

  it('locks an uncertain import with honest wording and no approval', async () => {
    const scenario: Scenario = { current: reviewBody(4, CANDIDATE, false, 'import-uncertain'), enabled: false, reason: 'import_locked', modelText: null, draftCalls: [], approveCalls: [] }
    openDialog(scenario)
    await waitFor(() => expect(screen.getByText(/Výsledek importu nelze potvrdit\. Neopakujte import/)).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Schválit a importovat' })).toBeDisabled()
    expect(screen.getByLabelText('Kandidát FHIR ve formátu JSON')).toHaveAttribute('readonly')
  })

  it('tells the truth when the server has no review route', async () => {
    const capability = stubCapability({ current: reviewBody(0, CANDIDATE, false, 'draft'), enabled: false, reason: null, modelText: null, draftCalls: [], approveCalls: [] })
    const failing: UploadCapability = {
      ...capability,
      fetchReview: async () => ({ ok: false, error: { code: 'unavailable', message: 'Ruční kontrola není na tomto serveru k dispozici.', currentRevision: null } }),
    }
    render(<ReviewDialog capability={failing} caseId={CASE} job={jobFixture('manual-review', true)} returnFocus={{ current: null }} onClose={vi.fn()} onChanged={vi.fn()} />)
    await waitFor(() => expect(screen.getByText(/není na tomto serveru k dispozici/)).toBeInTheDocument())
  })

  it('unmounts the dialog immediately when the selected case changes', async () => {
    const scenario: Scenario = { current: reviewBody(0, CANDIDATE, false, 'draft'), enabled: false, reason: 'invalid_candidate', modelText: null, draftCalls: [], approveCalls: [] }
    const capability = stubCapability(scenario)
    const view = render(<UploadPanel capability={capability} caseId={CASE} mockMode={false} />)
    await screen.findByText('zprava.pdf')
    fireEvent.click(screen.getByRole('button', { name: 'Zkontrolovat / upravit' }))
    await screen.findByRole('dialog', { name: 'Kontrola a úprava převodu' })
    view.rerender(<UploadPanel capability={capability} caseId="synthetic-9" mockMode={false} />)
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Kontrola a úprava převodu' })).toBeNull())
    expect(screen.queryByRole('button', { name: 'Zkontrolovat / upravit' })).toBeNull()
  })

  it('asks inline before discarding unsaved changes', async () => {
    const scenario: Scenario = { current: reviewBody(0, CANDIDATE, true, 'draft'), enabled: true, reason: null, modelText: null, draftCalls: [], approveCalls: [] }
    const { onClose } = openDialog(scenario)
    const box = await editor()
    fireEvent.change(box, { target: { value: `${CANDIDATE} ` } })
    fireEvent.click(screen.getByRole('button', { name: 'Zavřít' }))
    expect(screen.getByText(/Zahodit rozepsané změny a zavřít\?/)).toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Pokračovat v úpravách' }))
    expect(screen.queryByText(/Zahodit rozepsané změny a zavřít\?/)).toBeNull()
    expect(onClose).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Zavřít' }))
    fireEvent.click(screen.getByRole('button', { name: 'Zahodit a zavřít' }))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('reports the locally saved revision back to the card', async () => {
    const scenario: Scenario = { current: reviewBody(0, CANDIDATE, false, 'draft'), enabled: false, reason: 'invalid_candidate', modelText: null, draftCalls: [], approveCalls: [] }
    const changed: UploadReviewSummary[] = []
    const focus = { current: null as HTMLElement | null }
    render(<ReviewDialog capability={stubCapability(scenario)} caseId={CASE} job={jobFixture('manual-review', true)} returnFocus={focus} onClose={vi.fn()} onChanged={summary => { changed.push(summary) }} />)
    await editor()
    await waitFor(() => expect(changed.length).toBeGreaterThan(0))
    expect(changed[changed.length - 1]).toMatchObject({ revision: 0, valid: false })
  })

  it('explains image history honestly without claiming an older record', async () => {
    const base = reviewBody(0, CANDIDATE, false, 'draft')
    const scenario: Scenario = { current: { ...base, modelDraftAvailable: false, modelDraftReason: 'model-not-invoked:image_no_ocr' }, enabled: false, reason: 'invalid_candidate', modelText: null, draftCalls: [], approveCalls: [] }
    openDialog(scenario)
    await editor()
    expect(screen.getAllByText(/Model soubor nečetl/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/nahrajte znovu/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/Starší záznam/)).toBeNull()
  })

  it('keeps the genuine legacy notice for old records', async () => {
    const base = reviewBody(0, CANDIDATE, false, 'draft')
    const scenario: Scenario = { current: { ...base, modelDraftAvailable: false, modelDraftReason: 'legacy-draft-missing' }, enabled: false, reason: 'invalid_candidate', modelText: null, draftCalls: [], approveCalls: [] }
    openDialog(scenario)
    await editor()
    expect(screen.getAllByText(/Starší záznam bez uloženého výstupu modelu/).length).toBeGreaterThan(0)
  })

  it('shows raw transcription with an unverified banner and keeps import blocked', async () => {
    const raw = '{"transcription":{"text":"neověřený přepis"}}'
    const base = reviewBody(0, '', false, 'draft')
    const current: UploadReview = { ...base, sourceMethod: 'opencode-native-files', transcriptionUntrusted: true, validation: { ...base.validation, sourceMethod: 'opencode-native-files', transcriptionUntrusted: true } }
    const scenario: Scenario = { current, enabled: false, reason: 'invalid_candidate', modelText: raw, draftCalls: [], approveCalls: [] }
    openDialog(scenario)
    await editor()
    expect(screen.getByText(/Přepis vytvořil model a nebyl nezávisle ověřen/)).toBeInTheDocument()
    expect(screen.getByText(raw)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Schválit a importovat' })).toBeDisabled()
  })

  it('shows a separate model fetch error and keeps the draft editable', async () => {
    const scenario: Scenario = { current: reviewBody(0, CANDIDATE, false, 'draft'), enabled: false, reason: 'invalid_candidate', modelText: null, draftCalls: [], approveCalls: [] }
    const capability = stubCapability(scenario)
    const failing: UploadCapability = { ...capability, fetchModelText: async () => ({ ok: false, error: { code: 'unavailable', message: 'Služba není dostupná. Zkuste to prosím později.', currentRevision: null } }) }
    render(<ReviewDialog capability={failing} caseId={CASE} job={jobFixture('manual-review', true)} returnFocus={{ current: null }} onClose={vi.fn()} onChanged={vi.fn()} />)
    const box = await editor()
    expect(screen.getByRole('alert')).toHaveTextContent(/nepodařilo načíst/)
    expect(box).toHaveValue(CANDIDATE)
    expect(screen.queryByText(/Výstup modelu není k dispozici/)).toBeNull()
  })
})
