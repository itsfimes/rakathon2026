import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { BackendUploads } from '../src/data/backend/uploads'
import { useUploadReview } from '../src/hooks/useUploadReview'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const JOB_ID = 'a'.repeat(32)
const CASE = 'synthetic-0'
const CANDIDATE = '{"resourceType":"Bundle","type":"collection","entry":[]}'

function validationBody(valid: boolean) {
  return {
    valid,
    issues: valid ? [] : [{ code: 'invalid_candidate', path: '', message: 'bad' }],
    counts: {},
    patientRef: `Patient/${CASE}`,
    sourceUrn: 'urn:test:1',
    sourceSha256: 'abc',
    modelDraftAvailable: true,
    updatedAt: '2026-10-16T12:00:00Z',
    reviewedBy: null,
  }
}
function reviewBody(revision: number, candidate: string, valid: boolean, state = 'draft', caseId: string = CASE) {
  return {
    jobId: JOB_ID,
    revision,
    state,
    candidateText: candidate,
    validation: validationBody(valid),
    counts: {},
    patientRef: `Patient/${caseId}`,
    sourceUrn: 'urn:test:1',
    sourceSha256: 'abc',
    caseId,
    modelDraftAvailable: true,
    modelDraftReason: null,
    updatedAt: '2026-10-16T12:00:00Z',
    reviewedBy: null,
    importReceipt: null,
    approvalId: null,
  }
}
const envelope = (revision: number, candidate: string, valid: boolean, state: string, enabled: boolean, reason: string | null) => ({
  version: 1,
  review: reviewBody(revision, candidate, valid, state),
  approvalEnabled: enabled,
  approvalReason: reason,
})
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })

interface Route {
  readonly url: string
  readonly init: RequestInit
}
function setup(handler: (route: Route) => Response | Promise<Response>, csrf: string | null = 'csrf-test') {
  const seen: Route[] = []
  const unauthorized = vi.fn()
  const fetcher = vi.fn(async (input: unknown, init?: RequestInit) => {
    const route = { url: String(input), init: (init ?? {}) as RequestInit }
    seen.push(route)
    return handler(route)
  }) as unknown as typeof fetch
  const capability = new BackendUploads(true, fetcher, { csrfToken: () => csrf, onUnauthorized: unauthorized })
  return { seen, unauthorized, capability }
}
function bodies(seen: Route[], suffix: string): unknown[] {
  return seen.filter(route => route.url.endsWith(suffix)).map(route => JSON.parse(String(route.init.body)))
}

describe('upload review client', () => {
  it('loads review and model text with same-origin cookies', async () => {
    const { seen, capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return json({ version: 1, modelOutputText: 'model-text' })
      return json(envelope(0, CANDIDATE, false, 'draft', false, 'invalid_candidate'))
    })
    const { result } = renderHook(() => useUploadReview(capability, CASE, JOB_ID))
    await waitFor(() => expect(result.current.review?.revision).toBe(0))
    expect(result.current.text).toBe(CANDIDATE)
    expect(result.current.modelText).toBe('model-text')
    expect(result.current.approvalEnabled).toBe(false)
    expect(result.current.approvalReason).toBe('invalid_candidate')
    for (const route of seen) expect(route.init.credentials).toBe('same-origin')
  })

  it('saves an invalid draft with exact fields and CSRF, then refreshes through GET', async () => {
    const fixed = `${CANDIDATE} `
    let draftRev = 0
    const { seen, capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return json({ version: 1, modelOutputText: null })
      if (route.url.endsWith('/review/draft')) {
        draftRev = 1
        return json({ version: 1, review: reviewBody(1, fixed, false) })
      }
      return json(envelope(draftRev, draftRev === 0 ? CANDIDATE : fixed, false, 'draft', false, 'invalid_candidate'))
    })
    const { result } = renderHook(() => useUploadReview(capability, CASE, JOB_ID))
    await waitFor(() => expect(result.current.review?.revision).toBe(0))
    act(() => result.current.setText(fixed))
    act(() => result.current.save())
    await waitFor(() => expect(result.current.review?.revision).toBe(1))
    expect(result.current.dirty).toBe(false)
    expect(result.current.saving).toBe(false)
    expect(bodies(seen, '/review/draft')).toEqual([{ revision: 0, candidateText: fixed }])
    const post = seen.find(route => route.url.endsWith('/review/draft'))
    const headers = post?.init.headers as Record<string, string>
    expect(headers['X-CSRF-Token']).toBe('csrf-test')
    expect(headers['Content-Type']).toBe('application/json')
  })

  it('never sends approve for an invalid or edited draft', async () => {
    const { seen, capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return json({ version: 1, modelOutputText: null })
      return json(envelope(0, CANDIDATE, true, 'draft', true, null))
    })
    const { result } = renderHook(() => useUploadReview(capability, CASE, JOB_ID))
    await waitFor(() => expect(result.current.review?.revision).toBe(0))
    act(() => result.current.setConfirmed(true))
    act(() => result.current.setText(`${CANDIDATE} `))
    act(() => result.current.approve())
    await new Promise(resolve => setTimeout(resolve, 30))
    expect(seen.some(route => route.url.endsWith('/review/approve'))).toBe(false)
    expect(result.current.approving).toBe(false)
  })

  it('approves only the saved valid revision with explicit confirmation', async () => {
    let approved = false
    const { seen, capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return json({ version: 1, modelOutputText: null })
      if (route.url.endsWith('/review/approve')) {
        approved = true
        return json({ version: 1, review: reviewBody(2, CANDIDATE, true, 'imported') })
      }
      if (approved) return json(envelope(2, CANDIDATE, true, 'imported', false, 'already_imported'))
      return json(envelope(2, CANDIDATE, true, 'draft', true, null))
    })
    const { result } = renderHook(() => useUploadReview(capability, CASE, JOB_ID))
    await waitFor(() => expect(result.current.review?.revision).toBe(2))
    act(() => result.current.approve())
    await new Promise(resolve => setTimeout(resolve, 30))
    expect(seen.some(route => route.url.endsWith('/review/approve'))).toBe(false)
    act(() => result.current.setConfirmed(true))
    act(() => result.current.approve())
    await waitFor(() => expect(result.current.review?.state).toBe('imported'))
    expect(bodies(seen, '/review/approve')).toEqual([{ revision: 2, patientConfirmed: true }])
    expect(result.current.confirmed).toBe(false)
    expect(result.current.approvalReason).toBe('already_imported')
  })

  it('keeps user text on 409 and resets only through explicit reload', async () => {
    let saved = false
    let reloaded = false
    const edited = `${CANDIDATE} `
    const { capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return json({ version: 1, modelOutputText: null })
      if (route.url.endsWith('/review/draft') && !saved) {
        saved = true
        return json({ version: 1, error: { code: 'conflict', message: 'stale', currentRevision: 3 } }, 409)
      }
      if (route.url.endsWith('/review') && reloaded) return json(envelope(3, 'nova', true, 'draft', true, null))
      return json(envelope(0, CANDIDATE, true, 'draft', true, null))
    })
    const { result } = renderHook(() => useUploadReview(capability, CASE, JOB_ID))
    await waitFor(() => expect(result.current.review?.revision).toBe(0))
    act(() => result.current.setText(edited))
    act(() => result.current.save())
    await waitFor(() => expect(result.current.conflict).toBe(3))
    expect(result.current.text).toBe(edited)
    expect(result.current.error).toMatch(/novější verzi/)
    reloaded = true
    act(() => result.current.reload())
    await waitFor(() => expect(result.current.review?.revision).toBe(3))
    expect(result.current.text).toBe('nova')
    expect(result.current.conflict).toBeNull()
  })

  it('aborts a stale load on case switch and ignores its late response', async () => {
    let releaseA!: (value: Response) => void
    const gated = new Promise<Response>(resolve => {
      releaseA = resolve
    })
    let second = false
    const { seen, capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return json({ version: 1, modelOutputText: null })
      if (!second) {
        second = true
        return gated
      }
      return json({ version: 1, review: reviewBody(5, 'pro-pripad-b', true, 'draft', 'synthetic-9'), approvalEnabled: true, approvalReason: null })
    })
    const { result, rerender } = renderHook(({ caseId }: { caseId: string }) => useUploadReview(capability, caseId, JOB_ID), {
      initialProps: { caseId: CASE },
    })
    await waitFor(() => expect(seen.length).toBeGreaterThan(0))
    rerender({ caseId: 'synthetic-9' })
    await waitFor(() => expect(result.current.review?.caseId).toBe('synthetic-9'))
    releaseA(json(envelope(0, 'stara-pro-pripad-a', true, 'draft', true, null)))
    await new Promise(resolve => setTimeout(resolve, 30))
    expect(result.current.review?.caseId).toBe('synthetic-9')
    expect(result.current.text).toBe('pro-pripad-b')
    expect((seen[0]?.init.signal as AbortSignal | undefined)?.aborted).toBe(true)
  })

  it('reports an old server without review routes as honestly unavailable', async () => {
    const { capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return new Response('missing', { status: 404 })
      return new Response('missing', { status: 404 })
    })
    const { result } = renderHook(() => useUploadReview(capability, CASE, JOB_ID))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.review).toBeNull()
    expect(result.current.error).toMatch(/není na tomto serveru k dispozici/)
  })

  it('ends the session on 401 and clears review state', async () => {
    let expired = false
    const { unauthorized, capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return expired ? json({ error: 'x' }, 401) : json({ version: 1, modelOutputText: null })
      if (expired) return json({ error: 'x' }, 401)
      expired = true
      return json(envelope(0, CANDIDATE, true, 'draft', true, null))
    })
    const { result } = renderHook(() => useUploadReview(capability, CASE, JOB_ID))
    await waitFor(() => expect(result.current.review?.revision).toBe(0))
    act(() => result.current.reload())
    await waitFor(() => expect(unauthorized).toHaveBeenCalled())
    await waitFor(() => expect(result.current.review).toBeNull())
    expect(result.current.text).toBe('')
  })

  it('keeps attempt codes with Czech labels and the optional review badge', async () => {
    const { capability } = setup(route => {
      if (route.url === '/api/v1/uploads/capabilities') {
        return json({ version: 1, enabled: true, maxFileBytes: 5242880, reason: null, aiAvailable: true })
      }
      return json({
        version: 1,
        jobs: [{
          id: JOB_ID,
          caseId: CASE,
          filename: 'zprava.pdf',
          sha256: 'abc',
          sourceUrn: 'urn:test:1',
          detectedType: 'pdf',
          status: 'running',
          createdAt: '2026-10-16T12:00:00Z',
          events: [{ code: 'new_format_detected', status: 'ok' }, { code: 'mystery_xyz', status: 'tried' }],
          eventCount: 2,
          counts: {},
          recipeReuse: false,
          newFormat: false,
          plannerMode: 'none',
          model: { providerId: 'rakathon-azure', model: 'gpt-6-luna-dz-eu', mode: 'none' },
          review: { state: 'draft', revision: 2, valid: false, updatedAt: 't', reviewedBy: null },
        }],
      })
    })
    const listed = await capability.listCase(CASE)
    expect(listed.ok).toBe(true)
    if (!listed.ok) return
    expect(listed.value[0]?.events[0]).toMatchObject({ label: 'Zjištěn nový formát', code: 'new_format_detected', status: 'ok' })
    expect(listed.value[0]?.events[1]).toMatchObject({ label: 'mystery_xyz', code: 'mystery_xyz', status: 'tried' })
    expect(listed.value[0]?.review).toMatchObject({ state: 'draft', revision: 2, valid: false })
  })

  it('refuses draft POST without a CSRF token', async () => {
    const { seen, capability } = setup(() => json({ version: 1, review: reviewBody(1, CANDIDATE, true) }), null)
    const saved = await capability.saveDraft?.(JOB_ID, 0, CANDIDATE)
    expect(saved?.ok).toBe(false)
    if (saved?.ok !== false) return
    expect(saved.error.message).toMatch(/Relace/)
    expect(seen).toHaveLength(0)
  })

  it('surfaces model fetch failure separately without wiping the draft', async () => {
    const { capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return new Response('down', { status: 503 })
      return json(envelope(0, CANDIDATE, false, 'draft', false, 'invalid_candidate'))
    })
    const { result } = renderHook(() => useUploadReview(capability, CASE, JOB_ID))
    await waitFor(() => expect(result.current.review?.revision).toBe(0))
    await waitFor(() => expect(result.current.modelLoading).toBe(false))
    expect(result.current.modelText).toBeNull()
    expect(result.current.modelError).toMatch(/dostupná|později/)
    expect(result.current.text).toBe(CANDIDATE)
    expect(result.current.error).toBeNull()
  })

  it('reports model loading explicitly before the text arrives', async () => {
    let release!: (value: Response) => void
    const gated = new Promise<Response>(resolve => { release = resolve })
    const { capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return gated
      return json(envelope(0, CANDIDATE, false, 'draft', false, 'invalid_candidate'))
    })
    const { result } = renderHook(() => useUploadReview(capability, CASE, JOB_ID))
    await waitFor(() => expect(result.current.review?.revision).toBe(0))
    expect(result.current.modelLoading).toBe(true)
    expect(result.current.modelError).toBeNull()
    release(json({ version: 1, modelOutputText: 'raw' }))
    await waitFor(() => expect(result.current.modelLoading).toBe(false))
    expect(result.current.modelText).toBe('raw')
  })

  it('clears model error, loading and text on case switch', async () => {
    const { capability, seen } = setup(route => {
      if (route.url.endsWith('/review/model')) return new Response('down', { status: 503 })
      return json(envelope(0, CANDIDATE, false, 'draft', false, 'invalid_candidate'))
    })
    const { result, rerender } = renderHook(({ caseId }: { caseId: string }) => useUploadReview(capability, caseId, JOB_ID), { initialProps: { caseId: CASE } })
    await waitFor(() => expect(result.current.modelError).not.toBeNull())
    rerender({ caseId: 'synthetic-9' })
    expect(result.current.modelText).toBeNull()
    expect(result.current.modelError).toBeNull()
    expect(result.current.text).toBe('')
    await waitFor(() => expect(seen.length).toBeGreaterThan(2))
  })

  it('parses new provenance fields and stays compatible with old fixtures', async () => {
    const { capability } = setup(route => {
      if (route.url.endsWith('/review/model')) return json({ version: 1, modelOutputText: null })
      const base = reviewBody(0, '', false)
      const withProvenance = { ...base, sourceMethod: 'opencode-native-files', transcriptionUntrusted: true, validation: { ...base.validation, sourceMethod: 'opencode-native-files', transcriptionUntrusted: true } }
      return json({ version: 1, review: withProvenance, approvalEnabled: false, approvalReason: 'invalid_candidate' })
    })
    const { result } = renderHook(() => useUploadReview(capability, CASE, JOB_ID))
    await waitFor(() => expect(result.current.review?.revision).toBe(0))
    expect(result.current.review?.sourceMethod).toBe('opencode-native-files')
    expect(result.current.review?.transcriptionUntrusted).toBe(true)
    expect(result.current.review?.candidateText).toBe('')
  })
})
