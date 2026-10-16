import type { ClinicalCoverage, ClinicalDomains, ClinicalFact, ClinicalSource, LabPayload, MedicationPayload } from '../../../data/clinical'
import { Notice } from '../../../components/ui/Notice'
import { Panel, PanelBody } from '../../../components/ui/Panel'
import { StackCell, Table } from '../../../components/ui/Table'
import { Tag } from '../../../components/ui/Tag'
import { Fields, FactBlock, FactTags, SourceInspect } from './FactBlock'
import { clinicalTimeText, HISTORY_CATEGORY, LAB_FLAG, LAB_PANEL, MEASUREMENT_TYPE, MEDICATION_STATEMENT, ONCOLOGY_KIND, SUSCEPTIBILITY } from './clinicalText'
import { CoverageNotice } from './CoverageNotice'

interface BodyProps {
  readonly coverage?: ClinicalCoverage | undefined
  readonly domains: ClinicalDomains
  readonly sources: readonly ClinicalSource[]
  /** Distinct heading ids when two bodies could ever share a page. */
  readonly idPrefix: string
}

const yesNo = (value: boolean | undefined) => value === undefined ? undefined : value ? 'ano (dle záznamu)' : 'ne (dle záznamu)'
const none = (count: number, text: string) => count === 0 ? <p className="placeholder-text">{text}</p> : null

/** Health data and results: grouped readable renderers for the supplied domains. */
export function ClinicalRecordBody({ domains, sources, idPrefix, coverage }: BodyProps) {
  return (
    <div className="record">
      <CoverageNotice coverage={coverage} />
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
        <div className="fact-list">
          {facts.map(fact => {
            const v = fact.value
            return (
              <FactBlock key={fact.id} fact={fact} sources={sources} kicker={ONCOLOGY_KIND[v.kind]} title={v.description}>
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
          })}
        </div>
      </PanelBody>
    </Panel>
  )
}

function ImagingPanel({ facts, sources, id, unavailable }: PanelProps<ClinicalDomains['imagingProcedures'][number]['value']>) {
  return (
    <Panel id={id} icon="eye" title="Zprávy z vyšetření a výkony" meta="Textové zprávy a dodaná metadata dokumentů. Obrazová data (DICOM) nejsou součástí.">
      <PanelBody>
        {none(facts.length, unavailable ? 'Zdroj zpráv nebo dokumentů není dostupný.' : 'Žádná zpráva z vyšetření ani výkonu není v záznamu.')}
        <div className="fact-list">
          {facts.map(fact => {
            const v = fact.value
            return (
              <FactBlock key={fact.id} fact={fact} sources={sources} title={v.type} time={v.date ?? fact.effective} timeLabel="Datum vyšetření">
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
              </FactBlock>
            )
          })}
        </div>
      </PanelBody>
    </Panel>
  )
}

function labValue(v: LabPayload) {
  if (v.value === undefined) return <span className="placeholder-text">hodnota neuvedena</span>
  return <span className="num">{v.value}{v.unit ? ` ${v.unit}` : ''}</span>
}

function LabsPanel({ facts, sources, id, unavailable }: PanelProps<LabPayload>) {
  return (
    <Panel id={id} icon="file" title="Laboratoř" meta="Hodnoty, jednotky, rozmezí a označení přesně podle zdroje. Aplikace je neinterpretuje.">
      {facts.length === 0 ? <PanelBody>{none(0, unavailable ? 'Laboratorní výsledky nejsou dostupné — zdroj pozorování se nepodařilo načíst.' : 'Žádný laboratorní výsledek není v záznamu.')}</PanelBody> : (
        <Table labelledBy={id} columns={['Vyšetření', 'Hodnota', 'Rozmezí ze zdroje', 'Označení', 'Odběr · výsledek', 'Stav a zdroj']}>
          {facts.map(fact => {
            const v = fact.value
            const flag = v.abnormalFlag ? LAB_FLAG[v.abnormalFlag] : null
            return (
              <tr key={fact.id}>
                <StackCell label="Vyšetření">
                  <span className="cell-strong">{v.test}</span>
                  {v.suppliedNote && <span className="sub">{v.suppliedNote}</span>}
                  {v.panel && <span className="sub">{LAB_PANEL[v.panel]}</span>}
                  {v.culture && <div className="culture">
                    <p>{v.culture.organism}{v.culture.quantity ? ` · ${v.culture.quantity}` : ''}</p>
                    <ul className="plain-list">{v.culture.susceptibility.map(item => <li key={item.agent}>{item.agent}: {SUSCEPTIBILITY[item.result]}{item.mic ? ` (MIC ${item.mic}${item.unit ? ` ${item.unit}` : ''})` : ''}</li>)}</ul>
                  </div>}
                  {v.sediment && <span className="sub">Sediment: {v.sediment}</span>}
                </StackCell>
                <StackCell label="Hodnota">{v.culture && v.value === undefined ? <span className="sub">viz kultivace</span> : labValue(v)}</StackCell>
                <StackCell label="Rozmezí">{v.referenceRange ?? <span className="placeholder-text">neuvedeno</span>}</StackCell>
                <StackCell label="Označení">{flag ? <Tag label={flag} /> : <span className="placeholder-text">bez označení</span>}</StackCell>
                <StackCell label="Odběr · výsledek"><span className="sub sub--ink">Odběr: {clinicalTimeText(v.sampleAt)}</span><span className="sub">Výsledek: {clinicalTimeText(v.resultAt)}</span></StackCell>
                <StackCell label="Stav a zdroj"><FactTags fact={fact} /><SourceInspect fact={fact} sources={sources} effectiveLabel="Platnost výsledku" /></StackCell>
              </tr>
            )
          })}
        </Table>
      )}
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
  const block = (fact: ClinicalFact<MedicationPayload>) => (
    <FactBlock key={fact.id} fact={fact} sources={sources} kicker={MEDICATION_STATEMENT[fact.value.statement]} title={fact.value.name}>
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
            <div className="conflict__pair">{conflicted.map(block)}</div>
          </section>
        )}
        {reported.length > 0 && <section className="record-group" aria-labelledby={`${id}-rep`}>
          <h3 className="record-group__title" id={`${id}-rep`}>Udává, že užívá</h3>
          <div className="fact-list">{reported.map(block)}</div>
        </section>}
        {advice.length > 0 && <section className="record-group" aria-labelledby={`${id}-adv`}>
          <h3 className="record-group__title" id={`${id}-adv`}>Doporučení, pokyny k výkonu a interakce</h3>
          <div className="fact-list">{advice.map(block)}</div>
        </section>}
      </PanelBody>
    </Panel>
  )
}

function HistoryPanel({ facts, sources, id, unavailable }: PanelProps<ClinicalDomains['history'][number]['value']>) {
  const allergies = facts.filter(fact => fact.value.category === 'allergy')
  const other = facts.filter(fact => fact.value.category !== 'allergy')
  const block = (fact: ClinicalFact<ClinicalDomains['history'][number]['value']>) => (
    <FactBlock key={fact.id} fact={fact} sources={sources} kicker={HISTORY_CATEGORY[fact.value.category]} title={fact.value.description}
      time={fact.value.onset ?? fact.effective} timeLabel={fact.value.onset ? 'Začátek' : 'Týká se doby'}>
      <Fields items={[['Kód', fact.value.code]]} />
    </FactBlock>
  )
  return (
    <Panel id={id} icon="help" title="Anamnéza a alergie" meta="Výslovné popření se liší od chybějícího údaje.">
      <PanelBody>
        <section className="record-group" aria-labelledby={`${id}-all`}>
          <h3 className="record-group__title" id={`${id}-all`}>Alergie</h3>
          {allergies.length === 0 ? <p className="placeholder-text">Údaj o alergiích není v záznamu (není to totéž jako popření).</p> : <div className="fact-list">{allergies.map(block)}</div>}
        </section>
        <section className="record-group" aria-labelledby={`${id}-oth`}>
          <h3 className="record-group__title" id={`${id}-oth`}>Onemocnění, operace a další anamnéza</h3>
          {other.length === 0 ? <p className="placeholder-text">{unavailable ? 'Zdroj onemocnění není dostupný.' : 'Další anamnéza není v záznamu.'}</p> : <div className="fact-list">{other.map(block)}</div>}
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
        <div className="fact-list">
          {facts.map(fact => {
            const v = fact.value
            return (
              <FactBlock key={fact.id} fact={fact} sources={sources} title={v.type} time={v.onset ?? fact.effective} timeLabel="Začátek">
                <Fields items={[
                  ['Místo', v.site], ['Charakter', v.character], ['Průběh', v.course], ['Horečka', yesNo(v.fever)], ['Žloutenka', yesNo(v.jaundice)],
                  ['Tmavá moč', yesNo(v.darkUrine)], ['Chuť k jídlu', v.appetite], ['Nevolnost', yesNo(v.nausea)], ['Hubnutí', v.weightLoss],
                  ['Spánek', v.sleep], ['Fungování', v.function], ['Bolest (NRS)', v.nrs?.toString()],
                ]} />
              </FactBlock>
            )
          })}
        </div>
      </PanelBody>
    </Panel>
  )
}

function MeasurementsPanel({ facts, sources, id, unavailable }: PanelProps<ClinicalDomains['measurements'][number]['value']>) {
  return (
    <Panel id={id} icon="calendar" title="Měření" meta="Každá hodnota nese své datum. Hodnota bez data není označena jako aktuální.">
      <PanelBody>
        {none(facts.length, unavailable ? 'Měření nejsou dostupná — zdroj pozorování se nepodařilo načíst.' : 'Žádné měření není v záznamu.')}
        <div className="fact-list">
          {facts.map(fact => (
            <FactBlock key={fact.id} fact={fact} sources={sources} title={<>{MEASUREMENT_TYPE[fact.value.type]}: <span className="num">{fact.value.value}{fact.value.unit ? ` ${fact.value.unit}` : ''}</span></>} timeLabel="Změřeno">
              <Fields items={[['Popis vyšetření', fact.value.examination]]} />
            </FactBlock>
          ))}
        </div>
      </PanelBody>
    </Panel>
  )
}
