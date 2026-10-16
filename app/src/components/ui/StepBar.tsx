import { Icon } from '../../icons/Icon'
import type { Phase } from '../../data/contracts'
import { formatDayMonth, formatDays } from '../../lib/format'
import { PROGRESS_ICON } from '../../lib/labels'

function heading(phase: Phase): string {
  if (phase.days === undefined || phase.state === 'later') return phase.id
  return phase.state === 'done' ? `${phase.id} · ${formatDays(phase.days)}` : `${phase.id} · den ${phase.days}`
}

function detail(phase: Phase): string {
  if (phase.state === 'later') return 'zatím nezačalo'
  if (phase.state === 'now') return phase.startedAt ? `od ${formatDayMonth(phase.startedAt)} · běží` : 'běží'
  const range = [phase.startedAt, phase.endedAt].filter((value): value is string => Boolean(value)).map(formatDayMonth).join('–')
  return range ? `${range} · hotovo` : 'hotovo'
}

/** Labelled T1–T3 segments; the current one is marked by fill, rule and word. */
export function StepBar({ phases, label }: { readonly phases: readonly Phase[]; readonly label: string }) {
  return (
    <ol className="stepbar" aria-label={label}>
      {phases.map(phase => (
        <li key={phase.id} className={phase.state === 'later' ? undefined : `is-${phase.state}`} aria-current={phase.state === 'now' ? 'step' : undefined}>
          <b><Icon name={PROGRESS_ICON[phase.state]} small />{heading(phase)}</b>
          {phase.label}<br />{detail(phase)}
        </li>
      ))}
    </ol>
  )
}

/** Compact three-cell phase indicator for table rows (decorative; text sits next to it). */
export function MiniSteps({ phase }: { readonly phase: Phase['id'] }) {
  const index = ['T1', 'T2', 'T3'].indexOf(phase)
  return (
    <span className="mini-steps" aria-hidden="true">
      {[0, 1, 2].map(cell => <span key={cell} className={cell < index ? 'is-done' : cell === index ? 'is-now' : undefined} />)}
    </span>
  )
}
