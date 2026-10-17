import type { ClinicalSource, SourceSummary, SourceSummaryValue } from '../../../data/clinical'
import { SOURCE_KIND_LABEL, sourceStatusText } from '../../../data/sourceText'
import { Fields } from './FactBlock'
import { clinicalTimeText } from './clinicalText'

const EVENT_LABEL: Readonly<Record<SourceSummary['kind'], string>> = {
  laboratory: 'Odebráno / zjištěno', measurement: 'Změřeno', condition: 'Začátek dle záznamu', report: 'Vyšetření provedeno', document: 'Týká se doby', patient: 'Týká se doby',
}
const valueText = (v: SourceSummaryValue) => `${v.value}${v.unit ? ` ${v.unit}` : ''}`

/** What the record holds: values (all components), status and the clinical date. */
function Contents({ summary }: { readonly summary: SourceSummary }) {
  const values = summary.values ?? []
  const single = values.length === 1 && (values[0]!.label === summary.title || values[0]!.label === 'Hodnota')
  return <>
    {single ? <p className="source-record__value">{valueText(values[0]!)}</p>
      : values.length > 0 && <Fields items={values.map(v => [v.label, valueText(v)] as const)} />}
    <Fields items={[
      ['Stav záznamu', summary.status ? sourceStatusText(summary.status) : undefined],
      ['Klinický stav', summary.clinicalStatus],
      [EVENT_LABEL[summary.kind], summary.clinicalTime && summary.clinicalTime.kind !== 'unknown' ? clinicalTimeText(summary.clinicalTime) : undefined],
      ['Zapsáno do záznamu', summary.recorded ? clinicalTimeText(summary.recorded) : undefined],
      ['Počet výsledků ve zprávě', summary.resultCount],
    ]} />
  </>
}

/** One resolved source version: readable content first, record-keeping times and identity second. */
export function SourceRecord({ source, refText, showIdentity }: { readonly source: ClinicalSource; readonly refText: string; readonly showIdentity: boolean }) {
  const summary = source.summary
  const structured = summary && summary.kind !== 'document'
  return <>
    <p className="source-list__label">
      {summary ? <><span className="source-record__kind">{SOURCE_KIND_LABEL[summary.kind]}</span>{summary.title ?? 'Bez uvedeného názvu'}</> : source.label}
    </p>
    {structured && <p className="meta">Údaje ze strukturovaného zdrojového záznamu.</p>}
    {summary && <Contents summary={summary} />}
    <div className="source-record__keeping">
      <Fields items={[
        ['Vydáno ve zdroji', clinicalTimeText(source.issued)],
        ['Zpřístupněno', source.locallyAvailable.kind === 'unknown' ? 'Datum zpřístupnění není uvedeno' : clinicalTimeText(source.locallyAvailable)],
        ['Kontrola zdroje', source.review === 'reviewed' ? 'zkontrolováno' : source.review === 'unreviewed' ? 'zatím nezkontrolováno' : undefined],
        ['Označení záznamu', showIdentity ? refText : undefined],
      ]} />
    </div>
  </>
}
