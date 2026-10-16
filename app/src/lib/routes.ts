import type { ViewId } from './roles'

/** Roles with the four clinician case sections. */
export type ClinicianRole = 'koordinator' | 'lekar'
/** Roles with their own case list and routed case pages. */
export type ListRole = ClinicianRole | 'mdt'
export const CLINICIAN_SECTIONS = ['overview', 'record', 'care', 'person'] as const
export type ClinicianSection = (typeof CLINICIAN_SECTIONS)[number]
/** MDT case pages: the frozen preparation (base) and the separately routed current recorded plan. */
export const MDT_SECTIONS = ['preparation', 'plan'] as const
export type MdtSection = (typeof MDT_SECTIONS)[number]
export type Route =
  | { readonly view: ListRole; readonly page: 'list' }
  | { readonly view: ClinicianRole; readonly page: 'detail'; readonly caseId: string; readonly section?: ClinicianSection }
  | { readonly view: 'mdt'; readonly page: 'detail'; readonly caseId: string; readonly section?: MdtSection }
  | { readonly view: ListRole; readonly page: 'invalid-detail' }
  | { readonly view: Exclude<ViewId, ListRole>; readonly page: 'view' }
  | { readonly view: 'pacient'; readonly page: 'record' }
  | { readonly view: Exclude<ViewId, ListRole>; readonly page: 'invalid-view' }

const roleRoutes: Readonly<Record<ViewId, Route>> = {
  koordinator: { view: 'koordinator', page: 'list' }, lekar: { view: 'lekar', page: 'list' },
  pacient: { view: 'pacient', page: 'view' }, mdt: { view: 'mdt', page: 'list' }, specimen: { view: 'specimen', page: 'view' },
}

export function isListRole(value: string): value is ListRole {
  return value === 'koordinator' || value === 'lekar' || value === 'mdt'
}

export function isMdtSection(value: string): value is MdtSection {
  return (MDT_SECTIONS as readonly string[]).includes(value)
}

export function isClinicianSection(value: string): value is ClinicianSection {
  return (CLINICIAN_SECTIONS as readonly string[]).includes(value)
}

export function detailSection(route: Extract<Route, { page: 'detail' }>): ClinicianSection | MdtSection {
  return route.section ?? (route.view === 'mdt' ? 'preparation' : 'overview')
}

const isBaseSection = (section: string) => section === 'overview' || section === 'preparation'

/** Main-role navigation always reaches the list for clinician roles. */
export function roleRoute(view: ViewId): Route {
  return roleRoutes[view]
}

export function validCaseId(value: string): boolean {
  if (!value.trim() || Array.from(value).some(character => {
    const code = character.codePointAt(0)!
    return code < 32 || (code >= 127 && code <= 159)
  })) return false
  try {
    encodeURIComponent(value)
    return true
  } catch {
    return false
  }
}

/** Decode exactly once. Encoded slashes belong to an opaque ID; literal extra segments do not. */
export function routeFromLocation(location: Pick<Location, 'hash' | 'search'>): Route {
  const hash = location.hash.startsWith('#') ? location.hash.slice(1) : location.hash
  if (!hash) {
    const legacyRole = new URLSearchParams(location.search).get('role') ?? ''
    return Object.hasOwn(roleRoutes, legacyRole) ? roleRoutes[legacyRole as ViewId] : roleRoutes.koordinator
  }
  const [view, segment, encodedId, section, ...extra] = hash.split('/')
  if (isListRole(view!)) {
    if (segment === undefined) return roleRoutes[view]
    const sectionValid = section === undefined || (view === 'mdt' ? isMdtSection(section) : isClinicianSection(section))
    if (segment === 'case' && encodedId !== undefined && extra.length === 0 && sectionValid) {
      try {
        const caseId = decodeURIComponent(encodedId)
        if (validCaseId(caseId)) {
          if (view === 'mdt') return { view, page: 'detail', caseId, ...(section === 'plan' ? { section } : {}) }
          return { view, page: 'detail', caseId, ...(section !== undefined && isClinicianSection(section) && section !== 'overview' ? { section } : {}) }
        }
      } catch {
        // A malformed encoded identifier is an explicit invalid detail, never a default case.
      }
    }
    // Includes the former #mdt/plan: no case is chosen silently.
    return { view, page: 'invalid-detail' }
  }
  if (view === 'pacient' && hash === 'pacient/record') return { view, page: 'record' }
  if ((view === 'pacient' || view === 'specimen') && segment !== undefined) return { view, page: 'invalid-view' }
  return Object.hasOwn(roleRoutes, hash) ? roleRoutes[hash as ViewId] : roleRoutes.koordinator
}

export function routeHref(route: Route): string {
  if (route.page === 'detail') return validCaseId(route.caseId)
    ? `#${route.view}/case/${encodeURIComponent(route.caseId)}${isBaseSection(detailSection(route)) ? '' : `/${detailSection(route)}`}` : `#${route.view}/case/`
  if (route.page === 'record') return `#${route.view}/${route.page}`
  if (route.page === 'invalid-view') return `#${route.view}/invalid`
  return route.page === 'invalid-detail' ? `#${route.view}/case/` : `#${route.view}`
}

export function routeKey(route: Route): string {
  return JSON.stringify(route.page === 'detail' ? [route.view, route.page, route.caseId, detailSection(route)] : [route.view, route.page])
}

export function routesEqual(a: Route, b: Route): boolean {
  return routeKey(a) === routeKey(b)
}

/** Temporary compatibility seam; in-page controls must not overwrite the route hash. */
export function isInPageHash(hash: string): boolean {
  return hash === '#obsah' || hash === '#o-ukazce'
}
