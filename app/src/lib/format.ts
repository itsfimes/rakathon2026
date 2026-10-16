import type { SourceMetadata } from '../data/contracts'
/* Pure Czech formatters. ISO date-only values are parsed as calendar parts, never through
   local-time Date construction, so no timezone shift can move a day. */

const MONTHS_GENITIVE = ['ledna', 'února', 'března', 'dubna', 'května', 'června', 'července', 'srpna', 'září', 'října', 'listopadu', 'prosince']
const MONTHS_NOMINATIVE = ['leden', 'únor', 'březen', 'duben', 'květen', 'červen', 'červenec', 'srpen', 'září', 'říjen', 'listopad', 'prosinec']
const WEEKDAYS = ['neděle', 'pondělí', 'úterý', 'středa', 'čtvrtek', 'pátek', 'sobota']

export interface CalendarParts {
  readonly year: number
  readonly month: number // 1–12
  readonly day: number
}

/** Reads the calendar date written in an ISO string (YYYY-MM-DD…), ignoring any time/offset. */
export function calendarParts(iso: string): CalendarParts | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso)
  if (!match) return null
  const year = Number(match[1])
  const month = Number(match[2])
  const day = Number(match[3])
  if (month < 1 || month > 12 || day < 1 || day > 31) return null
  return { year, month, day }
}

function weekdayIndex({ year, month, day }: CalendarParts): number {
  return new Date(Date.UTC(year, month - 1, day)).getUTCDay()
}

/** "13. 1." */
export function formatDayMonth(iso: string): string {
  const parts = calendarParts(iso)
  return parts ? `${parts.day}. ${parts.month}.` : iso
}

/** "13. 1. 2026" */
export function formatDate(iso: string): string {
  const parts = calendarParts(iso)
  return parts ? `${parts.day}. ${parts.month}. ${parts.year}` : iso
}

/** "Úterý 13. ledna 2026" */
export function formatLongDate(iso: string): string {
  const parts = calendarParts(iso)
  if (!parts) return iso
  const weekday = WEEKDAYS[weekdayIndex(parts)] ?? ''
  const capitalised = weekday.charAt(0).toUpperCase() + weekday.slice(1)
  return `${capitalised} ${parts.day}. ${MONTHS_GENITIVE[parts.month - 1] ?? ''} ${parts.year}`
}

export interface CalendarTileText {
  readonly month: string
  readonly day: string
  readonly weekday: string
}

export function calendarTile(iso: string): CalendarTileText | null {
  const parts = calendarParts(iso)
  if (!parts) return null
  return {
    month: MONTHS_NOMINATIVE[parts.month - 1] ?? '',
    day: String(parts.day),
    weekday: WEEKDAYS[weekdayIndex(parts)] ?? '',
  }
}

/** Czech plural for days: 1 den, 2–4 dny, 5+ dní. */
export function formatDays(count: number): string {
  if (count === 1) return '1 den'
  if (count >= 2 && count <= 4) return `${count} dny`
  return `${count} dní`
}

/** Supplied source metadata as one line: title · date · page. */
export function sourceLine(source: SourceMetadata): string {
  return `${source.title} · ${formatDate(source.date)}${source.page !== undefined ? ` · str. ${source.page}` : ''}`
}
