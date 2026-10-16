import { bootstrap } from './data/bootstrap'
import type { BootstrapResult } from './data/contracts'

let boot: Promise<BootstrapResult> | undefined

/** One bootstrap per page load, shared by every render (StrictMode-safe). */
export function bootOnce(): Promise<BootstrapResult> {
  boot ??= bootstrap()
  return boot
}
