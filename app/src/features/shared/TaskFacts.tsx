import { Facts } from '../../components/ui/Facts'
import type { Fact } from '../../components/ui/Facts'
import { Tag } from '../../components/ui/Tag'
import type { NextStep } from '../../data/contracts'
import { formatDate, formatDayMonth } from '../../lib/format'
import { acknowledgementLabel, ownerText } from '../../lib/labels'

/** Owner / deadline / acknowledgement rows of a task. */
export function TaskFacts({ step, withOwnerName = true, withAcknowledgement = true, inline = false }: { readonly step: NextStep; readonly withOwnerName?: boolean; readonly withAcknowledgement?: boolean; readonly inline?: boolean }) {
  const items: Fact[] = [
    { key: 'owner', icon: 'person', label: 'Vlastník', value: withOwnerName ? ownerText(step) : step.owner.organization },
    { key: 'due', icon: 'calendar', label: 'Termín', value: formatDate(step.dueAt) },
  ]
  if (withAcknowledgement) {
    items.push({
      key: 'ack', icon: acknowledgementLabel(step).icon, label: 'Převzetí',
      value: <><Tag label={acknowledgementLabel(step)} />{step.acknowledgement === 'pending' ? ` odesláno ${formatDayMonth(step.requestedAt)}` : ''}</>,
    })
  }
  return <Facts items={items} inline={inline} />
}
