/* Static UI vocabulary: maps contract enums to Czech labels, tag tones and icons.
   No case data lives here — only labels for states defined by the contract. */
import type { IconName } from '../icons/paths'
import type { Diagnosis, DocumentState, NextStep, Priority, ProgressState, SourceField } from '../data/contracts'
import { formatDayMonth } from './format'

export type Tone = 'danger' | 'warning' | 'success' | 'neutral' | 'info'
export interface StatusLabel {
  readonly tone: Tone
  readonly icon: IconName
  readonly text: string
}

export const PRIORITY: Record<Priority, StatusLabel> = {
  high: { tone: 'danger', icon: 'flag', text: 'Vysoká' },
  medium: { tone: 'warning', icon: 'flag', text: 'Střední' },
  low: { tone: 'neutral', icon: 'flag', text: 'Nízká' },
}

export const ageText = (age: number | null) => age === null ? 'věk neuveden' : `${age} let`
export const diagnosisText = (diagnosis: Diagnosis | null) => diagnosis ? `${diagnosis.code} · ${diagnosis.label}` : 'diagnóza neuvedena'
export const unknownPriority: StatusLabel = { tone: 'neutral', icon: 'help', text: 'Priorita neuvedena' }
export function acknowledgementLabel(step: NextStep | null): StatusLabel {
  if (!step) return { tone: 'neutral', icon: 'help', text: 'Převzetí neuvedeno' }
  switch (step.acknowledgement) {
    case 'pending': return { tone: 'danger', icon: 'missing', text: step.pendingLabel ?? 'Nepřevzato' }
    case 'accepted': return { tone: 'success', icon: 'check', text: step.acceptedAt ? `Převzato ${formatDayMonth(step.acceptedAt)}` : 'Převzato' }
    case 'awaiting-information': return { tone: 'warning', icon: 'clock', text: 'Čeká na doplnění' }
    case 'new': return { tone: 'info', icon: 'info', text: 'Nový' }
  }
}

export function documentLabel(state: DocumentState, stateLabel: string): StatusLabel {
  switch (state) {
    case 'available': return { tone: 'success', icon: 'check', text: stateLabel }
    case 'missing': return { tone: 'danger', icon: 'missing', text: stateLabel }
    case 'uncertain': return { tone: 'warning', icon: 'alert', text: stateLabel }
  }
}

export function sourceFieldLabel(field: SourceField): StatusLabel {
  switch (field.status) {
    case 'literal': return { tone: 'success', icon: 'check', text: field.statusLabel }
    case 'uncertain': return { tone: 'warning', icon: 'alert', text: field.statusLabel }
    case 'awaiting': return { tone: 'warning', icon: 'clock', text: field.statusLabel }
    case 'absent': return { tone: 'danger', icon: 'missing', text: field.statusLabel }
  }
}

export const REVIEWED_LOCAL: StatusLabel = { tone: 'info', icon: 'eye', text: 'Zkontrolováno (lokálně v demu)' }

export const PROGRESS_ICON: Record<ProgressState, IconName> = { done: 'check', now: 'clock', later: 'later' }

export function ownerText(step: NextStep | null): string {
  if (!step) return 'vlastník neuveden'
  return step.owner.name ? `${step.owner.organization} · ${step.owner.name}` : step.owner.organization
}
