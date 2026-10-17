import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { AboutFooter } from '../src/components/shell/AboutFooter'

afterEach(cleanup)
const body = () => document.querySelector('footer')!.textContent ?? ''
const noop = () => {}

describe('AboutFooter', () => {
  it('backend: neutral summary, no false "not connected" or "nothing is sent"', () => {
    render(<AboutFooter demo={false} open onOpenChange={noop} />)
    expect(screen.getByText('O aplikaci a omezeních')).toBeInTheDocument()
    expect(body()).toContain('Klinické údaje aplikace ze zdroje jen čte a nic do něj nezapisuje.')
    expect(body()).not.toMatch(/není připojen|Nic se neodesílá|nezobrazuje žádná data|poskytovatel/)
    expect(body()).toContain('Přepnutí role není přihlášení ani ochrana dat')
  })
  it('backend with server assistant states that messages and attached context go to the configured AI provider', () => {
    render(<AboutFooter demo={false} serverAssistant open onOpenChange={noop} />)
    expect(body()).toContain('odchází ke konfigurovanému poskytovateli umělé inteligence')
    expect(body()).not.toMatch(/neuchovává|nesdílí|bezpečně uloženo/)
  })
  it('mock keeps the synthetic/local-reset disclaimer and ignores the assistant flag', () => {
    render(<AboutFooter demo serverAssistant open onOpenChange={noop} />)
    expect(screen.getByText('O ukázce: smyšlená data, žádné skutečné akce')).toBeInTheDocument()
    expect(body()).toContain('obnovením dema zmizí')
    expect(body()).not.toContain('poskytovateli')
  })
})
