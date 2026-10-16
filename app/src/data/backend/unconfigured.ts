import { failure } from '../contracts'
import type { CaseDetail, Gateway, Result, Workspace } from '../contracts'

export class UnconfiguredBackendGateway implements Gateway {
  readonly mode = 'backend' as const

  async readWorkspace(signal?: AbortSignal): Promise<Result<Workspace>> {
    return this.unconfigured(signal)
  }

  async readCase(_caseId: string, signal?: AbortSignal): Promise<Result<CaseDetail>> {
    return this.unconfigured(signal)
  }

  private unconfigured(signal?: AbortSignal): Result<never> {
    return signal?.aborted
      ? failure('aborted', 'Požadavek byl zrušen.')
      : failure('backend-unconfigured', 'Backend není připojen. Nejsou načtena žádná data.')
  }
}
