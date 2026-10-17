import { closeSync, constants, fstatSync, lstatSync, openSync, readSync } from 'node:fs'
import { dirname, isAbsolute, relative, resolve } from 'node:path'
import type { ProxyOptions } from 'vite'

function readPrivateKey(filename: string, appRoot: string): string {
  let fd: number | undefined
  try {
    const path = resolve(filename)
    const within = relative(resolve(appRoot), path)
    if (!within || (!within.startsWith('..') && !isAbsolute(within))) throw new Error()
    for (let parent = dirname(path); ; parent = dirname(parent)) {
      if (lstatSync(parent).isSymbolicLink()) throw new Error()
      if (dirname(parent) === parent) break
    }
    fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK)
    const info = fstatSync(fd)
    if (!info.isFile() || info.uid !== process.getuid?.() || (info.mode & 0o7777) !== 0o600 || info.nlink !== 1 || info.size > 128) throw new Error()
    const buffer = Buffer.alloc(128)
    const key = buffer.subarray(0, readSync(fd, buffer, 0, 128, 0)).toString('ascii').trim()
    if (!/^[A-Za-z0-9_-]{43}$/.test(key)) throw new Error()
    return key
  } catch { throw new Error('Unsafe or unavailable backend proxy key file') }
  finally { if (fd !== undefined) closeSync(fd) }
}

function resolveProxyTarget(target: string | undefined): { target: string; host: string } {
  if (target === undefined) return { target: 'http://127.0.0.1:8765', host: '127.0.0.1:8765' }
  const text = target.trim()
  if (!text || !text.startsWith('http://')) throw new Error('Unsafe or unavailable backend proxy target')
  let url: URL
  try { url = new URL(text) } catch { throw new Error('Unsafe or unavailable backend proxy target') }
  if (url.protocol !== 'http:' || url.username !== '' || url.password !== '' || url.search !== '' || url.hash !== '') throw new Error('Unsafe or unavailable backend proxy target')
  if (url.pathname !== '/' && url.pathname !== '') throw new Error('Unsafe or unavailable backend proxy target')
  const rawHostname = url.hostname.toLowerCase()
  const bare = rawHostname.startsWith('[') && rawHostname.endsWith(']') ? rawHostname.slice(1, -1) : rawHostname
  if (bare !== '127.0.0.1' && bare !== 'localhost' && bare !== '::1') throw new Error('Unsafe or unavailable backend proxy target')
  if (url.port === '') throw new Error('Unsafe or unavailable backend proxy target')
  const port = Number(url.port)
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Unsafe or unavailable backend proxy target')
  const host = url.host.toLowerCase()
  return { target: `http://${host}`, host }
}

interface BrowserOriginSettings {
  readonly allowedOrigins?: string | undefined
  readonly canonicalOrigin?: string | undefined
}

function browserOriginPolicy(settings: BrowserOriginSettings) {
  let { allowedOrigins, canonicalOrigin } = settings
  if (allowedOrigins === undefined && canonicalOrigin === undefined) {
    allowedOrigins = 'http://localhost:5173,http://127.0.0.1:5173'
    canonicalOrigin = 'http://localhost:5173'
  }
  const invalid = () => new Error('Unsafe or unavailable backend browser origin policy')
  function parseOrigin(value: string): URL {
    let url: URL
    try { url = new URL(value) } catch { throw invalid() }
    if (!['http:', 'https:'].includes(url.protocol) || url.origin !== value) throw invalid()
    return url
  }
  if (!allowedOrigins || !canonicalOrigin) throw invalid()
  const origins = new Set(allowedOrigins.split(',').map(value => value.trim()))
  const hosts = new Set([...origins].map(value => parseOrigin(value).host))
  const canonical = parseOrigin(canonicalOrigin)
  if (!origins.has(canonicalOrigin) || !['localhost', '127.0.0.1', '[::1]'].includes(canonical.hostname)) throw invalid()
  return { origins, hosts, canonicalOrigin }
}

/** Node-only capability: never returned as client env, response, define or build metadata. */
export function backendProxy(filename: string | undefined, appRoot: string, target?: string, browserOrigins: BrowserOriginSettings = {}): Record<string, ProxyOptions> | undefined {
  if (filename === undefined) return undefined
  const key = readPrivateKey(filename, appRoot)
  const upstream = resolveProxyTarget(target)
  const policy = browserOriginPolicy(browserOrigins)
  return { '/api': {
    target: upstream.target, changeOrigin: true, xfwd: false,
    bypass(request, response) {
      const origin = request.headers.origin
      const host = request.headers.host
      const readOnly = request.method === 'GET' || request.method === 'HEAD'
      const allowed = host !== undefined && policy.hosts.has(host)
        && (origin === undefined ? readOnly : policy.origins.has(origin) && new URL(origin).host === host)
      if (!allowed) {
        if (!response) return false
        response.writeHead(403, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
        response.end(JSON.stringify({ error: 'frontend_origin_denied' }))
        return request.url ?? '/'
      }
    },
    configure(proxy) {
      proxy.on('proxyReq', (request, incoming) => {
        for (const name of ['Forwarded', 'X-Forwarded-For', 'X-Forwarded-Host', 'X-Forwarded-Proto', 'X-Forwarded-Port', 'X-Original-Host']) request.removeHeader(name)
        request.setHeader('Host', upstream.host)
        request.setHeader('X-Rakathon-Proxy-Key', key)
        if (incoming.headers.origin !== undefined) request.setHeader('Origin', policy.canonicalOrigin)
      })
    },
  } }
}
