import { createContext, useContext } from 'react'

export interface DetailScopeValue {
  /** Changes with session, role, case, data revision and demo reset; remounts (closes) every scoped disclosure. */
  readonly key: string
  /** False while the shown case is a retained snapshot (refresh/failed refresh) or a local change is in flight. */
  readonly live: boolean
}

const DetailScope = createContext<DetailScopeValue>({ key: 'none', live: false })
export const DetailScopeProvider = DetailScope.Provider
export const useDetailScope = (): DetailScopeValue => useContext(DetailScope)
