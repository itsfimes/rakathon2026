import { Icon } from '../../icons/Icon'
import type { StatusLabel } from '../../lib/labels'

/** Rectangular status label: icon + word, never colour alone. */
export function Tag({ label }: { readonly label: StatusLabel }) {
  return <span className={`tag tag--${label.tone}`}><Icon name={label.icon} />{label.text}</span>
}
