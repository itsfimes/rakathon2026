import type { ReactNode } from 'react'
import type { ClinicalFact, ClinicalSource, ClinicalTime, SourceRef } from '../../../data/clinical'
import { Tag } from '../../../components/ui/Tag'
import { ScopedDisclosure } from '../ScopedDisclosure'
import { clinicalFactState, clinicalTimeText, factStatusLabels } from './clinicalText'
import { SourceRecord } from './SourceRecord'
import { SourceDialog } from './SourceDialog'
import { SOURCE_KIND_LABEL } from '../../../data/sourceText'

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

/** Exact supplied source versions; the effective-time line is shown only when no structured source already states its own date. */
export function SourceList({ fact, sources, effectiveLabel }: { readonly fact: ClinicalFact<unknown>; readonly sources: readonly ClinicalSource[]; readonly effectiveLabel: string }) {
  const resolved = fact.sources.map(ref => findSource(sources, ref))
  const datedBySource = resolved.every(matches => matches.length === 1 && matches[0]!.summary?.clinicalTime && matches[0]!.summary.clinicalTime.kind !== 'unknown')
  return <>
    {!datedBySource && <p className="meta">{effectiveLabel}: {clinicalTimeText(fact.effective)}. Datum vydání ani dostupnosti není datum klinické události.</p>}
    <ul className="source-list">
      {fact.sources.map((ref, index) => {
        const matches = resolved[index]!
        const source = matches.length === 1 ? matches[0] : undefined
        return (
          <li key={refText(ref)}>
            {source ? <SourceRecord source={source} refText={refText(ref)} showIdentity />
              : <p className="placeholder-text">{refText(ref)}: {matches.length > 1 ? 'zdroj není jednoznačný' : 'zdroj v záznamu nenalezen'}</p>}
          </li>
        )
      })}
    </ul>
  </>
}

/** On-demand inspection of the exact supplied source versions. Inside tables use `dialog` so the row never grows. */
export function SourceInspect({ fact, sources, effectiveLabel = 'Týká se doby', presentation = 'inline', compactFor }: {
  readonly fact: ClinicalFact<unknown>
  readonly sources: readonly ClinicalSource[]
  readonly effectiveLabel?: string
  readonly presentation?: 'inline' | 'dialog'
  /** Dense tables: visible trigger shortens to "Zdroj"; the accessible name keeps the full wording plus this row name. */
  readonly compactFor?: string | undefined
}) {
  if (fact.sources.length === 0) return <p className="fact__meta">Zdroj není uveden.</p>
  const only = fact.sources.length === 1 ? findSource(sources, fact.sources[0]!) : []
  const kind = only.length === 1 ? only[0]!.summary?.kind : undefined
  const summary = kind ? `Zdrojový záznam: ${SOURCE_KIND_LABEL[kind].toLowerCase()}` : fact.sources.length === 1 ? 'Zdrojový záznam' : `Zdrojové záznamy (${fact.sources.length})`
  const body = <SourceList fact={fact} sources={sources} effectiveLabel={effectiveLabel} />
  const title = only.length === 1 ? only[0]!.label : summary
  if (presentation === 'dialog') return compactFor === undefined
    ? <SourceDialog summary={summary} title={title}>{body}</SourceDialog>
    : <SourceDialog summary="Zdroj" label={`Zdroj – ${compactFor} (${summary})`} title={title}>{body}</SourceDialog>
  return <ScopedDisclosure icon="file" summary={summary}>{body}</ScopedDisclosure>
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
  /** Inside FactGroups: time sits in the group header, source becomes a compact "Zdroj" button in the head. */
  readonly grouped?: boolean
  readonly children?: ReactNode
}

/** One supplied fact: title + visible status words, readable value, one quiet time line, sources on demand. */
export function FactBlock({ fact, sources, title, kicker, time, timeLabel = 'Týká se doby', showTime = true, grouped = false, children }: FactBlockProps) {
  return (
    <article className="fact">
      <div className="fact__head">
        <h4 className="fact__title">{kicker && <span className="fact__kind">{kicker}</span>}{title}</h4>
        <FactTags fact={fact} />
        {grouped && <SourceInspect fact={fact} sources={sources} presentation="dialog" compactFor={typeof title === 'string' ? title : kicker ?? 'záznam'} />}
      </div>
      {children && <div className="fact__body">{children}</div>}
      {showTime && !grouped && <p className="fact__meta">{timeLabel}: {clinicalTimeText(time ?? fact.effective)}</p>}
      {!grouped && <SourceInspect fact={fact} sources={sources} />}
    </article>
  )
}
