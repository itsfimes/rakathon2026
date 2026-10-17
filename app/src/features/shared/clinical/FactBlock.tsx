import type { ReactNode } from 'react'
import type { ClinicalFact, ClinicalSource, ClinicalTime, SourceRef } from '../../../data/clinical'
import { Tag } from '../../../components/ui/Tag'
import { ScopedDisclosure } from '../ScopedDisclosure'
import { clinicalFactState, clinicalTimeText, factStatusLabels } from './clinicalText'

/** Label/value list that renders only supplied values; explicit "neuvedeno" is the caller's choice. */
export function Fields({ items }: { readonly items: readonly (readonly [string, ReactNode | undefined])[] }) {
  const shown = items.filter(([, value]) => value !== undefined && value !== null && value !== '')
  if (shown.length === 0) return null
  return (
    <dl className="fields">
      {shown.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
  )
}

/** Status words for one fact: conflict, denial, unknown, verification. Always visible, never behind the source disclosure. */
export function FactTags({ fact }: { readonly fact: ClinicalFact<unknown> }) {
  const labels = factStatusLabels(clinicalFactState(fact))
  if (labels.length === 0) return null
  return <span className="fact__tags">{labels.map(label => <Tag key={label.text} label={label} />)}</span>
}

const refText = (ref: SourceRef) => `${ref.sourceId} · verze ${ref.version}`
const findSource = (sources: readonly ClinicalSource[], ref: SourceRef) =>
  sources.filter(source => source.ref.sourceId === ref.sourceId && source.ref.version === ref.version)

/** On-demand inspection of the exact supplied source versions and their three distinct times. */
export function SourceInspect({ fact, sources, effectiveLabel = 'Týká se doby' }: {
  readonly fact: ClinicalFact<unknown>
  readonly sources: readonly ClinicalSource[]
  readonly effectiveLabel?: string
}) {
  if (fact.sources.length === 0) return <p className="fact__meta">Zdroj není uveden.</p>
  return (
    <ScopedDisclosure icon="file" summary={`Zdroj a časy (${fact.sources.length})`}>
      <p className="meta">{effectiveLabel}: {clinicalTimeText(fact.effective)}. Datum vydání ani dostupnosti není datum klinické události.</p>
      <ul className="source-list">
        {fact.sources.map(ref => {
          const matches = findSource(sources, ref)
          const source = matches.length === 1 ? matches[0] : undefined
          return (
            <li key={refText(ref)}>
              {source ? (
                <>
                  <p className="source-list__label">{source.label}</p>
                  <Fields items={[
                    ['Označení zdroje', refText(ref)],
                    ['Vydáno', clinicalTimeText(source.issued)],
                    ['Místně k dispozici', clinicalTimeText(source.locallyAvailable)],
                    ['Kontrola zdroje', source.review === 'reviewed' ? 'zkontrolováno' : source.review === 'unreviewed' ? 'zatím nezkontrolováno' : undefined],
                  ]} />
                </>
              ) : <p className="placeholder-text">{refText(ref)}: {matches.length > 1 ? 'zdroj není jednoznačný' : 'zdroj v záznamu nenalezen'}</p>}
            </li>
          )
        })}
      </ul>
    </ScopedDisclosure>
  )
}

interface FactBlockProps {
  readonly fact: ClinicalFact<unknown>
  readonly sources: readonly ClinicalSource[]
  readonly title: ReactNode
  readonly kicker?: string | undefined
  readonly time?: ClinicalTime
  readonly timeLabel?: string
  /** False when the caller already shows the time in its own leading line (avoids a duplicate date). */
  readonly showTime?: boolean
  readonly children?: ReactNode
}

/** One supplied fact: title + visible status words, readable value, one quiet time line, sources on demand. */
export function FactBlock({ fact, sources, title, kicker, time, timeLabel = 'Týká se doby', showTime = true, children }: FactBlockProps) {
  return (
    <article className="fact">
      <div className="fact__head">
        <h4 className="fact__title">{kicker && <span className="fact__kind">{kicker}</span>}{title}</h4>
        <FactTags fact={fact} />
      </div>
      {children && <div className="fact__body">{children}</div>}
      {showTime && <p className="fact__meta">{timeLabel}: {clinicalTimeText(time ?? fact.effective)}</p>}
      <SourceInspect fact={fact} sources={sources} />
    </article>
  )
}
