import { useState } from 'react'
import type { FormEvent } from 'react'
import { Field, Input } from '../../components/ui/Field'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { Icon } from '../../icons/Icon'
import { IconSprite } from '../../icons/IconSprite'
import { VIEW_LINKS } from '../../lib/roles'
import type { ViewId } from '../../lib/roles'
import './demoLogin.css'

export type DemoRole = Exclude<ViewId, 'specimen'>
export const DEMO_DEFAULT_ROLE: DemoRole = 'pacient'
const ROLE_HINT: Readonly<Record<DemoRole, string>> = {
  pacient: 'Co mě čeká, kdy a kde',
  koordinator: 'Fronta případů a další kroky',
  lekar: 'Odeslané případy a závěry',
  mdt: 'Příprava a jednání komise',
}
/** Patient first: the safest default for a shared screen. */
const ROLES = [...VIEW_LINKS].sort((a, b) => Number(b.id === 'pacient') - Number(a.id === 'pacient')) as readonly (typeof VIEW_LINKS[number] & { id: DemoRole })[]

/** Presentation-only entry. Any name and password (even empty) continue; nothing is checked, stored or sent.
    The typed values never leave this component and are cleared on submit. */
export function DemoLogin({ onEnter }: { readonly onEnter: (role: DemoRole) => void }) {
  const [name, setName] = useState('')
  const [secret, setSecret] = useState('')
  const [role, setRole] = useState<DemoRole>(DEMO_DEFAULT_ROLE)

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setName('')
    setSecret('')
    onEnter(role)
  }

  return (
    <>
      <IconSprite />
      <main className="demologin" aria-labelledby="demo-login-title">
        <Panel id="demo-login-title" title="Demo přihlášení" icon="person" meta="Atlas">
          <PanelBody>
            <form onSubmit={submit} aria-label="Demo přihlášení" autoComplete="off">
              <Field id="demo-name" label="Jméno (libovolné)">
                <Input id="demo-name" name="demo-name" type="text" autoComplete="off" spellCheck={false} value={name} onChange={event => setName(event.target.value)} />
              </Field>
              <Field id="demo-secret" label="Heslo (libovolné, nezadávejte skutečné)">
                <Input id="demo-secret" name="demo-secret" type="password" autoComplete="new-password" value={secret} onChange={event => setSecret(event.target.value)} />
              </Field>
              <fieldset className="demologin__roles">
                <legend className="label">Pokračovat jako</legend>
                {ROLES.map(item => (
                  <label key={item.id} className="demologin__role">
                    <input type="radio" name="demo-role" value={item.id} checked={role === item.id} onChange={() => setRole(item.id)} />
                    <span className="demologin__role-body">
                      <span className="demologin__role-name"><Icon name={item.icon} small />{item.label}</span>
                      <span className="demologin__role-hint">{ROLE_HINT[item.id]}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
              <div className="btn-row">
                <button type="submit" className="btn">Pokračovat</button>
              </div>
            </form>
          </PanelBody>
        </Panel>
      </main>
    </>
  )
}
