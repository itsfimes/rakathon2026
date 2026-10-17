import type { ClinicalRecord, RecordedConsent } from '../../../data/clinical'
import { Panel, PanelBody } from '../../../components/ui/Panel'
import { Tag } from '../../../components/ui/Tag'
import { ScopedDisclosure } from '../ScopedDisclosure'
import { Fields, FactBlock } from './FactBlock'
import { clinicalTimeText } from './clinicalText'
import { FactGroups } from './FactGroups'
import { FoldToggle } from './GroupedTable'
import { ENTRIES, useFolded } from './grouping'

const WISH_STATE = {
  recorded: { tone: 'info', icon: 'check', text: 'Zaznamenáno' },
  declined: { tone: 'neutral', icon: 'missing', text: 'Odmítnuto' },
  unknown: { tone: 'warning', icon: 'help', text: 'Stav neznámý' },
} as const

const given = (value: string | undefined) => value ?? 'neuvedeno'

function Wish({ wish }: { readonly wish: RecordedConsent }) {
  return (
    <li className="wish">
      <Tag label={WISH_STATE[wish.state]} />
      <p>{wish.text}</p>
      <Fields items={[['Rozsah', wish.scope], ['Zaznamenáno', wish.recordedAt && clinicalTimeText(wish.recordedAt)]]} />
    </li>
  )
}

/** Wishes in record order; a long list folds after a few entries behind one explicit toggle. */
function WishList({ wishes }: { readonly wishes: readonly RecordedConsent[] }) {
  const folded = useFolded(wishes.map((wish, index) => ({ key: index, items: [wish] })), 4)
  return <>
    <ul className="wish-list">{folded.shown.map(group => <Wish key={group.key} wish={group.items[0]!} />)}</ul>
    <FoldToggle fold={{ unit: 'záznamy', items: ENTRIES }} expanded={folded.expanded} hiddenGroups={folded.hiddenGroups} hiddenItems={folded.hiddenItems} onToggle={folded.toggle} />
  </>
}

/** Person and support: identity with deliberate disclosure of sensitive details, social context, wishes, mental support. */
export function PersonBody({ record, idPrefix }: { readonly record: ClinicalRecord; readonly idPrefix: string }) {
  const { domains, sources } = record
  return (
    <div className="record">
      <Panel id={`${idPrefix}-id`} icon="person" title="Totožnost a kontakt" meta="Citlivé identifikátory a kontakty se zobrazí jen na vyžádání. Nikdy nejsou v seznamech ani v adrese stránky.">
        <PanelBody>
          {domains.identity.length === 0 && <p className="placeholder-text">Identifikační údaje nejsou v klinickém záznamu.</p>}
          <FactGroups facts={domains.identity} render={fact => {
              const v = fact.value
              return (
                <FactBlock key={fact.id} fact={fact} sources={sources} title="Základní údaje" grouped>
                  <Fields items={[['Pohlaví', v.sex], ['Věk', v.age?.toString()], ['Kontaktní osoba – vztah', v.contactPerson?.relationship]]} />
                  <ScopedDisclosure icon="lock" summary="Zobrazit citlivé identifikační a kontaktní údaje">
                    <Fields items={[
                      ['Jméno', given(v.name)], ['Datum narození', v.birthDate ? clinicalTimeText(v.birthDate) : 'neuvedeno'],
                      ['Rodné číslo', given(v.nationalIdentifier)], ['Číslo pojištěnce', given(v.insuranceIdentifier)], ['Pojišťovna', given(v.insurer)],
                      ['Adresa', given(v.address)], ['Kontakt', given(v.contact)],
                      ['Kontaktní osoba', v.contactPerson ? `${given(v.contactPerson.name)} · ${v.contactPerson.relationship}${v.contactPerson.contact ? ` · ${v.contactPerson.contact}` : ' · kontakt neuveden'}` : 'neuvedena'],
                    ]} />
                  </ScopedDisclosure>
                </FactBlock>
              )
            }} />
        </PanelBody>
      </Panel>
      <Panel id={`${idPrefix}-wish`} icon="team" title="Přání ke sdílení a souhlasy" meta="Zaznamenané přání není oprávnění k přístupu v této aplikaci.">
        <PanelBody>
          {domains.identity.every(fact => !fact.value.sharingWish && !fact.value.consents?.length)
            ? <p className="placeholder-text">Žádné přání ke sdílení ani souhlas nejsou zaznamenány.</p>
            : <WishList wishes={domains.identity.flatMap(fact => [...(fact.value.sharingWish ? [fact.value.sharingWish] : []), ...(fact.value.consents ?? [])])} />}
        </PanelBody>
      </Panel>
      <div className="record__pair">
        <Panel id={`${idPrefix}-soc`} icon="building" title="Domácnost, práce a soběstačnost">
          <PanelBody>
            {domains.personalSocial.length === 0 && <p className="placeholder-text">Sociální údaje nejsou v záznamu.</p>}
            <FactGroups facts={domains.personalSocial} render={fact => {
                const v = fact.value
                return (
                  <FactBlock key={fact.id} fact={fact} sources={sources} title="Sociální situace" grouped>
                    <Fields items={[['Rodinný stav', v.maritalStatus], ['Bydlení', v.livingSituation], ['Podpora blízkých', v.support], ['Zaměstnání', v.occupation],
                      ['Pracovní neschopnost', v.sickLeave], ['Kouření', v.smoking], ['Alkohol', v.alcohol], ['Soběstačnost', v.independence]]} />
                  </FactBlock>
                )
              }} />
          </PanelBody>
        </Panel>
        <Panel id={`${idPrefix}-sup`} icon="help" title="Psychická podpora" meta="Jen zaznamenané údaje a doporučení, bez nového hodnocení.">
          <PanelBody>
            {domains.supportiveCare.length === 0 && <p className="placeholder-text">Údaje o podpoře nejsou v záznamu.</p>}
            <FactGroups facts={domains.supportiveCare} render={fact => {
                const v = fact.value
                return (
                  <FactBlock key={fact.id} fact={fact} sources={sources} title={v.description} grouped>
                    <Fields items={[
                      ['Udávaná úzkost', v.reportedAnxiety], ['Potřeba podpory', v.supportNeed],
                      ['HADS', v.hads ? `úzkost ${v.hads.anxiety ?? 'neuvedeno'} · deprese ${v.hads.depression ?? 'neuvedeno'} · ${clinicalTimeText(v.hads.date)}` : undefined],
                      ['Distres', v.distress ? `${v.distress.value}${v.distress.scale ? ` (${v.distress.scale})` : ''}` : undefined],
                      ['Závěr psychologa', v.psychologyConclusion], ['Doporučená psychoterapie', v.psychotherapyRecommendation],
                      ['Doporučená psychiatrie', v.psychiatryRecommendation], ['Sledování bolesti', v.painFollowup],
                    ]} />
                  </FactBlock>
                )
              }} />
          </PanelBody>
        </Panel>
      </div>
    </div>
  )
}
