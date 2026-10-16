import { Icon } from '../../icons/Icon'
import type { IconName } from '../../icons/paths'

export interface SegmentLink {
  readonly id: string
  readonly href: string
  readonly label: string
  readonly icon: IconName
}

interface SegmentedLinksProps {
  readonly items: readonly SegmentLink[]
  readonly current: string
  /** Plain primary clicks go here; modified clicks (new tab, copy) keep the native href. */
  readonly onActivate?: (id: string) => void
}

/** Navigation variant: links; the current one carries aria-current="page". */
export function SegmentedLinks({ items, current, onActivate }: SegmentedLinksProps) {
  return (
    <div className="segmented">
      {items.map(item => (
        <a key={item.id} className="segmented__item" href={item.href} aria-current={item.id === current ? 'page' : undefined}
          onClick={event => {
            if (!onActivate || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
            event.preventDefault()
            onActivate(item.id)
          }}>
          <Icon name={item.icon} />{item.label}
        </a>
      ))}
    </div>
  )
}

interface SegmentedRadiosProps<T extends string> {
  readonly name: string
  readonly legend: string
  readonly options: readonly { readonly value: T; readonly label: string }[]
  readonly value: T
  readonly onChange: (value: T) => void
}

/** Choice variant: native radios styled as segments. */
export function SegmentedRadios<T extends string>({ name, legend, options, value, onChange }: SegmentedRadiosProps<T>) {
  return (
    <fieldset className="segmented">
      <legend className="visually-hidden">{legend}</legend>
      {options.map(option => (
        <label key={option.value}>
          <input type="radio" name={name} value={option.value} checked={option.value === value} onChange={() => onChange(option.value)} />
          <span className="segmented__item">{option.label}</span>
        </label>
      ))}
    </fieldset>
  )
}
