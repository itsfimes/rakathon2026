import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NAVIGATION_STATE_KEY, useView } from '../src/hooks/useView'
import { detailSection, roleRoute } from '../src/lib/routes'
import type { ClinicianRole, ClinicianSection, Route } from '../src/lib/routes'

const sectionRoute = (section: ClinicianSection, view: ClinicianRole = 'koordinator', caseId = 'chosen'): Route => ({ view, page: 'detail', caseId, section })
beforeEach(() => window.history.replaceState({ unrelated: { retained: true } }, '', '/?source=mock#koordinator'))
afterEach(() => { cleanup(); vi.restoreAllMocks() })
const settle = async (check: () => void) => waitFor(check, { timeout: 1500 })

describe('proven contiguous clinician section history', () => {
  it.each(['koordinator', 'lekar'] as const)('%s returns across four owned detail entries and restores the origin row/scroll', async view => {
    window.history.replaceState({ unrelated: { retained: true } }, '', `/#${view}`)
    const { result } = renderHook(() => useView())
    const go = vi.spyOn(window.history, 'go')
    act(() => result.current.navigate(sectionRoute('overview', view), { scrollY: 456 }))
    for (const section of ['record', 'care', 'person'] as const) act(() => result.current.navigate(sectionRoute(section, view)))
    expect(window.history.state[NAVIGATION_STATE_KEY]).toMatchObject({ depth: 4, origin: expect.any(String), predecessor: expect.any(String) })
    act(() => { result.current.returnToList(); result.current.returnToList() })
    expect(go).toHaveBeenCalledExactlyOnceWith(-4)
    await settle(() => expect(result.current.route).toEqual({ view, page: 'list' }))
    expect(result.current.restoration).toEqual({ role: view, caseId: 'chosen', scrollY: 456 })
    expect(result.current.focus).toBe('restore-list')
    expect(window.history.state.unrelated).toEqual({ retained: true })
    act(() => window.history.forward())
    await settle(() => expect(result.current.route).toEqual({ view, page: 'detail', caseId: 'chosen' }))
    act(() => window.history.forward())
    await settle(() => expect(result.current.route).toEqual(sectionRoute('record', view)))
  })

  it('ordinary Back/Forward between sections updates identity once; an overview alias is a no-op', async () => {
    const { result } = renderHook(() => useView())
    act(() => result.current.navigate(sectionRoute('overview')))
    act(() => result.current.navigate(sectionRoute('record')))
    act(() => result.current.navigate(sectionRoute('care')))
    const id = result.current.navigationId
    act(() => window.history.back())
    await settle(() => expect(result.current.route).toEqual(sectionRoute('record')))
    expect(result.current.navigationId).toBe(id + 1)
    act(() => window.history.forward())
    await settle(() => expect(result.current.route).toEqual(sectionRoute('care')))
    expect(result.current.navigationId).toBe(id + 2)
    act(() => { window.dispatchEvent(new PopStateEvent('popstate')); window.dispatchEvent(new HashChangeEvent('hashchange')) })
    expect(result.current.navigationId).toBe(id + 2)
    act(() => result.current.navigate(sectionRoute('overview')))
    const length = window.history.length
    act(() => result.current.navigate({ view: 'koordinator', page: 'detail', caseId: 'chosen' }))
    expect(window.history.length).toBe(length)
  })

  it('Back then a new section branch prunes forward proof and returns by the new contiguous depth', async () => {
    const { result } = renderHook(() => useView())
    for (const section of ['overview', 'record', 'care'] as const) act(() => result.current.navigate(sectionRoute(section)))
    act(() => window.history.back())
    await settle(() => expect(result.current.route).toEqual(sectionRoute('record')))
    act(() => result.current.navigate(sectionRoute('person')))
    const go = vi.spyOn(window.history, 'go')
    act(() => result.current.returnToList())
    expect(go).toHaveBeenCalledExactlyOnceWith(-3)
    await settle(() => expect(result.current.route.page).toBe('list'))
    expect(result.current.restoration?.caseId).toBe('chosen')
  })

  it('a discarded forward marker cannot resurrect a stale chain after branching', async () => {
    const { result } = renderHook(() => useView())
    for (const section of ['overview', 'record', 'care'] as const) act(() => result.current.navigate(sectionRoute(section)))
    const discarded: unknown = window.history.state
    act(() => window.history.back())
    await settle(() => expect(result.current.route).toEqual(sectionRoute('record')))
    act(() => result.current.navigate(sectionRoute('person')))
    act(() => {
      window.history.replaceState(discarded, '', '/#koordinator/case/chosen/care')
      window.dispatchEvent(new PopStateEvent('popstate'))
    })
    const go = vi.spyOn(window.history, 'go')
    act(() => result.current.returnToList())
    expect(go).not.toHaveBeenCalled()
    expect(result.current.route.page).toBe('list')
    expect(result.current.restoration).toBeNull()
  })

  it('external hash navigation to the same case breaks proof; later internal sections cannot inherit it', async () => {
    const { result } = renderHook(() => useView())
    act(() => result.current.navigate(sectionRoute('overview')))
    act(() => result.current.navigate(sectionRoute('record')))
    act(() => { window.location.hash = '#koordinator/case/chosen/care' })
    await settle(() => expect(result.current.route).toEqual(sectionRoute('care')))
    act(() => result.current.navigate(sectionRoute('person')))
    const go = vi.spyOn(window.history, 'go')
    act(() => result.current.returnToList())
    expect(go).not.toHaveBeenCalled()
    expect(result.current.route).toEqual(roleRoute('koordinator'))
    expect(result.current.restoration).toBeNull()
  })

  it.each(['role', 'case'] as const)('%s changes cannot traverse an old list chain', kind => {
    const { result } = renderHook(() => useView())
    act(() => result.current.navigate(sectionRoute('overview')))
    if (kind === 'role') act(() => result.current.navigate(roleRoute('pacient')))
    act(() => result.current.navigate(sectionRoute('record', 'koordinator', kind === 'case' ? 'other-case' : 'chosen')))
    const go = vi.spyOn(window.history, 'go')
    act(() => result.current.returnToList())
    expect(go).not.toHaveBeenCalled()
    expect(result.current.route.page).toBe('list')
  })

  it('a direct section and reloaded owned section always replace with a list', () => {
    window.history.replaceState({}, '', '/#lekar/case/direct/person')
    const first = renderHook(() => useView())
    const go = vi.spyOn(window.history, 'go')
    act(() => first.result.current.returnToList())
    expect(first.result.current.route).toEqual(roleRoute('lekar'))
    act(() => first.result.current.navigate(sectionRoute('record', 'lekar')))
    act(() => first.result.current.navigate(sectionRoute('care', 'lekar')))
    first.unmount()
    const reloaded = renderHook(() => useView())
    act(() => reloaded.result.current.returnToList())
    expect(go).not.toHaveBeenCalled()
    expect(reloaded.result.current.route).toEqual(roleRoute('lekar'))
    expect(reloaded.result.current.restoration).toBeNull()
  })

  it('owned same-case section replacement preserves depth, unrelated history state and list restoration', async () => {
    const { result } = renderHook(() => useView())
    act(() => result.current.navigate(sectionRoute('overview'), { scrollY: 90 }))
    act(() => result.current.navigate(sectionRoute('record')))
    const length = window.history.length
    act(() => result.current.navigate(sectionRoute('person'), { replace: true }))
    expect(window.history.length).toBe(length)
    expect(window.history.state.unrelated).toEqual({ retained: true })
    const go = vi.spyOn(window.history, 'go')
    act(() => result.current.returnToList())
    expect(go).toHaveBeenCalledExactlyOnceWith(-2)
    await settle(() => expect(result.current.route.page).toBe('list'))
    expect(result.current.restoration?.scrollY).toBe(90)
  })

  it('reset clears all chain proof, including old entries reached later by browser Back', async () => {
    const { result } = renderHook(() => useView())
    for (const section of ['overview', 'record', 'care'] as const) act(() => result.current.navigate(sectionRoute(section)))
    act(() => result.current.resetNavigation())
    expect(result.current.route.page).toBe('list')
    expect(window.history.state[NAVIGATION_STATE_KEY].origin).toBeUndefined()
    act(() => window.history.back())
    await settle(() => expect(result.current.route.page === 'detail' && detailSection(result.current.route)).toBe('record'))
    const go = vi.spyOn(window.history, 'go')
    act(() => result.current.returnToList())
    expect(go).not.toHaveBeenCalled()
    expect(result.current.restoration).toBeNull()
  })
})
