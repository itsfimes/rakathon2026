import { Disclosure } from '../ui/Disclosure'

interface AboutFooterProps {
  readonly demo: boolean
  readonly authed?: boolean | undefined
  /** Owned by App so the in-page "O ukázce" link can open it without touching the route. */
  readonly open: boolean
  readonly onOpenChange: (open: boolean) => void
}

/** Disclaimer at the end of every page. */
export function AboutFooter({ demo, authed, open, onOpenChange }: AboutFooterProps) {
  const summary = demo ? 'O ukázce: smyšlená data, žádné skutečné akce'
    : authed ? 'O aplikaci: přihlášení ověřuje server'
    : 'O aplikaci: backend zatím není připojen'
  return (
    <footer className="about" id="o-ukazce">
      <Disclosure icon="info" open={open} onToggle={onOpenChange} summary={summary}>
        <p>
          {demo
            ? 'Všichni pacienti, lékaři a koordinátoři jsou smyšlení. Změny (převzetí, kontrola podkladu) platí jen lokálně v tomto okně a obnovením dema zmizí. Nic se neodesílá, nepodepisuje, neukládá na server ani nezpracovává umělou inteligencí.'
            : authed
              ? 'Jste přihlášeni a server vaši totožnost ověřil. Oprávnění k datům určuje server; případný výpadek hlásí příslušná část stránky.'
              : 'Aplikace zatím nemá připojený backend, proto nezobrazuje žádná data pacientů. Nic se neodesílá ani neukládá.'}
          {' '}Přepnutí pohledu podle role není přihlášení; skutečná oprávnění určuje server. Pořadí případů vyjadřuje naléhavost organizace, ne zdravotní riziko.
        </p>
      </Disclosure>
    </footer>
  )
}
