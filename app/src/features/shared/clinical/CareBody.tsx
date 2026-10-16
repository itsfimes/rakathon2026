import type { ClinicalFact, ClinicalRecord, ClinicalSource, MdtPlanPayload } from '../../../data/clinical'
import { Panel, PanelBody } from '../../../components/ui/Panel'
import { StackCell, Table } from '../../../components/ui/Table'
import { Fields, FactBlock } from './FactBlock'
import { clinicalTimeText, EXAM_STATE, PLAN_KIND, PLAN_STATE } from './clinicalText'

/** Recorded meeting/plan entries exactly as supplied: attendees, conclusion, follow-ups, owners. */
export function PlanFacts({ facts, sources, empty }: { readonly facts: readonly ClinicalFact<MdtPlanPayload>[]; readonly sources: readonly ClinicalSource[]; readonly empty: string }) {
  if (facts.length === 0) return <p className="placeholder-text">{empty}</p>
  return (
    <div className="fact-list">
      {facts.map(fact => {
        const v = fact.value
        return (
          <FactBlock key={fact.id} fact={fact} sources={sources} kicker={PLAN_KIND[v.kind]} title={v.description}
            time={v.scheduledAt ?? v.meetingDate ?? fact.effective} timeLabel={v.scheduledAt ? 'Termín' : v.meetingDate ? 'Datum porady' : 'Týká se doby'}>
            <Fields items={[
              ['Stav', v.state && PLAN_STATE[v.state]],
              ['Účastníci', v.attendees?.length ? <ul className="plain-list">{v.attendees.map(person => <li key={`${person.name}-${person.specialty}`}>{person.name} · {person.specialty}</li>)}</ul> : undefined],
              ['Klinické shrnutí', v.clinicalSummary], ['Závěr', v.conclusion], ['Doporučená léčba', v.recommendedTreatment], ['Podpora', v.support],
              ['Navazující kroky', v.followups?.length ? <ul className="plain-list">{v.followups.map(item => <li key={item.description}>{item.description} · {clinicalTimeText(item.date)}</li>)}</ul> : undefined],
              ['Kdo odpovídá', v.owners?.length ? <ul className="plain-list">{v.owners.map(owner => <li key={owner.organization + owner.responsibility}>{owner.organization}{owner.person ? ` · ${owner.person}` : ''}: {owner.responsibility}</li>)}</ul> : undefined],
              ['Zpráva pro', v.reportRecipient],
            ]} />
          </FactBlock>
        )
      })}
    </div>
  )
}

/** Course and plan: referral/continuity, recorded meetings and plan, and when each document arrived. */
export function CareBody({ record, idPrefix, snapshot = false }: { readonly record: ClinicalRecord; readonly idPrefix: string; readonly snapshot?: boolean }) {
  const { domains, sources } = record
  return (
    <div className="record">
      <Panel id={`${idPrefix}-ref`} icon="arrow" title="Odeslání a návaznost">
        <PanelBody>
          {domains.referralContinuity.length === 0 && <p className="placeholder-text">Údaje o odeslání nejsou v záznamu.</p>}
          <div className="fact-list">
            {domains.referralContinuity.map(fact => {
              const v = fact.value
              return (
                <FactBlock key={fact.id} fact={fact} sources={sources} title={v.reason ?? 'Odeslání'}>
                  <Fields items={[
                    ['Odesílající', v.referrer], ['Pracoviště', v.site], ['Žádost na KOC', v.kocRequest], ['Dotaz na specialistu', v.specialistQuestion],
                    ['Vyšetření', v.examinations?.length ? <ul className="plain-list">{v.examinations.map(exam => <li key={exam.description}>{exam.description} · {EXAM_STATE[exam.state]}</li>)}</ul> : undefined],
                    ['Potíže s přístupem', v.accessDifficulties],
                    ['Doporučené konzultace', v.consultations?.length ? v.consultations.join(', ') : undefined],
                  ]} />
                </FactBlock>
              )
            })}
          </div>
        </PanelBody>
      </Panel>
      {!snapshot && <Panel id={`${idPrefix}-plan`} icon="team" title="Porady, závěry a plán" meta="Aktuální záznam včetně údajů po poradě. Není to podklad, který měla porada k dispozici.">
        <PanelBody><PlanFacts facts={domains.mdtPlan} sources={sources} empty="Žádná porada ani plán nejsou v záznamu." /></PanelBody>
      </Panel>}
      <Panel id={`${idPrefix}-docs`} icon="calendar" title={snapshot ? 'Verze zdrojů použité v přípravě' : 'Dokumenty podle času'}
        meta={snapshot ? 'Jen verze, na které odkazují doložené položky. Vydání a dostupnost nejsou datum klinické události.' : 'Vydání a místní dostupnost dokumentu nejsou datum klinické události.'}>
        {sources.length === 0 ? <PanelBody><p className="placeholder-text">Žádný zdroj není v záznamu.</p></PanelBody> : (
          <Table labelledBy={`${idPrefix}-docs`} columns={['Dokument', 'Vydáno', 'Místně k dispozici', 'Kontrola']}>
            {sources.map(source => (
              <tr key={`${source.ref.sourceId}|${source.ref.version}`}>
                <StackCell label="Dokument"><span className="cell-strong">{source.label}</span><span className="sub">{source.ref.sourceId} · verze {source.ref.version}</span></StackCell>
                <StackCell label="Vydáno">{clinicalTimeText(source.issued)}</StackCell>
                <StackCell label="K dispozici">{clinicalTimeText(source.locallyAvailable)}</StackCell>
                <StackCell label="Kontrola">{source.review === 'reviewed' ? 'zkontrolováno' : source.review === 'unreviewed' ? 'nezkontrolováno' : 'neuvedeno'}</StackCell>
              </tr>
            ))}
          </Table>
        )}
      </Panel>
    </div>
  )
}
