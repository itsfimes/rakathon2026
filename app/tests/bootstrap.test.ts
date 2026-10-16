import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const imported = { mock: vi.fn(), backend: vi.fn() }
beforeEach(() => {
  vi.stubEnv('VITE_BACKEND_API_BASE', undefined)
  vi.resetModules()
  imported.mock.mockClear()
  imported.backend.mockClear()
  vi.doMock('../src/data/mock/provider', () => {
    imported.mock()
    return { createMockSession: () => ({ mode: 'mock', gateway: {}, assistant: { availability: 'available', provenance: 'scripted' }, demoControls: {} }) }
  })
  vi.doMock('../src/data/backend/unconfigured', () => {
    imported.backend()
    return { UnconfiguredBackendGateway: class {} }
  })
})
afterEach(() => {
  vi.unstubAllEnvs()
  vi.doUnmock('../src/data/mock/provider')
  vi.doUnmock('../src/data/backend/unconfigured')
})

describe('composition import boundary', () => {
  it.each(['', 'invalid', 'MOCK'])('rejects %s before importing any provider', async value => {
    vi.stubEnv('VITE_DATA_MODE', value)
    const { bootstrap } = await import('../src/data/bootstrap')
    expect(await bootstrap()).toMatchObject({ status: 'configuration-error' })
    expect(imported.mock).not.toHaveBeenCalled()
    expect(imported.backend).not.toHaveBeenCalled()
  })
  it.each([undefined, 'backend'])('backend %s never imports mocks', async value => {
    vi.stubEnv('VITE_DATA_MODE', value)
    const { bootstrap } = await import('../src/data/bootstrap')
    expect(await bootstrap()).toMatchObject({ status: 'session', session: { mode: 'backend', assistant: { availability: 'unavailable', provenance: 'none' } } })
    expect(imported.backend).toHaveBeenCalledOnce()
    expect(imported.mock).not.toHaveBeenCalled()
  })
  it('explicit mock exposes demo controls and imports only mock provider', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'mock')
    const { bootstrap } = await import('../src/data/bootstrap')
    expect(await bootstrap()).toMatchObject({ status: 'session', session: { mode: 'mock', demoControls: {}, assistant: { availability: 'available', provenance: 'scripted' } } })
    expect(imported.mock).toHaveBeenCalledOnce()
    expect(imported.backend).not.toHaveBeenCalled()
  })
  it('configured backend imports no mocks, bootstraps session and reports session failure as unavailable', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'backend')
    vi.stubEnv('VITE_BACKEND_API_BASE', '/api/v1')
    const fetcher = vi.fn<typeof fetch>().mockRejectedValue(new Error('private upstream failure'))
    vi.stubGlobal('fetch', fetcher)
    const { bootstrap } = await import('../src/data/bootstrap')
    const result = await bootstrap()
    expect(result).toMatchObject({ status: 'session', session: { mode: 'backend', connection: 'unavailable' } })
    expect(imported.mock).not.toHaveBeenCalled()
    expect(fetcher.mock.calls[0]?.[0]).toBe('/api/v1/session')
    vi.unstubAllGlobals()
  })
  it('invalid configured API path fails closed before requests or provider imports', async () => {
    vi.stubEnv('VITE_DATA_MODE', 'backend'); vi.stubEnv('VITE_BACKEND_API_BASE', 'https://example.test')
    const { bootstrap } = await import('../src/data/bootstrap')
    expect(await bootstrap()).toMatchObject({ status: 'configuration-error' })
    expect(imported.mock).not.toHaveBeenCalled()
    expect(imported.backend).not.toHaveBeenCalled()
  })
})
