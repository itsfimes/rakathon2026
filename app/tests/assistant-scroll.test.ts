import { describe, expect, it } from 'vitest'
import { revealScrollTop } from '../src/features/assistant/scroll'

describe('new-turn reveal position', () => {
  it('a turn that fits is shown at the bottom', () => {
    expect(revealScrollTop({ turnTop: 600, turnHeight: 120, viewport: 300, scrollHeight: 740 })).toBe(440)
  })
  it('a turn taller than the view is shown from its start, not its tail', () => {
    expect(revealScrollTop({ turnTop: 200, turnHeight: 900, viewport: 300, scrollHeight: 1120 })).toBe(192)
  })
  it('never scrolls past the end or above the top', () => {
    expect(revealScrollTop({ turnTop: 4, turnHeight: 900, viewport: 300, scrollHeight: 920 })).toBe(0)
    expect(revealScrollTop({ turnTop: 50, turnHeight: 100, viewport: 300, scrollHeight: 200 })).toBe(0)
  })
})
