// @vitest-environment node
import { chmodSync, mkdirSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { backendProxy } from '../backend-proxy'

const roots: string[] = []
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
  it('fixes loopback upstream, overwrites key/Host and strips rejected forwarded headers without changing Origin', () => {
    const { file, app } = setup()
    const rule = backendProxy(file, app)!['/api']!
    expect(rule).toMatchObject({ target: 'http://127.0.0.1:8765', changeOrigin: true, xfwd: false })
    expect(JSON.stringify(rule)).not.toContain('synthetic_test_key_')
    const on = vi.fn()
    const configure = rule.configure!
    configure({ on } as unknown as Parameters<typeof configure>[0], {} as Parameters<typeof configure>[1])
    const listener = on.mock.calls[0]?.[1] as (request: { removeHeader: (name: string) => void; setHeader: (name: string, value: string) => void }) => void
    const removeHeader = vi.fn(), setHeader = vi.fn()
    listener({ removeHeader, setHeader })
    expect(removeHeader.mock.calls.map(c => c[0])).toEqual(['Forwarded', 'X-Forwarded-Host', 'X-Original-Host'])
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
})
