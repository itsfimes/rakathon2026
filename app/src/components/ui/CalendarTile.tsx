import { calendarTile } from '../../lib/format'

/** Graphical date tile. Decorative: the same date is written in the adjacent heading. */
export function CalendarTile({ date }: { readonly date: string }) {
  const tile = calendarTile(date)
  if (!tile) return null
  return (
    <p className="cal" aria-hidden="true">
      <span className="cal__month">{tile.month}</span>
      <span className="cal__day">{tile.day}</span>
      <span className="cal__wd">{tile.weekday}</span>
    </p>
  )
}
