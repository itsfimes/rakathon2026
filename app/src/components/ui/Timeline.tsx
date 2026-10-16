import { Icon } from '../../icons/Icon'
import type { IconName } from '../../icons/paths'
import type { JourneyItem } from '../../data/contracts'
import { formatDayMonth } from '../../lib/format'

const NODE_ICON: Record<JourneyItem['state'], IconName> = { done: 'check', now: 'team', later: 'later' }
const STATE_WORD: Record<JourneyItem['state'], string> = { done: 'Hotovo', now: 'Teď', later: 'Později' }

/** Vertical journey: done / now / later nodes with connectors; state is also in words. */
export function Timeline({ items, label }: { readonly items: readonly JourneyItem[]; readonly label: string }) {
  return (
    <ol className="timeline" aria-label={label}>
      {items.map(item => (
        <li key={item.id} className={`is-${item.state}`} aria-current={item.state === 'now' && !item.historical ? 'step' : undefined}>
          <span className="node"><Icon name={NODE_ICON[item.state]} /></span>
          <span className="timeline__text">
            <b>{item.date ? `${formatDayMonth(item.date)} · ${item.title}` : item.title}</b>
            <span className="meta">{item.note ?? STATE_WORD[item.state]}</span>
          </span>
        </li>
      ))}
    </ol>
  )
}
