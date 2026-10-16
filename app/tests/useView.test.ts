import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NAVIGATION_STATE_KEY, useView } from '../src/hooks/useView'
import { roleRoute } from '../src/lib/routes'

beforeEach(() => {
  window.history.replaceState({ unrelated: { keep: true } }, '', '/?source=mock#koordinator')
  Object.defineProperty(window.history, 'scrollRestoration', { configurable: true, writable: true, value: 'auto' })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })

describe('single route/history owner', () => {
  it('navigates every role without randomUUID while preserving unrelated history', () => {
    vi.stubGlobal('crypto', { randomUUID: undefined })
    vi.spyOn(Date, 'now').mockReturnValue(123456789)
    try {
      const { result } = renderHook(() => useView())
      const ids: string[] = []
      for (const view of ['lekar', 'pacient', 'mdt', 'specimen', 'koordinator'] as const) {
        act(() => result.current.navigate(roleRoute(view)))
        expect(result.current.route).toEqual(roleRoute(view))
        expect(window.location.hash).toBe(`#${view}`)
        expect(window.history.state.unrelated).toEqual({ keep: true })
        ids.push(window.history.state[NAVIGATION_STATE_KEY].entryId)
      }
      expect(ids.every(id => typeof id === 'string' && id.length > 0)).toBe(true)
      expect(new Set(ids).size).toBe(ids.length)
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it.each(['koordinator', 'lekar', 'mdt'] as const)('%s fallback IDs support section Back/return/reset with a frozen clock and never trust remounted markers', async view => {
    vi.stubGlobal('crypto', { randomUUID: undefined })
    vi.spyOn(Date, 'now').mockReturnValue(123456789)
    try {
      window.history.replaceState({ unrelated: 'preserved' }, '', `/#${view}`)
      const { result, unmount } = renderHook(() => useView())
      act(() => result.current.navigate({ view, page: 'detail', caseId: 'chosen' }, { scrollY: 412 }))
      const marker = window.history.state[NAVIGATION_STATE_KEY]
      const ids: string[] = [marker.predecessor, marker.entryId]
      const sectionRoute = view === 'mdt'
        ? { view, page: 'detail' as const, caseId: 'chosen', section: 'plan' as const }
        : { view, page: 'detail' as const, caseId: 'chosen', section: 'record' as const }
      act(() => result.current.navigate(sectionRoute))
      expect(result.current.route).toEqual(sectionRoute)
      ids.push(window.history.state[NAVIGATION_STATE_KEY].entryId)
      act(() => window.history.back())
      await waitFor(() => expect(result.current.route).toEqual({ view, page: 'detail', caseId: 'chosen' }))
      act(() => window.history.forward())
      await waitFor(() => expect(result.current.route).toEqual(sectionRoute))
      act(() => result.current.returnToList())
      await waitFor(() => expect(result.current.route).toEqual({ view, page: 'list' }))
      expect(result.current.restoration).toEqual({ role: view, caseId: 'chosen', scrollY: 412 })
      for (let reset = 0; reset < 2; reset++) {
        act(() => result.current.resetNavigation())
        expect(result.current.route).toEqual({ view, page: 'list' })
        expect(result.current.restoration).toBeNull()
        expect(window.history.state[NAVIGATION_STATE_KEY].predecessor).toBeUndefined()
        ids.push(window.history.state[NAVIGATION_STATE_KEY].entryId)
      }
      expect(ids.every(id => typeof id === 'string' && id.length > 0)).toBe(true)
      expect(new Set(ids).size).toBe(ids.length)
      expect(window.history.state.unrelated).toBe('preserved')
      act(() => result.current.navigate({ view, page: 'detail', caseId: 'chosen' }))
      unmount()
      const go = vi.spyOn(window.history, 'go')
      const reloaded = renderHook(() => useView())
      act(() => reloaded.result.current.returnToList())
      expect(go).not.toHaveBeenCalled()
      expect(reloaded.result.current.route).toEqual({ view, page: 'list' })
      expect(reloaded.result.current.restoration).toBeNull()
      expect(window.history.state.unrelated).toBe('preserved')
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it('keeps view compatibility while push/replace synchronously update full route and navigationId', () => {
    const { result } = renderHook(() => useView())
    expect(result.current).toMatchObject({ route: { view: 'koordinator', page: 'list' }, view: 'koordinator', navigationId: 0, navigated: false, focus: 'heading' })
    const length = window.history.length
    act(() => result.current.navigate({ view: 'koordinator', page: 'detail', caseId: 'opaque/id' }, { scrollY: 175 }))
    expect(window.location.hash).toBe('#koordinator/case/opaque%2Fid')
    expect(result.current.route).toEqual({ view: 'koordinator', page: 'detail', caseId: 'opaque/id' })
    expect(result.current.navigationId).toBe(1)
    expect(result.current.view).toBe('koordinator')
    expect(window.history.length).toBe(length + 1)
    expect(window.history.state.unrelated).toEqual({ keep: true })
    expect(window.history.state[NAVIGATION_STATE_KEY].predecessor).toEqual(expect.any(String))
    act(() => result.current.navigate(roleRoute('lekar'), { replace: true }))
    expect(result.current.route).toEqual({ view: 'lekar', page: 'list' })
    expect(window.history.length).toBe(length + 1)
    expect(window.history.state.unrelated).toEqual({ keep: true })
    expect(window.location.search).toBe('?source=mock')
  })

  it.each(['koordinator', 'lekar'] as const)('%s Back restores captured list selection/scroll; Forward restores the exact detail', async view => {
    window.history.replaceState({ unrelated: 'preserved' }, '', `/#${view}`)
    const { result } = renderHook(() => useView())
    act(() => result.current.navigate({ view, page: 'detail', caseId: 'chosen' }, { scrollY: 412 }))
    act(() => { result.current.returnToList(); result.current.returnToList() })
    await waitFor(() => expect(result.current.route).toEqual({ view, page: 'list' }), { timeout: 1500 })
    expect(result.current.restoration).toEqual({ role: view, caseId: 'chosen', scrollY: 412 })
    expect(result.current.focus).toBe('restore-list')
    expect(window.history.state).toMatchObject({ unrelated: 'preserved', [NAVIGATION_STATE_KEY]: { list: { role: view, caseId: 'chosen', scrollY: 412 } } })
    expect(result.current.navigationId).toBe(2)
    act(() => window.history.forward())
    await waitFor(() => expect(result.current.route).toEqual({ view, page: 'detail', caseId: 'chosen' }), { timeout: 1500 })
    expect(result.current.navigationId).toBe(3)
    expect(result.current.restoration).toBeNull()
    expect(result.current.focus).toBe('heading')
  })

  it('browser Back, not only the return action, exposes the list restoration directive', async () => {
    const { result } = renderHook(() => useView())
    act(() => result.current.navigate({ view: 'koordinator', page: 'detail', caseId: 'one' }, { scrollY: 23 }))
    act(() => window.history.back())
    await waitFor(() => expect(result.current.route.page).toBe('list'), { timeout: 1500 })
    expect(result.current.restoration).toEqual({ role: 'koordinator', caseId: 'one', scrollY: 23 })
  })

  it.each(['#lekar/case/direct', '#lekar/case/%'])('direct or malformed detail %s returns via replace, never untrusted Back', hash => {
    window.history.replaceState({ unrelated: true, [NAVIGATION_STATE_KEY]: { entryId: 'persisted', predecessor: 'untrusted' } }, '', `/${hash}`)
    const back = vi.spyOn(window.history, 'back')
    const length = window.history.length
    const { result } = renderHook(() => useView())
    act(() => result.current.returnToList())
    expect(back).not.toHaveBeenCalled()
    expect(result.current.route).toEqual({ view: 'lekar', page: 'list' })
    expect(window.location.hash).toBe('#lekar')
    expect(window.history.length).toBe(length)
    expect(window.history.state.unrelated).toBe(true)
    expect(result.current.restoration).toBeNull()
  })

  it('reload/remount cannot trust a marker created by an earlier hook instance', () => {
    const first = renderHook(() => useView())
    act(() => first.result.current.navigate({ view: 'koordinator', page: 'detail', caseId: 'one' }))
    expect(window.history.state[NAVIGATION_STATE_KEY].predecessor).toBeTruthy()
    first.unmount()
    const back = vi.spyOn(window.history, 'back')
    const reloaded = renderHook(() => useView())
    expect(reloaded.result.current.route).toEqual({ view: 'koordinator', page: 'detail', caseId: 'one' })
    act(() => reloaded.result.current.returnToList())
    expect(back).not.toHaveBeenCalled()
    expect(reloaded.result.current.route.page).toBe('list')
    expect(reloaded.result.current.restoration).toBeNull()
  })

  it('replacing a list with detail has no reliable predecessor and must not Back', () => {
    const back = vi.spyOn(window.history, 'back')
    const { result } = renderHook(() => useView())
    act(() => result.current.navigate({ view: 'koordinator', page: 'detail', caseId: 'one' }, { replace: true }))
    act(() => result.current.returnToList())
    expect(back).not.toHaveBeenCalled()
    expect(result.current.route.page).toBe('list')
    expect(result.current.restoration).toBeNull()
  })

  it('deduplicates popstate/hashchange by complete route, not merely role', () => {
    const { result } = renderHook(() => useView())
    act(() => {
      window.history.replaceState({}, '', '/#koordinator/case/one')
      window.dispatchEvent(new PopStateEvent('popstate'))
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(result.current.navigationId).toBe(1)
    act(() => {
      window.history.replaceState({}, '', '/#koordinator/case/two')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(result.current.route).toEqual({ view: 'koordinator', page: 'detail', caseId: 'two' })
    expect(result.current.navigationId).toBe(2)
    const length = window.history.length
    act(() => result.current.navigate({ view: 'koordinator', page: 'detail', caseId: 'two' }))
    expect(result.current.navigationId).toBe(2)
    expect(window.history.length).toBe(length)
  })

  it('same-role main navigation reaches list, with unknown hash fallback and legacy anchor compatibility', () => {
    const { result } = renderHook(() => useView())
    act(() => result.current.navigate({ view: 'koordinator', page: 'detail', caseId: 'one' }))
    for (const hash of ['#obsah', '#o-ukazce']) {
      act(() => {
        window.history.replaceState({}, '', `/${hash}`)
        window.dispatchEvent(new HashChangeEvent('hashchange'))
      })
      expect(result.current.route).toEqual({ view: 'koordinator', page: 'detail', caseId: 'one' })
    }
    act(() => result.current.navigate(roleRoute('koordinator')))
    expect(result.current.route.page).toBe('list')
    act(() => {
      window.history.replaceState({}, '', '/?role=mdt#unknown')
      window.dispatchEvent(new HashChangeEvent('hashchange'))
    })
    expect(result.current.route).toEqual({ view: 'koordinator', page: 'list' })
    act(() => {
      window.history.replaceState({}, '', '/?role=mdt&mode=mock')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    expect(result.current.route).toEqual({ view: 'mdt', page: 'list' })
  })

  it('reset synchronously replaces detail, clears restoration/predecessors and invalidates same-route state', () => {
    const { result } = renderHook(() => useView())
    act(() => result.current.navigate({ view: 'koordinator', page: 'detail', caseId: 'one' }, { scrollY: 200 }))
    const length = window.history.length
    act(() => result.current.resetNavigation())
    expect(result.current.route).toEqual({ view: 'koordinator', page: 'list' })
    expect(result.current.navigationId).toBe(2)
    expect(result.current.restoration).toBeNull()
    expect(window.history.length).toBe(length)
    expect(window.history.state[NAVIGATION_STATE_KEY].predecessor).toBeUndefined()
    act(() => result.current.resetNavigation())
    expect(result.current.navigationId).toBe(3)
    expect(result.current.focus).toBe('heading')
  })

  it('manual scroll restoration restores the previous browser setting on cleanup; hook never focuses or scrolls DOM', () => {
    const focus = vi.spyOn(HTMLElement.prototype, 'focus')
    const scroll = vi.spyOn(window, 'scrollTo')
    const { unmount } = renderHook(() => useView())
    expect(window.history.scrollRestoration).toBe('manual')
    unmount()
    expect(window.history.scrollRestoration).toBe('auto')
    expect(focus).not.toHaveBeenCalled()
    expect(scroll).not.toHaveBeenCalled()
  })
})
