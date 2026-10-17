import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LoginView } from '../src/features/auth/LoginView'

afterEach(() => { cleanup() })

describe('login icons without sprite', () => {
  it('renders team, person and role icons with inline geometry', () => {
    render(
      <LoginView
        initialUsername=""
        notice={null}
        problem={null}
        pending={false}
        disabled={false}
        onLogin={vi.fn()}
        demoAccounts={['koordinator', 'lekar', 'mdt', 'pacient']}
        demoPending={null}
        demoProblem={null}
        onDemoLogin={vi.fn()}
      />,
    )
    expect(screen.getByRole('heading', { name: 'Ukázkové přihlášení' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Přihlášení' })).toBeInTheDocument()
    for (const name of ['Koordinátor', 'Pacient', 'Lékař', 'MDT']) {
      expect(screen.getByRole('button', { name: new RegExp(name) })).toBeInTheDocument()
    }
    expect(document.querySelector('use')).toBeNull()
    const icons = Array.from(document.querySelectorAll('main.authgate svg.icon'))
    expect(icons.length).toBeGreaterThanOrEqual(6)
    for (const svg of icons) {
      expect(svg.getAttribute('viewBox')).toBe('0 0 24 24')
      expect(svg.querySelector('path, circle, rect, ellipse')).not.toBeNull()
    }
    const html = document.querySelector('main.authgate')?.innerHTML ?? ''
    expect(html).toContain('<circle')
    expect(html).toContain('<path')
  })
})
