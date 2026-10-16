import { ExampleNote } from '../../components/ui/Button'

/** Explains the controls next to it truthfully, depending on whether local demo actions exist. */
export function UnavailableNote({ id }: { readonly id: string }) {
  return <ExampleNote id={id}>Nedostupné: odesílání a ukládání zatím není připojeno. Nic se neodešle.</ExampleNote>
}
