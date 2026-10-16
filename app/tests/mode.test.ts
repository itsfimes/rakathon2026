import { describe, expect, it } from 'vitest'
import { parseDataMode } from '../src/data/mode'

describe('single fail-closed mode setting', () => {
  it.each([undefined, 'backend'])( '%s selects backend', value => {
    expect(parseDataMode(value)).toEqual({ ok: true, value: 'backend' })
  })
  it('requires exact mock opt-in', () => {
    expect(parseDataMode('mock')).toEqual({ ok: true, value: 'mock' })
  })
  it.each(['', 'MOCK', ' mock', 'mock ', 'true', 'demo', 'undefined'])( '%s is invalid', value => {
    expect(parseDataMode(value)).toMatchObject({ ok: false, error: { code: 'configuration-error' } })
  })
})
