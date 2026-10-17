import type { CaseDetail, Workspace } from '../data/contracts'
import type { DemoActions } from '../hooks/useDemoActions'
import type { ResourceState } from '../hooks/useResource'
import type { Route } from '../lib/routes'

/** What every role view receives from the App composition. */
export interface RoleViewProps {
  readonly workspace: ResourceState<Workspace>
  readonly detail: ResourceState<CaseDetail>
  readonly actions: DemoActions
  readonly route?: Route
  readonly onNavigate?: (route: Route) => void
  /** Matching current resource revision, with no local mutation in flight. */
  readonly detailFresh?: boolean
  readonly authed?: boolean | undefined
}

/** Routing seams handed to the two clinician roles (list ⇄ detail). App stays the only history owner. */
export interface ClinicianNavigation {
  readonly route: Route
  readonly onNavigate: (route: Route) => void
  readonly onReturn: () => void
}
