import type { SourceKind } from './clinical'

/** Readable Czech name of what kind of record a source is. */
export const SOURCE_KIND_LABEL: Readonly<Record<SourceKind, string>> = {
  laboratory: 'Laboratorní výsledek', measurement: 'Měření', condition: 'Záznam o onemocnění',
  report: 'Zpráva z vyšetření', document: 'Popis dokumentu', patient: 'Údaje o pacientovi',
}
const STATUS: Readonly<Record<string, string>> = {
  final: 'konečný', preliminary: 'předběžný', amended: 'opravený', corrected: 'opravený', appended: 'doplněný', registered: 'zaevidovaný',
  partial: 'částečný', cancelled: 'zrušený', 'entered-in-error': 'zadáno omylem', unknown: 'neznámý', current: 'platný', superseded: 'nahrazený',
}
/** Translates a known source status code; unknown codes are shown as written. */
export const sourceStatusText = (code: string): string => STATUS[code] ?? code
