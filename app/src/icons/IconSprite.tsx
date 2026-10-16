import { ICON_PATHS } from './paths'
import type { IconName } from './paths'

/** Hidden SVG sprite rendered once by the shell; <Icon> references its symbols. */
export function IconSprite() {
  return (
    <svg width="0" height="0" className="visually-hidden" aria-hidden="true" focusable="false">
      {(Object.keys(ICON_PATHS) as IconName[]).map(name => (
        <symbol key={name} id={`i-${name}`} viewBox="0 0 24 24">{ICON_PATHS[name]}</symbol>
      ))}
    </svg>
  )
}
