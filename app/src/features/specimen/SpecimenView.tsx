import { ViewHead } from '../../components/shell/ViewHead'
import { Icon } from '../../icons/Icon'
import type { IconName } from '../../icons/paths'
import { Button, ButtonRow } from '../../components/ui/Button'
import { Field, Input, Select } from '../../components/ui/Field'
import { Panel, PanelBody } from '../../components/ui/Panel'
import { Tag } from '../../components/ui/Tag'
import type { StatusLabel } from '../../lib/labels'
import { StatePreview } from './StatePreview'

/* Design-system tool view: tokens and primitives only. No case or patient data. */
const SWATCHES = [
  { chip: 'chip-ink', name: 'Text', value: '--c-ink · 15,7 : 1' },
  { chip: 'chip-muted', name: 'Text tlumený', value: '--c-ink-muted · 7,0 : 1' },
  { chip: 'chip-accent', name: 'Akce, výběr', value: '--c-accent · 6,1 : 1' },
  { chip: 'chip-danger', name: 'Chybí', value: '--c-danger · 5,8 : 1*' },
  { chip: 'chip-warning', name: 'Ověřit', value: '--c-warning · 5,8 : 1*' },
  { chip: 'chip-success', name: 'Máme', value: '--c-success · 5,7 : 1*' },
] as const

const ICONS: readonly [IconName, string][] = [
  ['check', 'Hotovo, máme'], ['missing', 'Chybí, nepřevzato'], ['alert', 'Ověřit'], ['clock', 'Čeká, běží'],
  ['calendar', 'Termín'], ['person', 'Vlastník'], ['file', 'Podklad'], ['lock', 'Zamčeno'],
]

const TAGS: readonly StatusLabel[] = [
  { tone: 'success', icon: 'check', text: 'Převzato' }, { tone: 'danger', icon: 'missing', text: 'Nepřevzato' },
  { tone: 'warning', icon: 'alert', text: 'Ověřit' }, { tone: 'info', icon: 'info', text: 'Nový' },
  { tone: 'neutral', icon: 'lock', text: 'Koncept' },
]

export function SpecimenView() {
  return (
    <>
      <ViewHead id="t-specimen" icon="layers" title="Vizuální jazyk" />
      <div className="spec-grid">
        <Panel id="t-col" title="Barvy">
          <PanelBody>
            <ul className="swatches">
              {SWATCHES.map(swatch => (
                <li key={swatch.chip} className="swatch">
                  <div className={`swatch__chip ${swatch.chip}`} />
                  <div className="swatch__text"><b>{swatch.name}</b><br />{swatch.value}</div>
                </li>
              ))}
            </ul>
            <p className="meta">* na světlém podkladu štítku. Barva vždy doplňuje ikonu a slovo.</p>
          </PanelBody>
        </Panel>
        <Panel id="t-type" title="Písmo a ikony">
          <PanelBody>
            <div className="type-scale">
              <p className="ts-2xl">36 · datum v kalendáři</p>
              <p className="ts-xl">24 · nadpis pohledu</p>
              <p className="ts-lg">19 · nadpis panelu, další úkol</p>
              <p>16 · text a vše pro pacienta: Příliš žluťoučký kůň úpěl ďábelské ódy.</p>
              <p className="ts-sm">14 · data v tabulce, citace, ovládací prvky</p>
              <p className="meta">13 · záhlaví, popisky, štítky, zdroj</p>
            </div>
            <ul className="icon-list">
              {ICONS.map(([name, label]) => <li key={name}><Icon name={name} />{label}</li>)}
            </ul>
          </PanelBody>
        </Panel>
        <Panel id="t-comp" title="Prvky">
          <PanelBody>
            <ButtonRow>
              <Button>Hlavní akce</Button>
              <Button variant="secondary">Vedlejší</Button>
              <Button disabled>Nedostupné</Button>
            </ButtonRow>
            <ButtonRow>{TAGS.map(tag => <Tag key={tag.text} label={tag} />)}</ButtonRow>
            <Field id="s-search" label="Hledat (vzhled)"><Input id="s-search" type="text" placeholder="Jméno nebo krok" /></Field>
            <Field id="s-owner" label="Vlastník kroku (vzhled)">
              <Select id="s-owner"><option>Patologie</option><option>Radiologie</option><option>Koordinátor</option></Select>
            </Field>
          </PanelBody>
        </Panel>
        <Panel id="t-states" title="Stavy">
          <PanelBody><StatePreview /></PanelBody>
        </Panel>
      </div>
    </>
  )
}
