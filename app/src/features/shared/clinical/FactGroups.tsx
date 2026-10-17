import type { ReactNode } from 'react'
import type { ClinicalFact } from '../../../data/clinical'
import { clinicalTimeText } from './clinicalText'
import { FoldToggle } from './GroupedTable'
import { ENTRIES, groupInOrder, useFolded } from './grouping'

/** Facts sharing one time line are listed under it once (source order kept); long lists fold behind one explicit toggle.
    Render each fact with FactBlock `grouped` so its own time line is not repeated. */
export function FactGroups<T>({ facts, timeLine, limit = 4, budget = 6, render }: {
  readonly facts: readonly ClinicalFact<T>[]
  /** Exact time sentence for a fact, e.g. "Týká se doby: 18. 10. 2026". */
  readonly timeLine?: (fact: ClinicalFact<T>) => string
  readonly limit?: number
  /** Approximate card budget before folding (whole groups only). */
  readonly budget?: number
  readonly render: (fact: ClinicalFact<T>) => ReactNode
}) {
  const line = timeLine ?? (fact => `Týká se doby: ${clinicalTimeText(fact.effective)}`)
  const folded = useFolded(groupInOrder(facts, line), limit, budget)
  return <>
    {folded.shown.map(group => (
      <section key={group.key} className="entry-group">
        <p className="entry-group__head">{group.key}</p>
        <div className="fact-list">{group.items.map(render)}</div>
      </section>
    ))}
    <FoldToggle fold={{ unit: 'skupiny', items: ENTRIES }} expanded={folded.expanded} hiddenGroups={folded.hiddenGroups} hiddenItems={folded.hiddenItems} onToggle={folded.toggle} />
  </>
}
