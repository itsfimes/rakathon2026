import type { ClinicalTime, ReportMetadata } from '../../../data/clinical'
import { ScopedDisclosure } from '../ScopedDisclosure'
import { clinicalTimeText } from './clinicalText'

/** Leading line under a report title: readable date first, then the source's literal status and category.
    These are document properties, not findings; English source terms stay as supplied. */
export function ReportLine({ date, meta, withDate = true }: { readonly date: ClinicalTime; readonly meta: ReportMetadata | undefined; readonly withDate?: boolean }) {
  const parts = [
    withDate && `Datum vyšetření: ${clinicalTimeText(date)}`,
    meta?.status && `Stav ve zdroji: ${meta.status}`,
    meta?.documentStatus && `Stav dokumentu: ${meta.documentStatus}`,
    meta?.category && `Kategorie: ${meta.category}`,
    meta?.periodEnd && `Konec období: ${clinicalTimeText(meta.periodEnd)}`,
    meta?.authors?.length && `Autor: ${meta.authors.join(', ')}`,
  ].filter((part): part is string => typeof part === 'string')
  if (parts.length === 0) return null
  return (
    <p className="report-line">
      {parts.map(part => <span key={part}>{part}</span>)}
    </p>
  )
}

/** Listed result names and attachments, closed by default. Names only: no values or normality are implied. */
export function ReportItems({ meta }: { readonly meta: ReportMetadata | undefined }) {
  const items = meta?.items ?? []
  const attachments = meta?.attachments ?? []
  const count = items.length + attachments.length
  return (
    <>
      {count > 0 && (
        <ScopedDisclosure icon="file" summary={`Položky a přílohy zprávy (${count})`}>
          {items.length > 0 && <>
            <p className="meta">Názvy položek uvedené ve zprávě. Hodnoty zde nejsou.</p>
            <ul className="plain-list">{items.map((item, index) => <li key={index}>{item}</li>)}</ul>
          </>}
          {attachments.length > 0 && <>
            <p className="meta">Přílohy</p>
            <ul className="plain-list">{attachments.map((item, index) => (
              <li key={index}>{[item.title ?? 'Příloha bez názvu', item.contentType, item.format, item.created && `vytvořeno ${clinicalTimeText(item.created)}`].filter(Boolean).join(' · ')}</li>
            ))}</ul>
          </>}
        </ScopedDisclosure>
      )}
      {meta?.contentSupplied === false && <p className="fact__meta">Obsah přílohy nebyl zdrojem dodán.</p>}
    </>
  )
}
