import { failure, success } from './contracts'
import type { DataMode, Result } from './contracts'

export function parseDataMode(value: string | undefined): Result<DataMode> {
  if (value === undefined || value === 'backend') return success('backend')
  if (value === 'mock') return success('mock')
  return failure('configuration-error', 'VITE_DATA_MODE musí být backend nebo mock; prázdná hodnota není platná.')
}
