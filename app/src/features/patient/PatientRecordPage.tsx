import type { ReactNode } from 'react'
import { Notice } from '../../components/ui/Notice'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { Tag } from '../../components/ui/Tag'
import type { PatientMeasurement, PatientMedication, PatientRecord, PatientRecordEntry, PatientResult } from '../../data/patientRecord'
import type { StatusLabel } from '../../lib/labels'
import { Fields } from '../shared/clinical/FactBlock'
import { clinicalTimeText, HISTORY_CATEGORY, SUSCEPTIBILITY } from '../shared/clinical/clinicalText'
import { FoldToggle, GroupedTable, Missing } from '../shared/clinical/GroupedTable'
import { ENTRIES, groupInOrder, labTimes, MEASUREMENT_COLUMNS, measurementSessions, SESSION_FOLD, SESSION_LIMIT, sharedValue, useFolded, VALUES } from '../shared/clinical/grouping'
import type { Column } from '../shared/clinical/grouping'
import { MeasurementCells } from '../shared/clinical/MeasurementTable'
import { CoverageNotice } from '../shared/clinical/CoverageNotice'

/** Plain-language state words for the patient; no internal review, conflict IDs or source references. */
function patientLabels(entry: PatientRecordEntry<unknown>): readonly StatusLabel[] {
  const labels: StatusLabel[] = []
  if (entry.conflict === 'unresolved') labels.push({ tone: 'warning', icon: 'alert', text: 'Záznamy se liší, zatím nevyjasněno' })
  if (entry.presence === 'denied') labels.push({ tone: 'neutral', icon: 'missing', text: 'Ve zprávě popřeno' })
  if (entry.knowledge === 'unknown') labels.push({ tone: 'warning', icon: 'help', text: 'Není známo' })
  if (entry.knowledge === 'not-recorded') labels.push({ tone: 'warning', icon: 'missing', text: 'Nezaznamenáno' })
  if (entry.verification === 'suspected') labels.push({ tone: 'warning', icon: 'help', text: 'Zatím jen podezření' })
  if (entry.verification === 'preliminary') labels.push({ tone: 'warning', icon: 'clock', text: 'Předběžný údaj' })
  if (entry.verification === 'confirmed') labels.push({ tone: 'success', icon: 'check', text: 'Potvrzeno ve zprávě' })
  return labels
}

function EntryTags({ entry }: { readonly entry: PatientRecordEntry<unknown> }) {
  const labels = patientLabels(entry)
  return labels.length ? <span className="fact__tags">{labels.map(label => <Tag key={label.text} label={label} />)}</span> : null
}

const sourceText = (entry: PatientRecordEntry<unknown>) => entry.sourceStatus === 'resolved' && entry.sources.length > 0
  ? entry.sources.map(source => `${source.label}, vydáno ${clinicalTimeText(source.issued)}`).join('; ')
  : 'zdroj nelze určit'

function Entry({ entry, title, children }: { readonly entry: PatientRecordEntry<unknown>; readonly title: ReactNode; readonly children?: ReactNode }) {
  return (
    <article className="fact">
      <div className="fact__head"><h3 className="fact__title">{title}</h3><EntryTags entry={entry} /></div>
      {children && <div className="fact__body">{children}</div>}
    </article>
  )
}

/** Entries sharing date and source are listed under ONE line "Kdy · Zdroj" instead of repeating it per entry (source order kept).
    Long lists fold after a few groups behind one explicit toggle. */
function EntryGroups<T>({ entries, timeLabel = 'Kdy', limit = 4, budget = 6, render }: {
  readonly entries: readonly PatientRecordEntry<T>[]
  readonly timeLabel?: string
  readonly limit?: number
  readonly budget?: number
  readonly render: (entry: PatientRecordEntry<T>, index: number) => ReactNode
}) {
  const groups = groupInOrder(entries, entry => `${timeLabel}: ${clinicalTimeText(entry.effective)} · Zdroj: ${sourceText(entry)}`)
  const folded = useFolded(groups, limit, budget)
  return <>
    {folded.shown.map(group => (
      <section key={group.key} className="entry-group">
        <p className="entry-group__head">{group.key}</p>
        <div className="fact-list">{group.items.map(entry => render(entry, entries.indexOf(entry)))}</div>
      </section>
    ))}
    <FoldToggle fold={{ unit: 'skupiny', items: ENTRIES }} expanded={folded.expanded} hiddenGroups={folded.hiddenGroups} hiddenItems={folded.hiddenItems} onToggle={folded.toggle} />
  </>
}

const RESULT_COLUMNS: readonly Column[] = [{ label: 'Vyšetření' }, { label: 'Výsledek', numeric: true }, { label: 'Jednotka' }, { label: 'Rozmezí podle zprávy' }, { label: 'Označení ve zprávě' }]

/** Results grouped by sample date, result date and source; those lines appear once per group instead of four lines per row. */
function ResultsTable({ results }: { readonly results: readonly PatientRecordEntry<PatientResult>[] }) {
  const groups = groupInOrder(results, entry => JSON.stringify([...labTimes(entry.value, entry.effective), sourceText(entry)])).map(group => {
    const first = group.items[0]!
    const [title, ...times] = labTimes(first.value, first.effective)
    const note = sharedValue(group.items, entry => entry.value.suppliedNote)
    return { key: group.key, items: group.items, title, meta: [...times, `Zdroj: ${sourceText(first)}`, ...note ? [note] : []] }
  })
  return <GroupedTable labelledBy="t-pr-results" caption="„—“ = ve zprávě neuvedeno." columns={RESULT_COLUMNS} groups={groups} fold={{ unit: 'skupiny', items: VALUES }}
    row={(entry, group) => {
      const v = entry.value
      const cultureOnly = v.culture && v.value === undefined
      return (
        <tr key={results.indexOf(entry)} className="lab-table__row">
          <th scope="row" className="lab-table__test">
            <span className="lab-table__name">{v.test}</span><EntryTags entry={entry} />
            {!sharedValue(group.items, item => item.value.suppliedNote) && v.suppliedNote && <span className="sub">{v.suppliedNote}</span>}
            {v.culture && <div className="culture"><p>{v.culture.organism}{v.culture.quantity ? ` · ${v.culture.quantity}` : ''}</p>
              <ul className="plain-list">{v.culture.susceptibility.map(item => <li key={item.agent}>{item.agent}: {SUSCEPTIBILITY[item.result] ?? item.result}</li>)}</ul></div>}
            {v.sediment && <span className="sub">Sediment: {v.sediment}</span>}
          </th>
          <td className="lab-table__num lab-table__value">{cultureOnly ? <span className="sub">viz kultivace</span> : v.value !== undefined ? <span className="num">{v.value}</span> : <Missing />}</td>
          <td className="lab-table__unit">{v.unit ?? (cultureOnly ? null : <Missing />)}</td>
          <td className="lab-table__range" data-label="Rozmezí"><span className="num">{v.referenceRange ?? <Missing />}</span></td>
          <td className="lab-table__flag" data-label="Označení">{v.abnormalFlag && FLAG[v.abnormalFlag] ? FLAG[v.abnormalFlag] : <Missing />}</td>
        </tr>
      )
    }} />
}

const REPORT_TYPE: Record<string, string> = {
  suspicion: 'Původní podezření', histology: 'Výsledek rozboru tkáně (histologie)', 'specialist-conclusion': 'Závěr odborníka',
}
const FLAG: Record<string, string> = {
  high: 'Zpráva uvádí: nad rozmezím', low: 'Zpráva uvádí: pod rozmezím', abnormal: 'Zpráva uvádí: odchylka', normal: 'Zpráva uvádí: v rozmezí',
}
const STATEMENT: Record<PatientMedication['statement'], string> = {
  'reported-taking': 'Uvedl(a) jste, že užíváte', recommended: 'Doporučení ve zprávě', 'periprocedure-instruction': 'Pokyn ke zákroku ve zprávě',
  'completed-course': 'Ukončená léčba', interaction: 'Zaznamenaná souhra léků',
}

/** Boolean answers stay distinct: false is a recorded "ne", missing is not shown at all. */
const yesNo = (value: boolean | undefined) => value === undefined ? undefined : value ? 'ano (dle zprávy)' : 'ne (dle zprávy)'

function Empty({ text }: { readonly text: string }) {
  return <p className="placeholder-text">{text}</p>
}

/** Same session table as the clinical record; the patient source line is shared per session, so it sits in the header. */
function MeasurementsTable({ entries }: { readonly entries: readonly PatientRecordEntry<PatientMeasurement>[] }) {
  const groups = measurementSessions(entries, entry => entry.value, entry => entry.effective, rows => {
    const source = sharedValue(rows, sourceText) ?? (rows.length === 1 ? sourceText(rows[0]!) : undefined)
    return source ? [`Zdroj: ${source}`] : []
  })
  const shared = new Map(groups.map(group => [group.key, group]))
  return <GroupedTable labelledBy="t-pr-measurements" caption={`Sezení měření v pořadí zpráv (${groups.length}). „—“ = ve zprávě neuvedeno.`} columns={MEASUREMENT_COLUMNS.slice(0, 3)}
    groups={groups} limit={SESSION_LIMIT} fold={SESSION_FOLD}
    row={(entry, group) => {
      const own = shared.get(group.key)!
      const perRow = own.meta.some(line => typeof line === 'string' && line.startsWith('Zdroj: ')) ? null : <span className="sub">Zdroj: {sourceText(entry)}</span>
      return (
        <tr key={entries.indexOf(entry)} className="lab-table__row">
          <MeasurementCells v={entry.value} shared={own.shared} tags={<><EntryTags entry={entry} />{perRow}</>} source={() => null} />
        </tr>
      )
    }} />
}

function MedicationEntry({ entry }: { readonly entry: PatientRecordEntry<PatientMedication> }) {
  const v = entry.value
  return (
    <Entry entry={entry} title={<><span className="fact__kind">{STATEMENT[v.statement]}</span>{v.name}</>}>
      <Fields items={[
        ['Síla', v.strength], ['Dávka', v.dose], ['Jak často', v.frequency], ['Důvod uvedený ve zprávě', v.suppliedIndication],
        ['Text pokynu ve zprávě', v.instruction], ['Navržená změna ve zprávě', v.recommendedChange], ['Souhra léků', v.interaction],
        ['Vysadit (dle zprávy)', v.stopAt && clinicalTimeText(v.stopAt)], ['Znovu nasadit (dle zprávy)', v.restartAt && clinicalTimeText(v.restartAt)],
        ['Začátek', v.courseStart && clinicalTimeText(v.courseStart)], ['Konec', v.courseEnd && clinicalTimeText(v.courseEnd)],
      ]} />
    </Entry>
  )
}

/** "Moje zdravotní údaje": consumes ONLY the explicit PatientRecord DTO. Values are shown as written in the source. */
export function PatientRecordPage({ record }: { readonly record: PatientRecord }) {
  const taking = record.medications.filter(entry => entry.value.statement === 'reported-taking' || entry.value.statement === 'completed-course')
  const advice = record.medications.filter(entry => !taking.includes(entry))
  const differs = record.medications.some(entry => entry.conflict === 'unresolved')
  return (
    <div className="patient-record">
      <CoverageNotice coverage={record.coverage} detail={record.collectionCoverage} />
      <Notice tone="info" icon="info" title="Údaje tak, jak jsou zapsané ve zprávách" role="note">
        Aplikace hodnoty nevysvětluje ani nehodnotí. Co znamenají pro vás, s vámi probere váš lékař.
        <ul className="plain-list">{record.limitations.map(item => <li key={item}>{item}</li>)}</ul>
        {record.omittedCount > 0 && <p>{record.omittedCount} {record.omittedCount === 1 ? 'položka se nevešla' : 'položek se nevešlo'} do přehledu a nejsou zobrazeny.</p>}
      </Notice>
      <div className="patient-record__main">
        <Panel id="t-pr-results" icon="file" title="Výsledky vyšetření" meta="Hodnota, jednotka a rozmezí přesně podle zprávy.">
          {record.results.length === 0 ? <PanelBody><Empty text={record.coverage?.observations === 'unavailable' ? 'Výsledky nejsou dostupné — zdroj pozorování se nepodařilo načíst.' : 'Žádné výsledky zatím nejsou k dispozici.'} /></PanelBody> : (
            <ResultsTable results={record.results} />
          )}
        </Panel>
        <Panel id="t-pr-reports" icon="file" title="Zprávy z vyšetření">
          <PanelBody>
            {record.reports.length === 0 && <Empty text={record.coverage?.diagnosticReports === 'unavailable' || record.coverage?.documents === 'unavailable' ? 'Zdroj zpráv nebo dokumentů není dostupný.' : 'Žádné zprávy zatím nejsou k dispozici.'} />}
            <EntryGroups entries={record.reports} timeLabel="Datum" render={(entry, index) => (
              <Entry key={index} entry={entry} title={REPORT_TYPE[entry.value.type] ?? entry.value.type}>
                <Fields items={[['Co zpráva uvádí', entry.value.finding], ['Závěr zprávy', entry.value.conclusion],
                  ['Datum zprávy', entry.value.date && clinicalTimeText(entry.value.date) !== clinicalTimeText(entry.effective) ? clinicalTimeText(entry.value.date) : undefined]]} />
              </Entry>
            )} />
          </PanelBody>
        </Panel>
        <Panel id="t-pr-symptoms" icon="person" title="Obtíže, které jste uvedl(a)" meta="Tak, jak jsou zapsané ve zprávách. Přibližný začátek zůstává přibližný.">
          <PanelBody>
            {record.symptoms.length === 0 ? <Empty text="Žádné obtíže nejsou zaznamenány." /> : <EntryGroups entries={record.symptoms} render={(entry, index) => {
                const v = entry.value
                return (
                  <Entry key={index} entry={entry} title={v.type}>
                    <Fields items={[
                      ['Kde', v.site], ['Jaké', v.character], ['Začátek', v.onset && clinicalTimeText(v.onset)], ['Průběh', v.course],
                      ['Horečka', yesNo(v.fever)], ['Žloutenka', yesNo(v.jaundice)], ['Tmavá moč', yesNo(v.darkUrine)], ['Chuť k jídlu', v.appetite],
                      ['Nevolnost', yesNo(v.nausea)], ['Hubnutí', v.weightLoss], ['Spánek', v.sleep], ['Běžné fungování', v.function],
                      ['Bolest na stupnici 0–10 (NRS)', v.nrs === undefined ? undefined : String(v.nrs)],
                    ]} />
                  </Entry>
                )
              }} />}
          </PanelBody>
        </Panel>
        <Panel id="t-pr-measurements" icon="calendar" title="Měření" meta="Hodnota a jednotka podle zprávy, vždy s datem měření, pokud je uvedeno.">
          {record.measurements.length === 0 ? <PanelBody><Empty text={record.coverage?.observations === 'unavailable' ? 'Měření nejsou dostupná — zdroj pozorování se nepodařilo načíst.' : 'Žádná měření nejsou zaznamenána.'} /></PanelBody>
            : <MeasurementsTable entries={record.measurements} />}
        </Panel>
      </div>
      <div className="patient-record__side">
        <Panel id="t-pr-meds" icon="file" title="Moje léky">
          <PanelBody>
            {differs && <Notice tone="warning" icon="alert" title="Některé záznamy o lécích se liší" role="note">Rozdíl je zde jen ukázán. Zatím nebyl vyjasněn.</Notice>}
            {record.medications.length === 0 && <Empty text="Žádné léky nejsou zaznamenány." />}
            {taking.length > 0 && <><h3 className="record-group__title">Co jste uvedl(a), že užíváte</h3><EntryGroups entries={taking} render={(entry, index) => <MedicationEntry key={index} entry={entry} />} /></>}
            {advice.length > 0 && <><h3 className="record-group__title">Doporučení a pokyny ve zprávách</h3><EntryGroups entries={advice} render={(entry, index) => <MedicationEntry key={index} entry={entry} />} /></>}
          </PanelBody>
        </Panel>
        <Panel id="t-pr-allergy" icon="alert" title="Alergie">
          <PanelBody>
            {record.allergies.length === 0 ? <Empty text="Údaj o alergiích není zaznamenán." /> : <EntryGroups entries={record.allergies} render={(entry, index) => <Entry key={index} entry={entry} title={entry.value.description} />} />}
          </PanelBody>
        </Panel>
        <Panel id="t-pr-history" icon="help" title="Dřívější onemocnění a operace">
          <PanelBody>
            {record.history.length === 0 ? <Empty text={record.coverage?.conditions === 'unavailable' ? 'Zdroj onemocnění není dostupný.' : 'Nic není zaznamenáno.'} /> : <EntryGroups entries={record.history} render={(entry, index) => <Entry key={index} entry={entry} title={<><span className="fact__kind">{HISTORY_CATEGORY[entry.value.category]}</span>{entry.value.description}</>} />} />}
          </PanelBody>
        </Panel>
        <Panel id="t-pr-support" icon="team" title="Domácnost a podpora">
          <PanelBody>
            {record.personSupport.length === 0 ? <Empty text="Nic není zaznamenáno." /> : <EntryGroups entries={record.personSupport} render={(entry, index) => {
                const v = entry.value
                return (
                  <Entry key={index} entry={entry} title={v.description ?? 'Domácnost a život'}>
                    <Fields items={[['Rodinný stav', v.maritalStatus], ['Bydlení', v.livingSituation], ['Pomoc blízkých', v.support], ['Zaměstnání', v.occupation],
                      ['Pracovní neschopnost', v.sickLeave], ['Kouření', v.smoking], ['Alkohol', v.alcohol], ['Soběstačnost', v.independence],
                      ['Obavy a úzkost', v.reportedAnxiety], ['Potřeba podpory', v.supportNeed], ['Závěr psychologa', v.psychologyConclusion],
                      ['Doporučená psychoterapie', v.psychotherapyRecommendation], ['Doporučená psychiatrická konzultace', v.psychiatryRecommendation], ['Sledování bolesti', v.painFollowup]]} />
                  </Entry>
                )
              }} />}
          </PanelBody>
        </Panel>
        <Panel id="t-pr-wish" icon="team" title="Vaše přání ke sdílení informací" meta="Zaznamenané přání není oprávnění k přístupu v této aplikaci.">
          <PanelBody>
            {record.sharingWishes.length === 0 ? <Empty text="Žádné přání není zaznamenáno." /> : <EntryGroups entries={record.sharingWishes} render={(entry, index) => (
                <Entry key={index} entry={entry} title={entry.value.text}>
                  <Fields items={[['Stav', entry.value.state === 'recorded' ? 'zaznamenáno' : entry.value.state === 'declined' ? 'odmítnuto' : 'není známo'],
                    ['Rozsah', entry.value.scope], ['Zaznamenáno', entry.value.recordedAt && clinicalTimeText(entry.value.recordedAt)]]} />
                </Entry>
              )} />}
          </PanelBody>
        </Panel>
      </div>
    </div>
  )
}
