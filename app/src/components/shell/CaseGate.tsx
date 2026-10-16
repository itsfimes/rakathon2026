import type { ReactNode } from 'react'
import type { CaseDetail, Workspace } from '../../data/contracts'
import type { ResourceState } from '../../hooks/useResource'
import { EmptyState, ErrorState, LoadingState } from './DataState'

interface CaseGateProps {
  readonly workspace: ResourceState<Workspace>
  readonly detail: ResourceState<CaseDetail>
  readonly children: (detail: CaseDetail) => ReactNode
}

/** Renders a role's case content only once the selected case snapshot has arrived. */
export function CaseGate({ workspace, detail, children }: CaseGateProps) {
  if (workspace.status === 'loading' || workspace.status === 'idle') return <LoadingState />
  if (workspace.status === 'error') return <ErrorState error={workspace.error} />
  if (detail.status === 'idle') return <EmptyState title="Žádný případ k zobrazení" text="Fronta je prázdná." />
  if (detail.status === 'loading') return <LoadingState />
  if (detail.status === 'error') return <ErrorState error={detail.error} />
  return <>{children(detail.value)}</>
}
