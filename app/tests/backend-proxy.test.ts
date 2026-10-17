// @vitest-environment node
import { chmodSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { backendProxy } from '../backend-proxy'

const roots: string[] = []
type ProxyRequestListener = (request: { removeHeader: (name: string) => void; setHeader: (name: string, value: string) => void }, incoming: { headers: { origin?: string } }) => void
afterEach(() => roots.splice(0).forEach(path => rmSync(path, { recursive: true, force: true })))
function setup() {
  const root = mkdtempSync(join(tmpdir(), 'synthetic-proxy-')); roots.push(root)
  const file = join(root, 'key'), app = join(root, 'app')
  mkdirSync(app)
  writeFileSync(file, 'synthetic_test_key_'.padEnd(43, 'x'), { mode: 0o600 })
  return { root, file, app }
}
describe('server-only proxy capability', () => {
  it('is disabled without a Node server key-file setting', () => expect(backendProxy(undefined, resolve('app'))).toBeUndefined())
  it('fixes loopback upstream, overwrites key/Host and strips rejected forwarded headers', () => {
    const { file, app } = setup()
    const rule = backendProxy(file, app)!['/api']!
    expect(rule).toMatchObject({ target: 'http://127.0.0.1:8765', changeOrigin: true, xfwd: false })
    expect(JSON.stringify(rule)).not.toContain('synthetic_test_key_')
    const on = vi.fn()
    const configure = rule.configure!
    configure({ on } as unknown as Parameters<typeof configure>[0], {} as Parameters<typeof configure>[1])
    const listener = on.mock.calls[0]?.[1] as ProxyRequestListener
    const removeHeader = vi.fn(), setHeader = vi.fn()
    listener({ removeHeader, setHeader }, { headers: {} })
    expect(removeHeader.mock.calls.map(c => c[0])).toEqual(['Forwarded', 'X-Forwarded-For', 'X-Forwarded-Host', 'X-Forwarded-Proto', 'X-Forwarded-Port', 'X-Original-Host'])
    expect(setHeader.mock.calls.map(c => c[0])).toEqual(['Host', 'X-Rakathon-Proxy-Key'])
    // Assertions expose only presence/length, never even synthetic key text on failure.
    expect(setHeader.mock.calls[1]?.[1].length === 43).toBe(true)
  })
  it('rejects unsafe permissions, symlinks, files inside app and symlink parent directories with safe errors', () => {
    const { root, file, app } = setup()
    chmodSync(file, 0o644)
    expect(() => backendProxy(file, app)).toThrow('Unsafe or unavailable backend proxy key file')
    chmodSync(file, 0o600)
    const link = join(root, 'link'); symlinkSync(file, link)
    expect(() => backendProxy(link, app)).toThrow('Unsafe or unavailable backend proxy key file')
    const inside = join(app, 'key'); writeFileSync(inside, 'x'.repeat(43), { mode: 0o600 })
    expect(() => backendProxy(inside, app)).toThrow('Unsafe or unavailable backend proxy key file')
    const dirLink = join(root, 'dir-link'); symlinkSync(app, dirLink)
    expect(() => backendProxy(join(dirLink, 'key'), join(root, 'other'))).toThrow('Unsafe or unavailable backend proxy key file')
  })
  it('defaults to explicit undefined target without changing existing two-arg calls', () => {
    const { file, app } = setup()
    const rule = backendProxy(file, app, undefined)!['/api']!
    expect(rule).toMatchObject({ target: 'http://127.0.0.1:8765', changeOrigin: true, xfwd: false })
  })
  it('uses explicit Docker HTTP loopback target with matching Host and keeps key/forwarded behavior', () => {
    const { file, app } = setup()
    const rule = backendProxy(file, app, 'http://127.0.0.1:18765')!['/api']!
    expect(rule).toMatchObject({ target: 'http://127.0.0.1:18765', changeOrigin: true, xfwd: false })
    expect(JSON.stringify(rule)).not.toContain('synthetic_test_key_')
    const on = vi.fn()
    const configure = rule.configure!
    configure({ on } as unknown as Parameters<typeof configure>[0], {} as Parameters<typeof configure>[1])
    const listener = on.mock.calls[0]?.[1] as ProxyRequestListener
    const removeHeader = vi.fn(), setHeader = vi.fn()
    listener({ removeHeader, setHeader }, { headers: {} })
    expect(removeHeader.mock.calls.map(c => c[0])).toEqual(['Forwarded', 'X-Forwarded-For', 'X-Forwarded-Host', 'X-Forwarded-Proto', 'X-Forwarded-Port', 'X-Original-Host'])
    expect(setHeader.mock.calls.map(c => c[0])).toEqual(['Host', 'X-Rakathon-Proxy-Key'])
    expect(setHeader.mock.calls[0]?.[1]).toBe('127.0.0.1:18765')
    expect(setHeader.mock.calls[1]?.[1].length === 43).toBe(true)
  })
  it('allows localhost and IPv6 loopback with matching authority', () => {
    const { file, app } = setup()
    const local = backendProxy(file, app, 'http://localhost:18765')!['/api']!
    expect(local).toMatchObject({ target: 'http://localhost:18765', changeOrigin: true, xfwd: false })
    const v6 = backendProxy(file, app, 'http://[::1]:18765')!['/api']!
    expect(v6).toMatchObject({ target: 'http://[::1]:18765', changeOrigin: true, xfwd: false })
    const on = vi.fn()
    const configure = v6.configure!
    configure({ on } as unknown as Parameters<typeof configure>[0], {} as Parameters<typeof configure>[1])
    const listener = on.mock.calls[0]?.[1] as ProxyRequestListener
    const setHeader = vi.fn()
    listener({ removeHeader: () => {}, setHeader }, { headers: {} })
    expect(setHeader.mock.calls[0]?.[1]).toBe('[::1]:18765')
  })
  it('rejects remote, wildcard, credentialed, pathed and malformed targets fail-closed', () => {
    const { file, app } = setup()
    const bad = ['', '   ', 'notaurl', 'https://127.0.0.1:8765', 'ws://127.0.0.1:8765', 'http://192.168.1.10:8765', 'http://10.0.0.5:8765', 'http://172.16.0.2:8765', 'http://example.com:8765', 'http://0.0.0.0:8765', 'http://user:pass@127.0.0.1:8765', 'http://127.0.0.1:8765/api', 'http://127.0.0.1:8765?x=1', 'http://127.0.0.1:8765#frag', 'http://127.0.0.1', 'http://[::1]', 'http://127.0.0.1:0', 'http://127.0.0.1:99999', 'http://127.0.0.1:abc', 'http://localhost:8765/api/v1']
    for (const target of bad) expect(() => backendProxy(file, app, target)).toThrow('Unsafe or unavailable backend proxy target')
  })
  it.each([undefined, 'http://127.0.0.1:5173'])('preserves absent Origin or rewrites allowed incoming Origin (%s) to canonical', origin => {
    const { file, app } = setup()
    const rule = backendProxy(file, app)!['/api']!
    const on = vi.fn()
    const configure = rule.configure!
    configure({ on } as unknown as Parameters<typeof configure>[0], {} as Parameters<typeof configure>[1])
    const listener = on.mock.calls[0]?.[1] as ProxyRequestListener
    const setHeader = vi.fn()
    listener({ removeHeader: vi.fn(), setHeader }, { headers: origin === undefined ? {} : { origin } })
    const origins = setHeader.mock.calls.filter(([name]) => name === 'Origin')
    expect(origins).toEqual(origin === undefined ? [] : [['Origin', 'http://localhost:5173']])
  })
  it.each([
    { host: 'evil.invalid', origin: 'http://localhost:5173', method: 'GET' },
    { host: 'localhost:5173', origin: 'https://evil.invalid', method: 'POST' },
    { host: 'localhost:5173', origin: 'http://127.0.0.1:5173', method: 'POST' },
    ...['POST', 'PUT', 'PATCH', 'DELETE'].map(method => ({ host: 'localhost:5173', origin: undefined, method })),
  ])('bypass rejects disallowed Host/Origin and originless writes: %j', ({ host, origin, method }) => {
    const { file, app } = setup()
    const rule = backendProxy(file, app)!['/api']!
    const bypass = rule.bypass!
    const request = { method, url: '/api/v1/assistant', headers: { host, ...(origin === undefined ? {} : { origin }) } }
    const response = { writeHead: vi.fn(), end: vi.fn() }
    expect(bypass(request as Parameters<typeof bypass>[0], response as unknown as Parameters<typeof bypass>[1], rule)).toBe('/api/v1/assistant')
    expect(response.writeHead).toHaveBeenCalledWith(403, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
    expect(response.end).toHaveBeenCalledWith(JSON.stringify({ error: 'frontend_origin_denied' }))
  })
  it.each([
    { method: 'GET', origin: undefined }, { method: 'HEAD', origin: undefined },
    { method: 'POST', origin: 'http://localhost:5173' },
  ])('bypass permits allowed requests: %j', ({ method, origin }) => {
    const { file, app } = setup()
    const rule = backendProxy(file, app)!['/api']!
    const bypass = rule.bypass!
    const response = { writeHead: vi.fn(), end: vi.fn() }
    const request = { method, url: '/api/v1/session', headers: { host: 'localhost:5173', ...(origin === undefined ? {} : { origin }) } }
    expect(bypass(request as Parameters<typeof bypass>[0], response as unknown as Parameters<typeof bypass>[1], rule)).toBeUndefined()
    expect(response.writeHead).not.toHaveBeenCalled()
    expect(response.end).not.toHaveBeenCalled()
  })
})
