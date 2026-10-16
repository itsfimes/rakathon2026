import { Avatar } from '../../components/ui/Avatar'
import type { PatientView } from '../../data/contracts'

export function HelperPanel({ coordinator }: { readonly coordinator: PatientView['coordinator'] }) {
  return (
    <section className="panel" aria-labelledby="t-help">
      <div className="panel__body helper">
        <Avatar />
        <div>
          <h2 className="event__title" id="t-help">{coordinator ? `Vaše koordinátorka: ${coordinator.name}` : 'Vaše koordinační centrum'}</h2>
          {coordinator?.help && <p>{coordinator.help}</p>}
          <p className="meta">{coordinator?.contact ?? 'Kontakt zatím není uveden.'}</p>
        </div>
      </div>
    </section>
  )
}
