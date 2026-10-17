import { afterEach, describe, expect, it, vi } from 'vitest'
import { ASSISTANT_PROMPTS } from '../src/assistant/prompts'
import { validReply } from '../src/assistant/validation'
import { UnconfiguredAssistant } from '../src/data/backend/assistant'
import { createMockSession } from '../src/data/mock/provider'

afterEach(() => vi.unstubAllGlobals())
const signal = () => new AbortController().signal
describe('assistant capabilities', () => {
  it('unconfigured backend never touches network', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    expect(await new UnconfiguredAssistant().send({ role: 'pacient', text: 'Dotaz' }, signal())).toEqual({ ok: false, error: { code: 'unavailable' } })
    expect(fetch).not.toHaveBeenCalled()
  })
  it.each(['koordinator', 'pacient', 'lekar', 'mdt'] as const)('%s script remains clearly not AI and does not load records', async role => {
    const { assistant } = createMockSession()
    const result = await assistant.send({ role, text: ASSISTANT_PROMPTS[role][0]!, caseId: 'novak' }, signal())
    expect(result.ok).toBe(true)
    if (!result.ok) return
    expect(validReply(result.value, 'scripted')).toBe(true)
    expect(result.value.text).toContain('Skriptovaná ukázka, nikoli AI.')
    expect(result.value.text).toContain('neposílá data do Azure AI')
    expect(result.value.sources).toEqual([])
    expect(result.value.text).not.toContain('RAKATHON_SCRIPTED_ASSISTANT_V1')
  })
  it('supports general questions without inventing records', async () => {
    const { assistant } = createMockSession()
    const result = await assistant.send({ role: 'pacient', text: ASSISTANT_PROMPTS.pacient[0]! }, signal())
    expect(result).toMatchObject({ ok: true, value: { sources: [], coverage: { status: 'general', resources: 0, uploads: 0 } } })
  })
  it('validates requests and respects abort', async () => {
    const { assistant } = createMockSession()
    expect(await assistant.send({ role: 'pacient', text: '' }, signal())).toMatchObject({ ok: false })
    const controller = new AbortController()
    controller.abort()
    expect(await assistant.send({ role: 'pacient', text: 'Dotaz' }, controller.signal)).toEqual({ ok: false, error: { code: 'aborted' } })
  })
})
