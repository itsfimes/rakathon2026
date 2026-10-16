import { failure, success } from '../contracts'
import type { CaseDetail, Gateway, Result, Session, Workspace } from '../contracts'
import { UnconfiguredAssistant } from './assistant'
import { caseDTO, sessionDTO, workspaceDTO } from './dto'
import { projectCase, projectWorkspace } from './projection'

const unavailable = () => failure('unavailable', 'Backend není dostupný nebo neposkytl platná úplná data.')
const aborted = () => failure('aborted', 'Požadavek byl zrušen.')
async function jsonBody(response: Response): Promise<unknown> {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('Missing response body')
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    for (;;) {
      const chunk = await reader.read()
      if (chunk.done) break
      size += chunk.value.byteLength
      if (size > 1024 * 1024) { await reader.cancel(); throw new Error('Response limit') }
      chunks.push(chunk.value)
    }
  } finally { reader.releaseLock() }
  const bytes = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
  return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as unknown
}
export function validApiBase(value: string | undefined): boolean { return value === '/api/v1' }
export interface BackendHooks {
  readonly onUnauthorized?: () => void
}
export class BackendGateway implements Gateway {
  readonly mode = 'backend' as const
  constructor(private readonly ready = true, private readonly fetcher: typeof fetch = (input, init) => globalThis.fetch(input, init), private readonly hooks: BackendHooks = {}) {}

  private async read<T>(path: string, decode: (value: unknown) => T, signal?: AbortSignal): Promise<Result<T>> {
    if (signal?.aborted) return aborted()
    if (!this.ready) return unavailable()
    try {
      const response = await this.fetcher(`/api/v1/${path}`, { method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { Accept: 'application/json' }, ...(signal ? { signal } : {}) })
      if (signal?.aborted) return aborted()
      if (response.status === 401) {
        this.hooks.onUnauthorized?.()
        return unavailable()
      }
      if (response.status === 403) return unavailable()
      if (response.status === 404) return failure('not-found', 'Případ nebyl nalezen.')
      // Workspace 503 deliberately uses the same coverage envelope. Never make its [] a success.
      if (!response.ok && !(path === 'workspace' && response.status === 503)) return unavailable()
      if (!response.headers.get('content-type')?.includes('application/json')) return unavailable()
      const value = decode(await jsonBody(response))
      if (signal?.aborted) return aborted()
      return response.ok ? success(value) : unavailable()
    } catch { return signal?.aborted ? aborted() : unavailable() }
  }
  readSession(signal?: AbortSignal) { return this.read('session', sessionDTO, signal) }
  readWorkspace(signal?: AbortSignal): Promise<Result<Workspace>> {
    return this.read('workspace', raw => {
      const dto = workspaceDTO(raw)
      if (dto.coverage.status !== 'complete') throw new Error('Unavailable coverage')
      return projectWorkspace(dto)
    }, signal)
  }
  readCase(caseId: string, signal?: AbortSignal): Promise<Result<CaseDetail>> {
    if (signal?.aborted) return Promise.resolve(aborted())
    if (!/^[A-Za-z0-9.-]{1,64}$/.test(caseId)) return Promise.resolve(failure('not-found', 'Případ nebyl nalezen.'))
    return this.read(`cases/${caseId}`, raw => projectCase(caseDTO(raw, caseId)), signal)
  }
}
export async function createBackendSession(signal?: AbortSignal, fetcher: typeof fetch = (input, init) => globalThis.fetch(input, init), hooks: BackendHooks = {}): Promise<Session> {
  const gateway = new BackendGateway(true, fetcher, hooks)
  const result = await gateway.readSession(signal)
  const connected = result.ok && result.value.health.ipc === 'up' && result.value.health.database === 'up'
  return { mode: 'backend', connection: connected ? 'connected' : 'unavailable',
    gateway: connected ? gateway : new BackendGateway(false, fetcher, hooks), assistant: new UnconfiguredAssistant() }
}
