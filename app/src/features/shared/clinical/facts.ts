import type { ClinicalDomains, ClinicalFact } from '../../../data/clinical'
import type { ClinicianSection } from '../../../lib/routes'
import { clinicalFactState, HISTORY_CATEGORY, MEASUREMENT_TYPE, ONCOLOGY_KIND, PLAN_KIND } from './clinicalText'

type Domain = keyof ClinicalDomains

export const DOMAIN_LABEL: Record<Domain, string> = {
  identity: 'Totožnost a sdílení', personalSocial: 'Sociální situace', history: 'Anamnéza a alergie', medications: 'Léky',
  symptoms: 'Příznaky', measurements: 'Měření', labs: 'Laboratoř', imagingProcedures: 'Zobrazení a výkony',
  oncologyHistology: 'Onkologie a histologie', supportiveCare: 'Psychická podpora', referralContinuity: 'Odeslání a návaznost', mdtPlan: 'Porady a plán',
}

export const DOMAIN_SECTION: Record<Domain, ClinicianSection> = {
  identity: 'person', personalSocial: 'person', supportiveCare: 'person', referralContinuity: 'care', mdtPlan: 'care',
  history: 'record', medications: 'record', symptoms: 'record', measurements: 'record', labs: 'record', imagingProcedures: 'record', oncologyHistology: 'record',
}

/** Short human title of a fact, taken from its own supplied fields only. */
export function factTitle(domain: Domain, fact: ClinicalFact<unknown>): string {
  const v = fact.value as Record<string, unknown>
  const text = (key: string) => typeof v[key] === 'string' ? v[key] as string : undefined
  switch (domain) {
    case 'history': return `${HISTORY_CATEGORY[text('category') ?? ''] ?? 'Anamnéza'}: ${text('description') ?? ''}`
    case 'medications': return text('name') ?? 'Lék'
    case 'symptoms': return text('type') ?? 'Příznak'
    case 'measurements': return MEASUREMENT_TYPE[text('type') ?? ''] ?? 'Měření'
    case 'labs': return text('test') ?? 'Výsledek'
    case 'imagingProcedures': return text('type') ?? 'Zpráva'
    case 'oncologyHistology': return ONCOLOGY_KIND[text('kind') ?? ''] ?? 'Onkologický údaj'
    case 'supportiveCare': return text('description') ?? 'Podpora'
    case 'mdtPlan': return `${PLAN_KIND[text('kind') ?? ''] ?? 'Plán'}: ${text('description') ?? ''}`
    default: return DOMAIN_LABEL[domain]
  }
}

export interface AttentionItem { readonly id: string; readonly domain: Domain; readonly title: string; readonly fact: ClinicalFact<unknown> }

/** Facts whose state needs a human eye: conflicts, unknown/not recorded, suspected or preliminary. No ranking, no inference. */
export function attentionItems(domains: ClinicalDomains): readonly AttentionItem[] {
  return (Object.keys(domains) as Domain[]).flatMap(domain => (domains[domain] as readonly ClinicalFact<unknown>[]).filter(fact => {
    const state = clinicalFactState(fact)
    return state.conflict || state.knowledge !== 'recorded' || state.verification === 'suspected' || state.verification === 'preliminary'
  }).map(fact => ({ id: fact.id, domain, title: factTitle(domain, fact), fact })))
}

export const SECTION_LABEL: Record<ClinicianSection, string> = {
  overview: 'Přehled', record: 'Zdravotní údaje a výsledky', care: 'Průběh a plán', person: 'Osoba a podpora',
}
