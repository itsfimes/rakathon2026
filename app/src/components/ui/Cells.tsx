import type { CSSProperties } from 'react'
import type { DocumentState } from '../../data/contracts'

const CLASS: Record<DocumentState, string> = { available: 'ok', uncertain: 'unsure', missing: 'missing' }

/** One cell per required document; decorative, the checklist next to it carries the words. */
export function Cells({ states }: { readonly states: readonly DocumentState[] }) {
  const style = { '--cells-count': String(Math.max(states.length, 1)) } as CSSProperties
  return (
    <ol className="cells" aria-hidden="true" style={style}>
      {states.map((state, index) => <li key={index} className={CLASS[state]} />)}
    </ol>
  )
}
