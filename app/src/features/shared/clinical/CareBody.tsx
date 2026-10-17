import type { ClinicalFact, ClinicalRecord, ClinicalSource, MdtPlanPayload } from '../../../data/clinical'
import { Panel, PanelBody } from '../../../components/ui/Panel'
import { Fields, FactBlock } from './FactBlock'
import { clinicalTimeText, EXAM_STATE, PLAN_KIND, PLAN_STATE } from './clinicalText'
import { FactGroups } from './FactGroups'
import { GroupedTable, Missing } from './GroupedTable'
import { groupInOrder } from './grouping'
import type { Column } from './grouping'

const planTime = (fact: ClinicalFact<MdtPlanPayload>) => {
  const v = fact.value
  return `${v.scheduledAt ? 'Termín' : v.meetingDate ? 'Datum porady' : 'Týká se doby'}: ${clinicalTimeText(v.scheduledAt ?? v.meetingDate ?? fact.effective)}`
}

const DOC_COLUMNS: readonly Column[] = [{ label: 'Dokument' }, { label: 'Místně k dispozici' }, { label: 'Kontrola' }]

/** Recorded meeting/plan entries exactly as supplied: attendees, conclusion, follow-ups, owners. */
export function PlanFacts({ facts, sources, empty }: { readonly facts: readonly ClinicalFact<MdtPlanPayload>[]; readonly sources: readonly ClinicalSource[]; readonly empty: string }) {
  if (facts.length === 0) return <p className="placeholder-text">{empty}</p>
  return (
    <FactGroups facts={facts} timeLine={planTime} render={fact => {
        const v = fact.value
        return (
          <FactBlock key={fact.id} fact={fact} sources={sources} kicker={PLAN_KIND[v.kind]} title={v.description} grouped>
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
      }} />
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
          <FactGroups facts={domains.referralContinuity} render={fact => {
              const v = fact.value
              return (
                <FactBlock key={fact.id} fact={fact} sources={sources} title={v.reason ?? 'Odeslání'} grouped>
                  <Fields items={[
                    ['Odesílající', v.referrer], ['Pracoviště', v.site], ['Žádost na KOC', v.kocRequest], ['Dotaz na specialistu', v.specialistQuestion],
                    ['Vyšetření', v.examinations?.length ? <ul className="plain-list">{v.examinations.map(exam => <li key={exam.description}>{exam.description} · {EXAM_STATE[exam.state]}</li>)}</ul> : undefined],
                    ['Potíže s přístupem', v.accessDifficulties],
                    ['Doporučené konzultace', v.consultations?.length ? v.consultations.join(', ') : undefined],
                  ]} />
                </FactBlock>
              )
            }} />
        </PanelBody>
      </Panel>
      {!snapshot && <Panel id={`${idPrefix}-plan`} icon="team" title="Porady, závěry a plán" meta="Aktuální záznam včetně údajů po poradě. Není to podklad, který měla porada k dispozici.">
        <PanelBody><PlanFacts facts={domains.mdtPlan} sources={sources} empty="Žádná porada ani plán nejsou v záznamu." /></PanelBody>
      </Panel>}
      <Panel id={`${idPrefix}-docs`} icon="calendar" title={snapshot ? 'Verze zdrojů použité v přípravě' : 'Dokumenty podle času'}
        meta={snapshot ? 'Jen verze, na které odkazují doložené položky. Vydání a dostupnost nejsou datum klinické události.' : 'Vydání a místní dostupnost dokumentu nejsou datum klinické události.'}>
        {sources.length === 0 ? <PanelBody><p className="placeholder-text">Žádný zdroj není v záznamu.</p></PanelBody> : (
          <GroupedTable labelledBy={`${idPrefix}-docs`} caption="Dokumenty seskupené podle data vydání, v pořadí záznamu. „—“ = ve zdroji neuvedeno." columns={DOC_COLUMNS}
            groups={groupInOrder(sources, source => clinicalTimeText(source.issued)).map(group => ({ key: group.key, items: group.items, title: `Vydáno: ${group.key}`, meta: [] }))}
            row={source => (
              <tr key={`${source.ref.sourceId}|${source.ref.version}`} className="lab-table__row">
                <th scope="row" className="lab-table__test"><span className="lab-table__name">{source.label}</span><span className="sub">{source.ref.sourceId} · verze {source.ref.version}</span></th>
                <td className="lab-table__range" data-label="K dispozici">{clinicalTimeText(source.locallyAvailable)}</td>
                <td className="lab-table__flag" data-label="Kontrola">{source.review === 'reviewed' ? 'zkontrolováno' : source.review === 'unreviewed' ? 'nezkontrolováno' : <Missing />}</td>
              </tr>
            )} />
        )}
      </Panel>
    </div>
  )
}
