import type { ReactNode } from 'react'
import { Notice } from '../../components/ui/Notice'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { StackCell, Table } from '../../components/ui/Table'
import { Tag } from '../../components/ui/Tag'
import type { PatientMedication, PatientRecord, PatientRecordEntry } from '../../data/patientRecord'
import type { StatusLabel } from '../../lib/labels'
import { Fields } from '../shared/clinical/FactBlock'
import { clinicalTimeText, HISTORY_CATEGORY, MEASUREMENT_TYPE, SUSCEPTIBILITY } from '../shared/clinical/clinicalText'
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

function SourceLine({ entry, timeLabel = 'Kdy' }: { readonly entry: PatientRecordEntry<unknown>; readonly timeLabel?: string }) {
  const sources = entry.sourceStatus === 'resolved' && entry.sources.length > 0
    ? entry.sources.map(source => `${source.label}, vydáno ${clinicalTimeText(source.issued)}`).join('; ')
    : 'zdroj nelze určit'
  return <p className="fact__meta">{timeLabel}: {clinicalTimeText(entry.effective)} · Zdroj: {sources}</p>
}

function Entry({ entry, title, children, timeLabel }: { readonly entry: PatientRecordEntry<unknown>; readonly title: ReactNode; readonly children?: ReactNode; readonly timeLabel?: string }) {
  return (
    <article className="fact">
      <div className="fact__head"><h3 className="fact__title">{title}</h3><EntryTags entry={entry} /></div>
      {children && <div className="fact__body">{children}</div>}
      <SourceLine entry={entry} {...(timeLabel ? { timeLabel } : {})} />
    </article>
  )
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
            <Table labelledBy="t-pr-results" columns={['Vyšetření', 'Výsledek', 'Rozmezí podle zprávy', 'Označení ve zprávě', 'Kdy']}>
              {record.results.map((entry, index) => {
                const v = entry.value
                return (
                  <tr key={index}>
                    <StackCell label="Vyšetření">
                      <span className="cell-strong">{v.test}</span><EntryTags entry={entry} />
                      {v.suppliedNote && <span className="sub">{v.suppliedNote}</span>}
                      {v.culture && <div className="culture"><p>{v.culture.organism}{v.culture.quantity ? ` · ${v.culture.quantity}` : ''}</p>
                        <ul className="plain-list">{v.culture.susceptibility.map(item => <li key={item.agent}>{item.agent}: {SUSCEPTIBILITY[item.result] ?? item.result}</li>)}</ul></div>}
                      {v.sediment && <span className="sub">Sediment: {v.sediment}</span>}
                    </StackCell>
                    <StackCell label="Výsledek">{v.value !== undefined ? <span className="num">{v.value}{v.unit ? ` ${v.unit}` : ''}</span> : <span className="placeholder-text">hodnota neuvedena</span>}</StackCell>
                    <StackCell label="Rozmezí">{v.referenceRange ?? <span className="placeholder-text">neuvedeno</span>}</StackCell>
                    <StackCell label="Označení">{v.abnormalFlag && FLAG[v.abnormalFlag] ? FLAG[v.abnormalFlag] : <span className="placeholder-text">bez označení</span>}</StackCell>
                    <StackCell label="Kdy"><span className="sub sub--ink">Odběr: {clinicalTimeText(v.sampleAt)}</span><span className="sub">Výsledek: {clinicalTimeText(v.resultAt)}</span>
                      <span className="sub">Zdroj: {entry.sourceStatus === 'resolved' && entry.sources.length > 0
                        ? entry.sources.map(source => `${source.label}, vydáno ${clinicalTimeText(source.issued)}`).join('; ') : 'nelze určit'}</span></StackCell>
                  </tr>
                )
              })}
            </Table>
          )}
        </Panel>
        <Panel id="t-pr-reports" icon="file" title="Zprávy z vyšetření">
          <PanelBody>
            {record.reports.length === 0 && <Empty text={record.coverage?.diagnosticReports === 'unavailable' || record.coverage?.documents === 'unavailable' ? 'Zdroj zpráv nebo dokumentů není dostupný.' : 'Žádné zprávy zatím nejsou k dispozici.'} />}
            <div className="fact-list">
              {record.reports.map((entry, index) => (
                <Entry key={index} entry={entry} title={REPORT_TYPE[entry.value.type] ?? entry.value.type} timeLabel="Datum">
                  <Fields items={[['Co zpráva uvádí', entry.value.finding], ['Závěr zprávy', entry.value.conclusion], ['Datum zprávy', entry.value.date && clinicalTimeText(entry.value.date)]]} />
                </Entry>
              ))}
            </div>
          </PanelBody>
        </Panel>
        <Panel id="t-pr-symptoms" icon="person" title="Obtíže, které jste uvedl(a)" meta="Tak, jak jsou zapsané ve zprávách. Přibližný začátek zůstává přibližný.">
          <PanelBody>
            {record.symptoms.length === 0 ? <Empty text="Žádné obtíže nejsou zaznamenány." /> : <div className="fact-list">
              {record.symptoms.map((entry, index) => {
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
              })}
            </div>}
          </PanelBody>
        </Panel>
        <Panel id="t-pr-measurements" icon="calendar" title="Měření" meta="Hodnota a jednotka podle zprávy, vždy s datem měření, pokud je uvedeno.">
          <PanelBody>
            {record.measurements.length === 0 ? <Empty text={record.coverage?.observations === 'unavailable' ? 'Měření nejsou dostupná — zdroj pozorování se nepodařilo načíst.' : 'Žádná měření nejsou zaznamenána.'} /> : <div className="fact-list">
              {record.measurements.map((entry, index) => (
                <Entry key={index} entry={entry} timeLabel="Změřeno"
                  title={<>{MEASUREMENT_TYPE[entry.value.type] ?? entry.value.type}: <span className="num">{entry.value.value}{entry.value.unit ? ` ${entry.value.unit}` : ''}</span></>}>
                  <Fields items={[['Popis vyšetření', entry.value.examination]]} />
                </Entry>
              ))}
            </div>}
          </PanelBody>
        </Panel>
      </div>
      <div className="patient-record__side">
        <Panel id="t-pr-meds" icon="file" title="Moje léky">
          <PanelBody>
            {differs && <Notice tone="warning" icon="alert" title="Některé záznamy o lécích se liší" role="note">Rozdíl je zde jen ukázán. Zatím nebyl vyjasněn.</Notice>}
            {record.medications.length === 0 && <Empty text="Žádné léky nejsou zaznamenány." />}
            {taking.length > 0 && <><h3 className="record-group__title">Co jste uvedl(a), že užíváte</h3><div className="fact-list">{taking.map((entry, index) => <MedicationEntry key={index} entry={entry} />)}</div></>}
            {advice.length > 0 && <><h3 className="record-group__title">Doporučení a pokyny ve zprávách</h3><div className="fact-list">{advice.map((entry, index) => <MedicationEntry key={index} entry={entry} />)}</div></>}
          </PanelBody>
        </Panel>
        <Panel id="t-pr-allergy" icon="alert" title="Alergie">
          <PanelBody>
            {record.allergies.length === 0 ? <Empty text="Údaj o alergiích není zaznamenán." /> : <div className="fact-list">
              {record.allergies.map((entry, index) => <Entry key={index} entry={entry} title={entry.value.description} />)}
            </div>}
          </PanelBody>
        </Panel>
        <Panel id="t-pr-history" icon="help" title="Dřívější onemocnění a operace">
          <PanelBody>
            {record.history.length === 0 ? <Empty text={record.coverage?.conditions === 'unavailable' ? 'Zdroj onemocnění není dostupný.' : 'Nic není zaznamenáno.'} /> : <div className="fact-list">
              {record.history.map((entry, index) => <Entry key={index} entry={entry} title={<><span className="fact__kind">{HISTORY_CATEGORY[entry.value.category]}</span>{entry.value.description}</>} />)}
            </div>}
          </PanelBody>
        </Panel>
        <Panel id="t-pr-support" icon="team" title="Domácnost a podpora">
          <PanelBody>
            {record.personSupport.length === 0 ? <Empty text="Nic není zaznamenáno." /> : <div className="fact-list">
              {record.personSupport.map((entry, index) => {
                const v = entry.value
                return (
                  <Entry key={index} entry={entry} title={v.description ?? 'Domácnost a život'}>
                    <Fields items={[['Rodinný stav', v.maritalStatus], ['Bydlení', v.livingSituation], ['Pomoc blízkých', v.support], ['Zaměstnání', v.occupation],
                      ['Pracovní neschopnost', v.sickLeave], ['Kouření', v.smoking], ['Alkohol', v.alcohol], ['Soběstačnost', v.independence],
                      ['Obavy a úzkost', v.reportedAnxiety], ['Potřeba podpory', v.supportNeed], ['Závěr psychologa', v.psychologyConclusion],
                      ['Doporučená psychoterapie', v.psychotherapyRecommendation], ['Doporučená psychiatrická konzultace', v.psychiatryRecommendation], ['Sledování bolesti', v.painFollowup]]} />
                  </Entry>
                )
              })}
            </div>}
          </PanelBody>
        </Panel>
        <Panel id="t-pr-wish" icon="team" title="Vaše přání ke sdílení informací" meta="Zaznamenané přání není oprávnění k přístupu v této aplikaci.">
          <PanelBody>
            {record.sharingWishes.length === 0 ? <Empty text="Žádné přání není zaznamenáno." /> : <div className="fact-list">
              {record.sharingWishes.map((entry, index) => (
                <Entry key={index} entry={entry} title={entry.value.text}>
                  <Fields items={[['Stav', entry.value.state === 'recorded' ? 'zaznamenáno' : entry.value.state === 'declined' ? 'odmítnuto' : 'není známo'],
                    ['Rozsah', entry.value.scope], ['Zaznamenáno', entry.value.recordedAt && clinicalTimeText(entry.value.recordedAt)]]} />
                </Entry>
              ))}
            </div>}
          </PanelBody>
        </Panel>
      </div>
    </div>
  )
}
