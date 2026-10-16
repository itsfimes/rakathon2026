import { useCallback, useState } from 'react'
import type { DemoControls, Result } from '../data/contracts'

export interface DemoFeedback {
  readonly tone: 'success' | 'error'
  readonly text: string
}

export interface DemoActions {
  readonly available: boolean
  readonly busy: boolean
  readonly feedback: DemoFeedback | null
  acceptTask(taskId: string): void
  markReviewed(documentId: string): void
  reset(): void
}

/** Local-only demo mutations. Exists only when the session is explicit mock mode;
    after every success the caller re-reads workspace + case so all views agree. */
export function useDemoActions(controls: DemoControls | null, onChanged: () => void): DemoActions {
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<DemoFeedback | null>(null)

  const run = useCallback((action: () => Promise<Result<void>>, done: string) => {
    setBusy(true)
    setFeedback(null)
    action().then(
      result => {
        setFeedback(result.ok ? { tone: 'success', text: done } : { tone: 'error', text: result.error.message })
        if (result.ok) onChanged()
      },
      () => setFeedback({ tone: 'error', text: 'Akci se nepodařilo provést.' }),
    ).finally(() => setBusy(false))
  }, [onChanged])

  return {
    available: controls !== null,
    busy,
    feedback,
    acceptTask: taskId => { if (controls) run(() => controls.acceptTask(taskId), 'Převzetí zaznamenáno lokálně v demu. Nic se neodeslalo.') },
    markReviewed: documentId => { if (controls) run(() => controls.markDocumentReviewed(documentId), 'Podklad označen jako zkontrolovaný lokálně v demu. Nic se neuložilo.') },
    reset: () => { if (controls) run(() => controls.reset(), 'Demo obnoveno do výchozího stavu.') },
  }
}
