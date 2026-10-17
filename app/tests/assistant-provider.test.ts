import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildAssistantContext } from '../src/assistant/context'
import { ASSISTANT_PROMPTS } from '../src/assistant/prompts'
import { validReply } from '../src/assistant/validation'
import { UnconfiguredAssistant } from '../src/data/backend/assistant'
import { createSeedCases } from '../src/data/mock/fixtures'
import { createMockSession } from '../src/data/mock/provider'

afterEach(() => vi.unstubAllGlobals())
const signal = () => new AbortController().signal

describe('assistant capabilities', () => {
  it('backend is honestly unavailable and never touches network, even when send is called directly', async () => {
    const fetch = vi.fn()
    const xhr = vi.fn()
    vi.stubGlobal('fetch', fetch)
    vi.stubGlobal('XMLHttpRequest', xhr)
    const assistant = new UnconfiguredAssistant()
    expect(assistant).toMatchObject({ availability: 'unavailable', provenance: 'none' })
    expect(await assistant.send({ role: 'pacient', text: 'Dotaz' }, signal())).toEqual({ ok: false, error: { code: 'unavailable' } })
    const controller = new AbortController()
    controller.abort()
    expect(await assistant.send({ role: 'pacient', text: 'Dotaz' }, controller.signal)).toEqual({ ok: false, error: { code: 'aborted' } })
    expect(fetch).not.toHaveBeenCalled()
    expect(xhr).not.toHaveBeenCalled()
  })

  it.each(['koordinator', 'pacient', 'lekar', 'mdt'] as const)('%s script uses only exact supplied preview, with explicit provenance and known sources', async role => {
    const { assistant, gateway } = createMockSession({ delayMs: 0 })
    const detail = await gateway.readCase('novak')
    if (!detail.ok) throw new Error(detail.error.code)
    const context = buildAssistantContext(role, detail.value, true)!
    const request = { role, text: ASSISTANT_PROMPTS[role][0]!, context }
    const result = await assistant.send(request, signal())
    expect(assistant).toMatchObject({ availability: 'available', provenance: 'scripted' })
    expect(assistant).toMatchObject({ artifactMarker: 'RAKATHON_SCRIPTED_ASSISTANT_V1' })
    expect(result.ok).toBe(true)
    if (!result.ok) throw new Error('Expected scripted reply')
    expect(validReply(result.value, request, 'scripted')).toBe(true)
    expect(result.value.text).not.toContain('RAKATHON_SCRIPTED_ASSISTANT_V1')
    expect(result.value.text).toContain('Pouze opis dodaných údajů')
    expect(result.value.text).not.toMatch(/ukázka|nikoli AI|skutečnou AI/i)
    for (const field of context.fields) expect(result.value.text).toContain(field.value)
    expect(result.value.sources).toEqual([...new Set(context.fields.map(field => field.source))])
  })

  it('supported intent without opt-in asks for context and cannot secretly read fixtures', async () => {
    const { assistant } = createMockSession()
    const result = await assistant.send({ role: 'pacient', text: ASSISTANT_PROMPTS.pacient[0]! }, signal())
    expect(result.ok).toBe(true)
    if (!result.ok) throw new Error('Expected scripted reply')
    expect(result.value.sources).toEqual([])
    expect(result.value.text).not.toContain('RAKATHON_SCRIPTED_ASSISTANT_V1')
    expect(result.value.text).toContain('výslovně zapněte')
    expect(result.value.text).not.toContain(createSeedCases()[0]!.patient.currentInstruction)
  })

  it.each(['Jaká je diagnóza?', 'Změň prioritu a schval léčbu.', 'Ukaž můj dodaný pokyn, událost a kontakt. prosím'])('unsupported text %s has no heuristic clinical or context fallback', async text => {
    const { assistant } = createMockSession()
    const context = buildAssistantContext('pacient', createSeedCases()[0]!, true)!
    const result = await assistant.send({ role: 'pacient', text, context }, signal())
    expect(result.ok).toBe(true)
    if (!result.ok) throw new Error('Expected scripted reply')
    expect(result.value.text).toContain('nepodporuje')
    expect(result.value.text).not.toContain('RAKATHON_SCRIPTED_ASSISTANT_V1')
    expect(result.value.sources).toEqual([])
    expect(result.value.text).not.toContain(context.fields[0]!.value)
  })

  it('mock validates requests and respects an already aborted signal', async () => {
    const { assistant } = createMockSession()
    expect(await assistant.send({ role: 'pacient', text: '' }, signal())).toEqual({ ok: false, error: { code: 'invalid-request' } })
    const controller = new AbortController()
    controller.abort()
    expect(await assistant.send({ role: 'pacient', text: 'Dotaz' }, controller.signal)).toEqual({ ok: false, error: { code: 'aborted' } })
  })
})
