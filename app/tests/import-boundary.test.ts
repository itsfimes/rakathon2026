import { readdirSync, readFileSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'
import ts from 'typescript'
import { expect, it } from 'vitest'

const root = resolve(import.meta.dirname, '../src')
const mockRoot = resolve(root, 'data/mock')
const compositionRoot = resolve(root, 'data/bootstrap.ts')

function filesIn(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = resolve(directory, entry.name)
    return entry.isDirectory() ? filesIn(path) : /\.[jt]sx?$/.test(path) ? [path] : []
  })
}

function forbiddenImport(file: string, specifier: string): boolean {
  const target = specifier.startsWith('.') ? resolve(dirname(file), specifier) : specifier
  return target.startsWith(mockRoot) || /(?:^|[/@])mock(?:[/]|$)/.test(specifier) || /fixture/i.test(specifier)
}

it('all present and future UI/backend modules cannot import or re-export mock providers/fixtures', () => {
  const violations: string[] = []
  for (const file of filesIn(root)) {
    if (file.startsWith(`${mockRoot}/`)) continue
    const source = ts.createSourceFile(file, readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true)
    const inspect = (node: ts.Node) => {
      let specifier: ts.Expression | undefined
      if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) specifier = node.moduleSpecifier
      if (ts.isCallExpression(node) && (node.expression.kind === ts.SyntaxKind.ImportKeyword || node.expression.getText(source) === 'require')) {
        specifier = node.arguments[0]
        if (!specifier || !ts.isStringLiteralLike(specifier)) violations.push(`${relative(root, file)}: nonliteral import`)
      }
      if (specifier && ts.isStringLiteralLike(specifier) && forbiddenImport(file, specifier.text)) {
        const allowed = file === compositionRoot && ts.isCallExpression(node)
          && node.expression.kind === ts.SyntaxKind.ImportKeyword && specifier.text === './mock/provider'
        if (!allowed) violations.push(`${relative(root, file)}: ${specifier.text}`)
      }
      ts.forEachChild(node, inspect)
    }
    inspect(source)
  }
  expect(violations).toEqual([])
})

it('boundary rule also catches future role/feature/backend paths and direct fixture aliases', () => {
  for (const file of ['features/patient/Patient.tsx', 'components/Shell.tsx', 'data/backend/adapter.ts', 'App.tsx']) {
    expect(forbiddenImport(resolve(root, file), `${mockRoot}/fixtures`)).toBe(true)
    expect(forbiddenImport(resolve(root, file), '@/data/mock/provider')).toBe(true)
    expect(forbiddenImport(resolve(root, file), '@/data/mock/assistant')).toBe(true)
    expect(forbiddenImport(resolve(root, file), '@/fixtures')).toBe(true)
  }
})
