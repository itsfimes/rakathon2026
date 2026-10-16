import { useCallback, useEffect, useRef, useState } from 'react'
import type { ViewId } from '../lib/roles'
import { isInPageHash, roleRoute, routeFromLocation, routeHref, routesEqual } from '../lib/routes'
import type { ListRole, Route } from '../lib/routes'

export const NAVIGATION_STATE_KEY = 'rakathon.navigation.v1'
const historyIdPrefix = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`
let historyIdCounter = 0

/** History bookkeeping only, not security IDs. HTTP LAN pages may lack randomUUID. */
function historyEntryIdValue(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  return `${historyIdPrefix}-${++historyIdCounter}`
}

export interface ListRestoration {
  readonly role: ListRole
  readonly caseId: string
  readonly scrollY: number
}
export interface NavigateOptions {
  readonly replace?: boolean
  /** Override the captured list scroll position; defaults to window.scrollY. */
  readonly scrollY?: number
}
interface NavigationState {
  readonly route: Route
  readonly navigationId: number
  readonly navigated: boolean
  readonly restoration: ListRestoration | null
}
interface KnownEntry {
  readonly route: Route
  readonly restoration?: ListRestoration
  readonly predecessor?: string
  readonly origin?: string
  readonly depth?: number
}
interface HistoryTrail { readonly ids: readonly string[]; readonly index: number; readonly length: number }
export interface ViewState extends NavigationState {
  readonly view: ViewId
  readonly focus: 'heading' | 'restore-list'
  navigate(route: Route, options?: NavigateOptions): void
  returnToList(): void
  resetNavigation(): void
}

function historyEntryId(): string | null {
  const state: unknown = window.history.state
  if (!state || typeof state !== 'object' || !(NAVIGATION_STATE_KEY in state)) return null
  const marker: unknown = state[NAVIGATION_STATE_KEY]
  if (!marker || typeof marker !== 'object' || !('entryId' in marker)) return null
  return typeof marker.entryId === 'string' ? marker.entryId : null
}

function writeEntry(entryId: string, entry: KnownEntry, replace: boolean, href: string) {
  const previous: unknown = window.history.state
  const unrelated = previous && typeof previous === 'object' ? previous : {}
  const state = { ...unrelated, [NAVIGATION_STATE_KEY]: {
    entryId, ...(entry.restoration ? { list: entry.restoration } : {}),
    ...(entry.predecessor ? { predecessor: entry.predecessor } : {}),
    ...(entry.origin ? { origin: entry.origin, depth: entry.depth } : {}),
  } }
  if (replace) window.history.replaceState(state, '', href)
  else window.history.pushState(state, '', href)
}

/** Every intervening entry must be an owned section of this same case and role. */
function listDepth(route: Route, id: string | null, entries: ReadonlyMap<string, KnownEntry>, trail: HistoryTrail): number | null {
  if (route.page !== 'detail' || !id || trail.ids[trail.index] !== id || trail.length !== window.history.length) return null
  const start = entries.get(id)
  if (!start?.origin || !start.depth || !routesEqual(start.route, route)) return null
  let child = start
  for (let remaining = start.depth, index = trail.index; remaining > 0; remaining--, index--) {
    if (child.route.page !== 'detail' || child.route.view !== route.view || child.route.caseId !== route.caseId
      || child.depth !== remaining || child.origin !== start.origin || child.predecessor !== trail.ids[index - 1]) return null
    const parent = child.predecessor ? entries.get(child.predecessor) : undefined
    if (!parent) return null
    if (remaining === 1) return child.predecessor === start.origin && parent.route.page === 'list'
      && parent.route.view === route.view && parent.restoration?.caseId === route.caseId ? start.depth : null
    child = parent
  }
  return null
}

/** One URL/history owner. Runtime-known entries, never persisted markers alone, authorize Back. */
export function useView(): ViewState {
  const [state, setState] = useState<NavigationState>(() => ({
    route: routeFromLocation(window.location), navigationId: 0, navigated: false, restoration: null,
  }))
  const current = useRef(state)
  const known = useRef(new Map<string, KnownEntry>())
  const trail = useRef<HistoryTrail>({ ids: [], index: -1, length: window.history.length })
  const returning = useRef(false)

  const publish = useCallback((route: Route, restoration: ListRestoration | null = null, force = false) => {
    const previous = current.current
    if (!force && routesEqual(previous.route, route)) return
    const next = { route, navigationId: previous.navigationId + 1, navigated: true, restoration }
    current.current = next
    setState(next)
  }, [])

  useEffect(() => {
    const sync = () => {
      // Legacy anchors keep the current route, but an external history entry cannot extend proof.
      if (isInPageHash(window.location.hash)) {
        known.current.clear()
        trail.current = { ids: [], index: -1, length: window.history.length }
        return
      }
      returning.current = false
      const route = routeFromLocation(window.location)
      const id = historyEntryId()
      const entry = id ? known.current.get(id) : undefined
      const index = id ? trail.current.ids.indexOf(id) : -1
      const owned = index >= 0 && entry && routesEqual(entry.route, route) && trail.current.length === window.history.length
      if (owned) trail.current = { ...trail.current, index }
      else {
        known.current.clear()
        trail.current = { ids: [], index: -1, length: window.history.length }
      }
      const restoration = owned && route.page === 'list' ? entry.restoration ?? null : null
      publish(route, restoration)
    }
    const history = window.history
    const previousRestoration = history.scrollRestoration
    const supportsRestoration = 'scrollRestoration' in history
    if (supportsRestoration) history.scrollRestoration = 'manual'
    window.addEventListener('hashchange', sync)
    window.addEventListener('popstate', sync)
    return () => {
      window.removeEventListener('hashchange', sync)
      window.removeEventListener('popstate', sync)
      if (supportsRestoration) history.scrollRestoration = previousRestoration
    }
  }, [publish])

  const navigate = useCallback((requested: Route, options: NavigateOptions = {}) => {
    returning.current = false
    const href = routeHref(requested)
    const route = routeFromLocation({ hash: href, search: '' })
    const from = current.current.route
    if (routesEqual(from, route)) return
    const currentId = historyEntryId()
    const currentEntry = currentId ? known.current.get(currentId) : undefined
    let owned = !!currentId && trail.current.ids[trail.current.index] === currentId && !!currentEntry
      && routesEqual(currentEntry.route, from) && routesEqual(routeFromLocation(window.location), from)
      && trail.current.length === window.history.length
    if (owned) {
      for (const discarded of trail.current.ids.slice(trail.current.index + 1)) known.current.delete(discarded)
      trail.current = { ...trail.current, ids: trail.current.ids.slice(0, trail.current.index + 1) }
    } else {
      known.current.clear()
      trail.current = { ids: [], index: -1, length: window.history.length }
    }
    let chain: Pick<KnownEntry, 'predecessor' | 'origin' | 'depth'> = {}
    if (!options.replace && from.page === 'list' && route.page === 'detail' && from.view === route.view) {
      const origin = owned ? currentId! : historyEntryIdValue()
      const scroll = options.scrollY ?? window.scrollY
      const entry: KnownEntry = { route: from, restoration: { role: from.view, caseId: route.caseId, scrollY: Number.isFinite(scroll) ? Math.max(0, scroll) : 0 } }
      known.current.set(origin, entry)
      writeEntry(origin, entry, true, `${window.location.pathname}${window.location.search}${routeHref(from)}`)
      if (!owned) trail.current = { ids: [origin], index: 0, length: window.history.length }
      owned = true
      chain = { predecessor: origin, origin, depth: 1 }
    } else if (owned && from.page === 'detail' && route.page === 'detail' && from.view === route.view && from.caseId === route.caseId
      && listDepth(from, currentId, known.current, trail.current) !== null) {
      chain = options.replace
        ? { predecessor: currentEntry!.predecessor!, origin: currentEntry!.origin!, depth: currentEntry!.depth! }
        : { predecessor: currentId!, origin: currentEntry!.origin!, depth: currentEntry!.depth! + 1 }
    }
    const id = historyEntryIdValue()
    const entry: KnownEntry = { route, ...chain }
    known.current.set(id, entry)
    writeEntry(id, entry, options.replace ?? false, `${window.location.pathname}${window.location.search}${href}`)
    if (owned && options.replace) {
      if (currentId) known.current.delete(currentId)
      trail.current = { ids: [...trail.current.ids.slice(0, trail.current.index), id], index: trail.current.index, length: window.history.length }
    } else {
      const ids = [...trail.current.ids, id]
      trail.current = { ids, index: ids.length - 1, length: window.history.length }
    }
    publish(route)
  }, [publish])

  const returnToList = useCallback(() => {
    if (returning.current) return
    const route = current.current.route
    if (route.page !== 'detail' && route.page !== 'invalid-detail') return
    const id = historyEntryId()
    const depth = routesEqual(routeFromLocation(window.location), route) ? listDepth(route, id, known.current, trail.current) : null
    if (depth !== null) {
      returning.current = true
      window.history.go(-depth)
    } else {
      navigate(roleRoute(route.view), { replace: true })
    }
  }, [navigate])

  const resetNavigation = useCallback(() => {
    returning.current = false
    known.current.clear()
    const previous = current.current.route
    const route = previous.page === 'detail' || previous.page === 'invalid-detail' || previous.page === 'invalid-view' ? roleRoute(previous.view) : previous
    const id = historyEntryIdValue()
    const entry = { route }
    known.current.set(id, entry)
    writeEntry(id, entry, true, `${window.location.pathname}${window.location.search}${routeHref(route)}`)
    trail.current = { ids: [id], index: 0, length: window.history.length }
    publish(route, null, true)
  }, [publish])

  return { ...state, view: state.route.view, focus: state.restoration ? 'restore-list' : 'heading', navigate, returnToList, resetNavigation }
}
