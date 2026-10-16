import type { ClinicalFact, ClinicalTime } from '../../../data/clinical'
import type { StatusLabel } from '../../../lib/labels'
import { calendarParts, formatDate } from '../../../lib/format'

const MONTHS = ['leden', 'únor', 'březen', 'duben', 'květen', 'červen', 'červenec', 'srpen', 'září', 'říjen', 'listopad', 'prosinec']

/** Literal Czech text for a supplied time at its own precision; never adds a day, hour or year. */
export function clinicalTimeText(time: ClinicalTime | undefined): string {
  if (!time || time.kind === 'unknown') return 'datum neuvedeno'
  if (time.kind === 'approximate') return `přibližně: ${time.label}`
  if (time.kind === 'month') {
    const match = /^(\d{4})-(\d{2})$/.exec(time.value)
    const month = match ? MONTHS[Number(match[2]) - 1] : undefined
    return match && month ? `${month} ${match[1]} (jen měsíc)` : time.value
  }
  if (time.kind === 'day') return calendarParts(time.value) ? formatDate(time.value) : time.value
  const match = /T(\d{2}):(\d{2})/.exec(time.value)
  return calendarParts(time.value) && match ? `${formatDate(time.value)} ${match[1]}:${match[2]} (čas dle zdroje)` : time.value
}

/** True when the time has no usable precision (unknown or only approximate). */
export const imprecise = (time: ClinicalTime | undefined) => !time || time.kind === 'unknown' || time.kind === 'approximate'

type FactState = Pick<ClinicalFact<unknown>, 'knowledge' | 'presence' | 'verification'> & { readonly conflict: boolean }

/** Orthogonal status words. Each axis stays separate: presence, knowledge, verification, conflict. */
export function factStatusLabels(fact: FactState): readonly StatusLabel[] {
  const labels: StatusLabel[] = []
  if (fact.conflict) labels.push({ tone: 'danger', icon: 'alert', text: 'Rozpor mezi záznamy · nevyřešeno' })
  if (fact.presence === 'denied') labels.push({ tone: 'neutral', icon: 'missing', text: 'Výslovně popřeno' })
  if (fact.knowledge === 'unknown') labels.push({ tone: 'warning', icon: 'help', text: 'Neznámo' })
  if (fact.knowledge === 'not-recorded') labels.push({ tone: 'warning', icon: 'missing', text: 'Nezaznamenáno' })
  if (fact.verification === 'suspected') labels.push({ tone: 'warning', icon: 'help', text: 'Podezření, nepotvrzeno' })
  if (fact.verification === 'preliminary') labels.push({ tone: 'warning', icon: 'clock', text: 'Předběžné' })
  if (fact.verification === 'confirmed') labels.push({ tone: 'success', icon: 'check', text: 'Potvrzeno ve zdroji' })
  return labels
}

export const clinicalFactState = (fact: ClinicalFact<unknown>): FactState => ({
  knowledge: fact.knowledge, presence: fact.presence, verification: fact.verification,
  conflict: fact.conflictIds.length > 0 || ('conflict' in fact && fact.conflict === 'unresolved'),
})

export const LAB_FLAG: Record<string, StatusLabel | null> = {
  high: { tone: 'warning', icon: 'alert', text: 'Nad rozmezím (dle zdroje)' },
  low: { tone: 'warning', icon: 'alert', text: 'Pod rozmezím (dle zdroje)' },
  abnormal: { tone: 'warning', icon: 'alert', text: 'Označeno jako odchylka' },
  normal: { tone: 'neutral', icon: 'check', text: 'V rozmezí (dle zdroje)' },
  'not-supplied': null,
}

export const MEDICATION_STATEMENT: Record<string, string> = {
  'reported-taking': 'Udává, že užívá',
  recommended: 'Doporučení nebo návrh',
  'periprocedure-instruction': 'Pokyn k výkonu',
  'completed-course': 'Ukončená kúra',
  interaction: 'Zaznamenaná interakce',
}

export const HISTORY_CATEGORY: Record<string, string> = {
  condition: 'Onemocnění', operation: 'Operace', family: 'Rodinná anamnéza', allergy: 'Alergie', 'mental-health': 'Duševní zdraví', cardiac: 'Srdce a oběh',
}

export const MEASUREMENT_TYPE: Record<string, string> = {
  height: 'Výška', weight: 'Hmotnost', 'blood-pressure': 'Krevní tlak', pulse: 'Tep', temperature: 'Teplota', examination: 'Vyšetření',
}

export const LAB_PANEL: Record<string, string> = {
  'blood-count': 'Krevní obraz', 'liver-biliary': 'Játra a žlučové cesty', inflammation: 'Zánět', renal: 'Ledviny', 'electrolytes-metabolic': 'Minerály a metabolismus',
  pancreatic: 'Slinivka', 'tumour-markers': 'Nádorové markery', urinalysis: 'Moč', culture: 'Kultivace', other: 'Ostatní',
}

export const ONCOLOGY_KIND: Record<string, string> = {
  suspicion: 'Původní podezření', histology: 'Histologie', 'specialist-conclusion': 'Závěr specialisty',
}

export const SUSCEPTIBILITY: Record<string, string> = {
  susceptible: 'citlivý', intermediate: 'středně citlivý', resistant: 'rezistentní', 'not-supplied': 'výsledek neuveden',
}

export const PLAN_KIND: Record<string, string> = {
  meeting: 'Porada', conclusion: 'Zaznamenaný závěr', recommendation: 'Doporučení', task: 'Úkol', appointment: 'Termín',
}

export const PLAN_STATE: Record<string, string> = {
  planned: 'plánováno', completed: 'proběhlo', proposed: 'navrženo', recorded: 'zaznamenáno',
}

export const EXAM_STATE: Record<string, string> = {
  requested: 'vyžádáno', done: 'provedeno', 'report-available': 'zpráva k dispozici', unknown: 'stav neznámý',
}
