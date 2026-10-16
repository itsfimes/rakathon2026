import { bootstrap } from './data/bootstrap'
import type { BootstrapResult } from './data/contracts'

let boot: Promise<BootstrapResult> | undefined

export function bootOnce(): Promise<BootstrapResult> {
  boot ??= bootstrap()
  return boot
}

export function resetBootCache(): void {
  boot = undefined
}
