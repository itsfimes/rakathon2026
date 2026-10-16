import { useState } from 'react'
import { Notice } from '../../components/ui/Notice'
import { SegmentedRadios } from '../../components/ui/Segmented'
import { Skeleton } from '../../components/ui/Skeleton'

type PreviewState = 'empty' | 'loading' | 'error' | 'done'
const OPTIONS: readonly { value: PreviewState; label: string }[] = [
  { value: 'empty', label: 'Prázdné' }, { value: 'loading', label: 'Načítání' },
  { value: 'error', label: 'Chyba' }, { value: 'done', label: 'Hotovo' },
]

/** Preview of state patterns; changes only what is shown here. */
export function StatePreview() {
  const [state, setState] = useState<PreviewState>('empty')
  return (
    <>
      <SegmentedRadios name="state" legend="Zobrazit stav" options={OPTIONS} value={state} onChange={setState} />
      {state === 'empty' && <Notice icon="queue" title="Žádný případ neodpovídá filtru">Zkuste filtr „Vše“ nebo upravte hledání.</Notice>}
      {state === 'loading' && <Notice icon="clock" title="Načítání"><Skeleton /><Skeleton />Statické, bez animace.</Notice>}
      {state === 'error' && <Notice tone="danger" icon="alert" title="Podklady se nepodařilo načíst">Zkuste to znovu za chvíli. Starší data se nezobrazují jako aktuální.</Notice>}
      {state === 'done' && <Notice tone="success" icon="check" title="Upozornění připraveno">Takto by vypadalo potvrzení.</Notice>}
    </>
  )
}
