import type { BootstrapResult } from './contracts'
import { parseDataMode } from './mode'
import { UnconfiguredAssistant } from './backend/assistant'

export async function bootstrap(signal?: AbortSignal): Promise<BootstrapResult> {
  const mode = parseDataMode(import.meta.env.VITE_DATA_MODE)
  if (!mode.ok) return { status: 'configuration-error', error: mode.error }

  if (import.meta.env.VITE_DATA_MODE === 'mock') {
    const { createMockSession } = await import('./mock/provider')
    return { status: 'session', session: createMockSession() }
  }

  if (import.meta.env.VITE_BACKEND_API_BASE !== undefined) {
    const { createBackendSession, validApiBase } = await import('./backend/gateway')
    if (!validApiBase(import.meta.env.VITE_BACKEND_API_BASE)) return { status: 'configuration-error', error: {
      code: 'configuration-error', message: 'VITE_BACKEND_API_BASE musí být přesně /api/v1 (stejný původ).',
    } }
    return { status: 'session', session: await createBackendSession(signal) }
  }

  const { UnconfiguredBackendGateway } = await import('./backend/unconfigured')
  return { status: 'session', session: { mode: 'backend', gateway: new UnconfiguredBackendGateway(), assistant: new UnconfiguredAssistant() } }
}
