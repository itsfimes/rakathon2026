import { isValidElement } from 'react'
import type { ReactNode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import type { BootstrapResult } from '../src/data/contracts'
import { jsonResponse, sessionResponse, workspaceResponse } from './backend-fixtures'

const root = vi.hoisted(() => ({ render: vi.fn<(node: unknown) => void>() }))
vi.mock('react-dom/client', () => ({ createRoot: () => root }))
vi.mock('../src/auth/LoginBoundary', () => { throw new Error('The development entry must not import the login gate.') })
vi.mock('../src/data/mock/provider', () => { throw new Error('The backend entry must not import clinical fixtures.') })

afterEach(() => {
  document.getElementById('root')?.remove()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

it('boots the actual entry through the backend gateway without auth requests or an invented identity', async () => {
  vi.stubEnv('VITE_DATA_MODE', 'backend')
  vi.stubEnv('VITE_BACKEND_API_BASE', '/api/v1')
  const fetcher = vi.fn<typeof fetch>().mockImplementation(async url => {
    if (url === '/api/v1/session') return jsonResponse(sessionResponse)
    if (url === '/api/v1/workspace') return jsonResponse(workspaceResponse())
    throw new Error('Unexpected request from the development entry.')
  })
  vi.stubGlobal('fetch', fetcher)
  const container = document.createElement('div')
  container.id = 'root'
  document.body.append(container)
  await import('../src/main')
  const tree = root.render.mock.calls[0]?.[0]
  if (!isValidElement<{ children: ReactNode }>(tree)) throw new Error('Missing root element.')
  const app = tree.props.children
  if (!isValidElement<{ boot: Promise<BootstrapResult>; authed?: boolean }>(app)) throw new Error('Missing demo entry.')
  expect((app.type as { name?: string }).name).toBe('DemoEntry')
  expect(app.props.authed).toBeUndefined()
  const boot = await app.props.boot
  expect(boot.status).toBe('session')
  if (boot.status !== 'session') throw new Error('Backend bootstrap failed.')
  expect(boot.session.mode).toBe('backend')
  expect((await boot.session.gateway.readWorkspace()).ok).toBe(true)
  expect(fetcher.mock.calls.map(call => call[0])).toEqual(['/api/v1/session', '/api/v1/workspace'])
})
