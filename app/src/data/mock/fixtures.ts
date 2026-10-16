import type { CaseDetail, NextStep, PhaseId, Priority } from '../contracts'
import { createClinicalRecord, SYNTHETIC_MEETING } from './clinicalFixtures'

export const AS_OF = '2026-10-27'
export const PROVENANCE = 'RAKATHON_SYNTHETIC_FIXTURE_V1'

interface Seed {
  id: string
  name: string
  address: string
  age: number
  diagnosis: string
  priority: Priority
  phase: PhaseId
  day?: number
  task: string
  owner: NextStep['owner']
  due: string
  requested: string
  acknowledgement: NextStep['acknowledgement']
  accepted?: string
  pending?: string
  koc?: string
}

const seeds: readonly Seed[] = [
  { id: 'novak', name: 'Jan Novák', address: 'Pan Novák', age: 60, diagnosis: 'hlava slinivky', priority: 'high', phase: 'T2', day: 5, task: 'Doručit histologii', owner: { organization: 'Patologie', name: 'MUDr. Petr Svoboda' }, due: '2026-01-16', requested: '2026-01-09', acknowledgement: 'pending', pending: 'Nepřevzato 3 dny', koc: '2026-01-07' },
  { id: 'simkova', name: 'Alena Šimková', address: 'Paní Šimková', age: 64, diagnosis: 'tělo slinivky', priority: 'high', phase: 'T3', task: 'Převzít do péče', owner: { organization: 'ROC (regionální centrum)' }, due: '2026-01-13', requested: '2026-01-09T20:00:00+01:00', acknowledgement: 'pending', pending: 'Nepřevzato 52 h', koc: '2026-01-04' },
  { id: 'dusek', name: 'Tomáš Dušek', address: 'Pan Dušek', age: 57, diagnosis: 'tělo slinivky', priority: 'medium', phase: 'T2', day: 3, task: 'Připravit podklady pro MDT', owner: { organization: 'Koordinátor', name: 'Lenka Horká' }, due: '2026-01-15', requested: '2026-01-10', acknowledgement: 'accepted', accepted: '2026-01-10', koc: '2026-01-09' },
  { id: 'kralova', name: 'Marie Králová', address: 'Paní Králová', age: 68, diagnosis: 'ocas slinivky', priority: 'medium', phase: 'T1', task: 'Objednat CT', owner: { organization: 'Radiologie', name: 'objednávky' }, due: '2026-01-14', requested: '2026-01-11', acknowledgement: 'accepted', accepted: '2026-01-11' },
  { id: 'riha', name: 'Pavel Říha', address: 'Pan Říha', age: 62, diagnosis: 'vývod slinivky', priority: 'low', phase: 'T2', day: 1, task: 'Doplnit zprávu z CT', owner: { organization: 'Odesílající lékař' }, due: '2026-01-19', requested: '2026-01-11', acknowledgement: 'awaiting-information', koc: '2026-01-11' },
  { id: 'vesely', name: 'Karel Veselý', address: 'Pan Veselý', age: 71, diagnosis: 'nový případ', priority: 'low', phase: 'T1', task: 'Zkontrolovat podklady', owner: { organization: 'Koordinátor', name: 'Lenka Horká' }, due: '2026-01-17', requested: '2026-01-12', acknowledgement: 'new' },
]

function createCase(seed: Seed): CaseDetail {
  const jan = seed.id === 'novak'
  const id = (suffix: string) => `${seed.id}-${suffix}`
  const imagingId = id('imaging')
  const histologyId = id('histology')
  const stagingId = id('staging')
  const date = seed.koc ?? '2026-01-11'
  const ultrasound = { title: 'UZ břicha', date: jan ? '2026-01-06' : date, page: 1 }
  const ct = { title: 'CT', date: '2026-01-12', page: 2 }
  const isNew = seed.phase === 'T1'
  const finding = jan ? 'ložisko v hlavě slinivky' : `Nález k ověření · ${seed.diagnosis}`
  const imagingSources = isNew ? [ultrasound] : [ultrasound, ct]
  const nextStep: NextStep = {
    id: id('task'), shortTitle: seed.task,
    title: jan ? 'Doručit histologii ze vzorku z 9. 1.' : seed.task,
    owner: seed.owner, dueAt: seed.due, requestedAt: seed.requested,
    acknowledgement: seed.acknowledgement,
    ...(seed.accepted ? { acceptedAt: seed.accepted } : {}),
    ...(seed.pending ? { pendingLabel: seed.pending } : {}),
  }
  const documents: CaseDetail['documents'] = [
    { id: imagingId, kind: 'imaging', label: jan ? 'Zobrazení (UZ 6. 1., CT 12. 1.)' : `Zobrazení · ${seed.name}`, coordinatorLabel: jan ? 'UZ břicha · 6. 1.' : 'UZ břicha', state: 'available', stateLabel: 'Máme', sources: imagingSources, reviewState: 'unreviewed' },
    { id: id('markers'), kind: 'markers', label: 'Nádorové markery CA 19-9', coordinatorLabel: jan ? 'CT a nádorové markery · 12. 1.' : 'CT a nádorové markery', state: isNew ? 'missing' : 'available', stateLabel: isNew ? 'Chybí' : 'Máme', sources: isNew ? [] : [{ title: 'Nádorové markery', date: '2026-01-12' }], reviewState: 'unreviewed' },
    { id: id('fitness'), kind: 'fitness', label: 'Komorbidity, ECOG', state: 'available', stateLabel: 'Máme', sources: [{ title: 'Odesílací zpráva', date }], reviewState: 'unreviewed' },
    { id: stagingId, kind: 'staging', label: 'Staging TNM', state: 'uncertain', stateLabel: 'Není ve zdroji – ověřit', sources: [], reviewState: 'unreviewed' },
    { id: histologyId, kind: 'histology', label: 'Histologie', state: 'missing', stateLabel: 'Chybí', sources: [], reviewState: 'unreviewed' },
  ]
  return {
    ...(jan ? { clinical: createClinicalRecord() } : {}),
    identity: {
      caseId: seed.id, patientId: id('patient'), patientLabel: seed.name, patientAddressLabel: seed.address,
      age: seed.age, diagnosis: { code: 'C25', label: seed.diagnosis },
      referrer: jan
        ? { name: 'MUDr. Jana Veselá', specialty: 'praktická lékařka', viewLabel: 'Pohled MUDr. Jany Veselé, praktické lékařky' }
        : { name: `Odesílající lékař · ${seed.name}`, specialty: 'praktický lékař', viewLabel: `Odesílající lékař případu ${seed.name}` },
      referredAt: jan ? '2026-01-06' : date,
      ...(seed.koc ? { acceptedAt: seed.koc } : {}),
    },
    phases: [
      { id: 'T1', label: 'příznak → předání do KOC', state: isNew ? 'now' : 'done', startedAt: jan ? '2026-01-05' : '2026-01-02', ...(seed.koc ? { endedAt: seed.koc } : {}), ...(jan ? { days: 2 } : {}) },
      { id: 'T2', label: 'KOC → rozhodnutí', state: isNew ? 'later' : seed.phase === 'T2' ? 'now' : 'done', ...(seed.koc ? { startedAt: seed.koc } : {}), ...(seed.day !== undefined ? { days: seed.day } : {}) },
      { id: 'T3', label: 'rozhodnutí → léčba', state: seed.phase === 'T3' ? 'now' : 'later' },
    ],
    nextStep,
    priorityExplanation: jan
      ? 'Krok má vlastníka a termín, ale tři dny ho nikdo nepřevzal. Odesláno neznamená převzato. Jde o zpoždění v organizaci, ne o hodnocení zdravotního stavu.'
      : `Pořadí případu ${seed.name} určuje termín kroku a stav převzetí. Nejde o hodnocení zdravotního stavu.`,
    documents,
    patient: {
      nextEvent: {
        date: jan ? '2026-01-13' : seed.due,
        title: jan ? 'lékaři proberou vaše výsledky' : `Koordinace dalšího kroku: ${seed.task}`,
        attendance: jan ? 'not-required' : 'to-be-confirmed',
        attendanceLabel: jan ? 'Porada lékařů, bez vás' : 'Účast upřesní koordinátorka',
        followup: jan ? 'Je to porada lékařů mezi sebou. Pokud byste měl někam přijít, ozve se vám koordinátorka.' : 'Další termín a případnou účast vám upřesní koordinátorka.',
      },
      currentInstruction: jan ? 'Teď od vás nic nepotřebujeme. Po poradě se vám ozve koordinátorka a řekne, co lékaři navrhli.' : `Váš další krok pomůže domluvit koordinátorka. Stav případu: ${seed.task}.`,
      journey: jan ? [
        { id: id('uz-event'), title: 'Ultrazvuk břicha', date: '2026-01-06', state: 'done', note: 'Hotovo' },
        { id: id('koc-event'), title: 'Přijetí v onkologickém centru', date: '2026-01-07', state: 'done', note: 'Hotovo' },
        { id: id('sample-event'), title: 'Stent a odběr vzorku tkáně', date: '2026-01-09', state: 'done', note: 'Hotovo · výsledek vzorku zatím není' },
        { id: id('ct-event'), title: 'CT a krevní testy', date: '2026-01-12', state: 'done', note: 'Hotovo' },
        { id: id('mdt-event'), title: 'Porada lékařů', date: '2026-01-13', state: 'now', note: 'Další na řadě · bez vás' },
        { id: id('talk-event'), title: 'Rozhovor o dalším postupu', state: 'later', note: 'Později · termín domluví koordinátorka' },
      ] : [
        { id: id('referral-event'), title: 'Odeslání podkladů', date, state: 'done' },
        { id: id('next-event'), title: seed.task, date: seed.due, state: 'now' },
        { id: id('talk-event'), title: 'Rozhovor o dalším postupu', state: 'later', note: 'Termín domluví koordinátorka' },
      ],
      coordinator: { name: 'Lenka Horká', help: 'Pomůže s termíny a s otázkou, kam a kdy jít.' },
    },
    doctor: {
      diagnosisStatus: 'Diagnóza zatím neuzavřena',
      sourceFields: [
        { id: id('finding'), documentId: imagingId, label: 'Nález na UZ', value: finding, quote: jan ? '…v hlavě pankreatu hypoechogenní ložisko…' : `…nález v oblasti: ${seed.diagnosis}; vyžaduje dovyšetření…`, source: ultrasound, status: 'literal', statusLabel: 'Doslovně ve zdroji', reviewState: 'unreviewed' },
        { id: id('diagnosis'), documentId: histologyId, label: 'Diagnóza', value: 'Výpis diagnózu nestanovuje. Nález na UZ není diagnóza.', status: 'awaiting', statusLabel: 'Čeká na histologii', reviewState: 'unreviewed' },
        { id: id('metastases'), documentId: imagingId, label: 'Vzdálené metastázy', ...(isNew ? { value: 'CT zatím není v dokumentaci.' } : { quote: '…bez jednoznačných známek vzdálených metastáz…', source: ct }), status: isNew ? 'absent' : 'uncertain', statusLabel: isNew ? 'Chybí CT' : 'Nejednoznačné – ověřit', reviewState: 'unreviewed' },
        { id: id('tnm'), documentId: stagingId, label: 'TNM', value: 'TNM není ve zdroji uvedeno — ověřit.', status: 'absent', statusLabel: 'Není ve zdroji', reviewState: 'unreviewed' },
        { id: id('histology-field'), documentId: histologyId, label: 'Histologie', ...(jan ? { value: 'Vzorek 9. 1. · Výsledek zatím není v dokumentaci.' } : { value: 'Výsledek zatím není v dokumentaci.' }), status: 'absent', statusLabel: 'Chybí', reviewState: 'unreviewed' },
      ],
      referralStatus: [
        { id: id('sent'), title: 'Odesláno', date: jan ? '2026-01-06' : date, state: 'done' },
        { id: id('accepted'), title: 'Přijato v KOC', ...(seed.koc ? { date: seed.koc } : {}), state: seed.koc ? 'done' : 'later' },
        { id: id('meeting'), title: 'Porada MDT', date: jan ? '2026-01-13' : seed.due, state: isNew ? 'later' : 'now', note: isNew ? 'Termín k ověření' : 'Naplánováno' },
        { id: id('conclusion'), title: 'Závěr porady', state: 'later', note: 'Zatím není · dostanete jej s původním kontextem' },
      ],
      obligations: jan ? 'K doručení histologie od vás nic nepotřebujeme. Kontrola výpisu z dokumentace zůstává na vás.' : `Zkontrolujte výpis pro případ ${seed.name}; další krok má vlastníka uvedeného v případu.`,
    },
    mdt: {
      meetingAt: jan ? SYNTHETIC_MEETING.date : seed.due,
      finding: jan ? 'ložisko v hlavě slinivky (UZ, CT)' : finding,
      requiredDocumentIds: documents.map(document => document.id),
      draft: { uncertainties: ['Histologie chybí.', 'TNM není ve zdroji uvedeno.', ...(isNew ? ['CT zatím není v dokumentaci.'] : ['CT: „bez jednoznačných známek vzdálených metastáz“ – nejednoznačné.'])] },
      finalization: { state: 'blocked', reason: 'Tato aplikace závěr porady nefinalizuje ani nepodepisuje. Stav podkladů je uveden výše.' },
    },
  }
}

export function createSeedCases(): CaseDetail[] {
  return seeds.map(createCase)
}

export function queueClassification(caseId: string): { priority: Priority; phase: PhaseId; phaseDay?: number } {
  const seed = seeds.find(item => item.id === caseId)
  if (!seed) throw new Error('Unknown internal seed')
  return { priority: seed.priority, phase: seed.phase, ...(seed.day !== undefined ? { phaseDay: seed.day } : {}) }
}
