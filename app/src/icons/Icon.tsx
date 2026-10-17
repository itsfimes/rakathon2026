import { ICON_PATHS } from './paths'
import type { IconName } from './paths'

interface IconProps {
  readonly name: IconName
  readonly small?: boolean
}

/** Decorative line icon; always placed next to a visible word. */
export function Icon({ name, small = false }: IconProps) {
  return (
    <svg className={small ? 'icon icon--sm' : 'icon'} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      {ICON_PATHS[name]}
    </svg>
  )
}
