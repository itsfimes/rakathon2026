import { jsonBody } from './http'

export type ReviewState = 'pending' | 'draft' | 'importing' | 'imported' | 'import-failed' | 'import-uncertain'
export type ApprovalReason = 'already_imported' | 'import_locked' | 'invalid_candidate' | 'not_configured' | 'forbidden' | 'unavailable'
export interface ReviewIssue {
  readonly code: string
  readonly path: string
  readonly message: string
}
export type ReviewSourceMethod = 'opencode-native-files'
export interface ReviewValidation {
  readonly valid: boolean
  readonly issues: readonly ReviewIssue[]
  readonly counts: Readonly<Record<string, number>>
  readonly patientRef: string
  readonly sourceUrn: string
  readonly sourceSha256: string
  readonly modelDraftAvailable: boolean
  readonly sourceMethod: ReviewSourceMethod | null
  readonly transcriptionUntrusted: boolean
  readonly updatedAt: string
  readonly reviewedBy: string | null
}
export interface UploadReview {
  readonly jobId: string
  readonly revision: number
  readonly state: ReviewState
  readonly candidateText: string
  readonly validation: ReviewValidation
  readonly counts: Readonly<Record<string, number>>
  readonly patientRef: string
  readonly sourceUrn: string
  readonly sourceSha256: string
  readonly caseId: string
  readonly modelDraftAvailable: boolean
  readonly modelDraftReason: string | null
  readonly sourceMethod: ReviewSourceMethod | null
  readonly transcriptionUntrusted: boolean
  readonly updatedAt: string
  readonly reviewedBy: string | null
  readonly importReceipt: unknown
  readonly approvalId: string | null
}
export interface ReviewEnvelope {
  readonly review: UploadReview
  readonly approvalEnabled: boolean
  readonly approvalReason: ApprovalReason | null
}
export type ReviewFailureCode = 'aborted' | 'unavailable' | 'too-large' | 'busy' | 'forbidden' | 'denied' | 'not-found' | 'invalid' | 'conflict'
export interface ReviewFailure {
  readonly code: ReviewFailureCode
  readonly message: string
  readonly currentRevision: number | null
}
export type ReviewResult<T> = { readonly ok: true; readonly value: T } | { readonly ok: false; readonly error: ReviewFailure }
export interface ReviewHooks {
  readonly onUnauthorized?: () => void
  readonly csrfToken?: () => string | null
}
export type ReviewFetcher = (input: string, init?: RequestInit) => Promise<Response>

const JOB_RE = /^[0-9a-fA-F]{32}$/
const STATES: readonly string[] = ['pending', 'draft', 'importing', 'imported', 'import-failed', 'import-uncertain']
const REASONS: readonly string[] = ['already_imported', 'import_locked', 'invalid_candidate', 'not_configured', 'forbidden', 'unavailable']
const MAX_CANDIDATE_BYTES = 262144

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : null
}
function text(value: unknown, limit: number): string | null {
  if (typeof value !== 'string') return null
  return value.length <= limit ? value : null
}
function revisionOf(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : null
}
function fail(code: ReviewFailureCode, message: string, currentRevision: number | null = null): ReviewResult<never> {
  return { ok: false, error: { code, message, currentRevision } }
}
function aborted(): ReviewResult<never> {
  return fail('aborted', 'Požadavek byl zrušen.')
}
function parseCounts(value: unknown): Readonly<Record<string, number>> | null {
  const source = record(value)
  if (!source) return null
  const out: Record<string, number> = {}
  for (const [key, entry] of Object.entries(source)) {
    if (typeof entry !== 'number' || !Number.isFinite(entry) || key.length === 0 || key.length > 64) return null
    out[key] = entry
  }
  return out
}
function parseIssues(value: unknown): readonly ReviewIssue[] | null {
  if (!Array.isArray(value)) return null
  const out: ReviewIssue[] = []
  for (const entry of value.slice(0, 100)) {
    const source = record(entry)
    if (!source) return null
    const code = text(source['code'], 64)
    const message = text(source['message'], 500)
    if (!code || !message) return null
    const path = text(source['path'], 256) ?? ''
    out.push({ code, path, message })
  }
  return out
}
function parseSourceMethod(value: unknown): ReviewSourceMethod | null {
  return value === 'opencode-native-files' ? 'opencode-native-files' : null
}
function parseUntrusted(value: unknown, method: ReviewSourceMethod | null): boolean {
  return value === true && method !== null
}
function parseValidation(value: unknown): ReviewValidation | null {
  const source = record(value)
  if (!source || typeof source['valid'] !== 'boolean') return null
  const issues = parseIssues(source['issues'])
  const counts = parseCounts(source['counts'])
  const patientRef = text(source['patientRef'], 128)
  const sourceUrn = text(source['sourceUrn'], 255)
  const sourceSha256 = text(source['sourceSha256'], 128)
  const updatedAt = text(source['updatedAt'], 64)
  if (!issues || !counts || !patientRef || sourceUrn === null || sourceSha256 === null || updatedAt === null) return null
  if (typeof source['modelDraftAvailable'] !== 'boolean') return null
  const reviewedBy = source['reviewedBy']
  if (reviewedBy !== null && typeof reviewedBy !== 'string') return null
  const method = parseSourceMethod(source['sourceMethod'] ?? null)
  return { valid: source['valid'], issues, counts, patientRef, sourceUrn, sourceSha256, modelDraftAvailable: source['modelDraftAvailable'], sourceMethod: method, transcriptionUntrusted: parseUntrusted(source['transcriptionUntrusted'] ?? false, method), updatedAt, reviewedBy }
}
function parseReview(value: unknown): UploadReview | null {
  const source = record(value)
  if (!source) return null
  const jobId = text(source['jobId'], 64)
  const revision = revisionOf(source['revision'])
  const state = text(source['state'], 32)
  const candidateText = typeof source['candidateText'] === 'string' ? source['candidateText'] : null
  const validation = parseValidation(source['validation'])
  const counts = parseCounts(source['counts'])
  const patientRef = text(source['patientRef'], 128)
  const sourceUrn = text(source['sourceUrn'], 255)
  const sourceSha256 = text(source['sourceSha256'], 128)
  const caseId = text(source['caseId'], 64)
  const updatedAt = text(source['updatedAt'], 64)
  if (!jobId || !JOB_RE.test(jobId) || revision === null || !state || !(STATES as readonly string[]).includes(state)) return null
  if (candidateText === null || !validation || !counts || !patientRef || sourceUrn === null || sourceSha256 === null || !caseId || updatedAt === null) return null
  if (typeof source['modelDraftAvailable'] !== 'boolean') return null
  const reason = source['modelDraftReason']
  const reviewedBy = source['reviewedBy']
  const approvalId = source['approvalId']
  if (reason !== null && typeof reason !== 'string') return null
  if (reviewedBy !== null && typeof reviewedBy !== 'string') return null
  if (approvalId !== null && typeof approvalId !== 'string') return null
  const method = parseSourceMethod(source['sourceMethod'] ?? null)
  return { jobId: jobId.toLowerCase(), revision, state: state as ReviewState, candidateText, validation, counts, patientRef, sourceUrn, sourceSha256, caseId, modelDraftAvailable: source['modelDraftAvailable'], modelDraftReason: reason, sourceMethod: method, transcriptionUntrusted: parseUntrusted(source['transcriptionUntrusted'] ?? false, method), updatedAt, reviewedBy, importReceipt: source['importReceipt'] ?? null, approvalId }
}
function parseEnvelope(value: unknown): ReviewEnvelope | null {
  const source = record(value)
  if (!source || source['version'] !== 1) return null
  const review = parseReview(source['review'])
  if (!review || typeof source['approvalEnabled'] !== 'boolean') return null
  const reason = source['approvalReason']
  if (reason !== null && (typeof reason !== 'string' || !(REASONS as readonly string[]).includes(reason))) return null
  return { review, approvalEnabled: source['approvalEnabled'], approvalReason: reason as ApprovalReason | null }
}
function parseSavedReview(value: unknown): UploadReview | null {
  const source = record(value)
  if (!source || source['version'] !== 1) return null
  return parseReview(source['review'])
}
function parseModelEnvelope(value: unknown): string | null | undefined {
  const source = record(value)
  if (!source || source['version'] !== 1) return undefined
  const raw = source['modelOutputText']
  if (raw !== null && typeof raw !== 'string') return undefined
  return raw
}
function serverFailure(code: string, currentRevision: number | null): ReviewResult<never> {
  if (code === 'conflict') return fail('conflict', 'Server má novější verzi kontroly.', currentRevision)
  if (code === 'not_found') return fail('not-found', 'Záznam nebyl nalezen.')
  if (code === 'forbidden') return fail('forbidden', 'Váš účet nemůže schvalovat změny.')
  if (code === 'invalid_schema') return fail('invalid', 'Požadavek nemá očekávaný tvar.')
  if (code === 'invalid_candidate') return fail('invalid', 'Kandidát není platný. Opravte ho a uložte znovu.')
  if (code === 'too_large' || code === 'oversize') return fail('too-large', 'Kandidát je příliš velký. Zkraťte ho a zkuste to znovu.')
  if (code === 'busy' || code === 'import_busy') return fail('busy', 'Import právě běží. Zkuste to prosím později.')
  if (code === 'not_configured') return fail('unavailable', 'Import není na serveru nastavený.')
  if (code === 'unavailable' || code === 'store_unavailable') return fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
  return fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
}
async function readError(response: Response): Promise<{ code: string; currentRevision: number | null } | null> {
  if (!response.headers.get('content-type')?.includes('application/json')) return null
  try {
    const source = record(await jsonBody(response))
    const error = source ? record(source['error']) : null
    const code = error ? text(error['code'], 64) : null
    if (!code) return null
    return { code, currentRevision: revisionOf(error?.['currentRevision']) }
  } catch {
    return null
  }
}
function bareFailure(response: Response, isGet: boolean): ReviewResult<never> {
  if (response.status === 409) return fail('conflict', 'Server má novější verzi kontroly.')
  if (response.status === 429) return fail('busy', 'Import právě běží. Zkuste to prosím později.')
  if (response.status === 413) return fail('too-large', 'Kandidát je příliš velký. Zkraťte ho a zkuste to znovu.')
  if (response.status === 403) return fail('forbidden', 'Váš účet nemůže schvalovat změny.')
  if (response.status === 404 && !isGet) return fail('not-found', 'Záznam nebyl nalezen.')
  if (response.status === 404) return fail('unavailable', 'Ruční kontrola není na tomto serveru k dispozici.')
  if (response.status === 400 || response.status === 405 || response.status === 422) return fail('invalid', 'Požadavek nemá očekávaný tvar.')
  if (response.status === 503) return fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
  return fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
}
async function failed(response: Response, isGet: boolean): Promise<ReviewResult<never>> {
  const parsed = await readError(response)
  return parsed ? serverFailure(parsed.code, parsed.currentRevision) : bareFailure(response, isGet)
}
async function send(path: string, init: RequestInit, fetcher: ReviewFetcher, signal?: AbortSignal): Promise<Response> {
  return fetcher(path, { credentials: 'same-origin', cache: 'no-store', redirect: 'error', ...init, ...(signal ? { signal } : {}) })
}
function relace(): ReviewResult<never> {
  return fail('unavailable', 'Relace vypršela. Přihlaste se prosím znovu.')
}

export async function fetchReviewRequest(fetcher: ReviewFetcher, hooks: ReviewHooks, jobId: string, signal?: AbortSignal): Promise<ReviewResult<ReviewEnvelope>> {
  if (signal?.aborted) return aborted()
  try {
    const response = await send(`/api/v1/uploads/${jobId}/review`, { method: 'GET', headers: { Accept: 'application/json' } }, fetcher, signal)
    if (signal?.aborted) return aborted()
    if (response.status === 401) {
      hooks.onUnauthorized?.()
      return relace()
    }
    if (!response.ok) return failed(response, true)
    if (!response.headers.get('content-type')?.includes('application/json')) return fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
    const parsed = parseEnvelope(await jsonBody(response))
    if (signal?.aborted) return aborted()
    return parsed ? { ok: true, value: parsed } : fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
  } catch {
    return signal?.aborted ? aborted() : fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
  }
}

export async function fetchModelTextRequest(fetcher: ReviewFetcher, hooks: ReviewHooks, jobId: string, signal?: AbortSignal): Promise<ReviewResult<string | null>> {
  if (signal?.aborted) return aborted()
  try {
    const response = await send(`/api/v1/uploads/${jobId}/review/model`, { method: 'GET', headers: { Accept: 'application/json' } }, fetcher, signal)
    if (signal?.aborted) return aborted()
    if (response.status === 401) {
      hooks.onUnauthorized?.()
      return relace()
    }
    if (!response.ok) return failed(response, true)
    if (!response.headers.get('content-type')?.includes('application/json')) return fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
    const parsed = parseModelEnvelope(await jsonBody(response))
    if (signal?.aborted) return aborted()
    return parsed === undefined ? fail('invalid', 'Odpověď serveru nemá očekávaný tvar.') : { ok: true, value: parsed }
  } catch {
    return signal?.aborted ? aborted() : fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
  }
}

export async function postDraftRequest(fetcher: ReviewFetcher, hooks: ReviewHooks, jobId: string, revision: number, candidateText: string, signal?: AbortSignal): Promise<ReviewResult<UploadReview>> {
  if (signal?.aborted) return aborted()
  if (!Number.isInteger(revision) || revision < 0) return fail('invalid', 'Požadavek nemá očekávaný tvar.')
  if (new TextEncoder().encode(candidateText).length > MAX_CANDIDATE_BYTES) return fail('too-large', 'Kandidát je větší než 256 KiB. Zkraťte ho a zkuste to znovu.')
  const token = hooks.csrfToken?.() ?? null
  if (hooks.csrfToken && !token) return relace()
  try {
    const response = await send(`/api/v1/uploads/${jobId}/review/draft`,
      { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...(token ? { 'X-CSRF-Token': token } : {}) }, body: JSON.stringify({ revision, candidateText }) },
      fetcher, signal)
    if (signal?.aborted) return aborted()
    if (response.status === 401) {
      hooks.onUnauthorized?.()
      return relace()
    }
    if (!response.ok) return failed(response, false)
    if (!response.headers.get('content-type')?.includes('application/json')) return fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
    const parsed = parseSavedReview(await jsonBody(response))
    if (signal?.aborted) return aborted()
    return parsed ? { ok: true, value: parsed } : fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
  } catch {
    return signal?.aborted ? aborted() : fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
  }
}

export async function postApproveRequest(fetcher: ReviewFetcher, hooks: ReviewHooks, jobId: string, revision: number, signal?: AbortSignal): Promise<ReviewResult<UploadReview>> {
  if (signal?.aborted) return aborted()
  if (!Number.isInteger(revision) || revision < 0) return fail('invalid', 'Požadavek nemá očekávaný tvar.')
  const token = hooks.csrfToken?.() ?? null
  if (hooks.csrfToken && !token) return relace()
  try {
    const response = await send(`/api/v1/uploads/${jobId}/review/approve`,
      { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...(token ? { 'X-CSRF-Token': token } : {}) }, body: JSON.stringify({ revision, patientConfirmed: true }) },
      fetcher, signal)
    if (signal?.aborted) return aborted()
    if (response.status === 401) {
      hooks.onUnauthorized?.()
      return relace()
    }
    if (!response.ok) return failed(response, false)
    if (!response.headers.get('content-type')?.includes('application/json')) return fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
    const parsed = parseSavedReview(await jsonBody(response))
    if (signal?.aborted) return aborted()
    return parsed ? { ok: true, value: parsed } : fail('invalid', 'Odpověď serveru nemá očekávaný tvar.')
  } catch {
    return signal?.aborted ? aborted() : fail('unavailable', 'Služba není dostupná. Zkuste to prosím později.')
  }
}
