import { readdir, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const sentinel = 'RAKATHON_SYNTHETIC_FIXTURE_V1'
const assistantSentinel = 'RAKATHON_SCRIPTED_ASSISTANT_V1'
const forbidden = [
  sentinel, assistantSentinel, /(?:src\/data|\.\.\/data|data)\/mock\//,
  /mock\/(?:provider|fixtures|assistant)\.[jt]s/,
  'Tento volný dotaz asistent nepodporuje.',
  'Pro tento přehled nejprve výslovně zapněte sdílení',
  'Jan Novák', 'Alena Šimková', 'Tomáš Dušek', 'Marie Králová', 'Pavel Říha', 'Karel Veselý',
  'MUDr. Petr Svoboda', 'MUDr. Jana Veselá', 'Lenka Horká',
  'v hlavě pankreatu hypoechogenní ložisko',
]

async function filesIn(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const files = await Promise.all(entries.map(entry => {
    const path = resolve(directory, entry.name)
    return entry.isDirectory() ? filesIn(path) : [path]
  }))
  return files.flat()
}

export async function verifyArtifacts(directory, mode) {
  if (mode !== 'backend' && mode !== 'mock') throw new Error('Expected backend or mock artifact mode')
  const files = await filesIn(resolve(directory))
  if (!files.length) throw new Error('Build directory is empty')
  let foundSentinel = false
  let foundAssistantSentinel = false
  for (const file of files) {
    const raw = (await readFile(file)).toString('utf8')
    // Source maps may encode Unicode; scan both raw bytes and decoded JSON strings.
    let content = raw
    if (file.endsWith('.map') || file.endsWith('.json')) content += `\n${JSON.stringify(JSON.parse(raw))}`
    content = content.replace(/\\u([0-9a-f]{4})/gi, (_, hex) => String.fromCharCode(parseInt(hex, 16)))
    foundSentinel ||= content.includes(sentinel)
    foundAssistantSentinel ||= content.includes(assistantSentinel)
    if (mode === 'backend') {
      for (const token of forbidden) {
        if (typeof token === 'string' ? content.includes(token) : token.test(content)) {
          throw new Error(`Mock fixture/module leaked into ${file}: ${String(token)}`)
        }
      }
    }
  }
  if (mode === 'mock' && !foundSentinel) throw new Error('Mock artifact sentinel missing; scan would be vacuous')
  if (mode === 'mock' && !foundAssistantSentinel) throw new Error('Scripted assistant sentinel missing; scan would be vacuous')
  return files.length
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const count = await verifyArtifacts(process.argv[2] ?? 'dist', process.argv[3] ?? 'backend')
  console.log(`Verified ${count} emitted files (${process.argv[3] ?? 'backend'}).`)
}
