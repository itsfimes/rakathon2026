import { useState } from 'react'
import { App } from '../../App'
import type { BootstrapResult } from '../../data/contracts'
import { DemoLogin } from './DemoLogin'
import type { DemoRole } from './DemoLogin'

/** Development entry: a presentation-only "login" picks one role view; the app then shows only that role.
    The role lives in memory only (a refresh returns here). Each entry remounts App, so no case selection,
    preview, assistant transcript or local workflow state carries over between roles. */
export function DemoEntry({ boot }: { readonly boot: Promise<BootstrapResult> }) {
  const [entry, setEntry] = useState<{ readonly role: DemoRole; readonly n: number } | null>(null)
  if (!entry) return <DemoLogin onEnter={role => {
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}#${role}`)
    setEntry(previous => ({ role, n: (previous?.n ?? 0) + 1 }))
  }} />
  return <App key={entry.n} boot={boot} lockedRole={entry.role} onExitDemo={() => {
    window.history.replaceState(window.history.state, '', `${window.location.pathname}${window.location.search}`)
    setEntry(null)
  }} />
}
