import { failure, success } from '../contracts'
import type { CaseDetail, Gateway, Result, Session, Workspace } from '../contracts'
import { BackendAssistant, UnconfiguredAssistant } from './assistant'
import { caseDTO, sessionDTO, workspaceDTO } from './dto'
import { projectCase, projectWorkspace } from './projection'
import { jsonBody } from './http'

const unavailable = () => failure('unavailable', 'Backend není dostupný nebo neposkytl platná úplná data.')
const aborted = () => failure('aborted', 'Požadavek byl zrušen.')
export function validApiBase(value: string | undefined): boolean { return value === '/api/v1' }
export class BackendGateway implements Gateway {
  readonly mode = 'backend' as const
  constructor(private readonly ready = true, private readonly fetcher: typeof fetch = (input, init) => globalThis.fetch(input, init)) {}

  private async read<T>(path: string, decode: (value: unknown) => T, signal?: AbortSignal): Promise<Result<T>> {
    if (signal?.aborted) return aborted()
    if (!this.ready) return unavailable()
    try {
      const response = await this.fetcher(`/api/v1/${path}`, { method: 'GET', credentials: 'same-origin', cache: 'no-store', redirect: 'error',
        headers: { Accept: 'application/json' }, ...(signal ? { signal } : {}) })
      if (signal?.aborted) return aborted()
      if (response.status === 404) return failure('not-found', 'Případ nebyl nalezen.')
      // Workspace 503 deliberately uses the same coverage envelope. Never make its [] a success.
      if (!response.ok && !(path === 'workspace' && response.status === 503)) return unavailable()
      if (!response.headers.get('content-type')?.includes('application/json')) return unavailable()
      const value = decode(await jsonBody(response))
      if (signal?.aborted) return aborted()
      if (response.ok) return success(value)
      const coverage = workspaceDTO(value).coverage
      return { ok: false, error: { code: 'unavailable', message: 'Backend není dostupný nebo neposkytl platná úplná data.', coverage } }
    } catch { return signal?.aborted ? aborted() : unavailable() }
  }
  readSession(signal?: AbortSignal) { return this.read('session', sessionDTO, signal) }
  readWorkspace(signal?: AbortSignal): Promise<Result<Workspace>> {
    return this.read('workspace', workspaceDTO, signal).then(result => {
      if (!result.ok) return result
      if (result.value.coverage.status !== 'complete') return { ok: false as const, error: { code: 'unavailable' as const, message: 'Backend není dostupný nebo neposkytl platná úplná data.', coverage: result.value.coverage } }
      return success(projectWorkspace(result.value))
    })
  }
  readCase(caseId: string, signal?: AbortSignal): Promise<Result<CaseDetail>> {
    if (signal?.aborted) return Promise.resolve(aborted())
    if (!/^[A-Za-z0-9.-]{1,64}$/.test(caseId)) return Promise.resolve(failure('not-found', 'Případ nebyl nalezen.'))
    return this.read(`cases/${caseId}`, raw => projectCase(caseDTO(raw, caseId)), signal)
  }
}
export async function createBackendSession(signal?: AbortSignal, fetcher: typeof fetch = (input, init) => globalThis.fetch(input, init)): Promise<Session> {
  const gateway = new BackendGateway(true, fetcher)
  const result = await gateway.readSession(signal)
  const connected = result.ok && result.value.health.ipc === 'up' && result.value.health.database === 'up'
  return { mode: 'backend', connection: connected ? 'connected' : 'unavailable',
    gateway: connected ? gateway : new BackendGateway(false, fetcher), assistant: connected && result.ok && result.value.assistant ? new BackendAssistant(fetcher) : new UnconfiguredAssistant() }
}
