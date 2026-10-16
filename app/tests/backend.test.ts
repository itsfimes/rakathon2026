import { afterEach, expect, it, vi } from 'vitest'
import { UnconfiguredBackendGateway } from '../src/data/backend/unconfigured'

afterEach(() => vi.unstubAllGlobals())

it('backend is unavailable, never empty or fixture fallback, and makes zero requests', async () => {
  const fetch = vi.fn()
  const xhr = vi.fn()
  vi.stubGlobal('fetch', fetch)
  vi.stubGlobal('XMLHttpRequest', xhr)
  const gateway = new UnconfiguredBackendGateway()
  expect(gateway.mode).toBe('backend')
  expect(await gateway.readWorkspace()).toMatchObject({ ok: false, error: { code: 'backend-unconfigured' } })
  expect(await gateway.readCase('unknown')).toMatchObject({ ok: false, error: { code: 'backend-unconfigured' } })
  expect(fetch).not.toHaveBeenCalled()
  expect(xhr).not.toHaveBeenCalled()
})

it('backend normalizes cancellation', async () => {
  const controller = new AbortController()
  controller.abort()
  const gateway = new UnconfiguredBackendGateway()
  expect(await gateway.readWorkspace(controller.signal)).toMatchObject({ ok: false, error: { code: 'aborted' } })
  expect(await gateway.readCase('anything', controller.signal)).toMatchObject({ ok: false, error: { code: 'aborted' } })
})
