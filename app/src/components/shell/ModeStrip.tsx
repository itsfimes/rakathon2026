import { forwardRef } from 'react'
import { Icon } from '../../icons/Icon'
import type { DemoFeedback } from '../../hooks/useDemoActions'

export type ModeStripState =
  | { readonly kind: 'starting' }
  | { readonly kind: 'configuration-error'; readonly message: string }
  | { readonly kind: 'backend'; readonly connection?: 'connected' | 'unavailable' }
  | { readonly kind: 'mock'; readonly busy: boolean; readonly onReset: () => void }

interface ModeStripProps {
  readonly state: ModeStripState
  readonly feedback: DemoFeedback | null
}

/** Persistent, always-pinned statement of where the data comes from. Derived only from
    the bootstrapped session; no role, query or storage can change or hide it. */
export const ModeStrip = forwardRef<HTMLDivElement, ModeStripProps>(function ModeStrip({ state, feedback }, ref) {
  const tone = state.kind === 'mock' ? 'mock' : state.kind === 'configuration-error' ? 'error' : 'backend'
  return (
    <div ref={ref} className={`mode-strip mode-strip--${tone}`} data-mode={state.kind} role="region" aria-label="Zdroj dat">
      {state.kind === 'mock' && <>
        <span className="mode-strip__label"><Icon name="database" />DEMO · SYNTETICKÁ DATA · bez backendu</span>
        <span className="mode-strip__detail">Změny jsou jen lokální v tomto okně.</span>
      </>}
      {state.kind === 'backend' && <>
        <span className="mode-strip__label"><Icon name="database" />{state.connection === 'connected' ? 'Backend IRIS · vývojové připojení' : state.connection === 'unavailable' ? 'Backend IRIS · není dostupný' : 'Backend · není nakonfigurován'}</span>
        <span className="mode-strip__detail">{state.connection ? 'Přihlášení ověřuje server. Volba pohledu je pouze zobrazení.' : 'Nejsou načtena žádná data pacientů.'}</span>
      </>}
      {state.kind === 'configuration-error' && <>
        <span className="mode-strip__label"><Icon name="alert" />Konfigurace zdroje dat je neplatná</span>
        <span className="mode-strip__detail">{state.message}</span>
      </>}
      {state.kind === 'starting' && <span className="mode-strip__label"><Icon name="clock" />Zdroj dat · načítání konfigurace</span>}
      {state.kind === 'mock' && (
        <span className="mode-strip__actions">
          <button type="button" className="btn" onClick={state.onReset} disabled={state.busy}>
            <Icon name="reset" /><span className="mode-strip__btn-text">Obnovit demo</span>
          </button>
        </span>
      )}
      <span className="mode-strip__status" role="status">{feedback?.text ?? ''}</span>
    </div>
  )
})
