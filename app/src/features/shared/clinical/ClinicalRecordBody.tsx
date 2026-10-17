import type { ClinicalCoverage, ClinicalRecord, ClinicalDomains, ClinicalFact, ClinicalSource, LabPayload, MedicationPayload } from '../../../data/clinical'
import { Notice } from '../../../components/ui/Notice'
import { Panel, PanelBody } from '../../../components/ui/Panel'
import { Fields, FactBlock } from './FactBlock'
import { clinicalTimeText, HISTORY_CATEGORY, MEDICATION_STATEMENT, ONCOLOGY_KIND } from './clinicalText'
import { CoverageNotice } from './CoverageNotice'
import { LabTable } from './LabTable'
import { MeasurementTable } from './MeasurementTable'
import { FactGroups } from './FactGroups'
import { ReportItems, ReportLine } from './ReportMeta'

interface BodyProps {
  readonly coverage?: ClinicalCoverage | undefined
  readonly coverageDetail?: ClinicalRecord['collectionCoverage'] | undefined
  readonly domains: ClinicalDomains
  readonly sources: readonly ClinicalSource[]
  /** Distinct heading ids when two bodies could ever share a page. */
  readonly idPrefix: string
}

const yesNo = (value: boolean | undefined) => value === undefined ? undefined : value ? 'ano (dle záznamu)' : 'ne (dle záznamu)'
const none = (count: number, text: string) => count === 0 ? <p className="placeholder-text">{text}</p> : null

/** Health data and results: grouped readable renderers for the supplied domains. */
export function ClinicalRecordBody({ domains, sources, idPrefix, coverage, coverageDetail }: BodyProps) {
  return (
    <div className="record">
      <CoverageNotice coverage={coverage} detail={coverageDetail} />
      <OncologyPanel facts={domains.oncologyHistology} sources={sources} id={`${idPrefix}-onc`} />
      <ImagingPanel facts={domains.imagingProcedures} sources={sources} id={`${idPrefix}-img`} unavailable={coverage?.diagnosticReports === 'unavailable' || coverage?.documents === 'unavailable'} />
      <LabsPanel facts={domains.labs} sources={sources} id={`${idPrefix}-lab`} unavailable={coverage?.observations === 'unavailable'} />
      <MedicationsPanel facts={domains.medications} sources={sources} id={`${idPrefix}-med`} />
      <HistoryPanel facts={domains.history} sources={sources} id={`${idPrefix}-hist`} unavailable={coverage?.conditions === 'unavailable'} />
      <div className="record__pair">
        <SymptomsPanel facts={domains.symptoms} sources={sources} id={`${idPrefix}-sym`} />
        <MeasurementsPanel facts={domains.measurements} sources={sources} id={`${idPrefix}-meas`} unavailable={coverage?.observations === 'unavailable'} />
      </div>
    </div>
  )
}

interface PanelProps<T> { readonly facts: readonly ClinicalFact<T>[]; readonly sources: readonly ClinicalSource[]; readonly id: string; readonly unavailable?: boolean }

function OncologyPanel({ facts, sources, id }: PanelProps<ClinicalDomains['oncologyHistology'][number]['value']>) {
  return (
    <Panel id={id} icon="file" title="Onkologie a histologie" meta="Původní podezření a pozdější potvrzení jsou samostatné záznamy. Staging jen podle dodaného závěru.">
      <PanelBody>
        {none(facts.length, 'Žádný onkologický ani histologický údaj není v záznamu.')}
        <FactGroups facts={facts} render={fact => {
            const v = fact.value
            return (
              <FactBlock key={fact.id} fact={fact} sources={sources} kicker={ONCOLOGY_KIND[v.kind]} title={v.description} grouped>
                <Fields items={[
                  ['Lokalizace', v.site], ['Typ', v.type], ['Stupeň (grade)', v.grade], ['Perineurální invaze', v.perineuralInvasion],
                  ['Imunohistochemie', v.ihc?.length ? <ul className="plain-list">{v.ihc.map(item => <li key={item.marker}>{item.marker}: {item.result}</li>)}</ul> : undefined],
                  ['Kód diagnózy', v.diagnosisCode], ['Kód morfologie', v.morphologyCode],
                  ['Odběr vzorku', v.sampleAt && clinicalTimeText(v.sampleAt)], ['Datum zprávy', v.reportAt && clinicalTimeText(v.reportAt)],
                  ['Staging', v.kind === 'suspicion' ? undefined : v.staging ?? 've zdroji neuveden'],
                  ['Resekabilita', v.resectability],
                ]} />
              </FactBlock>
            )
          }} />
      </PanelBody>
    </Panel>
  )
}

function ImagingPanel({ facts, sources, id, unavailable }: PanelProps<ClinicalDomains['imagingProcedures'][number]['value']>) {
  return (
    <Panel id={id} icon="eye" title="Zprávy z vyšetření a výkony" meta="Textové zprávy a dodaná metadata dokumentů. Obrazová data (DICOM) nejsou součástí.">
      <PanelBody>
        {none(facts.length, unavailable ? 'Zdroj zpráv nebo dokumentů není dostupný.' : 'Žádná zpráva z vyšetření ani výkonu není v záznamu.')}
        <FactGroups facts={facts} budget={2} timeLine={fact => `Datum vyšetření: ${clinicalTimeText(fact.value.date ?? fact.effective)}`} render={fact => {
            const v = fact.value
            return (
              <FactBlock key={fact.id} fact={fact} sources={sources} title={v.type} grouped>
                <ReportLine date={v.date ?? fact.effective} meta={v.meta} withDate={false} />
                <Fields items={[['Oblast', v.site], ['Indikace', v.indication]]} />
                {v.findings && <div className="report-text"><h5>Nález</h5><p>{v.findings}</p></div>}
                {v.conclusion && <div className="report-text"><h5>Závěr</h5><p>{v.conclusion}</p></div>}
                {v.lesion && <Fields items={[
                  ['Ložisko', v.lesion.site], ['Rozměry', v.lesion.dimensions], ['Cévy', v.lesion.vessels], ['Vývody', v.lesion.ducts],
                  ['Uzliny', v.lesion.nodes], ['Vzdálené nálezy', v.lesion.distantFindings],
                ]} />}
                {v.biopsy && <Fields items={[
                  ['Odběr – metoda', v.biopsy.method], ['Počet vzorků', v.biopsy.sampleCount?.toString()], ['Místo odběru', v.biopsy.sampleSite], ['Komplikace', v.biopsy.complications],
                ]} />}
                <ReportItems meta={v.meta} />
              </FactBlock>
            )
          }} />
      </PanelBody>
    </Panel>
  )
}

function LabsPanel({ facts, sources, id, unavailable }: PanelProps<LabPayload>) {
  return (
    <Panel id={id} icon="file" title="Laboratoř" meta="Hodnoty, jednotky, rozmezí a označení přesně podle zdroje. Aplikace je neinterpretuje.">
      {facts.length === 0 ? <PanelBody>{none(0, unavailable ? 'Laboratorní výsledky nejsou dostupné — zdroj pozorování se nepodařilo načíst.' : 'Žádný laboratorní výsledek není v záznamu.')}</PanelBody>
        : <LabTable facts={facts} sources={sources} labelledBy={id} />}
    </Panel>
  )
}

function MedicationFields({ v }: { readonly v: MedicationPayload }) {
  return (
    <Fields items={[
      ['Síla', v.strength], ['Dávka', v.dose], ['Frekvence', v.frequency],
      ['Režim', v.schedule === 'regular' ? 'pravidelně' : v.schedule === 'as-needed' ? 'při potížích' : v.schedule === 'course' ? 'kúra' : undefined],
      ['Uvedená indikace', v.suppliedIndication], ['Pokyn ve zdroji', v.instruction], ['Navržená změna', v.recommendedChange], ['Interakce', v.interaction],
      ['Vysadit', v.stopAt && clinicalTimeText(v.stopAt)], ['Znovu nasadit', v.restartAt && clinicalTimeText(v.restartAt)],
      ['Začátek kúry', v.courseStart && clinicalTimeText(v.courseStart)], ['Konec kúry', v.courseEnd && clinicalTimeText(v.courseEnd)],
    ]} />
  )
}

function MedicationsPanel({ facts, sources, id }: PanelProps<MedicationPayload>) {
  const conflicted = facts.filter(fact => fact.conflictIds.length > 0 || ('conflict' in fact && fact.conflict === 'unresolved'))
  const rest = facts.filter(fact => !conflicted.includes(fact))
  const reported = rest.filter(fact => fact.value.statement === 'reported-taking' || fact.value.statement === 'completed-course')
  const advice = rest.filter(fact => !reported.includes(fact))
  const block = (fact: ClinicalFact<MedicationPayload>, grouped = false) => (
    <FactBlock key={fact.id} fact={fact} sources={sources} kicker={MEDICATION_STATEMENT[fact.value.statement]} title={fact.value.name} grouped={grouped}>
      <MedicationFields v={fact.value} />
    </FactBlock>
  )
  return (
    <Panel id={id} icon="file" title="Léky" meta="Co pacient udává, že užívá, je odděleno od doporučení a pokynů. Nic se nesjednocuje automaticky.">
      <PanelBody>
        {none(facts.length, 'Žádný lékový záznam není v záznamu.')}
        {conflicted.length > 0 && (
          <section className="conflict" aria-labelledby={`${id}-conflict`}>
            <Notice tone="danger" icon="alert" title={<span id={`${id}-conflict`}>Nevyřešený rozpor v lécích</span>} role="note">
              Tyto záznamy si odporují. Aplikace žádný z nich nevybírá; rozhodne člověk podle zdrojů.
            </Notice>
            <div className="conflict__pair">{conflicted.map(fact => block(fact))}</div>
          </section>
        )}
        {reported.length > 0 && <section className="record-group" aria-labelledby={`${id}-rep`}>
          <h3 className="record-group__title" id={`${id}-rep`}>Udává, že užívá</h3>
          <FactGroups facts={reported} render={fact => block(fact, true)} />
        </section>}
        {advice.length > 0 && <section className="record-group" aria-labelledby={`${id}-adv`}>
          <h3 className="record-group__title" id={`${id}-adv`}>Doporučení, pokyny k výkonu a interakce</h3>
          <FactGroups facts={advice} render={fact => block(fact, true)} />
        </section>}
      </PanelBody>
    </Panel>
  )
}

function HistoryPanel({ facts, sources, id, unavailable }: PanelProps<ClinicalDomains['history'][number]['value']>) {
  const allergies = facts.filter(fact => fact.value.category === 'allergy')
  const other = facts.filter(fact => fact.value.category !== 'allergy')
  const timeLine = (fact: ClinicalFact<ClinicalDomains['history'][number]['value']>) =>
    `${fact.value.onset ? 'Začátek' : 'Týká se doby'}: ${clinicalTimeText(fact.value.onset ?? fact.effective)}`
  const block = (fact: ClinicalFact<ClinicalDomains['history'][number]['value']>) => (
    <FactBlock key={fact.id} fact={fact} sources={sources} kicker={HISTORY_CATEGORY[fact.value.category]} title={fact.value.description} grouped>
      <Fields items={[['Kód', fact.value.code]]} />
    </FactBlock>
  )
  return (
    <Panel id={id} icon="help" title="Anamnéza a alergie" meta="Výslovné popření se liší od chybějícího údaje.">
      <PanelBody>
        <section className="record-group" aria-labelledby={`${id}-all`}>
          <h3 className="record-group__title" id={`${id}-all`}>Alergie</h3>
          {allergies.length === 0 ? <p className="placeholder-text">Údaj o alergiích není v záznamu (není to totéž jako popření).</p> : <FactGroups facts={allergies} timeLine={timeLine} render={block} />}
        </section>
        <section className="record-group" aria-labelledby={`${id}-oth`}>
          <h3 className="record-group__title" id={`${id}-oth`}>Onemocnění, operace a další anamnéza</h3>
          {other.length === 0 ? <p className="placeholder-text">{unavailable ? 'Zdroj onemocnění není dostupný.' : 'Další anamnéza není v záznamu.'}</p> : <FactGroups facts={other} timeLine={timeLine} render={block} />}
        </section>
      </PanelBody>
    </Panel>
  )
}

function SymptomsPanel({ facts, sources, id }: PanelProps<ClinicalDomains['symptoms'][number]['value']>) {
  return (
    <Panel id={id} icon="person" title="Příznaky" meta="Přibližný začátek zůstává přibližný.">
      <PanelBody>
        {none(facts.length, 'Žádné příznaky nejsou v záznamu.')}
        <FactGroups facts={facts} timeLine={fact => `Začátek: ${clinicalTimeText(fact.value.onset ?? fact.effective)}`} render={fact => {
            const v = fact.value
            return (
              <FactBlock key={fact.id} fact={fact} sources={sources} title={v.type} grouped>
                <Fields items={[
                  ['Místo', v.site], ['Charakter', v.character], ['Průběh', v.course], ['Horečka', yesNo(v.fever)], ['Žloutenka', yesNo(v.jaundice)],
                  ['Tmavá moč', yesNo(v.darkUrine)], ['Chuť k jídlu', v.appetite], ['Nevolnost', yesNo(v.nausea)], ['Hubnutí', v.weightLoss],
                  ['Spánek', v.sleep], ['Fungování', v.function], ['Bolest (NRS)', v.nrs?.toString()],
                ]} />
              </FactBlock>
            )
          }} />
      </PanelBody>
    </Panel>
  )
}

function MeasurementsPanel({ facts, sources, id, unavailable }: PanelProps<ClinicalDomains['measurements'][number]['value']>) {
  return (
    <Panel id={id} icon="calendar" title="Měření" meta="Každá hodnota nese své datum. Hodnota bez data není označena jako aktuální.">
      {facts.length === 0 ? <PanelBody>{none(0, unavailable ? 'Měření nejsou dostupná — zdroj pozorování se nepodařilo načíst.' : 'Žádné měření není v záznamu.')}</PanelBody>
        : <MeasurementTable facts={facts} sources={sources} labelledBy={id} />}
    </Panel>
  )
}
