import type { ClinicalFact, ClinicalRecord, ClinicalSource, ClinicalTime, SourceRef } from '../clinical'
import type { PreparationRequirement } from '../mdtPreparation'

export const SYNTHETIC_MEETING = Object.freeze({ id: 'SYNTHETIC-MDT-2026-10-21', date: '2026-10-21' })
const day = (value: string): ClinicalTime => ({ kind: 'day', value })
const unknown: ClinicalTime = { kind: 'unknown' }
const ref = (name: string): SourceRef => ({ sourceId: `SYNTHETIC-${name}`, version: '1' })
const source = (name: string, label: string, issued: string, available: string): ClinicalSource => ({
  ref: ref(name), label: `SYNTHETIC — ${label}; autorská ukázka, nikoli výpis zprávy`, issued: day(issued), locallyAvailable: day(available), review: 'unreviewed',
})
function fact<T>(id: string, value: T, options: Partial<Omit<ClinicalFact<T>, 'id' | 'value'>> = {}): ClinicalFact<T> {
  return { id: `SYNTHETIC-${id}`, value, sources: [ref('basic')], effective: day('2026-10-18'), knowledge: 'recorded', presence: 'present', verification: 'unspecified', conflictIds: [], review: 'unreviewed', ...options }
}

/** Authored demonstrations, NOT extracted or attributed to real reports 01–13. */
export function createClinicalRecord(): ClinicalRecord {
  return {
    revision: 'SYNTHETIC-clinical-v1',
    sources: [source('basic', 'základní modelový záznam', '2026-10-18', '2026-10-19'),
      source('medication-b', 'druhé neověřené lékové tvrzení', '2026-10-19', '2026-10-20'),
      source('results', 'modelové výsledky a histologie', '2026-10-20', '2026-10-20'),
      source('meeting-conclusion', 'modelový závěr po poradě', '2026-10-21', '2026-10-21'),
      source('support-later', 'modelová podpora po poradě', '2026-10-23', '2026-10-23'),
      source('support-followup', 'modelová následná podpora', '2026-10-26', '2026-10-26')],
    domains: {
      identity: [fact('sharing', { sex: 'Modelový údaj: muž', contactPerson: { relationship: 'blízká osoba, bez kontaktních údajů' },
        sharingWish: { text: 'Modelové zaznamenané přání sdílet informace s blízkou osobou.', state: 'recorded', scope: 'Rozsah je třeba ověřit', recordedAt: day('2026-10-18') },
        consents: [{ text: 'Modelový záznam souhlasu, ne oprávnění aplikace.', state: 'unknown' }],
      })],
      personalSocial: [fact('social', { maritalStatus: 'Modelově žije s partnerem', livingSituation: 'Společná domácnost', support: 'Udává pomoc blízké osoby', occupation: 'Modelové zaměstnání', sickLeave: 'Neuvedeno', smoking: 'Modelově dříve kouřil', alcohol: 'Údaj není upřesněn', independence: 'Udává samostatnost' })],
      history: [fact('allergies-denied', { category: 'allergy', description: 'V modelovém záznamu výslovně popírá alergie.' }, { presence: 'denied' }),
        fact('history-suspected', { category: 'condition', description: 'Modelové podezření na přidružené onemocnění.' }, { verification: 'suspected' }),
        fact('history-confirmed', { category: 'condition', description: 'Samostatný modelový potvrzený anamnestický údaj.', code: 'SYNTHETIC-DX' }, { verification: 'confirmed' }),
        fact('operation', { category: 'operation', description: 'Modelová dřívější operace, přesné datum neuvedeno.' }, { effective: unknown })],
      medications: [fact('apixaban-a', { name: 'Apixaban — syntetické tvrzení A', strength: '2,5 mg', dose: '1 tableta', frequency: '2× denně', schedule: 'regular', statement: 'reported-taking' }, { conflictIds: ['SYNTHETIC-apixaban-b'] }),
        fact('apixaban-b', { name: 'Apixaban — syntetické tvrzení B', strength: '5 mg', dose: '1 tableta', frequency: '2× denně', schedule: 'regular', statement: 'reported-taking' }, { sources: [ref('medication-b')], conflictIds: ['SYNTHETIC-apixaban-a'] }),
        fact('med-recommendation', { name: 'Modelový lék', statement: 'recommended', recommendedChange: 'Modelový návrh změny k ověření, nikoli pokyn k užívání.' }, { verification: 'preliminary' }),
        fact('med-procedure', { name: 'Modelový lék před výkonem', statement: 'periprocedure-instruction', instruction: 'Existuje samostatný modelový pokyn; konkrétní režim zde není určen.' })],
      symptoms: [fact('symptoms', { type: 'Modelově udávané obtíže břicha', site: 'Břicho', character: 'Popis ze syntetického příkladu', onset: { kind: 'approximate', label: 'Přibližně několik týdnů před vyšetřením' }, course: 'Kolísavé dle udání', appetite: 'Udává menší chuť k jídlu', nausea: false, weightLoss: 'Ztráta hmotnosti dle udání, bez odvození trendu' }, { effective: { kind: 'approximate', label: 'Několik týdnů před vyšetřením' } })],
      measurements: [fact('weight-undated', { type: 'weight', value: '78', unit: 'kg' }, { effective: unknown }),
        fact('weight-july', { type: 'weight', value: '82', unit: 'kg' }, { effective: { kind: 'month', value: '2026-07' } }),
        fact('blood-pressure', { type: 'blood-pressure', value: '130/80', unit: 'mmHg' })],
      labs: [fact('lab', { test: 'Modelový bilirubin', panel: 'liver-biliary', value: '25', unit: 'µmol/l', referenceRange: 'Pouze modelový rozsah 5–21', abnormalFlag: 'high', sampleAt: day('2026-10-18'), resultAt: day('2026-10-20') }, { sources: [ref('results')], verification: 'preliminary' }),
        fact('culture', { test: 'Modelová kultivace', panel: 'culture', culture: { organism: 'SYNTHETIC organismus', quantity: 'Modelové množství', susceptibility: [{ agent: 'SYNTHETIC antibiotikum', result: 'not-supplied' }] }, sampleAt: day('2026-10-18'), resultAt: day('2026-10-20') }, { sources: [ref('results')] })],
      imagingProcedures: [fact('procedure', { type: 'Modelové EUS-FNB', format: 'text-report', date: day('2026-10-18'), site: 'Modelová lokalizace', indication: 'Ukázka struktury', findings: 'Syntetický textový nález; nejde o skutečný report ani obrazová data.', conclusion: 'Závěr pouze modelového příkladu.', lesion: { site: 'Modelové místo', dimensions: 'Modelové rozměry nejsou určeny', vessels: 'Neuvedeno', ducts: 'Neuvedeno', nodes: 'Neuvedeno', distantFindings: 'Neuvedeno' }, biopsy: { method: 'Modelový odběr', sampleCount: 2, sampleSite: 'Modelové místo', complications: 'Údaj není v ukázce potvrzen' } })],
      oncologyHistology: [fact('oncology-suspicion', { kind: 'suspicion', description: 'Původní modelové podezření není potvrzená diagnóza.' }, { verification: 'suspected' }),
        fact('histology', { kind: 'histology', description: 'Samostatný modelový histologický závěr, nikoli interpretace původního podezření.', type: 'SYNTHETIC typ', grade: 'SYNTHETIC stupeň', perineuralInvasion: 'V modelu neuvedeno', ihc: [{ marker: 'SYNTHETIC marker', result: 'Modelový výsledek' }], diagnosisCode: 'SYNTHETIC-DX', morphologyCode: 'SYNTHETIC-MORPH', sampleAt: day('2026-10-18'), reportAt: day('2026-10-20') }, { sources: [ref('results')], verification: 'confirmed' })],
      supportiveCare: [fact('support-basic', { description: 'Před poradou udává obavy.', reportedAnxiety: 'Modelově udávaná úzkost', supportNeed: 'Žádá srozumitelné informace' }),
        fact('support-later', { description: 'SYNTHETIC podpora zaznamenaná až po MDT.', hads: { anxiety: 8, depression: 5, date: day('2026-10-23') }, distress: { value: '5', scale: 'Modelová škála' }, psychologyConclusion: 'Modelový závěr psychologické konzultace.', psychotherapyRecommendation: 'Modelový návrh podpory, nikoli aktuální pokyn.' }, { sources: [ref('support-later')], effective: day('2026-10-23') }),
        fact('support-followup', { description: 'SYNTHETIC následná podpora po MDT.', psychiatryRecommendation: 'Modelově zaznamenaná možnost konzultace.', painFollowup: 'Modelový následný záznam bolesti.' }, { sources: [ref('support-followup')], effective: day('2026-10-26') })],
      referralContinuity: [fact('referral', { referrer: 'SYNTHETIC odesílající pracoviště', site: 'SYNTHETIC centrum', reason: 'Modelový odborný dotaz', kocRequest: 'Modelová žádost o posouzení', specialistQuestion: 'Doplnit pouze dodané podklady', examinations: [{ description: 'Modelové vyšetření', state: 'report-available' }], accessDifficulties: 'V ukázce nejsou potvrzeny', consultations: ['Modelová konzultace'] })],
      mdtPlan: [fact('meeting', { kind: 'meeting', description: 'SYNTHETIC plán porady', meetingDate: day(SYNTHETIC_MEETING.date), attendees: [{ name: 'SYNTHETIC účastník', specialty: 'Modelová odbornost' }], state: 'planned' }, { effective: day(SYNTHETIC_MEETING.date) }),
        fact('task', { kind: 'task', description: 'Modelově zajistit předání dostupných podkladů.', owners: [{ organization: 'SYNTHETIC koordinace', responsibility: 'Modelové předání podkladů' }], scheduledAt: day('2026-10-22'), state: 'planned' }, { effective: day('2026-10-22') }),
        fact('meeting-conclusion', { kind: 'conclusion', description: 'SYNTHETIC zaznamenaný plán po poradě.', conclusion: 'Modelový závěr, nikoli klinické doporučení.', reportRecipient: 'SYNTHETIC odesílající pracoviště', state: 'recorded' }, { sources: [ref('meeting-conclusion')], effective: day('2026-10-21') })],
    },
  }
}

export function createPreparationRequirements(): readonly ClinicalFact<PreparationRequirement>[] {
  return (['imaging', 'markers', 'fitness', 'staging', 'histology'] as const).map(kind => fact(`requirement-${kind}`, {
    documentKind: kind, state: kind === 'staging' ? 'uncertain' : 'available',
  }, { sources: [ref(kind === 'histology' || kind === 'markers' ? 'results' : 'basic')] }))
}
