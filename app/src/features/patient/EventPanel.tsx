import { CalendarTile } from '../../components/ui/CalendarTile'
import { Tag } from '../../components/ui/Tag'
import type { PatientView } from '../../data/contracts'
import { formatLongDate } from '../../lib/format'
import { ScopedDisclosure } from '../shared/ScopedDisclosure'

const lowerFirst = (text: string) => text.charAt(0).toLowerCase() + text.slice(1)

/** Next date as a calendar tile with a plain-language heading. A date before the record's "as of" day is
    shown as an earlier record, never as a current promise; whether it took place is not claimed. */
export function EventPanel({ event, earlier }: { readonly event: PatientView['nextEvent']; readonly earlier: boolean }) {
  // No date tile, so reuse the existing single-column layout; the message then spans the whole card.
  if (!event) return <section className="panel event event--earlier" aria-labelledby="t-event"><div><h2 className="event__title" id="t-event">Další termín zde není uveden</h2></div></section>
  if (earlier) {
    return (
      <section className="panel event event--earlier" aria-labelledby="t-event">
        <div>
          <h2 className="event__title" id="t-event">Dříve uvedený termín: {lowerFirst(formatLongDate(event.date))}</h2>
          <p>Aktuální termín zde není potvrzen.</p>
          <ScopedDisclosure icon="info" summary="Původní záznam o termínu">
            <p>{event.title} · {event.attendanceLabel}</p>
            <p>{event.followup}</p>
          </ScopedDisclosure>
        </div>
      </section>
    )
  }
  return (
    <section className="panel event" aria-labelledby="t-event">
      <CalendarTile date={event.date} />
      <div>
        <h2 className="event__title" id="t-event">{formatLongDate(event.date)}: {event.title}</h2>
        <Tag label={{ tone: 'info', icon: event.attendance === 'not-required' ? 'team' : 'info', text: event.attendanceLabel }} />
        <ScopedDisclosure icon="info" summary="Podrobnosti k tomuto termínu"><p>{event.followup}</p></ScopedDisclosure>
      </div>
    </section>
  )
}
