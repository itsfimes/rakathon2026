export type CoverageReason = 'upstream_error' | 'auth_failed' | 'invalid_response' | 'unsafe_paging_link' | 'paging_cycle' | 'duplicate_resource' | 'inconsistent_total' | 'deadline_exceeded' | 'resource_limit' | 'truncated' | 'upstream_unavailable_or_incomplete'
export interface CollectionCoverage {
  readonly status: 'complete' | 'unavailable'
  readonly serverTotal: number | null
  readonly reason: CoverageReason | null
  readonly receivedCount: number | null
  readonly encounteredCount: number | null
  readonly pagesFetched: number | null
}
