import { useEffect, useState } from 'react'
import type { DataError, Result } from '../data/contracts'

export type ResourceState<T> =
  | { readonly status: 'idle' }
  | { readonly status: 'loading' }
  | { readonly status: 'error'; readonly error: DataError }
  | { readonly status: 'ready'; readonly value: T; readonly fresh: boolean }

interface Settled<T> {
  readonly key: string
  readonly requestKey: string
  readonly load: (key: string, signal: AbortSignal) => Promise<Result<T>>
  readonly result: Result<T>
}

const unexpected = (reason: unknown): DataError => ({
  code: 'unavailable',
  message: reason instanceof Error && reason.message ? `Neočekávaná chyba: ${reason.message}` : 'Neočekávaná chyba při čtení dat.',
})

/**
 * Reads one gateway snapshot for `key` (null = nothing to read). Each read gets its own
 * AbortController; a result is only shown while its key and version still match, so a late
 * answer for a previous case can never appear under a newly selected one. A re-read of the
 * same key (after a local demo change) keeps that same item's last snapshot meanwhile.
 */
export function useResource<T>(
  key: string | null,
  version: number,
  load: (key: string, signal: AbortSignal) => Promise<Result<T>>,
): ResourceState<T> {
  const [settled, setSettled] = useState<Settled<T> | null>(null)
  const requestKey = key === null ? null : `${key}\u0000${version}`

  useEffect(() => {
    if (key === null || requestKey === null) return
    const controller = new AbortController()
    load(key, controller.signal).then(
      result => {
        if (controller.signal.aborted) return
        if (!result.ok && result.error.code === 'aborted') return
        setSettled({ key, requestKey, load, result })
      },
      (reason: unknown) => {
        if (!controller.signal.aborted) setSettled({ key, requestKey, load, result: { ok: false, error: unexpected(reason) } })
      },
    )
    return () => controller.abort()
  }, [key, requestKey, load])

  if (requestKey === null) return { status: 'idle' }
  if (!settled || settled.key !== key) return { status: 'loading' }
  // Same item re-read after a local change: keep showing its last snapshot until the new one lands.
  if (settled.requestKey !== requestKey && !settled.result.ok) return { status: 'loading' }
  return settled.result.ok ? { status: 'ready', value: settled.result.value, fresh: settled.requestKey === requestKey && settled.load === load } : { status: 'error', error: settled.result.error }
}
