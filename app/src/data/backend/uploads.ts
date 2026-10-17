import { jsonBody } from './http'
import type { ReviewEnvelope, ReviewResult, UploadReview } from './uploadReview'
import { fetchModelTextRequest, fetchReviewRequest, postApproveRequest, postDraftRequest } from './uploadReview'

export const MAX_UPLOAD_BYTES = 5242880
export type UploadStatus = 'queued' | 'running' | 'complete' | 'manual-review' | 'failed' | 'cancelled' | 'interrupted'
export interface UploadHooks {
  readonly onUnauthorized?: () => void
  readonly csrfToken?: () => string | null
}
export interface UploadCapabilities {
  readonly enabled: boolean
  readonly maxFileBytes: number
  readonly reason: string | null
  readonly aiAvailable: boolean
}
export interface UploadAttempt {
  readonly label: string
  readonly detail: string | null
  readonly code?: string | null
  readonly status?: string | null
}
export interface UploadReviewSummary {
  readonly state: string
  readonly revision: number
  readonly valid: boolean
  readonly updatedAt: string
  readonly reviewedBy: string | null
}
export interface UploadModel {
  readonly providerId: string
  readonly model: string
  readonly mode: string
}
export interface UploadJob {
  readonly id: string
  readonly caseId: string
  readonly filename: string
  readonly sha256: string
  readonly sourceUrn: string
  readonly detectedType: string
  readonly status: UploadStatus
  readonly createdAt: string
  readonly events: readonly UploadAttempt[]
  readonly eventCount: number
  readonly counts: Readonly<Record<string, number>>
  readonly recipeReuse: boolean
  readonly newFormat: boolean
  readonly plannerMode: string
  readonly model: UploadModel
  readonly review?: UploadReviewSummary | null | undefined
}
export type UploadFailureCode = 'aborted' | 'unavailable' | 'too-large' | 'busy' | 'forbidden' | 'denied' | 'not-found' | 'invalid'
export interface UploadFailure {
  readonly code: UploadFailureCode
  readonly message: string
}
export type UploadResult<T> = { readonly ok: true; readonly value: T } | { readonly ok: false; readonly error: UploadFailure }
export interface UploadCapability {
  capabilities(signal?: AbortSignal): Promise<UploadResult<UploadCapabilities>>
  listCase(caseId: string, signal?: AbortSignal): Promise<UploadResult<readonly UploadJob[]>>
  fetchJob(jobId: string, signal?: AbortSignal): Promise<UploadResult<UploadJob>>
  upload(caseId: string, filename: string, data: ArrayBuffer, signal?: AbortSignal): Promise<UploadResult<UploadJob>>
  fetchReview?(jobId: string, signal?: AbortSignal): Promise<ReviewResult<ReviewEnvelope>>
  fetchModelText?(jobId: string, signal?: AbortSignal): Promise<ReviewResult<string | null>>
  saveDraft?(jobId: string, revision: number, candidateText: string, signal?: AbortSignal): Promise<ReviewResult<UploadReview>>
  approveReview?(jobId: string, revision: number, signal?: AbortSignal): Promise<ReviewResult<UploadReview>>
  originalUrl(jobId: string): string
  exportUrl(jobId: string): string
}

const STATUSES: readonly UploadStatus[] = ['queued', 'running', 'complete', 'manual-review', 'failed', 'cancelled', 'interrupted']
const CASE_RE = /^[A-Za-z0-9.-]{1,64}$/
const JOB_RE = /^[0-9a-fA-F]{32}$/

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null
}
function text(value: unknown, limit = 500): string | null {
  if (typeof value !== 'string') return null
  const trimmed = value.trim()
  return trimmed.length > 0 && trimmed.length <= limit ? trimmed : null
}
function fail(code: UploadFailureCode, message: string): UploadResult<never> {
  return { ok: false, error: { code, message } }
}
function aborted(): UploadResult<never> {
  return fail('aborted', 'Požadavek byl zrušen.')
}
function pickString(source: Record<string, unknown>, keys: readonly string[]): string | null {
  for (const key of keys) {
    const found = text(source[key])
    if (found) return found
  }
  return null
}
const ATTEMPT_LABELS: Readonly<Record<string, string>> = {
  queued: 'Zařazeno do fronty',
  running: 'Zpracovává se',
  new_format_detected: 'Zjištěn nový formát',
  busy: 'Odloženo, fronta je plná',
  deferred: 'Odloženo, fronta je plná',
  complete: 'Převod dokončen',
  failed: 'Pokus se nezdařil',
  'manual-review': 'Předáno ke kontrole člověkem',
  manual_review: 'Předáno ke kontrole člověkem',
  interrupted: 'Přerušeno restartem serveru',
  interrupted_restart: 'Přerušeno restartem serveru',
  cancelled: 'Zrušeno',
}
function parseAttempt(value: unknown, index: number): UploadAttempt {
  const fallback: UploadAttempt = { label: `Krok ${index + 1}`, detail: null, code: null, status: null }
  const source = record(value)
  if (!source) return fallback
  const code = text(source['code'], 64)
  const status = text(source['status'], 32)
  const message = pickString(source, ['message', 'label', 'title', 'text', 'step', 'stage'])
  const mapped = code ? (ATTEMPT_LABELS[code] ?? ATTEMPT_LABELS[code.toLowerCase()] ?? null) : null
  return { label: message ?? mapped ?? code ?? fallback.label, detail: pickString(source, ['detail', 'info', 'error']), code, status }
}
function parseReviewSummary(value: unknown): UploadReviewSummary | null {
  const source = record(value)
  if (!source) return null
  const state = text(source['state'], 32)
  const revision = source['revision']
  const updatedAt = text(source['updatedAt'], 64) ?? ''
  if (!state || typeof revision !== 'number' || !Number.isInteger(revision) || revision < 0) return null
  if (typeof source['valid'] !== 'boolean') return null
  const reviewedBy = source['reviewedBy']
  if (reviewedBy !== null && reviewedBy !== undefined && typeof reviewedBy !== 'string') return null
  return { state, revision, valid: source['valid'], updatedAt, reviewedBy: typeof reviewedBy === 'string' ? reviewedBy : null }
}
function parseCounts(value: unknown): Readonly<Record<string, number>> {
  const source = record(value)
  if (!source) return {}
  const out: Record<string, number> = {}
  for (const [key, entry] of Object.entries(source)) {
    if (typeof entry === 'number' && Number.isFinite(entry) && key.length > 0 && key.length <= 64) out[key] = entry
  }
  return out
}
function parseModel(value: unknown, fallbackMode: string): UploadModel | null {
  const source = record(value)
  if (!source) return null
  const providerId = text(source['providerId'], 120)
  const model = text(source['model'], 120)
  const mode = text(source['mode'], 120) ?? fallbackMode
  return providerId && model ? { providerId, model, mode } : null
}
function parseJob(value: unknown): UploadJob | null {
  const source = record(value)
  if (!source) return null
  const id = text(source['id'], 64)
  const caseId = text(source['caseId'], 64)
  const filename = text(source['filename'], 255)
  const status = text(source['status'], 32)
  if (!id || !JOB_RE.test(id) || !caseId || !filename || !status || !(STATUSES as readonly string[]).includes(status)) return null
  const rawEvents = Array.isArray(source['events']) ? source['events'] : []
  const plannerMode = text(source['plannerMode'], 120) ?? 'none'
  const model = parseModel(source['model'], plannerMode)
  if (!model) return null
  const count = typeof source['eventCount'] === 'number' && Number.isFinite(source['eventCount']) ? source['eventCount'] : rawEvents.length
  return {
    id: id.toLowerCase(),
    caseId,
    filename,
    sha256: text(source['sha256'], 128) ?? '',
    sourceUrn: text(source['sourceUrn'], 255) ?? '',
    detectedType: text(source['detectedType'], 120) ?? '',
    status: status as UploadStatus,
    createdAt: text(source['createdAt'], 64) ?? '',
    events: rawEvents.slice(0, 60).map((entry, index) => parseAttempt(entry, index)),
    eventCount: count,
    counts: parseCounts(source['counts']),
    recipeReuse: source['recipeReuse'] === true,
    newFormat: source['newFormat'] === true,
    plannerMode,
    model,
    review: parseReviewSummary(source['review']) ?? undefined,
  }
}
function parseJobEnvelope(value: unknown): UploadJob | null {
  const source = record(value)
  if (!source || source['version'] !== 1) return null
  return parseJob(source['job'])
}
function parseCapabilities(value: unknown): UploadCapabilities | null {
  const source = record(value)
  if (!source || source['version'] !== 1 || typeof source['enabled'] !== 'boolean') return null
  const maxFileBytes = source['maxFileBytes']
  if (typeof maxFileBytes !== 'number' || !Number.isFinite(maxFileBytes) || maxFileBytes <= 0) return null
  const reason = source['reason']
  if (reason !== null && typeof reason !== 'string') return null
  if (typeof source['aiAvailable'] !== 'boolean') return null
  return { enabled: source['enabled'], maxFileBytes, reason, aiAvailable: source['aiAvailable'] }
}
function parseJobList(value: unknown): readonly UploadJob[] | null {
  const source = record(value)
  if (!source || source['version'] !== 1 || !Array.isArray(source['jobs'])) return null
  const jobs: UploadJob[] = []
  for (const entry of source['jobs'].slice(0, 100)) {
    const job = parseJob(entry)
    if (!job) return null
    jobs.push(job)
  }
  return jobs
}

function reviewAborted(): ReviewResult<never> {
  return { ok: false, error: { code: 'aborted', message: 'Požadavek byl zrušen.', currentRevision: null } }
}
function reviewMissing(): ReviewResult<never> {
  return { ok: false, error: { code: 'not-found', message: 'Záznam nebyl nalezen.', currentRevision: null } }
}

export class BackendUploads implements UploadCapability {
  constructor(private readonly ready = true, private readonly fetcher: typeof fetch = (input, init) => globalThis.fetch(input, init), private readonly hooks: UploadHooks = {}) {}

  originalUrl(jobId: string): string {
    return `/api/v1/uploads/${jobId}/original`
  }

  exportUrl(jobId: string): string {
    return `/api/v1/uploads/${jobId}/export`
  }

  async capabilities(signal?: AbortSignal): Promise<UploadResult<UploadCapabilities>> {
    if (signal?.aborted) return aborted()
    if (!this.ready) return fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
    try {
      const response = await this.fetcher('/api/v1/uploads/capabilities', { method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { Accept: 'application/json' }, ...(signal ? { signal } : {}) })
      if (signal?.aborted) return aborted()
      if (response.status === 401) {
        this.hooks.onUnauthorized?.()
        return fail('unavailable', 'Relace vypršela. Přihlaste se prosím znovu.')
      }
      if (!response.ok) return fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
      if (!response.headers.get('content-type')?.includes('application/json')) return fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
      const parsed = parseCapabilities(await jsonBody(response))
      if (signal?.aborted) return aborted()
      return parsed ? { ok: true, value: parsed } : fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
    } catch {
      return signal?.aborted ? aborted() : fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
    }
  }

  async listCase(caseId: string, signal?: AbortSignal): Promise<UploadResult<readonly UploadJob[]>> {
    if (signal?.aborted) return aborted()
    if (!this.ready || !CASE_RE.test(caseId)) return fail('not-found', 'Případ nebyl nalezen.')
    try {
      const response = await this.fetcher(`/api/v1/cases/${caseId}/uploads`, { method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { Accept: 'application/json' }, ...(signal ? { signal } : {}) })
      if (signal?.aborted) return aborted()
      if (response.status === 401) {
        this.hooks.onUnauthorized?.()
        return fail('unavailable', 'Relace vypršela. Přihlaste se prosím znovu.')
      }
      if (response.status === 404) return fail('not-found', 'Případ nebyl nalezen.')
      if (!response.ok) return fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
      if (!response.headers.get('content-type')?.includes('application/json')) return fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
      const parsed = parseJobList(await jsonBody(response))
      if (signal?.aborted) return aborted()
      return parsed ? { ok: true, value: parsed } : fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
    } catch {
      return signal?.aborted ? aborted() : fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
    }
  }

  async fetchJob(jobId: string, signal?: AbortSignal): Promise<UploadResult<UploadJob>> {
    if (signal?.aborted) return aborted()
    if (!this.ready || !JOB_RE.test(jobId)) return fail('not-found', 'Záznam nebyl nalezen.')
    try {
      const response = await this.fetcher(`/api/v1/uploads/${jobId.toLowerCase()}`, { method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { Accept: 'application/json' }, ...(signal ? { signal } : {}) })
      if (signal?.aborted) return aborted()
      if (response.status === 401) {
        this.hooks.onUnauthorized?.()
        return fail('unavailable', 'Relace vypršela. Přihlaste se prosím znovu.')
      }
      if (response.status === 404) return fail('not-found', 'Záznam nebyl nalezen.')
      if (!response.ok) return fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
      if (!response.headers.get('content-type')?.includes('application/json')) return fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
      const parsed = parseJobEnvelope(await jsonBody(response))
      if (signal?.aborted) return aborted()
      return parsed ? { ok: true, value: parsed } : fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
    } catch {
      return signal?.aborted ? aborted() : fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
    }
  }

  async upload(caseId: string, filename: string, data: ArrayBuffer, signal?: AbortSignal): Promise<UploadResult<UploadJob>> {
    if (signal?.aborted) return aborted()
    const name = filename.trim()
    if (!this.ready || !CASE_RE.test(caseId) || name.length === 0 || name.length > 255 || data.byteLength === 0) {
      return fail('denied', 'Soubor se nepodařilo odeslat. Zkontrolujte název a zkuste to znovu.')
    }
    if (data.byteLength > MAX_UPLOAD_BYTES) return fail('too-large', 'Soubor je větší než 5 MiB. Zmenšete ho a zkuste to znovu.')
    const token = this.hooks.csrfToken?.() ?? null
    if (this.hooks.csrfToken && !token) return fail('unavailable', 'Relace vypršela. Přihlaste se prosím znovu.')
    try {
      const response = await this.fetcher(`/api/v1/cases/${caseId}/uploads`, { method: 'POST', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { Accept: 'application/json', 'Content-Type': 'application/octet-stream', 'X-Upload-Name': encodeURIComponent(name), ...(token ? { 'X-CSRF-Token': token } : {}) },
        body: data, ...(signal ? { signal } : {}) })
      if (signal?.aborted) return aborted()
      if (response.status === 401) {
        this.hooks.onUnauthorized?.()
        return fail('unavailable', 'Relace vypršela. Přihlaste se prosím znovu.')
      }
      if (response.status === 403) return fail('forbidden', 'Váš účet nemůže nahrávat soubory.')
      if (response.status === 404) return fail('not-found', 'Případ nebyl nalezen.')
      if (response.status === 413) return fail('too-large', 'Soubor je větší než 5 MiB. Zmenšete ho a zkuste to znovu.')
      if (response.status === 429) return fail('busy', 'Fronta je plná. Soubor zůstal ve frontě, zkuste ho odeslat znovu ručně.')
      if (response.status === 503) return fail('unavailable', 'Převod je na serveru vypnutý. Soubor se neodeslal.')
      if (response.status !== 202) return fail('denied', 'Server soubor odmítl. Zkontrolujte typ souboru a zkuste to znovu.')
      if (!response.headers.get('content-type')?.includes('application/json')) return fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
      const parsed = parseJobEnvelope(await jsonBody(response))
      if (signal?.aborted) return aborted()
      return parsed ? { ok: true, value: parsed } : fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
    } catch {
      return signal?.aborted ? aborted() : fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
    }
  }

  async fetchReview(jobId: string, signal?: AbortSignal): Promise<ReviewResult<ReviewEnvelope>> {
    if (signal?.aborted) return reviewAborted()
    if (!this.ready || !JOB_RE.test(jobId)) return reviewMissing()
    return fetchReviewRequest(this.fetcher, this.hooks, jobId.toLowerCase(), signal)
  }

  async fetchModelText(jobId: string, signal?: AbortSignal): Promise<ReviewResult<string | null>> {
    if (signal?.aborted) return reviewAborted()
    if (!this.ready || !JOB_RE.test(jobId)) return reviewMissing()
    return fetchModelTextRequest(this.fetcher, this.hooks, jobId.toLowerCase(), signal)
  }

  async saveDraft(jobId: string, revision: number, candidateText: string, signal?: AbortSignal): Promise<ReviewResult<UploadReview>> {
    if (signal?.aborted) return reviewAborted()
    if (!this.ready || !JOB_RE.test(jobId)) return reviewMissing()
    return postDraftRequest(this.fetcher, this.hooks, jobId.toLowerCase(), revision, candidateText, signal)
  }

  async approveReview(jobId: string, revision: number, signal?: AbortSignal): Promise<ReviewResult<UploadReview>> {
    if (signal?.aborted) return reviewAborted()
    if (!this.ready || !JOB_RE.test(jobId)) return reviewMissing()
    return postApproveRequest(this.fetcher, this.hooks, jobId.toLowerCase(), revision, signal)
  }
}
