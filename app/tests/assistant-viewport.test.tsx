import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { App } from '../src/App'
import type { BootstrapResult, Session } from '../src/data/contracts'
import { createMockSession } from '../src/data/mock/provider'
import { lockBodyScroll } from '../src/features/assistant/bodyLock'

const boot = (value: Session): Promise<BootstrapResult> => Promise.resolve({ status: 'session', session: value })

function phone(matches: boolean) {
  const listeners = new Set<() => void>()
  const query = {
    matches, media: '(max-width: 760px)',
    addEventListener: vi.fn((_type: string, listener: () => void) => { listeners.add(listener) }),
    removeEventListener: vi.fn((_type: string, listener: () => void) => { listeners.delete(listener) }),
  }
  vi.stubGlobal('matchMedia', () => query)
  return {
    query, listeners,
    change(value: boolean) {
      query.matches = value
      listeners.forEach(listener => listener())
    },
  }
}

let scrollTo: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  window.history.replaceState(null, '', '/')
  document.body.removeAttribute('style')
  scrollTo = vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  Object.defineProperty(window, 'scrollY', { configurable: true, value: 240 })
})
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks() })

async function openOnCase(strict = false) {
  const user = userEvent.setup()
  window.location.hash = 'koordinator/case/novak'
  const app = <App boot={boot(createMockSession({ delayMs: 0 }))} />
  render(strict ? <StrictMode>{app}</StrictMode> : app)
  await screen.findByRole('heading', { level: 2, name: /Jan Novák · 60 let/ })
  await user.click(screen.getByRole('button', { name: 'Asistent' }))
  return { user, dialog: screen.getByRole('dialog', { name: 'Asistent' }) }
}

describe('body scroll lock helper', () => {
  it('saves and restores each touched inline property separately and is idempotent', () => {
    document.body.style.setProperty('position', 'relative')
    document.body.style.setProperty('overflow', 'auto', 'important')
    document.body.style.setProperty('color', 'red')
    const release = lockBodyScroll()
    expect(document.body.style.position).toBe('fixed')
    expect(document.body.style.top).toBe('-240px')
    expect(document.body.style.overflow).toBe('hidden')
    release(true)
    expect(document.body.style.position).toBe('relative')
    expect(document.body.style.getPropertyPriority('overflow')).toBe('important')
    expect(document.body.style.top).toBe('')
    expect(document.body.style.color).toBe('red')
    expect(scrollTo).toHaveBeenCalledTimes(1)
    expect(scrollTo).toHaveBeenCalledWith({ top: 240, left: 0, behavior: 'instant' })
    release(true)
    expect(scrollTo).toHaveBeenCalledTimes(1)
  })

  it('release without scroll restoration leaves page scroll to the caller', () => {
    lockBodyScroll()(false)
    expect(document.body.getAttribute('style') ?? '').toBe('')
    expect(scrollTo).not.toHaveBeenCalled()
  })
})

describe('assistant dialog page freeze (policy: phones only, via max-width 760px)', { timeout: 15000 }, () => {
  it('phone: open freezes the page, close restores styles and the same scroll position', async () => {
    const media = phone(true)
    const { dialog } = await openOnCase()
    expect(document.body.style.position).toBe('fixed')
    expect(media.listeners.size).toBe(1)
    const staleListener = media.query.addEventListener.mock.calls.at(-1)![1]
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    await waitFor(() => expect(dialog).not.toHaveAttribute('open'))
    expect(document.body.style.position).toBe('')
    expect(scrollTo).toHaveBeenCalledWith({ top: 240, left: 0, behavior: 'instant' })
    expect(screen.getByRole('button', { name: 'Asistent' })).toHaveFocus()
    expect(media.listeners.size).toBe(0)
    expect(media.query.removeEventListener).toHaveBeenCalledWith('change', staleListener)
    act(() => staleListener())
    expect(document.body.style.position).toBe('')
  })

  it('desktop: no freeze', async () => {
    phone(false)
    await openOnCase()
    expect(document.body.style.position).toBe('')
  })

  it('an open desktop dialog locks on crossing to mobile, unlocks on desktop and locks again at the current scroll position', async () => {
    const media = phone(false)
    document.body.style.setProperty('position', 'relative')
    document.body.style.setProperty('overflow', 'auto', 'important')
    document.body.style.setProperty('color', 'red')
    const { dialog } = await openOnCase()
    expect(document.body.style.position).toBe('relative')
    expect(media.listeners.size).toBe(1)
    act(() => media.change(true))
    expect(document.body.style.position).toBe('fixed')
    expect(document.body.style.top).toBe('-240px')
    act(() => media.change(false))
    expect(dialog).toHaveAttribute('open')
    expect(document.body.style.position).toBe('relative')
    expect(document.body.style.overflow).toBe('auto')
    expect(document.body.style.getPropertyPriority('overflow')).toBe('important')
    expect(document.body.style.color).toBe('red')
    expect(document.body.style.top).toBe('')
    expect(scrollTo).toHaveBeenCalledWith({ top: 240, left: 0, behavior: 'instant' })
    Object.defineProperty(window, 'scrollY', { configurable: true, value: 415 })
    act(() => media.change(true))
    expect(document.body.style.position).toBe('fixed')
    expect(document.body.style.top).toBe('-415px')
    scrollTo.mockClear()
    act(() => media.change(true))
    expect(scrollTo).not.toHaveBeenCalled()
    fireEvent(dialog, new Event('cancel', { cancelable: true }))
    await waitFor(() => expect(dialog).not.toHaveAttribute('open'))
    expect(document.body.style.position).toBe('relative')
    expect(document.body.style.getPropertyPriority('overflow')).toBe('important')
    expect(scrollTo).toHaveBeenCalledExactlyOnceWith({ top: 415, left: 0, behavior: 'instant' })
    expect(media.listeners.size).toBe(0)
  })

  it('route closure releases without scrolling back to the old position', async () => {
    phone(true)
    const { dialog } = await openOnCase()
    scrollTo.mockClear()
    await act(async () => { window.location.hash = 'lekar'; window.dispatchEvent(new HashChangeEvent('hashchange')) })
    await waitFor(() => expect(dialog).not.toHaveAttribute('open'))
    expect(document.body.style.position).toBe('')
    expect(scrollTo).not.toHaveBeenCalledWith({ top: 240, left: 0, behavior: 'instant' })
  })

  it('StrictMode remount and unmount while open leave no lock behind', async () => {
    const media = phone(true)
    await openOnCase(true)
    expect(document.body.style.position).toBe('fixed')
    expect(media.listeners.size).toBe(1)
    const staleListener = media.query.addEventListener.mock.calls.at(-1)![1]
    cleanup()
    expect(document.body.getAttribute('style') ?? '').toBe('')
    expect(media.listeners.size).toBe(0)
    expect(media.query.removeEventListener).toHaveBeenCalledWith('change', staleListener)
    act(() => staleListener())
    expect(document.body.getAttribute('style') ?? '').toBe('')
  })
})

function stubBody(body: HTMLElement, scrollHeight: number, clientHeight: number) {
  Object.defineProperty(body, 'scrollHeight', { configurable: true, get: () => scrollHeight })
  Object.defineProperty(body, 'clientHeight', { configurable: true, get: () => clientHeight })
}

describe('conversation scroll ownership', { timeout: 15000 }, () => {
  it('a reader scrolled away from the bottom keeps position and focus through typing, pending and reply', async () => {
    const { user, dialog } = await openOnCase()
    const body = dialog.querySelector<HTMLElement>('.assistant__body')!
    stubBody(body, 1000, 300)
    body.scrollTop = 100
    fireEvent.scroll(body)
    await user.type(within(dialog).getByLabelText('Váš dotaz'), 'Kdy?')
    const submit = within(dialog).getByRole('button', { name: 'Odeslat dotaz' })
    await user.click(submit)
    await within(dialog).findByText(/Odpověď 1 je připravena/)
    expect(body.scrollTop).toBe(100)
    expect(submit).toHaveFocus()
  })

  it('at the bottom a long reply opens at its start; a later viewport-only change does not scroll', async () => {
    const { user, dialog } = await openOnCase()
    const body = dialog.querySelector<HTMLElement>('.assistant__body')!
    stubBody(body, 1000, 300)
    await user.type(within(dialog).getByLabelText('Váš dotaz'), 'Kdy?')
    await user.click(within(dialog).getByRole('button', { name: 'Odeslat dotaz' }))
    await within(dialog).findByText(/Odpověď 1 je připravena/)
    // jsdom has no layout: turn offsetTop is 0, so "start" is 0 while the bottom would be 700.
    expect(body.scrollTop).toBe(0)
    body.scrollTop = 37
    stubBody(body, 1000, 200)
    await act(async () => { window.dispatchEvent(new Event('resize')) })
    expect(body.scrollTop).toBe(37)
  })
})
