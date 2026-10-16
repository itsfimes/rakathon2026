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

/** Node-only capability: never returned as client env, response, define or build metadata. */
export function backendProxy(filename: string | undefined, appRoot: string): Record<string, ProxyOptions> | undefined {
  if (filename === undefined) return undefined
  const key = readPrivateKey(filename, appRoot)
  return { '/api': {
    target: 'http://127.0.0.1:8765', changeOrigin: true, xfwd: false,
    configure(proxy) {
      proxy.on('proxyReq', request => {
        for (const name of ['Forwarded', 'X-Forwarded-For', 'X-Forwarded-Host', 'X-Forwarded-Proto', 'X-Forwarded-Port', 'X-Original-Host']) request.removeHeader(name)
        request.setHeader('Host', '127.0.0.1:8765')
        request.setHeader('X-Rakathon-Proxy-Key', key)
      })
    },
  } }
}
