import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { spawnSync } from 'node:child_process'
import { expect, it } from 'vitest'

function scan(files: Record<string, string>, mode: 'backend' | 'mock'): number | null {
  const cache = resolve(import.meta.dirname, '../.vite')
  mkdirSync(cache, { recursive: true })
  const directory = mkdtempSync(resolve(cache, 'artifact-test-'))
  try {
    for (const [name, content] of Object.entries(files)) {
      const path = resolve(directory, name)
      mkdirSync(resolve(path, '..'), { recursive: true })
      writeFileSync(path, content)
    }
    const result = spawnSync(process.execPath, [resolve(import.meta.dirname, '../scripts/verify-artifacts.mjs'), directory, mode])
    return result.status
  } finally {
    rmSync(directory, { recursive: true })
  }
}

it('artifact scanner accepts clean output including hidden manifests', () => {
  expect(scan({ 'assets/main.js': 'backend only', '.vite/manifest.json': '{}' }, 'backend')).toBe(0)
})

it.each([
    ['assets/extra.txt', 'RAKATHON_SYNTHETIC_FIXTURE_V1'],
    ['assets/assistant.txt', 'RAKATHON_SCRIPTED_ASSISTANT_V1'],
    ['assets/scripted.js.map', JSON.stringify({ sourcesContent: ['RAKATHON_SCRIPTED_ASSISTANT_V1'] })],
    ['.vite/scripted-manifest.json', JSON.stringify({ label: 'RAKATHON_SCRIPTED_ASSISTANT_V1' })],
    ['assets/assistant.js.map', JSON.stringify({ sources: ['../../src/data/mock/assistant.ts'] })],
    ['.vite/assistant-manifest.json', JSON.stringify({ 'src/data/mock/assistant.ts': {} })],
    ['assets/script.js', 'Tento volný dotaz skriptovaná ukázka nepodporuje.'],
    ['assets/main.js.map', JSON.stringify({ sources: ['../../src/data/mock/fixtures.ts'] })],
    ['.vite/manifest.json', JSON.stringify({ 'src/data/mock/provider.ts': {} })],
    ['assets/another.js', 'Jan Novák'],
    ['assets/escaped.js.map', '{"sourcesContent":["Jan Nov\\u00e1k"]}'],
])('artifact scanner rejects leaked content in %s', (path, content) => {
  expect(scan({ 'assets/main.js': 'clean', [path]: content }, 'backend')).toBe(1)
})

it('artifact scanner fails on empty output or vacuous mock scan', () => {
  expect(scan({}, 'backend')).toBe(1)
  expect(scan({ 'main.js': 'no fixtures here' }, 'mock')).toBe(1)
  expect(scan({ 'main.js': 'RAKATHON_SYNTHETIC_FIXTURE_V1' }, 'mock')).toBe(1)
  expect(scan({ 'main.js': 'RAKATHON_SCRIPTED_ASSISTANT_V1' }, 'mock')).toBe(1)
  expect(scan({ 'main.js': 'RAKATHON_SYNTHETIC_FIXTURE_V1 RAKATHON_SCRIPTED_ASSISTANT_V1' }, 'mock')).toBe(0)
})
