import { useCallback } from 'react'
import type { CaseDetail, Gateway, Workspace } from '../data/contracts'
import { useResource } from './useResource'
import type { ResourceState } from './useResource'

export function useWorkspace(gateway: Gateway | null, version: number): ResourceState<Workspace> {
  const load = useCallback((_key: string, signal: AbortSignal) => {
    if (!gateway) return Promise.reject(new Error('Gateway chybí.'))
    return gateway.readWorkspace(signal)
  }, [gateway])
  return useResource(gateway ? 'workspace' : null, version, load)
}

export function useCaseDetail(gateway: Gateway | null, caseId: string | null, version: number): ResourceState<CaseDetail> {
  const load = useCallback((key: string, signal: AbortSignal) => {
    if (!gateway) return Promise.reject(new Error('Gateway chybí.'))
    return gateway.readCase(key, signal)
  }, [gateway])
  return useResource(gateway ? caseId : null, version, load)
}
