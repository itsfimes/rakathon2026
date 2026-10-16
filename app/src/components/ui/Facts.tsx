import type { ReactNode } from 'react'
import { Icon } from '../../icons/Icon'
import type { IconName } from '../../icons/paths'

export interface Fact {
  readonly key: string
  readonly icon: IconName
  readonly label: string
  readonly value: ReactNode
  readonly placeholder?: boolean
}

/** Icon / label / value rows; `inline` lays them out side by side without the outer box. */
export function Facts({ items, inline = false }: { readonly items: readonly Fact[]; readonly inline?: boolean }) {
  return (
    <dl className={inline ? 'facts facts--inline' : 'facts'}>
      {items.map(item => (
        <div key={item.key}>
          <Icon name={item.icon} />
          <dt>{item.label}</dt>
          <dd className={item.placeholder ? 'placeholder-text' : undefined}>{item.value}</dd>
        </div>
      ))}
    </dl>
  )
}
