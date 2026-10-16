import { Disclosure } from '../ui/Disclosure'

interface AboutFooterProps {
  readonly demo: boolean
  /** Owned by App so the in-page "O ukázce" link can open it without touching the route. */
  readonly open: boolean
  readonly onOpenChange: (open: boolean) => void
}

/** Disclaimer at the end of every page. */
export function AboutFooter({ demo, open, onOpenChange }: AboutFooterProps) {
  return (
    <footer className="about" id="o-ukazce">
      <Disclosure icon="info" open={open} onToggle={onOpenChange} summary={demo ? 'O ukázce: smyšlená data, žádné skutečné akce' : 'O aplikaci: backend zatím není připojen'}>
        <p>
          {demo
            ? 'Všichni pacienti, lékaři a koordinátoři jsou smyšlení. Změny (převzetí, kontrola podkladu) platí jen lokálně v tomto okně a obnovením dema zmizí. Nic se neodesílá, nepodepisuje, neukládá na server ani nezpracovává umělou inteligencí.'
            : 'Aplikace zatím nemá připojený backend, proto nezobrazuje žádná data pacientů. Nic se neodesílá ani neukládá.'}
          {' '}Přepnutí role není přihlášení ani ochrana dat; skutečná oprávnění musí vynucovat server. Pořadí případů vyjadřuje naléhavost organizace, ne zdravotní riziko.
        </p>
      </Disclosure>
    </footer>
  )
}
