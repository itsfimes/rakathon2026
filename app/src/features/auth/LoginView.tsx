import { useState } from 'react'
import type { FormEvent } from 'react'
import { Field, Input } from '../../components/ui/Field'
import { Notice } from '../../components/ui/Notice'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { Icon } from '../../icons/Icon'
import { VIEW_LINKS } from '../../lib/roles'
import type { AuthFailureKind, DemoAccount } from '../../auth/contracts'

interface LoginViewProps {
  readonly initialUsername: string
  readonly notice: string | null
  readonly problem: AuthFailureKind | null
  readonly pending: boolean
  readonly disabled: boolean
  readonly onLogin: (username: string, password: string) => void
  readonly demoAccounts?: readonly DemoAccount[] | null
  readonly demoPending?: DemoAccount | null
  readonly demoProblem?: AuthFailureKind | null
  readonly onDemoLogin?: (account: DemoAccount) => void
}

function problemText(problem: AuthFailureKind): string {
  if (problem === 'limited') return 'Příliš mnoho pokusů. Zkuste to prosím za chvíli znovu.'
  if (problem === 'unavailable') return 'Služba není dostupná. Zkuste to prosím později.'
  return 'Přihlášení se nezdařilo. Zkontrolujte jméno a heslo a zkuste to znovu.'
}

function demoProblemText(problem: AuthFailureKind): string {
  if (problem === 'limited') return 'Příliš mnoho pokusů. Zkuste to prosím za chvíli znovu.'
  return 'Ukázkový účet nyní není dostupný. Zkuste to prosím znovu.'
}

const ROLE_HINT: Readonly<Record<DemoAccount, string>> = {
  pacient: 'Co mě čeká, kdy a kde',
  koordinator: 'Fronta případů a další kroky',
  lekar: 'Odeslané případy a závěry',
  mdt: 'Příprava a jednání komise',
}

export function LoginView({ initialUsername, notice, problem, pending, disabled, onLogin, demoAccounts, demoPending, demoProblem, onDemoLogin }: LoginViewProps) {
  const [username, setUsername] = useState(initialUsername)
  const [password, setPassword] = useState('')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (pending || disabled) return
    onLogin(username, password)
    setPassword('')
  }

  const cards = demoAccounts && demoAccounts.length > 0 && onDemoLogin
    ? [...VIEW_LINKS].filter(item => (demoAccounts as readonly string[]).includes(item.id))
    : []

  return (
    <main className="authgate" aria-labelledby="auth-title">
      {cards.length > 0 && (
        <Panel id="demo-title" title="Ukázkové přihlášení" icon="team" meta="Jedním kliknutím">
          <PanelBody>
            <p className="authgate__lead">Vyberte si ukázkovou roli. Každé tlačítko rovnou přihlásí příslušný ukázkový účet.</p>
            {demoProblem && !demoPending && (
              <p className="authgate__error" role="alert">{demoProblemText(demoProblem)}</p>
            )}
            <div className="authgate__roles">
              {cards.map(item => (
                <button
                  key={item.id}
                  type="button"
                  className="authgate__role"
                  disabled={disabled || demoPending !== null}
                  aria-busy={demoPending === item.id}
                  onClick={() => onDemoLogin?.(item.id as DemoAccount)}
                >
                  <span className="authgate__role-name"><Icon name={item.icon} small />{item.label}</span>
                  <span className="authgate__role-hint">{ROLE_HINT[item.id as DemoAccount]}</span>
                  <span className="authgate__role-go">{demoPending === item.id ? 'Přihlašování…' : 'Pokračovat'}</span>
                </button>
              ))}
            </div>
          </PanelBody>
        </Panel>
      )}
      <Panel id="auth-title" title="Přihlášení" icon="person" meta="Přístup ke sdílenému případu">
        <PanelBody>
          <p className="authgate__lead">Zadejte své přihlašovací jméno ve tvaru jméno.příjmení a heslo, které vám přidělil správce.</p>
          {notice && <Notice tone="info" icon="info" title="Oznámení" role="status"><p>{notice}</p></Notice>}
          {problem && !pending && (
            <p className="authgate__error" role="alert">{problemText(problem)}</p>
          )}
          <form onSubmit={submit} aria-label="Přihlašovací formulář">
            <Field id="auth-username" label="Přihlašovací jméno (jméno.příjmení)">
              <Input
                id="auth-username"
                name="username"
                type="text"
                autoComplete="username"
                required
                maxLength={128}
                value={username}
                disabled={pending || disabled}
                onChange={event => setUsername(event.target.value)}
              />
            </Field>
            <Field id="auth-password" label="Heslo">
              <Input
                id="auth-password"
                name="password"
                type="password"
                autoComplete="current-password"
                required
                maxLength={256}
                value={password}
                disabled={pending || disabled}
                onChange={event => setPassword(event.target.value)}
              />
            </Field>
            <div className="btn-row">
              <button type="submit" className="btn" disabled={pending || disabled} aria-busy={pending}>
                {pending ? 'Ověřování…' : 'Přihlásit'}
              </button>
            </div>
          </form>
          <p className="meta">Přístup zřizuje správce. Pokud údaje nemáte, obraťte se na něj.</p>
        </PanelBody>
      </Panel>
    </main>
  )
}
